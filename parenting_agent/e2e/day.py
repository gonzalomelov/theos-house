"""One realistic first-month day and night, as the parents live it: what they say, when, and what should follow.

The baby is the e2e child "E2E Baby" (born Oct 1, 28 days old on Oct 29), with Test Baby's test history before the day. Gonza and Ceci write in Spanish, log by message, Ceci asks to sleep tonight, the
grandmother looks after him in the afternoon and writes to the bot herself, a cry at night, a voice note for the
3 AM bottle. Times are the family's (UTC-3). Day 0 is the day the run starts.
"""
import datetime
from pathlib import Path

from .harness import TZ

ROOT = Path(__file__).resolve().parents[2]
VOICE_NOTE = ROOT / "results/voice/notes/es01.ogg"  # "Le di noventa mililitros de mamadera a las tres."


def at(day0, day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime.combine(day0 + datetime.timedelta(days=day), datetime.time(h, m), TZ)


# (day, time, who, text, what the log should get: kind, details)
MESSAGES = [
    (0, "06:10", "gonza", "Le di 80 ml de mamadera.", ("feeding", {"amount": 80})),
    (0, "06:12", "gonza", "Cambié el pañal, estaba mojado.", ("change", {"wet": True})),
    (0, "06:20", "gonza", "Tenemos 26 pañales en casa.", None),
    (0, "06:35", "gonza", "Se durmió.", ("sleep_start", {})),
    (0, "08:05", "ceci", "Se despertó.", ("sleep_end", {})),
    (0, "08:15", "ceci", "Le di teta 15 minutos del lado izquierdo.", ("feeding", {"method": "left breast"})),
    (0, "08:20", "ceci", "Pañal con caca.", ("change", {"solid": True})),
    (0, "08:50", "ceci", "Se durmió de nuevo.", ("sleep_start", {})),
    (0, "10:30", "gonza", "Se despertó.", ("sleep_end", {})),
    (0, "10:40", "gonza", "Tomó 90 ml de mamadera.", ("feeding", {"amount": 90})),
    (0, "10:42", "gonza", "Pañal mojado.", ("change", {"wet": True})),
    (0, "11:20", "grandma", "Hola, soy la abuela. ¿Cuándo comió por última vez?", None),
    (0, "11:22", "ceci", "Mi mamá pregunta cuándo comió por última vez.", None),
    (0, "11:30", "gonza", "Se durmió.", ("sleep_start", {})),
    (0, "12:00", "ceci", "Mi mamá lo cuida hoy de 15 a 18. ¿Le preparás un resumen para ella?", None),
    (0, "13:15", "ceci", "Se despertó.", ("sleep_end", {})),
    (0, "13:25", "ceci", "Le di 90 ml de mamadera.", ("feeding", {"amount": 90})),
    (0, "13:27", "ceci", "Pañal mojado.", ("change", {"wet": True})),
    (0, "13:50", "ceci", "Se durmió.", ("sleep_start", {})),
    (0, "15:40", "gonza", "Se despertó.", ("sleep_end", {})),
    (0, "15:55", "gonza", "Tomó 80 ml.", ("feeding", {"amount": 80})),
    (0, "16:00", "gonza", "Pañal sucio.", ("change", {"solid": True})),
    (0, "16:10", "gonza", "Quedan pocos pañales, agregalos a la lista de compras.", None),
    (0, "16:30", "gonza", "Se durmió.", ("sleep_start", {})),
    (0, "18:20", "ceci", "Se despertó.", ("sleep_end", {})),
    (0, "18:35", "ceci", "Teta 20 minutos, los dos lados.", ("feeding", {"method": "both breasts"})),
    (0, "18:40", "ceci", "Pañal mojado.", ("change", {"wet": True})),
    (0, "19:05", "ceci", "Lo bañamos.", ("bath", {})),
    (0, "19:40", "ceci", "Se durmió para la noche.", ("sleep_start", {})),
    (0, "20:00", "ceci", "Esta noche necesito dormir. ¿Se puede encargar Gonza de la noche?", None),
    (0, "22:20", "gonza", "Se despertó.", ("sleep_end", {})),
    (0, "22:35", "gonza", "Le di 90 ml de mamadera.", ("feeding", {"amount": 90})),
    (0, "22:37", "gonza", "Pañal mojado.", ("change", {"wet": True})),
    (0, "22:55", "gonza", "Se durmió.", ("sleep_start", {})),
    (1, "03:15", "gonza", "Pañal mojado.", ("change", {"wet": True})),
    (1, "03:30", "gonza", "Se durmió.", ("sleep_start", {})),
    (1, "06:05", "gonza", "Se despertó.", ("sleep_end", {})),
    (1, "06:15", "gonza", "Tomó 80 ml.", ("feeding", {"amount": 80})),
]
VOICE = (1, "03:12", "gonza", ("feeding", {"amount": 90, "at": "03:00"}))
CRY = (1, "02:50")
START, END = (0, "06:00"), (1, "08:30")


def script(day0):
    steps = [{"at": at(day0, d, t), "do": "message", "who": who, "text": text, "expect": expect}
             for d, t, who, text, expect in MESSAGES]
    d, t, who, expect = VOICE
    steps.append({"at": at(day0, d, t), "do": "voice", "who": who, "voice": str(VOICE_NOTE), "expect": expect,
                  "text": ""})
    steps.append({"at": at(day0, *CRY), "do": "sound", "label": "cry"})
    return steps


def window(day0):
    return at(day0, *START), at(day0, *END)
