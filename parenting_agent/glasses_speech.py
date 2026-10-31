"""Speech on the glasses: what the parent says out loud, heard through the glasses microphone.

The glasses app cuts the microphone into utterances on the phone (a voice activity gate, apps/glasses/SPEECH.md) and
posts each one as a 16 kHz mono WAV to the glasses endpoint's /hear. Muse Spark Open's ear (voice/ear.py, the same call
that hears Telegram voice notes) writes the words down. Glasses that transcribe on the device (DAT's Speech capability)
post the text instead, and it takes the same path from here.

The microphone is always on near a baby, so most of what it hears is not for the agent: talk to the baby, to the other
parent, to the dog. The gate passes only:
  - a start phrase ("changing time", "hora del cambio"), any time,
  - a short answer the agent is waiting for: "done" or "listo" while the changing table watches, "sí" or "no" while
    the car seat coach or the agent asked, "ya llamé" or "entendido" while a red flag card is up,
  - anything after the wake word ("agente", "agent"), or the next utterance after the wake word alone.
Everything else is dropped here: it never becomes a message, never reaches the brain, and is not kept.
"""
import concurrent.futures
import re
import time
import unicodedata

# "a gente": Muse's ear sometimes splits "Agente" in two (2 of 96 test lines on Oct 30). "la gente" is ordinary Spanish
# ("people"), so it is not a wake word.
WAKE_WORDS = ("oye agente", "hey agent", "agente", "a gente", "agent")
# The ear's prompt for the glasses: the voice notes' prompt (voice/ear.py) plus keep the wake word. With the voice notes'
# prompt Muse dropped a leading "Agent," as if it were the address, not the words (1 of 4 calls, and in the test set).
EAR_PROMPT = ("This is a parent speaking out loud to their baby care assistant through their glasses, in Spanish (often "
              "rioplatense, from Uruguay or Argentina) or English. Write down exactly what the parent said, in the "
              "language they spoke, with every number written as digits. Keep every word, also the word they call the "
              "assistant by (\"agente\" or \"agent\") when it comes first. Reply with the words only: no quotes, no "
              "translation, no comment. If there is no speech, reply with nothing.")
# Muse's ear sometimes does not believe audio came with the request and answers with nothing, or as an assistant
# ("¿en qué puedo ayudarte?"), most often on one short word: in 96 test lines on Oct 30, 7 one-word lines came back
# empty after 3 calls in a row. So the glasses ask it several times at once and take the first real transcript.
RACE = 3
ROUNDS = 2
ASSISTANT = re.compile(r"puedo ayudar|en que te puedo|en que puedo|how can i help|i can help|happy to help|"
                       r"te asisto|comparte|share your|no audio|no hay audio")
WAKE_WINDOW_S = 8.0
WAIT_TTL_S = 30 * 60  # an answer the agent waits for stops counting after this long

START = re.compile(r"^(changing time|diaper time|time to change|hora del cambio|hora de cambiar(lo|la)?|"
                   r"cambio de panal|vamos a cambiar(lo|la)?)\b")
FINISH = re.compile(r"^(done|all done|finished|listo|lista|termine|terminamos|ya esta|ya termine)\b")
ANSWER = re.compile(r"^(si|yes|yeah|yep|no|nope|dale|ok|okay|claro)\b")
ACK = re.compile(r"^(ya llame|llame|i called|called|entendido|entendi|got it|understood|listo|ok|okay|dale)\b")
# (what the agent waits for, its pattern, the most words such an answer has)
WAITS = (("finish", FINISH, 8), ("answer", ANSWER, 4), ("ack", ACK, 8))


