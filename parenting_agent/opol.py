"""The OPOL helper (issue #144): how much of each language the baby hears from each parent, counted in the house.

The family raises Theo with OPOL, one parent, one language: Gonza speaks English to him, Ceci Spanish. The glasses
microphone is always on near the baby, and the glasses gate (glasses_speech.py) drops every utterance that is not for the
agent ("agente", a start phrase, an answer the agent waits for). This plug-in looks at those dropped utterances only, so
it never makes the agent speak while a parent talks to the baby:

1. The wearer is the speaker: each parent's glasses have their own pairing token, so the utterance is theirs.
2. Talk to someone else is left out when it opens with another parent's name or a word in "not_to_baby" (the dog).
3. The language comes from the audio, on this machine: Meta's MMS language ID (facebook/mms-lid-126) in a worker
   process (opol_worker.py), English or Spanish when the model is sure, else nothing is counted. Glasses that send text
   instead of audio (DAT Speech on the glasses) get the words' language from the agent's own word lists (rules.py).
4. Only the day, the parent, the language and the seconds are kept (table opol_seconds). Never the words, never the
   audio: the WAV stays in memory until it is scored and is never written anywhere.

What the parents get, descriptive only, never advice beyond the family's own goal ("languages" below):
- One optional short line in their morning message (channels/push.py), at most once a week (the report day covers the
  week before), or when the share of their language drifts: the last drift_days days against the week before, by
  drift_points percentage points or more, at most once per drift_days days. "Idiomas: la semana pasada Theo te escuchó
  3 h 20 min en inglés (tu idioma con él) y 25 min en español."
- On demand: "¿cuánto inglés escuchó Theo esta semana?", "how much Spanish did Theo hear today?", per parent.
- "apagá el conteo de idiomas" stops it (no counting, no lines), "prendé el conteo de idiomas" starts it again,
  "borrá el conteo de idiomas" deletes every count. "enabled": false in the config turns it off for good.

Before the birth ("baby": {"born": false}) nothing is counted, unless "count_before_birth" is true.

What it cannot know: it counts all of the wearer's speech that is not for the agent and does not open with someone
else's name, so talk to another adult without a name in front is counted too. The house microphone (house_sounds.py)
cannot tell who speaks, so it is not a source here.

Why MMS language ID: it is Meta's open spoken language ID (CC-BY-NC 4.0, like the MMS voices), it runs offline, and
it hears the language from the sound, so no audio and no words have to go anywhere for it. It is 1B parameters, so it
runs where the glasses endpoint and the other heavy models run (the Mac, the hearing venv), not in the stdlib only agent
image on the Vostro. Smaller language ID models exist (Whisper's, VoxLingua ECAPA) but are not Meta models.

Add "parenting_agent.opol:Opol" to the plug-ins. Settings under "opol":
    {"enabled": true, "languages": {"gonza": "en", "ceci": "es"}, "not_to_baby": ["firulais"],
     "lid": {"python": ".venv-hearing/bin/python", "model_dir": ".models/mms-lid-126", "device": "mps"}}
"""
import datetime
import io
import json
import os
import queue
import re
import struct
import subprocess
import threading
import unicodedata
import wave
from pathlib import Path

from . import baby_phase
from .agent import rules
from .agent.plugins import Plugin
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS

SCHEMA = """
create table if not exists opol_seconds (day text, person text, lang text, seconds real default 0,
  utterances integer default 0, primary key (day, person, lang));
create table if not exists opol_settings (key text primary key, value text, ts text);
create table if not exists opol_lines (day text, person text, kind text, week text, primary key (day, person));
"""
DEFAULTS = {"enabled": True, "languages": {}, "not_to_baby": [], "count_before_birth": False, "min_speech_s": 1.0,
            "max_speech_s": 20.0, "min_share": 0.8, "min_mass": 0.5, "min_text_words": 3, "report_day": "monday",
            "drift_days": 3, "drift_points": 20, "min_minutes": 10, "queue": 20, "pronoun": "he",
            "lid": {"enabled": True}}
RATE = 16000
LANGS = ("en", "es")
ISO = {"eng": "en", "spa": "es"}
REPO = Path(__file__).resolve().parent.parent
DEFAULT_PYTHON = REPO / ".venv-hearing/bin/python"
DEFAULT_MODEL = REPO / ".models/mms-lid-126"
WORKER = Path(__file__).with_name("opol_worker.py")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

