"""Dates and times as a speaker says them: "ayer a las 10:55", never "2026-10-31" or "07:50".

The Echo read "2026-10-31" out loud on Oct 31. Every spoken reply goes through natural_dates, and the Echo's own
confirmations are built with when().
"""
import datetime
import re

MONTHS = {"es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                 "noviembre", "diciembre"],
          "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"]}
RELATIVE = {"es": {0: "hoy", 1: "ayer", 2: "anteayer", -1: "mañana"},
            "en": {0: "today", 1: "yesterday", 2: "the day before yesterday", -1: "tomorrow"}}
ISO = re.compile(r"(?:\b(el|del|on)\s+)?\b(\d{4})-(\d{2})-(\d{2})"
                 r"(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b", re.I)
DAY_MONTH = re.compile(r"\b(del|on)\s+(\d{1,2})/(\d{1,2})\b", re.I)
# "07:50" is said "7:50". The hour after midnight keeps its two zeros, "00:34", never "0:34".
LEADING_ZERO = re.compile(r"(?<![\d:])0([1-9]):(\d{2})\b")


def clock(hour, minute):
    return f"{int(hour) or '00'}:{int(minute):02d}"


def at_words(hour, minute, lang):
    """"a las 7:50", "a la 1:05", "at 7:50"."""
    if lang == "es":
        return ("a la " if int(hour) == 1 else "a las ") + clock(hour, minute)
    return "at " + clock(hour, minute)


def day_words(day, today, lang, prep=None):
    """"hoy", "ayer", "el 28 de octubre" (or "del 28 de octubre" after "del"), "on October 28"."""
    lang = lang if lang in MONTHS else "en"
    word = RELATIVE[lang].get((today - day).days)
    if word:
        return ("de " + word) if lang == "es" and prep and prep.lower() == "del" else word
    if lang == "es":
        return f"{'del' if prep and prep.lower() == 'del' else 'el'} {day.day} de {MONTHS['es'][day.month - 1]}"
    return f"on {MONTHS['en'][day.month - 1]} {day.day}"


def when(moment, now, lang):
    """A moment as the Echo says it: "a las 7:50" today, "ayer a las 10:55" another day."""
    local = moment.astimezone(now.tzinfo) if moment.tzinfo and now.tzinfo else moment
    at = at_words(local.hour, local.minute, lang)
    if local.date() == now.date():
        return at
    return f"{day_words(local.date(), now.date(), lang)} {at}"


def natural_dates(text, now, lang):
    """Every ISO date, "del 31/10" and "07:50" in a reply said the way a person says it."""
    lang = lang if lang in MONTHS else "en"
    today = now.date()

    def iso(match):
        prep, year, month, day, hour, minute = match.groups()
        try:
            date = datetime.date(int(year), int(month), int(day))
        except ValueError:
            return match.group(0)
        said = day_words(date, today, lang, prep)
        return said + (" " + at_words(hour, minute, lang) if hour is not None else "")

    def day_month(match):
        prep, day, month = match.groups()
        try:
            date = datetime.date(today.year, int(month), int(day))
        except ValueError:
            return match.group(0)
        if date > today:
            date = date.replace(year=today.year - 1)
        return day_words(date, today, lang, prep)

    text = ISO.sub(iso, str(text or ""))
    text = DAY_MONTH.sub(day_month, text)
    text = LEADING_ZERO.sub(r"\1:\2", text)
    if lang == "es":
        text = re.sub(r"\b(a|de|desde|hasta) las 1:(\d{2})\b", r"\1 la 1:\2", text)
    return text
