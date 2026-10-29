"""Real run: 20 synthetic Telegram voice notes through the families bot's voice path, end to end.

Each note goes through FamiliesBot.poll_once exactly as a Telegram update would: the OGG Opus file is "downloaded",
converted to WAV with ffmpeg, heard by Muse Spark Open as audio input, handled by the families service with the
Muse brain, and the answer is spoken with Meta's MMS-TTS and "sent" as an OGG Opus voice note. Only Telegram is
faked. A note scores when the log holds the right entry with the right values (or the answer has the right number,
for the question), checked on the log itself, not on the reply text.

    <python with torch and transformers> scripts/voice_notes_run.py --keys-env ~/.parenting-agent.env

Needs torch and transformers (MMS-TTS) and ffmpeg. Writes results/voice/run.json, run.md and three reply samples.
"""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import time
import zoneinfo
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parenting_agent.channels.messaging import Incoming, Messenger  # noqa: E402
from parenting_agent.families import settings as settings_mod  # noqa: E402
from parenting_agent.families.bot import FamiliesBot  # noqa: E402
from parenting_agent.families.service import Families  # noqa: E402
from parenting_agent.families.store import visitor_id  # noqa: E402
from parenting_agent.voice import client as voice_client  # noqa: E402
from parenting_agent.voice.ear import MODEL as EAR_MODEL, PROMPT as EAR_PROMPT  # noqa: E402

TZ = zoneinfo.ZoneInfo("America/Montevideo")
NOTES = ROOT / "results" / "voice" / "notes"
OUT = ROOT / "results" / "voice"
SAMPLES = {"es01", "es08", "en06"}


class FileTelegram(Messenger):
    """Telegram with the network cut out: a voice note's file id is a path, sends are recorded."""
    name = "file"

    def __init__(self):
        self.sent, self.voices = [], []

    def poll(self, offset, timeout):
        return []

    def download(self, file_id):
        return Path(file_id).read_bytes()

    def send(self, chat_id, text):
        self.sent.append(text)
        return len(self.sent)

    def send_voice(self, chat_id, ogg):
        self.voices.append(ogg)
        return len(self.voices)


def entries(app, family_id, kind):
    return app.family(family_id).log.entries(kind, None, 1000)


def last(app, family_id, kind):
    rows = entries(app, family_id, kind)
    return rows[-1] if rows else None


def ml(e):
    value = (e or {}).get("details", {}).get("amount_ml")
    return float(value) if value not in (None, "") else None


def hhmm(value):
    return (value or "")[11:16]


def feed(amount, at=None):
    def check(app, f, reply):
        e = last(app, f, "feeding")
        ok = e is not None and ml(e) == amount and (at is None or hhmm(e["ts"]) == at)
        return ok, f"last feed is {amount:g} ml" + (f" at {at}" if at else "")
    return check


def breast(side, minutes):
    def check(app, f, reply):
        e = last(app, f, "feeding") or {}
        d = e.get("details", {})
        ok = str(d.get("method", "")).lower() == f"{side} breast" and float(d.get("duration_min") or 0) == minutes
        return ok, f"last feed is {side} breast, {minutes} min"
    return check


def diaper(wet, solid, count):
    def check(app, f, reply):
        d = (last(app, f, "diaper") or {}).get("details", {})
        n = len(entries(app, f, "diaper"))
        ok = bool(d) and bool(d.get("wet")) == wet and bool(d.get("solid")) == solid and n == count
        return ok, f"last diaper wet={wet} solid={solid}, {count} diapers in the log, got {n}"
    return check


def asleep(at):
    """The families log keeps a sleep that started as a fact until the baby wakes, then writes one sleep entry."""
    def check(app, f, reply):
        started = app.family(f).memory.facts().get("_sleep_started", {}).get("value") or ""
        return started[:16] == f"2026-10-29T{at}", f"a sleep started at {at} today"
    return check


def woke(at):
    def check(app, f, reply):
        e = last(app, f, "sleep") or {}
        d = e.get("details", {})
        ok = bool(e) and str(d.get("start", ""))[:16] == f"2026-10-29T{at}" and 0 < float(d.get("duration_min") or 0) < 600
        return ok, f"one sleep from {at} to now, got start {d.get('start')} and {d.get('duration_min')} min"
    return check


