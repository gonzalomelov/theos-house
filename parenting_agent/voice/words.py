"""Numbers and units as words, because MMS-TTS reads letters only and drops digits."""
import re

ES_UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
            "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno",
            "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho",
            "veintinueve"]
ES_TENS = {30: "treinta", 40: "cuarenta", 50: "cincuenta", 60: "sesenta", 70: "setenta", 80: "ochenta", 90: "noventa"}
ES_HUNDREDS = {100: "ciento", 200: "doscientos", 300: "trescientos", 400: "cuatrocientos", 500: "quinientos",
               600: "seiscientos", 700: "setecientos", 800: "ochocientos", 900: "novecientos"}
EN_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
            "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
EN_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty", 60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}
UNITS = {"es": {"ml": "mililitros", "min": "minutos", "h": "horas", "kg": "kilos", "g": "gramos", "%": "por ciento"},
         "en": {"ml": "milliliters", "min": "minutes", "h": "hours", "kg": "kilos", "g": "grams", "%": "percent"}}


def es(n):
    if n < 30:
        return ES_UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return ES_TENS[tens * 10] + (f" y {ES_UNITS[unit]}" if unit else "")
    if n == 100:
        return "cien"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return ES_HUNDREDS[hundreds * 100] + (f" {es(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return ("mil" if thousands == 1 else f"{es(thousands)} mil") + (f" {es(rest)}" if rest else "")


def en(n):
    if n < 20:
        return EN_UNITS[n]
    if n < 100:
        tens, unit = divmod(n, 10)
        return EN_TENS[tens * 10] + (f" {EN_UNITS[unit]}" if unit else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return f"{EN_UNITS[hundreds]} hundred" + (f" {en(rest)}" if rest else "")
    thousands, rest = divmod(n, 1000)
    return f"{en(thousands)} thousand" + (f" {en(rest)}" if rest else "")


def number(n, lang):
    return (es if lang == "es" else en)(n) if n < 1_000_000 else str(n)


def clock(hours, minutes, lang):
    if lang == "es":
        hour = number(hours % 12 or 12, lang)
        if minutes == 0:
            return hour
        if minutes == 30:
            return f"{hour} y media"
        if minutes == 15:
            return f"{hour} y cuarto"
        return f"{hour} y {number(minutes, lang)}"
    hour = number(hours % 12 or 12, lang)
    if minutes == 0:
        return f"{hour} o'clock"
    return f"{hour} {'oh ' + number(minutes, lang) if minutes < 10 else number(minutes, lang)}"


def spoken(text, lang):
    """The text as MMS-TTS can say it: no markdown, clock times, numbers with units and plain numbers as words."""
    text = re.sub(r"[*_#`>«»\"“”]", "", text)
    text = re.sub(r"\s*→\s*", " a " if lang == "es" else " to ", text)
    text = re.sub(r"\s*\+\s*", " y " if lang == "es" else " and ", text)
    text = re.sub(r"\s*\+\s*", " y " if lang == "es" else " and ", text)
    text = re.sub(r"\s*[—–•]\s*", ", ", text)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: clock(int(m.group(1)), int(m.group(2)), lang), text)
    units = UNITS["es" if lang == "es" else "en"]

    def with_unit(m):
        value = m.group(1).replace(",", ".")
        whole, _, frac = value.partition(".")
        said = number(int(whole), lang) + (f" {'coma' if lang == 'es' else 'point'} {' '.join(number(int(d), lang) for d in frac)}" if frac else "")
        unit = m.group(2)
        return said + (f" {units[unit.lower()]}" if unit else "")

    text = re.sub(r"(\d+(?:[.,]\d+)?)\s*(ml|min|h|kg|g|%)?(?![\w])", with_unit, text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?¡¿])\s+|\n+", text) if s.strip()]