# What a parent says, matched lower case with the accents folded.
LANG_WORD = r"(?:ingles|espanol|castellano|english|spanish|idiomas?|lenguas?|languages?)"
AMOUNT = re.compile(r"\b(?:cuant[oa]s?|how (?:much|many|long)|resumen|summary|conteo|count)\b")
HEARD = re.compile(r"\b(?:escuch\w*|oy[oe]\w*|habl\w*|heard|hear\w*|spoke|speak\w*|talk\w*|conteo|count)\b")
ASKS_LANG = re.compile(rf"\b{LANG_WORD}\b")
NAMED = re.compile(r"\bopol\b|\bconteo de (?:los )?idiomas\b|\blanguage count\b")
COUNT_WORDS = r"(?:el\s+|the\s+)?(?:conteo|contador|cuenta|count(?:ing)?|tracking)\s+(?:de\s+(?:los\s+)?)?(?:idiomas?|lenguas?|languages?)|opol"
OFF = re.compile(rf"\b(?:apaga|apagar|apague|desactiva|desactivar|pausa|pausar|turn off|stop|disable|pause)\b\s+(?:me\s+)?{COUNT_WORDS}|"
                 rf"\b(?:{COUNT_WORDS})\s+off\b")
ON = re.compile(rf"\b(?:prende|prender|prendan|encende|encender|activa|activar|reanuda|turn on|start|enable|resume)\b\s+{COUNT_WORDS}|"
                rf"\b(?:{COUNT_WORDS})\s+on\b")
DELETE = re.compile(rf"\b(?:borra|borrar|elimina|eliminar|delete|erase|clear)\b\s+(?:todo\s+)?{COUNT_WORDS}")
TODAY = re.compile(r"\b(?:hoy|today)\b")
YESTERDAY = re.compile(r"\b(?:ayer|yesterday)\b")
LAST_WEEK = re.compile(r"\b(?:semana pasada|ultima semana|last week)\b")

TEXT = {
    "es": {
        "en": "inglés", "es": "español",
        "period_today": "Hoy", "period_yesterday": "Ayer", "period_week": "Esta semana (desde el lunes {d})",
        "period_last_week": "La semana pasada ({d1} al {d2})",
        "heard": "{period} {baby} escuchó {parts}.", "lang_part": "{t} en {lang} ({who})", "who": "{name} {t}",
        "nothing": "{period} no conté nada en inglés ni en español.",
        "how": "Cuento lo que oyen los anteojos de cada uno cuando no le hablan al agente. Solo guardo idioma y minutos, "
               "nunca lo que dicen.",
        "off": "El conteo de idiomas está apagado. Para prenderlo: «prendé el conteo de idiomas».",
        "config_off": "El conteo de idiomas está apagado en la configuración del agente, no cuenta nada.",
        "not_born": "{baby} todavía no nació: el conteo de idiomas empieza cuando nazca.",
        "turned_off": "Listo, apagué el conteo de idiomas: no cuento nada ni lo pongo en el mensaje de la mañana. "
                      "Lo ya contado queda; para borrarlo: «borrá el conteo de idiomas».",
        "turned_on": "Listo, prendí el conteo de idiomas. Solo guardo idioma y minutos, nunca lo que dicen.",
        "deleted": "Listo, borré todo el conteo de idiomas ({n} días).",
        "weekly": "Idiomas: la semana pasada {baby} te escuchó {goal_t} en {goal} ({yours}){other}.",
        "weekly_other": " y {t} en {lang}", "yours": "tu idioma con {pron}",
        "drift": "Idiomas: en los últimos {n} días el {pct} % de lo que {baby} te escuchó fue en {goal} ({yours}), "
                 "la semana anterior el {base} %.",
"pron_he": "él", "pron_she": "ella", "baby": "el bebé",
    },
    "en": {
        "en": "English", "es": "Spanish",
        "period_today": "Today", "period_yesterday": "Yesterday", "period_week": "This week (since Monday {d})",
        "period_last_week": "Last week ({d1} to {d2})",
        "heard": "{period} {baby} heard {parts}.", "lang_part": "{t} of {lang} ({who})", "who": "{name} {t}",
        "nothing": "{period} I counted nothing in English or Spanish.",
        "how": "I count what each parent's glasses hear when you are not talking to the agent. Only the language and "
               "the minutes are kept, never the words.",
        "off": "The language count is off. To turn it on: \"turn on the language count\".",
        "config_off": "The language count is off in the agent's settings, it counts nothing.",
        "not_born": "{baby} is not born yet: the language count starts when he is born.",
        "turned_off": "Done, the language count is off: nothing is counted or put in the morning message. What was "
                      "counted stays; to delete it: \"delete the language count\".",
        "turned_on": "Done, the language count is on. Only the language and the minutes are kept, never the words.",
        "deleted": "Done, I deleted the whole language count ({n} days).",
        "weekly": "Languages: last week {baby} heard you for {goal_t} in {goal} ({yours}){other}.",
        "weekly_other": " and {t} in {lang}", "yours": "your language with {pron}",
        "drift": "Languages: in the last {n} days {pct}% of what {baby} heard from you was in {goal} ({yours}), "
                 "the week before {base}%.",
"pron_he": "him", "pron_she": "her", "baby": "the baby",
    },
}