def answer(total):
    def check(app, f, reply):
        return bool(re.search(rf"(?<!\d){total}(?!\d)", reply)), f"the answer says {total} ml"
    return check


def amounts(expected):
    def check(app, f, reply):
        got = [ml(e) for e in entries(app, f, "feeding") if ml(e) is not None]
        return got == expected, f"bottles in the log are {expected}, got {got}"
    return check


CHECKS = {
    "es01": feed(90, "03:00"), "es02": diaper(True, False, 1), "es03": diaper(False, True, 2), "es04": asleep("04:30"),
    "es05": woke("04:30"), "es06": breast("left", 10), "es07": feed(120), "es08": answer(210), "es09": amounts([90.0, 100.0]),
    "es10": diaper(True, True, 3),
    "en01": feed(60, "02:00"), "en02": diaper(True, False, 1), "en03": diaper(False, True, 2), "en04": asleep("03:15"),
    "en05": woke("03:15"), "en06": breast("right", 12), "en07": feed(150), "en08": answer(210), "en09": amounts([60.0, 130.0]),
    "en10": diaper(True, True, 3),
}


def at(hhmm_text):
    h, m = (int(x) for x in hhmm_text.split(":"))
    return datetime.datetime(2026, 10, 29, h, m, tzinfo=TZ)


def onboard(app, user, lang):
    code = app.store.create_invite(internal=True)
    for text in (f"/start {code}", "Tomi" if lang == "es" else "Mia", "20/10/2026", "no"):
        app.handle(user, user, text, "private", "es-UY" if lang == "es" else "en")
    return app.store.parent(visitor_id(user))["family_id"]


