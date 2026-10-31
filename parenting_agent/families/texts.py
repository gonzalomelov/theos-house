"""Every fixed message of the families bot, in English and in Rioplatense Spanish with voseo.

A family has one language, kept as the fact _lang in its own file. A new family starts in Spanish when the parent's
Telegram language_code starts with "es", in English otherwise, and /idioma or /language switches it. Strangers get
the language of their Telegram app, nothing about them is stored. Both tables have the same keys, a test checks it.
"""
import re

from ..agent import rules

LANGS = ("en", "es")

EN = {
    "NO_CODE": ("Hi. This bot is a private beta for invited families. If someone gave you an invite code, "
                "send /start followed by the code, for example /start K7QM3XPA."),
    "BAD_CODE": "That invite code is not valid or was already used. Please check it, or ask the person who invited you for a new one.",
    "TOO_MANY": "Too many codes tried today. Please try again tomorrow.",
    "FULL": "The beta is full right now. Thank you for your interest.",
    "GROUP": "I only work in a private chat. Please message me directly.",
    "ALREADY": "You are already set up. Send /help to see what I can do.",
    "TOO_LONG": "Please keep it under {n} characters.",
    "FAMILY_LIMIT": "Your family reached today's message limit. I will be back tomorrow. Nothing was logged from this message.",
    "THINK_FAIL": "I could not think that through just now. Please try again.",
    "NOT_LOGGED": "I could not log that. Could you send it again?",
    "SAVED_BEFORE_FAIL": "I could not finish my answer, but I logged {entries}. No need to send it again.",
    "ENTRY_FEEDING": "a feed", "ENTRY_FEEDING_ML": "a feed of {ml} ml", "ENTRY_DIAPER": "a diaper",
    "ENTRY_SLEEP": "sleep", "ENTRY_BATH": "a bath", "ENTRY_NOTE": "a note",
    "OK": "OK.",
    "ASK_NAME": "1 of 3. What is your baby's name or nickname?",
    "WELCOME": ("Welcome. I keep a private log of your baby's feeds, diapers, sleep and baths, answer questions from it, "
                "remind you of the next feed and send a short summary each evening. I am built to refuse medical advice. "
                "Three quick questions and you are logging. Send /privacy to read what I store. "
                "Para español mandá /idioma.\n\n"),
    "ASK_BORN": "2 of 3. When was {name} born? For example 2026-10-12 or 12/10/2026.",
    "BAD_BORN": "I could not read that date. Please write it like 2026-10-12 or 12/10/2026. It cannot be in the future.",
    "ASK_PARTNER": ("3 of 3. Should the other parent log too? Reply yes and I will make an invite code for them, "
                    "or no. You can also send /invite later."),
    "READY": ("All set for {name}. Just write what happened, for example:\n"
              "bottle 120 ml\nleft breast 15 min\nwet and dirty diaper\n{name} fell asleep\n{name} woke up\nbath done\n\n"
              "Or ask: when did {name} last eat? How much did {name} drink today?\n\n"
              "/summary today so far, /next next feed, /invite the other parent, /reminders off or on, "
              "/privacy what I store, /deletemydata delete everything, /idioma español."),
    "PARTNER_CODE": ("Here is the invite for the other parent, valid for {days} days and for one person:\n{code}\n{link}"
                     "They send /start {code} to this bot and join {name}'s log."),
    "PARTNER_WELCOME": ("Welcome. You joined {name}'s log. You and the other parent see and add to the same private log. "
                        "I am built to refuse medical advice. Send /privacy to read what I store.\n\n"),
    "PARTNER_MAX": "{name}'s log already has {n} people, the most it can have.",
    "PRIVACY": ("What I store: your baby's name and birth date, what you log (feeds, diapers, sleep, baths, notes), "
                "our conversation of the last 7 days, and your Telegram chat id so I can answer you. The only fact I keep is the "
                "baby's name: other names, phone numbers, addresses or codes are never saved as facts, but what you type stays "
                "in the conversation for 7 days, so please leave them out. For counting real use I keep one row per "
                "message with the time and a scrambled id, never the text.\n"
                "Where: one private file for your family on Gonza's home server in Uruguay. Other families cannot see it. "
                "To write replies, the conversation text and your log lines are sent to Muse Spark Open, Meta's open model, "
                "on Baseten. Voice notes you send are heard by Muse on Baseten too: the audio is sent once, never saved by me. "
                "These calls run on free hackathon credits, and Meta says content sent on those credits may be used to train "
                "future Meta models, so I cannot promise it is not kept or used for training. If Muse does not answer, simple "
                "fixed rules on the server reply instead, and no other company's model is used. Telegram carries the messages.\n"
                "Delete: send /deletemydata. It removes your family's file, the conversation, the rows and both parents' access, at once."),
    "DELETE_WORD": "DELETE",
    "DELETE_ASK": ("This deletes {name}'s whole log, our conversation and access for everyone in your family. It cannot be undone. "
                   "Send DELETE to confirm. Anything else cancels."),
    "DELETE_CANCELLED": "Not deleted. Everything is still here.",
    "DELETED": "Done. Everything about your family is deleted. Send /start with a new invite code if you ever want to come back.",
    "DELETED_OTHER": "The other parent deleted your family's data. Everything is gone. Thank you for trying the agent.",
    "REFUSAL": rules.REFUSAL,
    "EMERGENCY": rules.EMERGENCY_REPLY["en"],
    "REMINDERS_OFF": "Feed reminders are off. Send /reminders on to turn them back on.",
    "REMINDERS_ON": "Feed reminders are on.",
    "LANG_SET": "OK, from now on I write in English, to everyone in your family. Para español mandá /idioma.",
    "NEED_TWO_FEEDS": "I need two feeds in {name}'s log before I can tell the next one.",
    "NEXT_FEED_FEW": "From your log, the next feed for {name} would be around {when}, in about {minutes} min.",
    "NO_FEEDS_YET": "There is no feed in {name}'s log yet. Write one, for example: bottle 120 ml.",
    "FEW_FEEDS": ("The last feed in {name}'s log was {since}, {ago} ago. There are too few feeds logged in the last day "
                  "to tell how often {name} eats yet."),
    "NEXT_FEED": "From your log, the next feed for {name} would be around {when}, in about {minutes} min. Feeds have been about {gap} apart.",
    "NEXT_FEED_NOW": "From your log, the next feed for {name} would be about now, around {when}.",
    "NO_FEED_SINCE": "It has been {ago} since the last feed you logged, {since}. Did {name} eat?",
    "LAST_FEED_AT": "The last feed in {name}'s log was {since}, {ago} ago.",
    "AT_TODAY": "at {at}", "AT_YESTERDAY": "yesterday at {at}", "AT_DAY": "on {day} at {at}",
    "CRY_NOT_ENOUGH": "There is not enough in {name}'s log yet to guess why. This is never a diagnosis.",
    "CRY_GUESS": "This is only a guess from the log, never a diagnosis.",
    "CRY_PROBABLY": "From the log, probably {reason}: {evidence}.",
    "CRY_NO_REASON": "Nothing in the log points to a likely reason. Things to check: {evidence}.",
    "CRY_NEXT": "If not, {reason}: {evidence}.",
    "CRY_HUNGRY": "the last feed was {ago} ago and feeds come about every {gap}",
    "CRY_TIRED": "awake for {ago}, sleep usually comes again after about {usual}",
    "CRY_DIAPER": "the last diaper change was {ago} ago",
    "CRY_DIAPER_SINCE_FEED": "no diaper change logged since the {at} feed",
    "CRY_COMFORT": "a wet or dirty diaper, too warm or too cold, a burp after the feed, or maybe just wants to be held",
    "CRY_HUNGRY_WORD": "hungry", "CRY_TIRED_WORD": "tired", "CRY_DIAPER_WORD": "a diaper",
    "NOTHING_TODAY": "Nothing logged for {name} today yet.",
    "TODAY": "Today for {name}:",
    "FEEDS": "{feeds}{total}, the last at {last}.",
    "FEEDS_TOTAL": ", {ml} ml in total",
    "DIAPERS": "{diapers}, {wet} and {dirty}.",
    "WET": ("wet", "wet"),
    "DIRTY": ("dirty", "dirty"),
    "SLEEP": "{time} of sleep over {sleeps}.",
    "BATH": "Bath at {last}.",
    "FEED": ("feed", "feeds"),
    "DIAPER": ("diaper", "diapers"),
    "SLEEP_ONE": ("sleep", "sleeps"),
    "LOGGED": "Done, logged.",
    "NOTED": "Noted.",
    "NOT_DONE": "I could not do that just now.",
    "NOT_FOUND": "I could not find that in the log.",
    "LOGGED_FEEDS": "Logged feeds: {feeds}.",
    "FEED_AT": "{ml} ml at {at}",
    "NOTHING_YET": "Nothing logged yet today.",
}

