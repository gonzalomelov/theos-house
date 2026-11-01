"""The pediatrician visit summary (first month): the checkups, the questions the parents keep for them, and a short summary of
the log for the visit.

In the first month there are checkups in the first days, at about one week and at about one month. The parents say it in
their own words, on Telegram, the glasses or the Echo:

| A parent says | The agent |
|---|---|
| "turno con la pediatra el jueves 10:00", "control con la pediatra mañana a las 9, va Ceci" | keeps the visit in the agent's appointments (prep_appointments, the same calendar as the prep appointments) and says when the summary goes out |
| "preguntarle a la pediatra si es normal que..." | keeps the question on the open list, in the parent's words |
| "resumen para la pediatra" | the summary now |
| "preguntas para la pediatra" | the open questions, numbered |
| "la pediatra dijo que..." | a note in the baby log in the parent's words, the visit marked done |
| "cerrar pregunta 2", "cerrar todas las preguntas" | the question leaves the open list |
| "cancelá el turno con la pediatra" | the next visit is removed |

The day before the visit (eve_at, 19:00) and the morning of it (morning_at, 08:00, or 90 minutes before an early visit)
each parent, or only the one going, gets the summary in their own language (the people block, Spanish when it is not
set). It covers the log since the last visit, or since birth: feeds per day with the usual amounts and sides, diapers
per day wet and dirty, sleep per day, the notes the parents logged, the weight when one is logged, and the open
questions. Every number is computed here, in plain code, from the log.

It is strictly descriptive: no interpretation, no advice, never "normal" or "abnormal" in its own words, and the last
line says the pediatrician is the one who decides. Muse Spark Open does one thing: it writes each question the parents
keep as one short question in Spanish and in English. Its words are checked (the same numbers, no advice words the
parent did not say) and the parent's own words stand when Muse is off, slow, out of budget or fails the check.

The first two lines of every summary fit a glance: the glasses card (hud_cards.py, topic "pediatrician") shows them.
The Echo (voice_bridge.py) reads spoken(), a few short sentences with no question text, since anyone in the kitchen can
hear it. A red flag or a newborn call-now sign is never taken here: the agent's fixed lines answer it first.

Before the birth ("baby": {"born": false}) the log holds test entries only, so the summary carries only the questions.

Add "parenting_agent.pediatrician:Pediatrician" to the plug-ins. Settings under "pediatrician": eve_at, morning_at,
check_every_s, budget_usd (Muse, per day), muse (house_brain.MUSE keys).
"""
import datetime
import re
import statistics
import threading
import unicodedata
from collections import Counter

from . import baby_phase
from .agent import final_guard, rules
from .agent.memory import parse_time
from .agent.plugins import Plugin
from .prep import SCHEMA as PREP_SCHEMA
from .rhythm.engine import DEFAULTS as RHYTHM_DEFAULTS

SCHEMA = """
create table if not exists pedi_visits (id integer primary key, appointment_id integer, starts_at text, who text,
  added_by text, ts text, cancelled integer default 0, done_ts text);
create table if not exists pedi_questions (id integer primary key, text text, es text, en text, asked_by text, ts text,
  closed integer default 0, closed_by text, closed_ts text);
create table if not exists pedi_sent (visit_id integer, slot text, person text, ts text, status text,
  primary key (visit_id, slot, person));
"""
DEFAULTS = {"eve_at": "19:00", "morning_at": "08:00", "early_lead_min": 90, "check_every_s": 30, "budget_usd": 0.2,
            "muse": {"max_tokens": 3000, "timeout_s": 30}}
MAX_OPEN_QUESTIONS = 30
MAX_QUESTION_CHARS = 300
MAX_NOTES = 6
TITLE = {"es": "Control con la pediatra", "en": "Pediatrician checkup"}

# What a parent says. Each is matched on the message lower case with its accents folded (aligned()).
PEDI = r"(?:pediatr[ao]s?|pediatrician|doctor)"
SUMMARY = re.compile(rf"\bresumen\b[^.?!]*\b{PEDI}|\b{PEDI}\b[^.?!]*\bresumen\b|\bsummary\b[^.?!]*\b{PEDI}|"
                     rf"\b{PEDI}\b[^.?!]*\bsummary\b", re.I)
QUESTION = re.compile(r"^\s*(?:(?:hay que|tengo que|tenemos que|acordate de|anota(?:me)?|agrega(?:le)?)\s+(?:de\s+)?)?"
                      r"(?:pregunt(?:arle|ale|ar|emosle)|consultar(?:le)?)\s+(?:a\s+)?(?:la|el)\s+pediatra\b\s*[,:]?\s*"
                      r"(?P<q>.+)$|"
                      r"^\s*(?:una\s+)?pregunta\s+para\s+(?:la|el)\s+pediatra\s*[,:]\s*(?P<q2>.+)$|"
                      r"^\s*(?:(?:remember|we need|i need|need)\s+to\s+)?ask\s+the\s+(?:pediatrician|doctor)\s*[,:]?\s*"
                      r"(?P<q3>.+)$|"
                      r"^\s*(?:a\s+)?question\s+for\s+the\s+(?:pediatrician|doctor)\s*[,:]\s*(?P<q4>.+)$", re.I | re.S)
SAID = re.compile(r"^\s*(?:la|el)\s+pediatra\s+(?:nos\s+|me\s+|le\s+)?(?:dijo|comento|explico|indico|recomendo|mando)"
                  r"\s*[,:]?\s*(?P<s>.+)$|"
                  r"^\s*the\s+(?:pediatrician|doctor)\s+(?:said|told us|told me)\s*[,:]?\s*(?P<s2>.+)$", re.I | re.S)
CLOSE = re.compile(r"\bcerr(?:a|ar)\s+(?:la\s+)?pregunta\s+(?:numero\s+|n\s*)?(?P<n>\d+)|"
                   r"\bclose\s+question\s+(?:number\s+)?(?P<n2>\d+)", re.I)
CLOSE_ALL = re.compile(r"\bcerr(?:a|ar)\s+todas\s+las\s+preguntas|\bclose\s+all\s+(?:the\s+)?questions", re.I)
LIST = re.compile(rf"\b(?:las\s+)?preguntas\s+(?:para|de)\s+(?:la|el)\s+pediatra\b|"
                  rf"\bque\s+le\s+(?:ibamos|vamos|queriamos)\s+a\s+preguntar\b[^.?!]*\bpediatra|"
                  rf"\bquestions\s+for\s+the\s+(?:pediatrician|doctor)\b", re.I)
CANCEL = re.compile(rf"\b(?:cancela(?:r|mos)?|cancele|suspendi(?:o|mos)?|se\s+suspendio)\b[^.?!]*\b{PEDI}|"
                    rf"\bcancel(?:led|ed)?\b[^.?!]*\b{PEDI}", re.I)
VISIT = re.compile(rf"\b(?:turno|consulta|control|cita|hora|vamos|voy|va|lo\s+llevamos|appointment|visit|checkup|"
                   rf"check-up)\b[^.?!]*\b{PEDI}|\b{PEDI}\b[^.?!]*\b(?:turno|consulta|control|appointment|visit|checkup)\b",
                   re.I)