def run(keys_env, model):
    environ = {}
    settings_mod.read_keys(keys_env, environ)
    if "BASETEN_API_KEY" not in environ:
        raise SystemExit("no BASETEN_API_KEY in the keys file")
    os.environ["BASETEN_API_KEY"] = environ["BASETEN_API_KEY"]
    data = tempfile.mkdtemp(prefix="voice-notes-")
    s = settings_mod.load({"PA_FAMILIES_BRAIN": "baseten", "PA_FAMILIES_MODEL": model, "PA_FAMILIES_DATA_DIR": data,
                           "PA_FAMILIES_DAILY_USD": "20", "PA_FAMILIES_FAMILY_USD": "10"})
    clock = {"now": at("01:00")}
    app = Families(s, clock=lambda: clock["now"])
    users = {"es": 7001, "en": 7002}
    families = {lang: onboard(app, user, lang) for lang, user in users.items()}
    calls = []
    for family_id in families.values():
        agent = app.family(family_id).agent
        agent.tools.run = (lambda run: lambda name, arguments: (
            calls.append(f"{name}({json.dumps(arguments, ensure_ascii=False)})"), run(name, arguments))[1])(agent.tools.run)
    telegram = FileTelegram()
    voice = voice_client.Voice(voice_client.LocalVoice(), voice_client.Ear(model=EAR_MODEL))
    bot = FamiliesBot(app, telegram, poll_timeout_s=0, voice=voice)
    hear = voice.hear
    timing = {}

    def timed_hear(data):
        started = time.monotonic()
        text = hear(data)
        timing["hear_s"] = round(time.monotonic() - started, 3)
        timing["heard"] = text
        timing["ear_calls"] = list(voice.ear.calls)
        return text

    voice.hear = timed_hear
    speak = voice.speak

    def timed_speak(text, lang=None, fmt="ogg"):
        started = time.monotonic()
        out = speak(text, lang, fmt)
        timing["speak_s"] = round(time.monotonic() - started, 3)
        timing["speak_sentences"] = list(voice.backend.tts.last_timings)
        return out

    voice.speak = timed_speak
    notes = json.loads((NOTES / "notes.json").read_text())
    steps = []
    for update, note in enumerate(notes, start=1):
        lang = note["id"][:2]
        clock["now"] = at(note["sent_at"])
        timing.clear()
        calls.clear()
        telegram.sent.clear()
        telegram.voices.clear()
        item = Incoming(update, str(users[lang]), "", "parent", str(users[lang]), "private",
                        "es-UY" if lang == "es" else "en", str(NOTES / f"{note['id']}.ogg"))
        started = time.monotonic()
        bot.poll_once_items([item])
        if getattr(bot, "spoken_thread", None):
            bot.spoken_thread.join(120)
            bot.spoken_thread = None
        total = round(time.monotonic() - started, 3)
        reply = "\n".join(telegram.sent)
        ok, what = CHECKS[note["id"]](app, families[lang], reply)
        if telegram.voices and note["id"] in SAMPLES:
            (OUT / f"reply-{note['id']}.ogg").write_bytes(telegram.voices[0])
        steps.append({"id": note["id"], "said": note["text"], "voice": note["voice"], "heard": timing.get("heard"),
                      "reply": reply, "voice_reply_bytes": len(telegram.voices[0]) if telegram.voices else 0,
                      "tools": list(calls), "ear_calls": timing.get("ear_calls", []),
                      "check": what, "ok": bool(ok), "hear_s": timing.get("hear_s"), "speak_s": timing.get("speak_s"),
                      "speak_sentences": timing.get("speak_sentences", []), "total_s": total})
        print(f"{note['id']} {'ok  ' if ok else 'FAIL'} heard={timing.get('heard')!r} | {what} | {calls}", flush=True)
    sentence_s = [t["seconds"] for s in steps for t in s["speak_sentences"]]
    summary = {"ear": EAR_MODEL, "brain": model, "voice": "facebook/mms-tts-spa, facebook/mms-tts-eng (CC-BY-NC 4.0)",
               "notes": len(steps), "ok": sum(s["ok"] for s in steps),
               "ok_es": sum(s["ok"] for s in steps if s["id"].startswith("es")),
               "ok_en": sum(s["ok"] for s in steps if s["id"].startswith("en")),
               "voice_replies": sum(1 for s in steps if s["voice_reply_bytes"]),
               "hear_s_median": median([s["hear_s"] for s in steps if s["hear_s"] is not None]),
               "total_s_median": median([s["total_s"] for s in steps]),
               "tts_sentences": len(sentence_s), "tts_s_per_sentence_median": median(sentence_s),
               "tts_s_per_sentence_max": max(sentence_s) if sentence_s else None,
               "spend_usd": round(app.store.spent_today(), 4), "synthetic_audio": True,
               "ear_calls": sum(len(s["ear_calls"]) for s in steps), "ear_prompt": EAR_PROMPT,
               "failed": [f"{s['id']}: {s['check']} (heard {s['heard']!r})" for s in steps if not s["ok"]]}
    app.close()
    return summary, steps


def median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else round((values[mid - 1] + values[mid]) / 2, 3)


def write(summary, steps):
    (OUT / "run.json").write_text(json.dumps({"summary": summary, "steps": steps}, ensure_ascii=False, indent=2) + "\n")
    lines = [f"# Voice notes run, {datetime.date.today().isoformat()}", "",
             f"{summary['ok']} of {summary['notes']} synthetic voice notes logged right "
             f"({summary['ok_es']} of 10 Spanish, {summary['ok_en']} of 10 English). Ear {summary['ear']}, brain "
             f"{summary['brain']}, voice {summary['voice']}.", "",
             "| note | said (synthetic) | Muse heard | check | ok | ear calls, prompt tokens | hear s | total s |", "|---|---|---|---|---|---|---|---|"]
    for s in steps:
        lines.append(f"| {s['id']} | {s['said']} | {s['heard']} | {s['check']} | {'yes' if s['ok'] else 'NO'} | "
                     f"{len(s['ear_calls'])}, {' '.join(str(c['prompt_tokens']) for c in s['ear_calls'])} | {s['hear_s']} | {s['total_s']} |")
    lines += ["", "## Replies", ""]
    for s in steps:
        lines += [f"**{s['id']}** {s['reply']}".replace("\n", " / "), ""]
    (OUT / "run.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-env", required=True)
    parser.add_argument("--model", default="meta-models/muse-spark-open-1026")
    args = parser.parse_args()
    summary, steps = run(args.keys_env, args.model)
    write(summary, steps)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