ES = {
    "NO_CODE": ("Hola. Este bot es una beta privada para familias invitadas. Si alguien te pasó un código, "
                "mandá /start y el código, por ejemplo /start K7QM3XPA."),
    "BAD_CODE": "Ese código no sirve o ya se usó. Revisalo, o pedile uno nuevo a quien te invitó.",
    "TOO_MANY": "Probaste demasiados códigos hoy. Volvé a intentar mañana.",
    "FULL": "La beta está llena por ahora. Gracias por tu interés.",
    "GROUP": "Solo funciono en un chat privado. Escribime directo.",
    "ALREADY": "Ya quedó todo listo. Mandá /ayuda para ver lo que puedo hacer.",
    "TOO_LONG": "Escribí menos de {n} caracteres, por favor.",
    "FAMILY_LIMIT": "Tu familia llegó al límite de mensajes de hoy. Vuelvo mañana. No anoté nada de este mensaje.",
    "THINK_FAIL": "No pude pensarlo recién. Probá de nuevo.",
    "NOT_LOGGED": "No pude anotarlo, ¿me lo repetís?",
    "SAVED_BEFORE_FAIL": "No pude terminar la respuesta, pero ya anoté {entries}. No hace falta que lo mandes de nuevo.",
    "ENTRY_FEEDING": "una toma", "ENTRY_FEEDING_ML": "una toma de {ml} ml", "ENTRY_DIAPER": "un pañal",
    "ENTRY_SLEEP": "el sueño", "ENTRY_BATH": "un baño", "ENTRY_NOTE": "una nota",
    "OK": "Listo.",
    "ASK_NAME": "1 de 3. ¿Cómo se llama tu bebé, o cómo le dicen?",
    "WELCOME": ("Te doy la bienvenida. Llevo un registro privado de las tomas, pañales, sueño y baños de tu bebé, respondo lo que "
                "preguntes sobre eso, te aviso la próxima toma y te mando un resumen corto cada noche. Estoy hecho para no dar "
                "consejos médicos. Son tres preguntas rápidas y ya podés anotar. Mandá /privacidad para ver qué guardo. "
                "For English send /language.\n\n"),
    "ASK_BORN": "2 de 3. ¿Cuándo nació {name}? Por ejemplo 12/10/2026 o 2026-10-12.",
    "BAD_BORN": "No entendí la fecha. Escribila así: 12/10/2026 o 2026-10-12. No puede ser en el futuro.",
    "ASK_PARTNER": ("3 de 3. ¿Querés que el otro papá o la otra mamá también anote? Respondé sí y te hago un código "
                    "para pasarle, o no. También podés mandar /invitar más adelante."),
    "READY": ("Listo para {name}. Escribí lo que pasó, por ejemplo:\n"
              "mamadera 120 ml\npecho izquierdo 15 min\npañal mojado y sucio\n{name} se durmió\n{name} se despertó\nya se bañó\n\n"
              "O preguntá: ¿cuándo comió {name} por última vez? ¿Cuánto tomó {name} hoy?\n\n"
              "/resumen lo de hoy, /proxima la próxima toma, /invitar al otro papá o mamá, /avisos off u on, "
              "/privacidad qué guardo, /borrarmisdatos borrar todo, /language English."),
    "PARTNER_CODE": ("Acá tenés la invitación para el otro papá o mamá, sirve {days} días y para una persona:\n{code}\n{link}"
                     "Que le mande /start {code} a este bot y se suma al registro de {name}."),
    "PARTNER_WELCOME": ("Te doy la bienvenida. Te sumaste al registro de {name}. Vos y el otro papá o mamá ven y anotan en el mismo "
                        "registro privado. Estoy hecho para no dar consejos médicos. Mandá /privacidad para ver qué guardo.\n\n"),
    "PARTNER_MAX": "El registro de {name} ya tiene {n} personas, que es el máximo.",
    "PRIVACY": ("Qué guardo: el nombre y la fecha de nacimiento de tu bebé, lo que anotás (tomas, pañales, sueño, baños, notas), "
                "nuestra conversación de los últimos 7 días y tu id de chat de Telegram para poder responderte. El único dato "
                "que guardo es el nombre de tu bebé: otros nombres, teléfonos, direcciones o códigos nunca se guardan como dato, "
                "pero lo que escribís queda en la conversación 7 días, así que mejor no los mandes. Para contar el uso real guardo una "
                "fila por mensaje con la hora y un id mezclado, nunca el texto.\n"
                "Dónde: un archivo privado para tu familia en el servidor de la casa de Gonza, en Uruguay. Otras familias "
                "no lo pueden ver. Para escribir las respuestas, el texto de la conversación y lo que anotaste se mandan a Muse "
                "Spark Open, el modelo abierto de Meta, en Baseten. Los audios que mandás también los escucha Muse en Baseten: el audio se manda una vez y yo no lo guardo. "
                "Estas llamadas usan créditos gratis de la hackathon, y Meta dice que lo que se manda con esos créditos se puede "
                "usar para entrenar futuros modelos de Meta, así que no puedo prometer que no se guarde ni se use para entrenar. "
                "Si Muse no responde, contestan unas reglas fijas simples en el servidor, y no se usa el modelo de ninguna otra "
                "empresa. Telegram lleva los mensajes.\n"
                "Borrar: mandá /borrarmisdatos. Borra el archivo de tu familia, la conversación, las filas y el acceso de los dos, de una."),
    "DELETE_WORD": "BORRAR",
    "DELETE_ASK": ("Esto borra todo el registro de {name}, nuestra conversación y el acceso de todos en tu familia. No se puede "
                   "deshacer. Mandá BORRAR para confirmar. Cualquier otra cosa lo cancela."),
    "DELETE_CANCELLED": "No borré nada. Todo sigue acá.",
    "DELETED": "Listo. Borré todo lo de tu familia. Si algún día querés volver, mandá /start con un código nuevo.",
    "DELETED_OTHER": "El otro papá o mamá borró los datos de tu familia. No queda nada. Gracias por probar el agente.",
    "REFUSAL": ("No puedo dar consejos médicos. Para eso, mejor llamá a tu pediatra. Si es urgente, llamá al 911. "
                "Si querés, anoto lo que ves así lo tenés a mano para la llamada."),
    "EMERGENCY": rules.EMERGENCY_REPLY["es"],
    "REMINDERS_OFF": "Apagué los avisos de toma. Mandá /avisos on para prenderlos de nuevo.",
    "REMINDERS_ON": "Los avisos de toma están prendidos.",
    "LANG_SET": "Dale, desde ahora escribo en español, a todos en tu familia. For English send /language.",
    "NEED_TWO_FEEDS": "Necesito dos tomas en el registro de {name} para decirte la próxima.",
    "NEXT_FEED_FEW": "Según tu registro, la próxima toma de {name} sería cerca de las {when}, en unos {minutes} min.",
    "NO_FEEDS_YET": "Todavía no hay ninguna toma en el registro de {name}. Anotá una, por ejemplo: mamadera 120 ml.",
    "FEW_FEEDS": ("La última toma anotada de {name} fue {since}, hace {ago}. Todavía hay pocas tomas anotadas en el último "
                  "día para saber cada cuánto come {name}."),
    "NEXT_FEED": ("Según tu registro, la próxima toma de {name} sería cerca de las {when}, en unos {minutes} min. "
                  "Las tomas vienen cada {gap} más o menos."),
    "NEXT_FEED_NOW": "Según tu registro, la próxima toma de {name} sería más o menos ahora, cerca de las {when}.",
    "NO_FEED_SINCE": "Ya pasaron {ago} desde la última toma anotada, {since}. ¿Comió {name}?",
    "LAST_FEED_AT": "La última toma anotada de {name} fue {since}, hace {ago}.",
    "AT_TODAY": "a las {at}", "AT_YESTERDAY": "ayer a las {at}", "AT_DAY": "el {day} a las {at}",
    "CRY_NOT_ENOUGH": "Todavía no hay suficiente en el registro de {name} para adivinar por qué llora. No es un diagnóstico.",
    "CRY_GUESS": "Es solo una pista del registro, nunca un diagnóstico.",
    "CRY_PROBABLY": "Por el registro, capaz que es {reason}: {evidence}.",
    "CRY_NO_REASON": "En el registro no hay una razón probable. Para revisar: {evidence}.",
    "CRY_NEXT": "Si no, {reason}: {evidence}.",
    "CRY_HUNGRY": "la última toma fue hace {ago} y suele comer cada {gap}",
    "CRY_TIRED": "se despertó hace {ago} y suele volver a dormirse después de unos {usual}",
    "CRY_DIAPER": "el último cambio de pañal fue hace {ago}",
    "CRY_DIAPER_SINCE_FEED": "no hay cambio de pañal anotado desde la toma de las {at}",
    "CRY_COMFORT": "el pañal mojado o sucio, si tiene calor o frío, un provechito después de la toma, o capaz que solo quiere brazos",
    "CRY_HUNGRY_WORD": "hambre", "CRY_TIRED_WORD": "sueño", "CRY_DIAPER_WORD": "el pañal",
    "NOTHING_TODAY": "Todavía no hay nada anotado hoy para {name}.",
    "TODAY": "Hoy para {name}:",
    "FEEDS": "{feeds}{total}, la última a las {last}.",
    "FEEDS_TOTAL": ", {ml} ml en total",
    "DIAPERS": "{diapers}, {wet} y {dirty}.",
    "WET": ("mojado", "mojados"),
    "DIRTY": ("sucio", "sucios"),
    "SLEEP": "{time} de sueño en {sleeps}.",
    "BATH": "Baño a las {last}.",
    "FEED": ("toma", "tomas"),
    "DIAPER": ("pañal", "pañales"),
    "SLEEP_ONE": ("siesta", "siestas"),
    "LOGGED": "Listo, anotado.",
    "NOTED": "Entendido.",
    "NOT_DONE": "No pude hacerlo recién.",
    "NOT_FOUND": "No encontré eso en el registro.",
    "LOGGED_FEEDS": "Tomas anotadas: {feeds}.",
    "FEED_AT": "{ml} ml a las {at}",
    "NOTHING_YET": "Todavía no hay nada anotado hoy.",
}