VISIT_NOUN = re.compile(r"\b(?:turno|consulta|control|cita|hora\s+con|appointment|visit|checkup|check-up)\b", re.I)
WHEN_QUESTION = re.compile(r"^\s*(?:cuando|a\s+que\s+hora|que\s+dia|when|what\s+time)\b|\?\s*$", re.I)

# The log's routine notes, never a note for the pediatrician: baths, the night rota, the skills' own lines.
ROUTINE_NOTE = re.compile(r"^\s*(?:\[simulated\]\s*)?(?:bath\b|bano\b|night wake-up handled by|despertar de noche)|"
                          r"logged by the|logged by changing-table|^\s*note\s*$|^\s*(?:stock|supplies|insumos)\b", re.I)
WEIGHT = re.compile(r"\b(?:pes(?:o|a|aba|aron)|weigh(?:s|ed|t)?)\b[^.\n]*?\b(?P<v>\d+(?:[.,]\d+)?)\s*"
                    r"(?P<u>kg|kilos?|g|gr|gramos|grams)\b", re.I)
ADVICE = re.compile(r"\b(?:normal\w*|anormal\w*|abnormal|preocup\w*|tranquil\w*|recomend\w*|recommend\w*|deber\w*|"
                    r"should|probabl\w*|seguramente|likely|worr\w*|consult\w*|diagnos\w*|grave|serious|dosis|dose|"
                    r"tratamiento|treatment|sano|healthy|bien\b|fine\b|ok\b)", re.I)
WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6,
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
          "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12, "january": 1, "february": 2,
          "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
          "november": 11, "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
DAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
DAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
COLORS_ES = {"yellow": "amarillo", "green": "verde", "brown": "marrón", "black": "negro", "red": "rojo", "white": "blanco"}

TEXT = {
    "es": {
        "head_eve": "{title} mañana, {day}, a las {hhmm}.", "head_morning": "{title} hoy a las {hhmm}.",
        "head_now": "Resumen para la pediatra.", "head_now_next": "Resumen para la pediatra. Próximo control: {day} a las {hhmm}.",
        "glance": "Por día: {feeds} tomas, {diapers} pañales, {sleep} de sueño.",
        "glance_empty": "Todavía no hay registros para resumir.",
        "glance_prep": "{name} todavía no nació: el resumen del registro empieza cuando nazca.",
        "since_birth": "Desde el nacimiento ({day}).", "since_visit": "Desde el último control ({day}).",
        "since_first": "Desde el primer registro ({day}).",
        "days": "Los números por día son de {n} días completos, del {first} al {last}.",
        "days_one": "Los números son de 1 día, el {first}.",
        "feeds": "Tomas: por lo general {mid} por día (entre {lo} y {hi}).",
        "breast": "Pecho en esos días: {parts}.", "left": "izquierdo {n}", "right": "derecho {n}", "both": "los dos {n}",
        "side_unknown": "sin lado anotado {n}",
        "bottle": "Mamadera en esos días: {n}{milk}{amount}.", "milk": " ({parts})", "breast_milk": "leche materna {n}",
        "formula": "fórmula {n}", "amount": ", por lo general {mid} ml (entre {lo} y {hi} ml)",
        "diapers": "Pañales: por lo general {mid} por día (entre {lo} y {hi}): {wet} mojados y {dirty} sucios por día.",
        "diaper_both": "Un pañal puede estar mojado y sucio a la vez.",
        "colors": "Colores anotados: {parts}.",
        "sleep": "Sueño: por lo general {mid} por día (entre {lo} y {hi}).",
        "sleep_days": "Sueño: por lo general {mid} por día (entre {lo} y {hi}), en {n} días con sueño anotado.",
        "no_sleep": "Sueño: no hay sueño anotado en esos días.",
        "weight": "Peso: {value} el {day}.", "no_weight": "Peso: no hay un peso anotado.",
        "notes": "Notas que anotaron:", "notes_some": "Notas que anotaron (las {n} más recientes de {total}):",
        "no_notes": "Notas: ninguna anotada.",
        "questions": "Preguntas para la pediatra ({n}):",
        "no_questions": "Preguntas para la pediatra: ninguna anotada. Para sumar una: «preguntarle a la pediatra si...».",
        "unread": "No pude leer el registro ahora, así que van solo las preguntas.",
        "closing": "Es solo lo que anotaron, sin interpretar: la pediatra es quien evalúa y decide.",
        "spoken": "Para la pediatra, {since}: por día, unas {feeds} tomas, {diapers} pañales, {wet} mojados y {dirty} "
                  "sucios, y {sleep} de sueño.",
        "spoken_since_birth": "desde el nacimiento", "spoken_since_visit": "desde el último control",
        "spoken_since_first": "desde el primer registro",
        "spoken_questions": "Hay {n} preguntas anotadas.", "spoken_question": "Hay una pregunta anotada.",
        "spoken_no_questions": "No hay preguntas anotadas.",
        "spoken_closing": "Es lo que anotaron, la pediatra es quien decide.",
        "kept_visit": "Anotado: {title}, {day} a las {hhmm}{who}. {to} el resumen para la pediatra {when}.",
        "to_you": "Te mando", "to_both": "Les mando a los dos", "to_one": "Le mando a {name}",
        "who": ", va {name}", "both_go": "", "send_eve": "el día antes a las {eve} y el mismo día a las {morning}",
        "send_morning": "el mismo día a las {morning}", "send_now": "ahora mismo si me decís «resumen para la pediatra»",
        "when_missing": "¿Qué día y a qué hora es? Por ejemplo: «turno con la pediatra el jueves 10:00».",
        "past": "Esa fecha ya pasó. Decime el día y la hora del próximo control.",
        "next_visit": "El próximo control con la pediatra es el {day} a las {hhmm}{who}.",
        "no_visit": "No tengo un control con la pediatra anotado. Decime, por ejemplo: «turno con la pediatra el jueves 10:00».",
        "cancelled": "Listo, saqué el control del {day} a las {hhmm}.",
        "kept_question": "Anotado para la pediatra: {q} Ya son {n} preguntas.",
        "kept_question_one": "Anotado para la pediatra: {q} Es la primera pregunta.",
        "too_many": "Ya hay {n} preguntas abiertas. Cerrá alguna con «cerrar pregunta 1».",
        "no_secret": "Eso tiene un código o un número largo, no lo guardo en la lista para la pediatra.",
        "empty_question": "¿Qué le querés preguntar? Por ejemplo: «preguntarle a la pediatra si...».",
        "list": "Preguntas para la pediatra:", "list_empty": "No hay preguntas abiertas para la pediatra.",
        "closed": "Listo, cerré la pregunta {n}: {q}", "closed_all": "Listo, cerré las {n} preguntas.",
        "no_such": "No hay una pregunta {n}. Hay {total} abiertas.",
        "said": "Anotado en el registro: «{s}». ", "said_open": "Siguen abiertas: {list} Para cerrar una, decime «cerrar pregunta 1».",
        "said_none": "No quedan preguntas abiertas.",
        "said_failed": "No pude anotarlo en el registro ahora ({why}). Mandámelo de nuevo en un rato.",
    },
    "en": {
        "head_eve": "{title} tomorrow, {day}, at {hhmm}.", "head_morning": "{title} today at {hhmm}.",
        "head_now": "Summary for the pediatrician.",
        "head_now_next": "Summary for the pediatrician. Next checkup: {day} at {hhmm}.",
        "glance": "Per day: {feeds} feeds, {diapers} diapers, {sleep} of sleep.",
        "glance_empty": "There are no log entries to sum up yet.",
        "glance_prep": "{name} is not born yet: the log summary starts when he is born.",
        "since_birth": "Since birth ({day}).", "since_visit": "Since the last checkup ({day}).",
        "since_first": "Since the first log entry ({day}).",
        "days": "The per day numbers come from {n} full days, {first} to {last}.",
        "days_one": "The numbers come from 1 day, {first}.",
        "feeds": "Feeds: usually {mid} a day (from {lo} to {hi}).",
        "breast": "Breast on those days: {parts}.", "left": "left {n}", "right": "right {n}", "both": "both {n}",
        "side_unknown": "no side logged {n}",
        "bottle": "Bottle on those days: {n}{milk}{amount}.", "milk": " ({parts})", "breast_milk": "breast milk {n}",
        "formula": "formula {n}", "amount": ", usually {mid} ml (from {lo} to {hi} ml)",
        "diapers": "Diapers: usually {mid} a day (from {lo} to {hi}): {wet} wet and {dirty} dirty a day.",
        "diaper_both": "One diaper can be wet and dirty at once.",
        "colors": "Colors logged: {parts}.",
        "sleep": "Sleep: usually {mid} a day (from {lo} to {hi}).",
        "sleep_days": "Sleep: usually {mid} a day (from {lo} to {hi}), on {n} days with sleep logged.",
        "no_sleep": "Sleep: no sleep logged on those days.",
        "weight": "Weight: {value} on {day}.", "no_weight": "Weight: none logged.",
        "notes": "Notes you logged:", "notes_some": "Notes you logged (the {n} newest of {total}):",
        "no_notes": "Notes: none logged.",
        "questions": "Questions for the pediatrician ({n}):",
        "no_questions": "Questions for the pediatrician: none yet. To add one: \"ask the pediatrician if...\".",
        "unread": "I could not read the log just now, so only the questions follow.",
        "closing": "This is only what you logged, with no interpretation: the pediatrician is the one who assesses and decides.",
        "spoken": "For the pediatrician, {since}: a day, about {feeds} feeds, {diapers} diapers, {wet} wet and {dirty} "
                  "dirty, and {sleep} of sleep.",
        "spoken_since_birth": "since birth", "spoken_since_visit": "since the last checkup",
        "spoken_since_first": "since the first log entry",
        "spoken_questions": "There are {n} questions kept.", "spoken_question": "There is one question kept.",
        "spoken_no_questions": "There are no questions kept.",
        "spoken_closing": "It is what you logged, the pediatrician decides.",
        "kept_visit": "Kept: {title}, {day} at {hhmm}{who}. {to} the summary for the pediatrician {when}.",
        "to_you": "I will send you", "to_both": "I will send you both", "to_one": "I will send {name}",
        "who": ", {name} is going", "both_go": "", "send_eve": "the day before at {eve} and that morning at {morning}",
        "send_morning": "that morning at {morning}", "send_now": "right away if you say \"pediatrician summary\"",
        "when_missing": "What day and time is it? For example: \"pediatrician appointment Thursday 10:00\".",
        "past": "That time has passed. Tell me the day and time of the next checkup.",
        "next_visit": "The next pediatrician checkup is {day} at {hhmm}{who}.",
        "no_visit": "I have no pediatrician checkup kept. Tell me, for example: \"pediatrician appointment Thursday 10:00\".",
        "cancelled": "Done, I removed the checkup of {day} at {hhmm}.",
        "kept_question": "Kept for the pediatrician: {q} That makes {n} questions.",
        "kept_question_one": "Kept for the pediatrician: {q} It is the first question.",
        "too_many": "There are already {n} open questions. Close one with \"close question 1\".",
        "no_secret": "That holds a code or a long number, I do not keep it on the pediatrician list.",
        "empty_question": "What do you want to ask? For example: \"ask the pediatrician if...\".",
        "list": "Questions for the pediatrician:", "list_empty": "There are no open questions for the pediatrician.",
        "closed": "Done, I closed question {n}: {q}", "closed_all": "Done, I closed the {n} questions.",
        "no_such": "There is no question {n}. There are {total} open.",
        "said": "Kept in the log: \"{s}\". ", "said_open": "Still open: {list} To close one, say \"close question 1\".",
        "said_none": "No questions are left open.",
        "said_failed": "I could not keep it in the log just now ({why}). Send it again in a while.",
    },
}
TIDY_SYSTEM = (
    "You tidy one question that parents want to ask their newborn's pediatrician. Write it as one short question in "
    "Spanish (Uruguay, voseo) and the same question in English. Keep the parents' meaning, every detail and every "
    "number exactly. Never answer it, never add advice, a reason, a cause, a diagnosis, or a word such as normal, "
    "worry or should that the parents did not say. Only the question, starting with ¿ in Spanish. "
    'Answer JSON: {"es": "...", "en": "..."}')