def plain(text):
    """Lower case, no accents, no punctuation, single spaces: "¡Sí!" and "si" read the same."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def strip_wake(text, wake):
    """The words after the wake word, with its punctuation gone: "Agente, ¿cuándo comió?" -> "¿cuándo comió?"."""
    words = text.split()
    rest = " ".join(words[len(wake.split()):])
    return rest.lstrip(" ,.:;!¡-").strip()


class Gate:
    """Decides whether an utterance was meant for the agent. Waits are per wearer: {person: {kind: until_monotonic}}."""

    def __init__(self, wake_words=WAKE_WORDS, wake_window_s=WAKE_WINDOW_S, clock=time.monotonic):
        self.wake_words = sorted((plain(w) for w in wake_words), key=len, reverse=True)
        self.wake_window_s = wake_window_s
        self.clock = clock
        self.waits = {}
        self.window = {}

    def wait(self, person, kind, on=True):
        waits = self.waits.setdefault(person, {})
        if on:
            waits[kind] = self.clock() + WAIT_TTL_S
        else:
            waits.pop(kind, None)

    def waiting(self, person):
        now = self.clock()
        return {kind for kind, until in self.waits.get(person, {}).items() if until > now}

    def decide(self, text, person=None):
        """{"take": bool, "text": the words for the agent, "why": the rule}."""
        said = plain(text)
        if not said:
            return {"take": False, "text": "", "why": "no speech"}
        words = said.split()
        for wake in self.wake_words:
            if said == wake:
                self.window[person] = self.clock() + self.wake_window_s
                return {"take": False, "text": "", "why": "wake word, listening"}
            if said.startswith(wake + " "):
                return {"take": True, "text": strip_wake(text, wake), "why": "wake word"}
        # A command is judged on its first sentence, and a long tail is dropped: the ear sometimes adds a sentence of
        # its own ("Changing time. Please check the audio for the exact instructions.", Oct 30).
        first = re.split(r"(?<=[.!?])\s+", text.strip())[0]
        said, words = plain(first), plain(first).split()
        whole = len(plain(text).split())
        if START.match(said) and len(words) <= 6:
            return {"take": True, "text": text if whole <= 6 else first, "why": "start phrase"}
        waiting = self.waiting(person)
        for kind, pattern, most in WAITS:
            if kind in waiting and pattern.match(said) and len(words) <= most:
                # "Done. It was dirty." is all the parent's: the whole text when it is short enough
                return {"take": True, "text": text if whole <= most else first, "why": f"{kind} the agent waits for"}
        if self.window.pop(person, 0) > self.clock():
            return {"take": True, "text": text, "why": "after the wake word"}
        return {"take": False, "text": "", "why": "not for the agent"}


def transcript(text):
    """True for words a parent said, False for Muse answering as an assistant instead of writing them down."""
    return bool(text) and not ASSISTANT.search(plain(text))


def race(make_ear, wav, calls=RACE, rounds=ROUNDS, pool=None):
    """Hears one utterance with `calls` ear calls at once and returns (words, info) as soon as one is a transcript.
    The slower calls finish in the background and are dropped. A round with no transcript is asked again, up to
    `rounds` rounds, then the words are "" (nothing heard). Raises the ear's error only when every call failed."""
    pool = pool or concurrent.futures.ThreadPoolExecutor(max_workers=calls * rounds)
    started = time.monotonic()
    answers, errors = [], []
    for round_no in range(1, rounds + 1):
        futures = [pool.submit(make_ear().hear, wav) for _ in range(calls)]
        for future in concurrent.futures.as_completed(futures):
            try:
                text = future.result()
            except Exception as error:  # one failed call: the others may still hear it
                errors.append(str(error)[:200])
                continue
            # The parent's words are one line. Muse sometimes writes them and then answers them, even with medical
            # advice on an emergency ("Llamá ya a emergencias...", Oct 30): only the first line is the parent's.
            text = text.strip().split("\n")[0].strip()
            answers.append(text[:120])
            if transcript(text):
                return text, {"calls": round_no * calls, "round": round_no, "answers": answers, "errors": errors,
                              "seconds": round(time.monotonic() - started, 3)}
    if errors and not answers:
        raise RuntimeError(errors[0])
    return "", {"calls": rounds * calls, "round": rounds, "answers": answers, "errors": errors,
                "seconds": round(time.monotonic() - started, 3)}


def word_errors(reference, heard):
    """Word edit distance between what was said and what was heard, on plain words. Returns (errors, reference words)."""
    ref, hyp = plain(reference).split(), plain(heard).split()
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (r != h))
    return row[len(hyp)], len(ref)