TEXTS = {"en": EN, "es": ES}

# Commands in either language, to one name each. /deletemydata and /borrarmisdatos both work in both languages.
COMMANDS = {
    "ayuda": "help", "privacidad": "privacy", "borrarmisdatos": "deletemydata", "resumen": "summary",
    "proxima": "next", "próxima": "next", "invitar": "invite", "avisos": "reminders", "recordatorios": "reminders",
    "idioma": "language", "lang": "language",
}
LANGUAGE_ARGS = {"es": "es", "español": "es", "espanol": "es", "spanish": "es", "castellano": "es",
                 "en": "en", "english": "en", "inglés": "en", "ingles": "en"}

# Health words in Spanish, on top of the English ones in rules.MEDICAL. Either list sends the kind refusal.
MEDICAL_ES = rules.MEDICAL_ES
# Advice words in Spanish, on top of patterns.no_advice: a reminder or summary with one of them is never sent.
ADVICE_ES = re.compile(r"\b(deber[ií]as|ten[eé]s que|prob[aá]|recomiend\w*|m[eé]dic\w*|pediatra|normal|preocup\w*|"
                       r"fiebre|enferm\w*|remedio|dosis|consult\w*)\b", re.I)

# The free rule-based brain over a spend cap understands English notes. rules.NOTE_WORDS_ES turns Spanish words into
# the English ones it knows, so "mamadera 120 ml" or "pañal sucio" keep working in Spanish mode.
NOTE_WORDS_ES = rules.NOTE_WORDS_ES


def lang_for(language_code):
    return "es" if str(language_code or "").lower().startswith("es") else "en"


def t(lang, key, **values):
    text = TEXTS.get(lang, EN)[key]
    return text.format(**values) if values else text


def plural(lang, count, key):
    one, many = TEXTS.get(lang, EN)[key]
    return f"{count} {one if count == 1 else many}"


def is_medical(text):
    return rules.is_medical(text) or bool(MEDICAL_ES.search(text))


def no_advice_es(text):
    return ADVICE_ES.search(text) is None


def note_to_english(text):
    return rules.note_to_english(text)