class Unavailable(RuntimeError):
    pass


def plain(text):
    """Lower case, accents folded, punctuation gone, single spaces."""
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded).split())


def wav_pcm(wav):
    """(16-bit mono PCM at 16 kHz, seconds) from a WAV in memory. The glasses send 16 kHz mono 16-bit (SPEECH.md)."""
    with wave.open(io.BytesIO(wav)) as reader:
        rate, width, channels = reader.getframerate(), reader.getsampwidth(), reader.getnchannels()
        frames = reader.readframes(reader.getnframes())
    if width != 2 or rate != RATE:
        raise ValueError(f"expected 16-bit audio at {RATE} Hz, got {8 * width}-bit at {rate} Hz")
    if channels > 1:
        frames = b"".join(frames[i:i + 2] for i in range(0, len(frames), 2 * channels))
    return frames, len(frames) / 2 / RATE


def pick(reply, min_share, min_mass):
    """("en" or "es", the share) when the model is sure the speech is English or Spanish, else (None, the share)."""
    probs = reply.get("probs") or {}
    en, es = float(probs.get("eng", 0.0)), float(probs.get("spa", 0.0))
    mass = en + es
    if mass <= 0:
        return None, 0.0
    lang, share = ("en", en / mass) if en >= es else ("es", es / mass)
    if mass < min_mass or share < min_share:
        return None, round(share, 3)
    return lang, round(share, 3)


def text_lang(text, min_words):
    """The words' language from the agent's word lists, for glasses that send text, or None when too short to tell."""
    if len(plain(text).split()) < min_words:
        return None
    return rules.message_lang(text)


def length(seconds, lang):
    if seconds < 59.5:
        return f"{max(1, int(round(seconds)))} s"
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