TIDY_SCHEMA = {"type": "object", "properties": {"es": {"type": "string"}, "en": {"type": "string"}},
               "required": ["es", "en"], "additionalProperties": False}


def plain(text):
    """Lower case with the accents folded, for matching what a parent said."""
    folded = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(folded.lower().split())


def aligned(text):
    """(plain words, where): the message lower case with accents folded, and for each of its characters the index of
    the character it came from in the message with its spaces collapsed, so a match gives back the parent's own words."""
    original = " ".join(str(text or "").split())
    out, where = [], []
    for i, char in enumerate(original):
        for each in unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode().lower():
            out.append(each)
            where.append(i)
    return "".join(out), where


def lang_of(lang):
    return "en" if lang == "en" else "es"


# When: the day and the time a parent said, in plain code.

def parse_when(text, now):
    """(datetime or None, what is missing). Days: hoy, mañana, pasado mañana, a weekday, 6/11, 6 de noviembre, Nov 6.
    Times: 10:00, 10.30, 10 y media, a las 10, 10 hs, 3 pm, 3 de la tarde. An hour from 1 to 7 with no morning mark is
    in the afternoon."""
    words = plain(text)
    day = None
    found = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", words)
    if found:
        d, m, y = int(found.group(1)), int(found.group(2)), found.group(3)
        year = (2000 + int(y) if len(y) == 2 else int(y)) if y else now.year
        try:
            day = datetime.date(year, m, d)
        except ValueError:
            return None, "day"
        if not y and day < now.date() - datetime.timedelta(days=1):
            day = day.replace(year=year + 1)
        words = words.replace(found.group(0), " ")
    if day is None:
        found = re.search(r"\b(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")\b", words) or \
            re.search(r"\b(" + "|".join(MONTHS) + r")\w*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", words)
        if found:
            a, b = found.groups()
            d, m = (int(a), MONTHS[b]) if a.isdigit() else (int(b), MONTHS[a])
            try:
                day = datetime.date(now.year, m, d)
            except ValueError:
                return None, "day"
            if day < now.date() - datetime.timedelta(days=1):
                day = day.replace(year=now.year + 1)
            words = words.replace(found.group(0), " ")
    weekday = None
    if day is None:
        if re.search(r"\bpasado\s+manana\b|\bday after tomorrow\b", words):
            day = now.date() + datetime.timedelta(days=2)
        elif re.search(r"(?<!a la )(?<!de la )(?<!por la )\bmanana\b(?!\s+(?:a la|de la)\b)|\btomorrow\b", words) and \
                not re.search(r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", words):
            day = now.date() + datetime.timedelta(days=1)
        elif re.search(r"\bhoy\b|\btoday\b", words):
            day = now.date()
        else:
            found = re.search(r"\b(" + "|".join(WEEKDAYS) + r")\b", words)
            if found:
                weekday = WEEKDAYS[found.group(1)]
    hhmm = None
    found = re.search(r"\b(\d{1,2})[:.h](\d{2})\b", words)
    if found:
        hhmm = int(found.group(1)), int(found.group(2))
    else:
        found = re.search(r"\b(\d{1,2})\s+y\s+(media|cuarto)\b", words) or \
            re.search(r"\b(?:a\s+las|a\s+la|at)\s+(\d{1,2})\b()", words) or \
            re.search(r"\b(\d{1,2})\s*(?:hs|h|horas|am|pm|a\.m\.|p\.m\.)()", words)
        if found:
            hhmm = int(found.group(1)), {"media": 30, "cuarto": 15}.get(found.group(2), 0)
    if hhmm is None:
        return None, "time"
    hour, minute = hhmm
    after_noon = re.search(r"\bde\s+la\s+(?:tarde|noche)\b|\bpm\b|\bp\.m\.|\bin the (?:afternoon|evening)\b", words)
    morning = re.search(r"\bde\s+la\s+manana\b|\ba\s+la\s+manana\b|\bam\b|\ba\.m\.|\bin the morning\b", words)
    if hour < 12 and (after_noon or (1 <= hour <= 7 and not morning)):
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, "time"
    if weekday is not None:
        ahead = (weekday - now.weekday()) % 7
        day = now.date() + datetime.timedelta(days=ahead)
        if ahead == 0 and datetime.time(hour, minute) <= now.time():
            day += datetime.timedelta(days=7)
    if day is None:
        return None, "day"
    return datetime.datetime.combine(day, datetime.time(hour, minute), now.tzinfo), None


# The numbers, in plain code

def _int_median(values):
    return int(round(statistics.median(values))) if values else 0


def _method(details):
    method = str(details.get("method") or "").lower()
    if "left" in method or "izquierd" in method:
        return "left"
    if "right" in method or "derech" in method:
        return "right"
    if "both" in method or "ambos" in method:
        return "both"
    if "bottle" in method or "mamadera" in method:
        return "bottle"
    if "breast" in method or "pecho" in method or "teta" in method:
        return "breast"
    return "bottle" if details.get("amount_ml") is not None else "breast"


def _sleep_minutes(entry, tz):
    details = entry.get("details") or {}
    if details.get("duration_min") is not None:
        return float(details["duration_min"])
    if details.get("start"):
        return max(0.0, (parse_time(entry["ts"], tz) - parse_time(details["start"], tz)).total_seconds() / 60)
    return None


def _note_text(entry):
    return " ".join(str((entry.get("details") or {}).get("text") or "").split())


def full_days(dates):
    """The days the per-day numbers count: the first and the last day of the log are cut short (the birth, today), so
    the days between them, when there are two or more. Otherwise every day that has an entry."""
    dates = sorted(set(dates))
    if len(dates) >= 4:
        inner = [d for d in dates if dates[0] < d < dates[-1]]
        if len(inner) >= 2:
            return inner
    return dates


def facts(entries, start, end, tz):
    """Everything the summary says, computed from the log entries between start and end."""
    kept = [e for e in entries if start <= parse_time(e["ts"], tz) <= end]
    dates = [parse_time(e["ts"], tz).date() for e in kept]
    days = full_days(dates)
    counted = set(days)
    per_day = {d: Counter() for d in days}
    sides, milks, amounts, colors = Counter(), Counter(), [], Counter()
    sleep_by_day, notes, weights, both = {}, [], [], 0
    for entry in kept:
        moment = parse_time(entry["ts"], tz)
        details = entry.get("details") or {}
        kind, here = entry.get("kind"), moment.date() in counted
        if kind == "feeding" and here:
            per_day[moment.date()]["feeds"] += 1
            method = _method(details)
            if method == "bottle":
                sides["bottle"] += 1
                milk = str(details.get("type") or "").lower()
                milks["formula" if "formula" in milk else "breast_milk" if "breast" in milk else "unknown"] += 1
                if details.get("amount_ml") is not None:
                    amounts.append(float(details["amount_ml"]))
            else:
                sides[method] += 1
        elif kind == "diaper":
            wet, dirty = bool(details.get("wet")), bool(details.get("solid"))
            if here:
                per_day[moment.date()]["diapers"] += 1
                per_day[moment.date()]["wet"] += wet
                per_day[moment.date()]["dirty"] += dirty
                both += wet and dirty
            if details.get("color"):
                colors[str(details["color"]).lower()] += 1
        elif kind == "sleep" and here:
            minutes = _sleep_minutes(entry, tz)
            if minutes is not None:
                sleep_by_day[moment.date()] = sleep_by_day.get(moment.date(), 0) + minutes
        elif kind == "note":
            text = _note_text(entry)
            if not text or ROUTINE_NOTE.search(text):
                continue
            notes.append({"at": moment, "text": text})
            weight = WEIGHT.search(plain(text))
            if weight:
                weights.append({"at": moment, "value": weight.group("v").replace(",", "."), "unit": weight.group("u")})

    def spread(key):
        values = [per_day[d][key] for d in days]
        return {"mid": _int_median(values), "lo": min(values, default=0), "hi": max(values, default=0)}

    sleep_values = [sleep_by_day[d] for d in days if d in sleep_by_day]
    return {
        "entries": len(kept), "days": days,
        "feeds": spread("feeds"), "diapers": spread("diapers"), "wet": spread("wet"), "dirty": spread("dirty"),
        "diaper_both": both,
        "sides": dict(sides), "milks": dict(milks),
        "amount": ({"mid": _int_median(amounts), "lo": int(min(amounts)), "hi": int(max(amounts))} if amounts else None),
        "colors": dict(colors),
        "sleep": ({"mid": statistics.median(sleep_values), "lo": min(sleep_values), "hi": max(sleep_values),
                   "days": len(sleep_values)} if sleep_values else None),
        "notes": notes, "weight": weights[-1] if weights else None,
    }


def length(minutes, lang):
    minutes = int(round(minutes))
    h, m = divmod(minutes, 60)
    if lang == "spoken_es":
        return f"{h} horas" + (f" {m}" if m else "") if h else f"{m} minutos"
    if lang == "spoken_en":
        return f"{h} hours" + (f" {m} minutes" if m else "") if h else f"{m} minutes"
    return (f"{h} h {m} min" if m else f"{h} h") if h else f"{m} min"


def short_day(day):
    return f"{day.day}/{day.month}"


def long_day(day, lang):
    return f"{DAYS_ES[day.weekday()]} {day.day}/{day.month}" if lang == "es" else f"{DAYS_EN[day.weekday()]} {day.strftime('%b')} {day.day}"


def weight_text(weight, lang):
    value, unit = float(weight["value"]), plain(weight["unit"])
    if unit.startswith("k"):
        number, unit = (f"{value:.3f}".rstrip("0").rstrip("."), "kg")
    else:
        number, unit = (f"{value:.0f}", "g")
    return number.replace(".", ",") if lang == "es" else number, unit


def quoted(text, lang):
    text = text.replace("«", "").replace("»", "").replace('"', "")
    return f"«{text}»" if lang == "es" else f'"{text}"'


class Pediatrician(Plugin):
    name = "pediatrician"
    kind = "skill"

    def __init__(self, agent, config, clock=None, muse=None):
        super().__init__(agent, config)
        raw = config.get("pediatrician") or {}
        self.cfg = {**DEFAULTS, **raw, "muse": {**DEFAULTS["muse"], **(raw.get("muse") or {})}}
        rhythm = {**RHYTHM_DEFAULTS, **config.get("rhythm", {})}
        self.tz = datetime.timezone(datetime.timedelta(hours=rhythm["utc_offset_h"]))
        self.clock = clock or (lambda: datetime.datetime.now(self.tz))
        self.muse = muse
        self.phase = baby_phase.phase(config)
        self.baby = (config.get("baby") or {}).get("name")
        self.birth = (config.get("baby") or {}).get("birth_date")
        self.spend = {"day": None, "usd": 0.0}
        self.db, self.lock = agent.memory.db, agent.memory.lock
        with self.lock:
            self.db.executescript(PREP_SCHEMA + SCHEMA)
        self.stopped = threading.Event()
        self.thread = None
        agent.answer_takers = [*getattr(agent, "answer_takers", []), self.take]

    # Who, when, in which language

    def now(self):
        return self.clock().astimezone(self.tz)

    def people(self):
        return getattr(self.agent, "people", None)

    def person_lang(self, person, text=None):
        """The parent's language from the people block, else the message's when it is plainly English, else Spanish."""
        people = self.people()
        lang = people.lang(person) if people and person else None
        if lang:
            return lang
        if text and not rules.looks_spanish(text) and len(rules.ENGLISH.findall(text)) >= 2:
            return "en"
        return "es"

    def publish(self, action, **fields):
        event = getattr(self.agent, "current_event", None) or {}
        self.agent.bus.publish("pediatrician", action=action, person=event.get("person"), channel=event.get("channel"),
                               **fields)

    # What a parent says

    def take(self, event, text):
        """The agent's answer taker: the reply, or None to leave the message to the agent. Red flags and newborn
        call-now signs are always left to the agent's fixed lines."""
        words, where = aligned(text)
        if "pediatr" not in words and "doctor" not in words and not CLOSE.search(words) and not CLOSE_ALL.search(words):
            return None
        if rules.is_emergency(text) or rules.newborn_red_flag(text):
            return None
        person = event.get("person")
        lang = self.person_lang(person, text)

        def said_words(match):
            start = next(match.start(g) for g in range(1, len(match.groups()) + 1) if match.group(g))
            return " ".join(str(text).split())[where[start]:].strip() if start < len(where) else ""

        if CLOSE_ALL.search(words):
            return self.close_all(lang)
        found = CLOSE.search(words)
        if found:
            return self.close(int(found.group("n") or found.group("n2")), lang)
        found = SAID.match(words)
        if found:
            return self.said(said_words(found), lang)
        found = QUESTION.match(words)
        if found:
            return self.add_question(said_words(found), lang, person)
        if SUMMARY.search(words):
            return self.glance(lang) if event.get("channel") == "glasses" else self.summary(lang, "now")
        if CANCEL.search(words):
            return self.cancel_next(lang)
        if LIST.search(words):
            return self.list_questions(lang)
        if VISIT.search(words):
            if WHEN_QUESTION.search(words) and not re.search(r"\d", words):
                return self.next_visit(lang)
            if parse_when(text, self.now())[0] is None and not VISIT_NOUN.search(words):
                return None  # "voy a llamar a la pediatra": not a visit, the agent answers it
            return self.add_visit(text, lang, person)
        return None

    # Visits

    def visits(self, include_done=False):
        query = "select id, appointment_id, starts_at, who, done_ts from pedi_visits where cancelled = 0"
        with self.lock:
            rows = self.db.execute(query + ("" if include_done else " and done_ts is null") + " order by starts_at").fetchall()
        return [{"id": i, "appointment_id": a, "starts_at": datetime.datetime.fromisoformat(s), "who": w, "done": d}
                for i, a, s, w, d in rows]

    def upcoming(self):
        now = self.now()
        return [v for v in self.visits() if v["starts_at"] > now]

    def who_from(self, text, person):
        words = plain(text)
        people = self.people()
        if re.search(r"\bvamos\s+(?:los\s+dos|juntos|ambos)\b|\bboth of us\b|\bwe(?:'re| are) both going\b", words):
            return None
        if re.search(r"\bvoy\s+yo\b|\bva\s+a\s+ir\s+yo\b|\bi(?:'m| am) (?:going|taking)\b|\bi(?:'ll| will) (?:go|take)\b",
                     words):
            return person if people and people.person(person) else None
        found = re.search(r"\b(?:va|lo\s+lleva|la\s+lleva|lleva)\s+([a-z]+)\b|\b([a-z]+)\s+(?:va|lo\s+lleva|is going|is taking|takes)\b",
                          words)
        if found and people:
            return people.person(found.group(1) or found.group(2))
        return None

    def slots(self, starts_at):
        """(slot, time) the summary goes out for a visit: the evening before and the morning of it."""
        eve_h, eve_m = map(int, self.cfg["eve_at"].split(":"))
        morning_h, morning_m = map(int, self.cfg["morning_at"].split(":"))
        eve = datetime.datetime.combine(starts_at.date() - datetime.timedelta(days=1), datetime.time(eve_h, eve_m), self.tz)
        morning = datetime.datetime.combine(starts_at.date(), datetime.time(morning_h, morning_m), self.tz)
        lead = starts_at - datetime.timedelta(minutes=int(self.cfg["early_lead_min"]))
        if morning > lead:
            morning = max(lead, datetime.datetime.combine(starts_at.date(), datetime.time(6, 0), self.tz))
        return [("eve", eve), ("morning", morning)]

    def add_visit(self, text, lang, person):
        t = TEXT[lang]
        now = self.now()
        when, missing = parse_when(text, now)
        if when is None:
            return t["when_missing"]
        if when <= now:
            return t["past"]
        who = self.who_from(text, person)
        stamp = now.isoformat(timespec="seconds")
        with self.lock:
            cursor = self.db.execute(
                "insert into prep_appointments (title, starts_at, place, bring, added_by, ts) values (?, ?, null, null, ?, ?)",
                (TITLE["es"], when.isoformat(timespec="minutes"), person, stamp))
            appointment = cursor.lastrowid
            visit = self.db.execute("insert into pedi_visits (appointment_id, starts_at, who, added_by, ts) values (?, ?, ?, ?, ?)",
                                    (appointment, when.isoformat(timespec="minutes"), who, person, stamp)).lastrowid
            # A slot already past when the visit is kept is never sent late: the parent just said it.
            for slot, at in self.slots(when):
                if at <= now:
                    for each in self.recipients(who):
                        self.db.execute("insert or ignore into pedi_sent (visit_id, slot, person, ts, status) values "
                                        "(?, ?, ?, ?, 'skipped')", (visit, slot, each, stamp))
            self.db.commit()
        self.publish("visit", visit_id=visit, appointment_id=appointment, starts_at=when.isoformat(timespec="minutes"),
                     who=who)
        future = [at for slot, at in self.slots(when) if at > now]
        sends = (t["send_eve"] if len(future) == 2 else t["send_morning"] if future else t["send_now"]).format(
            eve=self.cfg["eve_at"], morning=future[-1].strftime("%H:%M") if future else "")
        people = self.people()
        name = people.name(who) if who and people else None
        to = (t["to_you"] if who == person else t["to_one"].format(name=name)) if name else \
            (t["to_both"] if people and len(people.keys()) > 1 else t["to_you"])
        return t["kept_visit"].format(title=TITLE[lang], day=long_day(when.date(), lang), hhmm=when.strftime("%H:%M"),
                                      who=t["who"].format(name=name) if name else t["both_go"], when=sends, to=to)

    def next_visit(self, lang):
        t = TEXT[lang]
        upcoming = self.upcoming()
        if not upcoming:
            return t["no_visit"]
        visit = upcoming[0]
        name = self.people().name(visit["who"]) if visit["who"] and self.people() else None
        return t["next_visit"].format(day=long_day(visit["starts_at"].date(), lang), hhmm=visit["starts_at"].strftime("%H:%M"),
                                      who=t["who"].format(name=name) if name else "")

    def cancel_next(self, lang):
        t = TEXT[lang]
        upcoming = self.upcoming()
        if not upcoming:
            return t["no_visit"]
        visit = upcoming[0]
        with self.lock:
            self.db.execute("update pedi_visits set cancelled = 1 where id = ?", (visit["id"],))
            self.db.execute("update prep_appointments set cancelled = 1 where id = ?", (visit["appointment_id"],))
            self.db.commit()
        self.publish("cancel", visit_id=visit["id"])
        return t["cancelled"].format(day=long_day(visit["starts_at"].date(), lang), hhmm=visit["starts_at"].strftime("%H:%M"))

    def last_visit(self):
        """The newest visit that already started and was not cancelled: the summary counts from it."""
        now = self.now()
        past = [v for v in self.visits(include_done=True) if v["starts_at"] <= now]
        return past[-1] if past else None

    # Questions

    def questions(self):
        with self.lock:
            rows = self.db.execute("select id, text, es, en from pedi_questions where closed = 0 order by id").fetchall()
        return [{"id": i, "text": t, "es": es, "en": en} for i, t, es, en in rows]

    @staticmethod
    def plain_question(words, lang):
        """The parent's words as a question, with no model: "si es normal que..." becomes "¿Es normal que...?"."""
        words = re.sub(r"^\s*(?:que\s+|si\s+|whether\s+|if\s+)", "", words.strip(" ,:.;"), flags=re.I).strip()
        words = re.sub(r"^[¿?]+|[?]+$", "", words).strip()
        if not words:
            return ""
        words = words[0].upper() + words[1:]
        return f"¿{words}?" if lang == "es" else f"{words}?"

    def budget_left(self):
        today = self.now().date().isoformat()
        if self.spend["day"] != today:
            self.spend = {"day": today, "usd": 0.0}
        return self.spend["usd"] < float(self.cfg["budget_usd"])

    def tidy(self, words):
        """{"es": ..., "en": ...} from Muse, each checked, or {} when Muse is off or its words fail a check."""
        if not self.budget_left():
            self.agent.bus.publish("pediatrician", action="muse_skipped", reason="budget")
            return {}
        muse = self.muse
        if muse is None:
            from .house_brain import MUSE, MuseClient  # here, so a family agent that never tidies loads no client
            muse = self.muse = MuseClient({**MUSE, **self.cfg["muse"]})
        try:
            answer, meta = muse.ask(TIDY_SYSTEM, words, TIDY_SCHEMA, name="question")
        except Exception as error:  # noqa: BLE001 Muse down, slow or off: the parent's words stand
            self.agent.bus.publish("pediatrician", action="muse_failed", error=f"{type(error).__name__}: {str(error)[:160]}")
            return {}
        self.spend["usd"] += float((meta or {}).get("usd") or 0)
        self.agent.bus.publish("brain_call", provider="pediatrician", model=(meta or {}).get("model"),
                               destination=(meta or {}).get("host"), seconds=(meta or {}).get("seconds"),
                               input_tokens=(meta or {}).get("input_tokens"),
                               output_tokens=(meta or {}).get("output_tokens"), usd=(meta or {}).get("usd"))
        out = {}
        for lang in ("es", "en"):
            text = " ".join(str((answer or {}).get(lang) or "").split())
            why = self.tidy_problem(words, text, lang)
            if why:
                self.agent.bus.publish("pediatrician", action="muse_rejected", lang=lang, why=why)
            else:
                out[lang] = text
        return out

    @staticmethod
    def tidy_problem(words, text, lang):
        """Why Muse's question is not kept, or None: it must hold the parent's numbers and nothing they did not say."""
        if not text or len(text) > MAX_QUESTION_CHARS or "\n" in text:
            return "empty or too long"
        if not text.endswith("?"):
            return "not a question"
        if sorted(re.findall(r"\d+", text)) != sorted(re.findall(r"\d+", words)):
            return "numbers changed"
        said = {m.group(0).lower()[:6] for m in ADVICE.finditer(plain(words))}
        added = [m.group(0) for m in ADVICE.finditer(plain(text)) if m.group(0).lower()[:6] not in said]
        if added:
            return f"added words: {', '.join(added[:3])}"
        if final_guard.why_internal(text):
            return "internal words"
        if lang == "es" and not rules.looks_spanish(text):
            return "not Spanish"
        if lang == "en" and rules.looks_spanish(text):
            return "not English"
        return None

    def question_text(self, question, lang):
        """The question in this language: Muse's checked words, else the parent's own words in quotes."""
        if question.get(lang):
            return question[lang]
        return quoted(question["text"], lang)

    def add_question(self, words, lang, person):
        """lang is the parent's language: their words are a question in it when Muse is off."""
        t = TEXT[lang]
        words = " ".join(words.split())[:MAX_QUESTION_CHARS]
        if not re.search(r"\w", words):
            return t["empty_question"]
        if rules.has_secret(words):
            return t["no_secret"]
        open_now = self.questions()
        if len(open_now) >= MAX_OPEN_QUESTIONS:
            return t["too_many"].format(n=len(open_now))
        tidy = self.tidy(words)
        tidy.setdefault(lang, self.plain_question(words, lang))
        stamp = self.now().isoformat(timespec="seconds")
        with self.lock:
            self.db.execute("insert into pedi_questions (text, es, en, asked_by, ts) values (?, ?, ?, ?, ?)",
                            (words, tidy.get("es"), tidy.get("en"), person, stamp))
            self.db.commit()
        n = len(open_now) + 1
        self.publish("question", open=n, tidied=sorted(tidy))
        q = self.question_text({"text": words, **tidy}, lang)
        return (t["kept_question_one"] if n == 1 else t["kept_question"]).format(q=q, n=n)

    def numbered(self, lang):
        return [f"{i}. {self.question_text(q, lang)}" for i, q in enumerate(self.questions(), 1)]

    def list_questions(self, lang):
        t = TEXT[lang]
        lines = self.numbered(lang)
        return "\n".join([t["list"], *lines]) if lines else t["list_empty"]

    def close(self, n, lang):
        t = TEXT[lang]
        open_now = self.questions()
        if not 1 <= n <= len(open_now):
            return t["no_such"].format(n=n, total=len(open_now))
        question = open_now[n - 1]
        self.close_ids([question["id"]])
        return t["closed"].format(n=n, q=self.question_text(question, lang))

    def close_all(self, lang):
        open_now = self.questions()
        self.close_ids([q["id"] for q in open_now])
        return TEXT[lang]["closed_all"].format(n=len(open_now)) if open_now else TEXT[lang]["list_empty"]

    def close_ids(self, ids):
        event = getattr(self.agent, "current_event", None) or {}
        stamp = self.now().isoformat(timespec="seconds")
        with self.lock:
            for each in ids:
                self.db.execute("update pedi_questions set closed = 1, closed_by = ?, closed_ts = ? where id = ?",
                                (event.get("person"), stamp, each))
            self.db.commit()
        self.publish("close", closed=len(ids))

    # After the visit

    def said(self, words, lang):
        """"la pediatra dijo que...": a note in the baby log in the parent's words, and the visit of today done."""
        t = TEXT[lang]
        words = " ".join(words.split())[:400]
        if rules.has_secret(words):
            return t["no_secret"]
        that = re.match(r"(?:que|that)\s+", words, re.I)
        note = ("La pediatra dijo" if lang == "es" else "The pediatrician said") + (" " if that else ": ") + words
        try:
            self.agent.baby_log.add("note", {"text": note})
        except Exception as error:  # noqa: BLE001 Baby Buddy down: said plainly, nothing claimed
            self.agent.bus.publish("pediatrician", action="said_failed", error=str(error)[:200])
            return t["said_failed"].format(why=type(error).__name__)
        now = self.now()
        stamp = now.isoformat(timespec="seconds")
        recent = [v for v in self.visits() if v["starts_at"] <= now + datetime.timedelta(hours=3)]
        with self.lock:
            if recent:
                self.db.execute("update pedi_visits set done_ts = ? where id = ?", (stamp, recent[-1]["id"]))
            else:
                # No visit was kept: the visit of today is kept as done, so the next summary counts from it.
                self.db.execute("insert into pedi_visits (starts_at, added_by, ts, done_ts) values (?, ?, ?, ?)",
                                (now.isoformat(timespec="minutes"), (self.agent.current_event or {}).get("person"), stamp,
                                 stamp))
            self.db.commit()
        self.publish("said", chars=len(words))
        lines = self.numbered(lang)
        return t["said"].format(s=note) + (t["said_open"].format(list=" ".join(lines)) if lines else t["said_none"])

    # The summary

    def period(self):
        """(start, how): since the last visit, else since birth, else since the first log entry (start None)."""
        last = self.last_visit()
        if last is not None:
            return last["starts_at"], "visit"
        born = self.birth_date()
        if born is not None:
            return datetime.datetime.combine(born, datetime.time(0, 0), self.tz), "birth"
        return None, "first"

    def birth_date(self):
        for value in (self.birth, self.agent_birth(), self.log_birth()):
            if value:
                try:
                    return value if isinstance(value, datetime.date) else datetime.date.fromisoformat(str(value)[:10])
                except ValueError:
                    continue
        return None

    def agent_birth(self):
        try:
            return self.agent.birth_date()
        except Exception:  # noqa: BLE001 an agent with no birth date
            return None

    def log_birth(self):
        """The child's birth date in Baby Buddy, when the log is Baby Buddy."""
        log = self.agent.baby_log
        if not hasattr(log, "request") or not hasattr(log, "child"):
            return None
        try:
            child = log.child()
            return next((c.get("birth_date") for c in log.request("GET", "/api/children/?limit=50")["results"]
                         if c["id"] == child), None)
        except Exception as error:  # noqa: BLE001 the summary goes on without it
            self.agent.bus.publish("pediatrician", action="read_failed", what="birth date", error=str(error)[:160])
            return None

    def log_weight(self, since):
        """The newest weight in Baby Buddy's weight list since the period start, when the log is Baby Buddy."""
        log = self.agent.baby_log
        if not hasattr(log, "request") or not hasattr(log, "child"):
            return None
        try:
            rows = log.request("GET", f"/api/weight/?child={log.child()}&limit=20&ordering=-date")["results"]
        except Exception as error:  # noqa: BLE001 no weight list: the notes may still hold one
            self.agent.bus.publish("pediatrician", action="read_failed", what="weight", error=str(error)[:160])
            return None
        for row in rows:
            day = datetime.date.fromisoformat(str(row.get("date"))[:10])
            if row.get("weight") is not None and (since is None or day >= since.date()):
                value = float(row["weight"])
                return {"at": datetime.datetime.combine(day, datetime.time(12, 0), self.tz), "value": str(value),
                        "unit": "kg" if value < 30 else "g"}
        return None

    def compute(self):
        """(facts or None when the log could not be read, start, how)."""
        start, how = self.period()
        now = self.now()
        if self.phase == "prep":
            return {"prep": True}, start, how
        try:
            entries = self.agent.baby_log.entries(None, start.isoformat() if start else None, 3000)
        except Exception as error:  # noqa: BLE001 the questions still go out
            self.agent.bus.publish("pediatrician", action="read_failed", what="log", error=str(error)[:200])
            return None, start, how
        if start is None and entries:
            start = parse_time(entries[0]["ts"], self.tz)
        found = facts(entries, start or now, now, self.tz)
        weight = self.log_weight(start)
        if weight and (found["weight"] is None or weight["at"] >= found["weight"]["at"]):
            found["weight"] = weight
        return found, start, how

    def head(self, lang, slot, visit=None):
        t = TEXT[lang]
        if slot in ("eve", "morning") and visit is not None:
            when = visit["starts_at"]
            return t[f"head_{slot}"].format(title=TITLE[lang], day=long_day(when.date(), lang), hhmm=when.strftime("%H:%M"))
        upcoming = self.upcoming()
        if upcoming:
            when = upcoming[0]["starts_at"]
            return t["head_now_next"].format(day=long_day(when.date(), lang), hhmm=when.strftime("%H:%M"))
        return t["head_now"]

    def glance_line(self, found, lang):
        t = TEXT[lang]
        if found is None:
            return t["unread"]
        if found.get("prep"):
            return t["glance_prep"].format(name=self.baby or ("El bebé" if lang == "es" else "The baby"))
        if not found["days"]:
            return t["glance_empty"]
        sleep = length(found["sleep"]["mid"], lang) if found["sleep"] else "0 h"
        return t["glance"].format(feeds=found["feeds"]["mid"], diapers=found["diapers"]["mid"], sleep=sleep)

    def body(self, found, start, how, lang):
        t = TEXT[lang]
        if found is None or found.get("prep") or not found["days"]:
            return []
        lines = [t[f"since_{how}"].format(day=short_day(start.date())) if start else t["since_first"].format(day="")]
        days = found["days"]
        lines.append(t["days"].format(n=len(days), first=short_day(days[0]), last=short_day(days[-1]))
                     if len(days) > 1 else t["days_one"].format(first=short_day(days[0])))
        lines.append(t["feeds"].format(**found["feeds"]))
        sides = found["sides"]
        parts = [t[key].format(n=sides[key]) for key in ("left", "right", "both") if sides.get(key)]
        if sides.get("breast"):
            parts.append(t["side_unknown"].format(n=sides["breast"]))
        if parts:
            lines.append(t["breast"].format(parts=", ".join(parts)))
        if sides.get("bottle"):
            milks = found["milks"]
            milk = [t[key].format(n=milks[key]) for key in ("breast_milk", "formula") if milks.get(key)]
            amount = t["amount"].format(**found["amount"]) if found["amount"] else ""
            lines.append(t["bottle"].format(n=sides["bottle"], milk=t["milk"].format(parts=", ".join(milk)) if milk else "",
                                            amount=amount))
        lines.append(t["diapers"].format(**found["diapers"], wet=found["wet"]["mid"], dirty=found["dirty"]["mid"]))
        if found["diaper_both"]:
            lines.append(t["diaper_both"])
        if found["colors"]:
            colors = [f"{COLORS_ES.get(c, c) if lang == 'es' else c} {n}" for c, n in sorted(found["colors"].items(), key=lambda x: -x[1])]
            lines.append(t["colors"].format(parts=", ".join(colors)))
        sleep = found["sleep"]
        if sleep:
            key = "sleep" if sleep["days"] == len(days) else "sleep_days"
            lines.append(t[key].format(mid=length(sleep["mid"], lang), lo=length(sleep["lo"], lang),
                                       hi=length(sleep["hi"], lang), n=sleep["days"]))
        else:
            lines.append(t["no_sleep"])
        weight = found["weight"]
        if weight:
            number, unit = weight_text(weight, lang)
            lines.append(t["weight"].format(value=f"{number} {unit}", day=short_day(weight["at"].date())))
        else:
            lines.append(t["no_weight"])
        notes = found["notes"]
        if notes:
            newest = notes[-MAX_NOTES:]
            lines.append(t["notes"] if len(notes) <= MAX_NOTES else t["notes_some"].format(n=len(newest), total=len(notes)))
            for note in newest:
                text = note["text"] if len(note["text"]) <= 140 else note["text"][:139].rsplit(" ", 1)[0] + "…"
                lines.append(f"- {short_day(note['at'].date())} {note['at'].strftime('%H:%M')}: {quoted(text, lang)}")
        else:
            lines.append(t["no_notes"])
        return lines

    def summary(self, lang="es", slot="now", visit=None, computed=None):
        """The whole summary, in lines: the two glance lines first, then the numbers, the notes, the questions and the
        closing line."""
        lang = lang_of(lang)
        t = TEXT[lang]
        found, start, how = computed or self.compute()
        questions = self.numbered(lang)
        lines = [self.head(lang, slot, visit), self.glance_line(found, lang), ""]
        lines += self.body(found, start, how, lang)
        lines += ([t["questions"].format(n=len(questions)), *questions] if questions else [t["no_questions"]])
        lines.append(t["closing"])
        self.publish("summary", slot=slot, lang=lang, questions=len(questions),
                     read=found is not None, days=len(found["days"]) if found and "days" in found else 0)
        return "\n".join(lines)

    def glance(self, lang="es"):
        """Two short lines for the glasses: the per day numbers, then how many questions are kept."""
        lang = lang_of(lang)
        found, _, _ = self.compute()
        n = len(self.questions())
        tail = {"es": f"{n} preguntas anotadas." if n != 1 else "1 pregunta anotada.",
                "en": f"{n} questions kept." if n != 1 else "1 question kept."}[lang]
        return f"{self.glance_line(found, lang)}\n{tail}"

    def spoken(self, lang="es"):
        """A few short sentences for the Echo: the per day numbers and how many questions, never their text."""
        lang = lang_of(lang)
        t = TEXT[lang]
        found, _, how = self.compute()
        n = len(self.questions())
        asks = t["spoken_question"] if n == 1 else t["spoken_questions"].format(n=n) if n else t["spoken_no_questions"]
        if found is None or found.get("prep") or not found.get("days"):
            first = self.glance_line(found, lang)
        else:
            sleep = length(found["sleep"]["mid"], f"spoken_{lang}") if found["sleep"] else ("0 horas" if lang == "es" else "0 hours")
            first = t["spoken"].format(since=t[f"spoken_since_{how}"], feeds=found["feeds"]["mid"],
                                       diapers=found["diapers"]["mid"], wet=found["wet"]["mid"],
                                       dirty=found["dirty"]["mid"], sleep=sleep)
        return f"{first} {asks} {t['spoken_closing']}"

    def asks_summary(self, text):
        return bool(SUMMARY.search(plain(text)))

    # The two pushes before a visit

    def recipients(self, who):
        people = self.people()
        if who:
            return [who]
        return people.keys() if people else [None]

    def sent(self, visit_id, slot, person):
        with self.lock:
            return self.db.execute("select 1 from pedi_sent where visit_id = ? and slot = ? and person is ?",
                                   (visit_id, slot, person)).fetchone() is not None

    def mark(self, visit_id, slot, person, status):
        with self.lock:
            self.db.execute("insert or ignore into pedi_sent (visit_id, slot, person, ts, status) values (?, ?, ?, ?, ?)",
                            (visit_id, slot, person, self.now().isoformat(timespec="seconds"), status))
            self.db.commit()

    def tick(self, now=None):
        """Sends each summary that is due: at its slot, before the visit starts, once per parent across restarts. When
        both slots are due (the agent was down overnight) only the morning one goes."""
        now = (now or self.now()).astimezone(self.tz)
        out = []
        for visit in self.visits():
            if visit["starts_at"] <= now:
                continue
            due = [(slot, at) for slot, at in self.slots(visit["starts_at"]) if at <= now]
            for slot, _ in due[:-1]:
                for person in self.recipients(visit["who"]):
                    if not self.sent(visit["id"], slot, person):
                        self.mark(visit["id"], slot, person, "skipped")
            if not due:
                continue
            slot = due[-1][0]
            people = [p for p in self.recipients(visit["who"]) if not self.sent(visit["id"], slot, p)]
            if not people:
                continue
            computed = self.compute()
            texts = {lang: self.summary(lang, slot, visit, computed) for lang in ("es", "en")}
            for person in people:
                lang = self.person_lang(person)
                self.mark(visit["id"], slot, person, "sent")
                out.append(self.agent.bus.publish("notify", text=texts[lang], texts=texts, person=person,
                                                  source="pediatrician", routine="pediatrician_summary", slot=slot))
        return out

    def run(self):
        while not self.stopped.is_set():
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 a bad tick is reported, the agent keeps running
                self.agent.bus.publish("pediatrician", action="tick_failed", error=f"{type(error).__name__}: {str(error)[:200]}")
                print(f"pediatrician: tick failed, {type(error).__name__}", flush=True)
            self.stopped.wait(int(self.cfg["check_every_s"]))

    def start(self):
        self.thread = threading.Thread(target=self.run, name="pediatrician", daemon=True)
        self.thread.start()
        self.agent.bus.publish("pediatrician_started", visits=len(self.upcoming()), questions=len(self.questions()))

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)