class MmsLid:
    """Meta's MMS language ID (facebook/mms-lid-126) in the worker process, in the Python that has transformers."""

    name = "mms-lid-126"

    def __init__(self, config=None):
        config = config or {}
        python = Path(os.path.expanduser(config.get("python") or os.environ.get("OPOL_LID_PYTHON") or DEFAULT_PYTHON))
        model_dir = Path(os.path.expanduser(config.get("model_dir") or os.environ.get("OPOL_LID_MODEL_DIR") or DEFAULT_MODEL))
        if not python.is_file():
            raise Unavailable(f"opol: no Python with transformers at {python}, run scripts/hearing-setup.sh")
        if not (model_dir / "model.safetensors").is_file():
            raise Unavailable(f"opol: no MMS language ID weights in {model_dir}, run scripts/opol_setup.sh")
        cfg = {"model_dir": str(model_dir), "device": config.get("device") or os.environ.get("OPOL_LID_DEVICE") or "cpu"}
        env = {**os.environ, "OPOL_LID_CONFIG": json.dumps(cfg), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        self.process = subprocess.Popen([str(python), str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, env=env)
        hello = json.loads(self.process.stdout.readline() or b'{"blocked": "worker exited"}')
        if "blocked" in hello:
            self.process.kill()
            raise Unavailable(f"opol: {hello['blocked']}")
        self.info = hello

    def classify(self, pcm):
        self.process.stdin.write(struct.pack(">I", len(pcm)) + pcm)
        self.process.stdin.flush()
        reply = json.loads(self.process.stdout.readline() or b'{"error": "worker exited"}')
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=10)


class Opol(Plugin):
    name = "opol"
    kind = "ears"

    def __init__(self, agent, config, clock=None, lid=None):
        super().__init__(agent, config)
        raw = config.get("opol") or {}
        self.cfg = {**DEFAULTS, **raw, "lid": {**DEFAULTS["lid"], **(raw.get("lid") or {})}}
        rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self.born = baby_phase.born(config)
        self.baby = (config.get("baby") or {}).get("name")
        self._lid, self.lid_error = lid, None
        self.db, self.lock = agent.memory.db, agent.memory.lock
        with self.lock:
            self.db.executescript(SCHEMA)
        self.queue = queue.Queue(maxsize=int(self.cfg["queue"]))
        self.thread = None
        agent.answer_takers = [*getattr(agent, "answer_takers", []), self.take]

    # State

    def now(self):
        return self.clock().astimezone(self.tz)

    def people(self):
        return getattr(self.agent, "people", None)

    def setting(self):
        with self.lock:
            row = self.db.execute("select value from opol_settings where key = 'state'").fetchone()
        return row[0] if row else "on"

    def set_state(self, value):
        with self.lock:
            self.db.execute("insert or replace into opol_settings (key, value, ts) values ('state', ?, ?)",
                            (value, self.now().isoformat(timespec="seconds")))
            self.db.commit()

    def counting(self):
        """None when it counts, else why not."""
        if not self.cfg["enabled"]:
            return "off in the config"
        if self.setting() == "off":
            return "turned off by a parent"
        if not self.born and not self.cfg["count_before_birth"]:
            return "not born yet"
        return None

    def publish(self, action, **fields):
        return self.agent.bus.publish("opol", action=action, **fields)

    # Hearing

    def lid(self):
        if self._lid is None and self.lid_error is None and self.cfg["lid"].get("enabled", True):
            try:
                self._lid = MmsLid(self.cfg["lid"])
                self.publish("lid_ready", model=self._lid.name, info=getattr(self._lid, "info", {}))
            except Unavailable as error:
                self.lid_error = str(error)[:200]
                self.publish("lid_unavailable", error=self.lid_error)
                print(self.lid_error, flush=True)
        return self._lid

    def overheard(self, wav, person, text="", meta=None):
        """An utterance the glasses gate dropped (not for the agent). Queued for the counting thread, never blocking
        the glasses. The words are only read here, in memory, for another person's name: they are never kept."""
        why = self.counting()
        if why is None and self.people() is not None and not self.people().person(person):
            why = "unknown speaker"
        if why is None and self.to_someone_else(text, person):
            why = "to someone else"
        if why is not None:
            return self.publish("skipped", person=person, reason=why)
        item = {"wav": wav, "person": person, "text": text or "", "meta": dict(meta or {}), "at": self.now()}
        if self.thread is None:
            return self.count(item)
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            return self.publish("skipped", person=person, reason="queue full")
        return None

    def to_someone_else(self, text, person):
        """True when the words open with another parent's name or a "not_to_baby" word: "Ceci, ¿me pasás el pañal?"."""
        first = plain(text).split()[:3]
        if not first:
            return False
        people = self.people()
        names = {plain(people.name(p)) for p in people.keys() if p != person} if people else set()
        names |= {plain(n) for n in self.cfg["not_to_baby"]}
        return any(word in names for word in first)

    def count(self, item):
        """Scores one utterance and adds its seconds. Returns the "opol" event."""
        wav, person, meta = item["wav"], item["person"], item["meta"]
        seconds, lang, share, by = meta.get("speech_s"), None, None, None
        try:
            if wav is not None:
                pcm, wav_s = wav_pcm(wav)
                seconds = float(seconds or wav_s)
                if seconds < float(self.cfg["min_speech_s"]):
                    return self.publish("skipped", person=person, reason="too short", seconds=round(seconds, 2))
                lid = self.lid()
                if lid is not None:
                    try:
                        reply = lid.classify(pcm)
                    except Exception:
                        broken, self._lid = self._lid, None  # a broken worker is replaced on the next utterance
                        getattr(getattr(broken, "process", None), "kill", lambda: None)()
                        raise
                    lang, share = pick(reply, float(self.cfg["min_share"]), float(self.cfg["min_mass"]))
                    by = "mms-lid"
                del pcm
            if by is None:
                if not seconds:
                    return self.publish("skipped", person=person, reason="no audio and no length")
                lang, by = text_lang(item["text"], int(self.cfg["min_text_words"])), "words"
        except Exception as error:  # noqa: BLE001 one bad utterance is reported, the next one is counted
            return self.publish("failed", person=person, error=f"{type(error).__name__}: {str(error)[:160]}")
        finally:
            item["wav"] = item["text"] = None
        if lang is None:
            return self.publish("skipped", person=person, reason="language not sure", by=by, share=share,
                                seconds=round(float(seconds or 0), 2))
        seconds = min(float(seconds), float(self.cfg["max_speech_s"]))
        day = item["at"].astimezone(self.tz).date().isoformat()
        self.add(day, person, lang, seconds)
        return self.publish("counted", person=person, lang=lang, seconds=round(seconds, 2), by=by, share=share, day=day)

    def add(self, day, person, lang, seconds):
        with self.lock:
            self.db.execute("insert into opol_seconds (day, person, lang, seconds, utterances) values (?, ?, ?, ?, 1) "
                            "on conflict (day, person, lang) do update set seconds = seconds + excluded.seconds, "
                            "utterances = utterances + 1", (day, person, lang, seconds))
            self.db.commit()

    def totals(self, first, last, person=None):
        """{person: {lang: seconds}} from day first to day last, both included."""
        query = "select person, lang, sum(seconds) from opol_seconds where day >= ? and day <= ?"
        args = [first.isoformat(), last.isoformat()]
        if person is not None:
            query += " and person = ?"
            args.append(person)
        with self.lock:
            rows = self.db.execute(query + " group by person, lang", args).fetchall()
        out = {}
        for who, lang, seconds in rows:
            out.setdefault(who, {})[lang] = seconds or 0.0
        return out

    # What a parent asks

    def lang_for(self, event, text):
        """The parent's language from the people block (the final guard holds every reply to it), else the words'."""
        people = self.people()
        said = rules.message_lang(text) if len(plain(text).split()) >= 3 else None
        return (people.lang(event.get("person")) if people else None) or said or "es"

    def take(self, event, text):
        """The agent's answer taker: the reply, or None to leave the message to the agent."""
        words = plain(text)
        if not words or rules.is_emergency(text) or rules.newborn_red_flag(text):
            return None
        lang = self.lang_for(event, text)
        toggles = DELETE.search(words) or OFF.search(words) or ON.search(words)
        if toggles and not self.cfg["enabled"]:
            return TEXT[lang]["config_off"]
        if DELETE.search(words):
            return self.delete(lang)
        if OFF.search(words):
            self.set_state("off")
            self.publish("turned_off", person=event.get("person"))
            return TEXT[lang]["turned_off"]
        if ON.search(words):
            self.set_state("on")
            self.publish("turned_on", person=event.get("person"))
            return TEXT[lang]["turned_on"]
        if NAMED.search(words) or (AMOUNT.search(words) and HEARD.search(words) and ASKS_LANG.search(words)):
            return self.answer(lang, self.period(words), first=self.asked_lang(words))
        return None

    @staticmethod
    def asked_lang(words):
        if re.search(r"\b(?:espanol|castellano|spanish)\b", words):
            return "es"
        return "en" if re.search(r"\b(?:ingles|english)\b", words) else None

    def period(self, words):
        today = self.now().date()
        monday = today - datetime.timedelta(days=today.weekday())
        if TODAY.search(words):
            return "today", today, today
        if YESTERDAY.search(words):
            yesterday = today - datetime.timedelta(days=1)
            return "yesterday", yesterday, yesterday
        if LAST_WEEK.search(words):
            return "last_week", monday - datetime.timedelta(days=7), monday - datetime.timedelta(days=1)
        return "week", monday, today

    def baby_name(self, lang):
        return self.baby or TEXT[lang]["baby"]

    def answer(self, lang, period, first=None):
        w = TEXT[lang]
        if not self.cfg["enabled"]:
            return w["config_off"]
        if self.setting() == "off":
            return w["off"]
        if not self.born and not self.cfg["count_before_birth"]:
            return w["not_born"].format(baby=self.baby_name(lang))
        kind, start, end = period
        short = lambda day: f"{day.day}/{day.month}"  # noqa: E731
        label = w[f"period_{kind}"].format(d=short(start), d1=short(start), d2=short(end))
        found = self.totals(start, end)
        people = self.people()
        order = [first] + [x for x in LANGS if x != first] if first else list(LANGS)
        parts = []
        for code in order:
            by_person = sorted(((who, langs.get(code, 0.0)) for who, langs in found.items() if langs.get(code, 0.0) > 0),
                               key=lambda pair: -pair[1])
            total = sum(seconds for _, seconds in by_person)
            if total <= 0:
                continue
            who = ", ".join(w["who"].format(name=(people.name(p) if people else None) or p.capitalize(), t=length(s, lang))
                            for p, s in by_person)
            parts.append(w["lang_part"].format(t=length(total, lang), lang=w[code], who=who))
        if not parts:
            return f"{w['nothing'].format(period=label)} {w['how']}"
        joined = parts[0] if len(parts) == 1 else f"{parts[0]} {'y' if lang == 'es' else 'and'} {parts[1]}"
        return f"{w['heard'].format(period=label, baby=self.baby_name(lang), parts=joined)} {w['how']}"

    def delete(self, lang):
        with self.lock:
            days = self.db.execute("select count(distinct day) from opol_seconds").fetchone()[0]
            self.db.execute("delete from opol_seconds")
            self.db.execute("delete from opol_lines")
            self.db.commit()
        self.publish("deleted", days=days)
        return TEXT[lang]["deleted"].format(n=days)

    # The morning line

    def morning_line(self, person, lang, now=None):
        """One short line for this parent's morning message, or None. Never raises: the message goes out without it."""
        try:
            return self._morning_line(person, "es" if lang == "es" else "en", (now or self.now()).astimezone(self.tz))
        except Exception as error:  # noqa: BLE001 a bad read leaves the line out, never the morning message
            self.publish("line_failed", person=person, error=f"{type(error).__name__}: {str(error)[:160]}")
            return None

    def _morning_line(self, person, lang, now):
        goal = (self.cfg["languages"] or {}).get(person)
        if goal not in LANGS or self.counting() is not None:
            return None
        today = now.date()
        with self.lock:
            lines = self.db.execute("select day, kind, week from opol_lines where person = ?", (person,)).fetchall()
        if any(day == today.isoformat() for day, _, _ in lines):
            return None
        w, other = TEXT[lang], "es" if goal == "en" else "en"
        fill = {"baby": self.baby_name(lang), "goal": w[goal],
                "yours": w["yours"].format(pron=w["pron_she" if self.cfg["pronoun"] == "she" else "pron_he"])}
        floor = float(self.cfg["min_minutes"]) * 60
        monday = today - datetime.timedelta(days=today.weekday())
        weekly_done = any(kind == "weekly" and week == monday.isoformat() for _, kind, week in lines)
        if today.weekday() >= WEEKDAYS.index(self.cfg["report_day"]) and not weekly_done:
            last = self.totals(monday - datetime.timedelta(days=7), monday - datetime.timedelta(days=1), person).get(person, {})
            if sum(last.values()) >= floor:
                rest = last.get(other, 0.0)
                tail = w["weekly_other"].format(t=length(rest, lang), lang=w[other]) if rest > 0 else ""
                self.mark(today, person, "weekly", monday)
                return w["weekly"].format(goal_t=length(last.get(goal, 0.0), lang), other=tail, **fill)
        n = int(self.cfg["drift_days"])
        since = today - datetime.timedelta(days=n)
        if any(day > since.isoformat() for day, _, _ in lines):
            return None
        recent = self.totals(since, today - datetime.timedelta(days=1), person).get(person, {})
        base = self.totals(since - datetime.timedelta(days=7), since - datetime.timedelta(days=1), person).get(person, {})
        if sum(recent.values()) < floor or sum(base.values()) < floor:
            return None
        share = lambda found: round(100 * found.get(goal, 0.0) / sum(found.values()))  # noqa: E731
        if abs(share(recent) - share(base)) < int(self.cfg["drift_points"]):
            return None
        self.mark(today, person, "drift", monday)
        return w["drift"].format(n=n, pct=share(recent), base=share(base), **fill)

    def mark(self, day, person, kind, monday):
        with self.lock:
            self.db.execute("insert or replace into opol_lines (day, person, kind, week) values (?, ?, ?, ?)",
                            (day.isoformat(), person, kind, monday.isoformat()))
            self.db.commit()
        self.publish("morning_line", person=person, line=kind)

    # Running

    def run(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                self.count(item)
            finally:
                self.queue.task_done()

    def start(self):
        if not self.cfg["enabled"]:
            return
        self.thread = threading.Thread(target=self.run, name="opol", daemon=True)
        self.thread.start()
        self.publish("started", state=self.setting(), counting=self.counting() or "yes",
                     languages=self.cfg["languages"])

    def stop(self):
        if self.thread is not None:
            self.queue.put(None)
            self.thread.join(timeout=5)
            self.thread = None
        if self._lid is not None and hasattr(self._lid, "close"):
            self._lid.close()
