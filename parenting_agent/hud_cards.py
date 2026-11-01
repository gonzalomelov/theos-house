"""Display cards for the Meta Ray-Ban Display: everything the agent tells a parent that fits a glance, as one card.

The glasses app draws a card through DAT's Display API (apps/glasses/ParentingGlasses/HUD/DisplayHUD.swift). Meta's
display rules shape every card (apps/glasses/HUD.md):

| Rule | What the card does |
|---|---|
| 600 x 600 pixels, one display in the right lens | a title, one status line, at most one detail line and one meta line, each cut to a length that fits |
| Additive light, black adds nothing | no backgrounds of our own, the system card background only |
| The display dims after 20 s without a change and sleeps at 25 s | a red flag is sticky: the app changes its meta line every 15 s so it never dims, everything else may dim |
| Each send replaces the whole display | a card is whole, never a partial update |
| A fixed icon catalog (DAT 1.0.1 IconName) | every icon is a name from ICONS below |

A card is written in the parent's language ("es" or "en", the people block) and in short words: the first sentence of
what the parent got on Telegram, or fixed words for the agent's own events. Internal text never reaches a card:
event names, tool names, JSON, error text or the agent's machinery (INTERNAL below) drop the line, and a card with no
line left is not sent. Every card here is plain data, so the routing (glasses.py) and the tests need no app.
"""
import re

from .agent import final_guard

# The icons this module uses, every one a case of IconName in MWDATDisplay 1.0.1 (the Meta icon catalog).
ICONS = frozenset({
    "phoneHandsetArrowUpRight", "exclamationTriangle", "clock", "bedSide", "lightBulb", "cart", "carFrontView",
    "dropper", "person", "speechBubble", "bell", "eye", "house", "checkmarkCircle", "cloudCrescentMoon", "forkKnife",
    "calendar", "threePeopleOverlapping", "iCircle", "speakerOff", "speakerWithTwoArcs",
})
LIMITS = {"title": 26, "status": 60, "detail": 90, "meta": 40}
DIM_S, SLEEP_S, KEEPALIVE_S = 20, 25, 15  # Meta: dims after 20 s without a change, sleeps at 25 s

# Words of the machinery, never on a lens (house_brain.INTERNAL_RE plus the agent's own event and tool vocabulary), on
# top of the shared final guard's (final_guard.py).
INTERNAL = re.compile(
    r"finish[_ ]?reason|reason length|\bJSON\b|invalid answer|\bfallback\b|\btoken\b|\btrigger\b|\bschema\b|<\||"
    r"\btraceback\b|\bexception\b|\berror:|\bHTTP \d{3}\b|\b[a-z]+_[a-z_]+\(|\b(?:switch|light|media_player|todo|notify|"
    r"vacuum|sensor|binary_sensor)\.[a-z0-9_]+|\bhouse_(?:dry|live|done|error)\b|\bstart_[a-z_]+\b|\bfinish_[a-z_]+\b",
    re.I)
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
TEST_MARK = re.compile(r"^\s*test\s*:\s*", re.I)

WORDS = {
    "en": {"red_flag": "Call 911 now", "urgent": "Pediatrician or ER now", "fever": "Fever under 3 months",
           "urgent_status": "A newborn sign to act on now", "emergency": "This may be an emergency",
           "tell": "Tell them what you see", "no_reach": "Can't reach them: call 911", "aap": "AAP public guidance",
           "next_feed": "Next feed", "around": "Around {at}", "in": "in {m} min", "apart": "Feeds about {gap} apart",
           "on_duty": "Tonight", "duty": "On duty: {name}", "you_duty": "You are on duty tonight",
           "handover": "Night handover", "night_feed": "Night feed", "nap_on": "Nap mode on", "nap_off": "Nap mode off",
           "sleep_on": "Sleep mode on", "nap_since": "{kind} since {at}", "nap": "Nap", "sleep": "Sleep",
           "quiet": "House kept quiet", "awake": "He woke up, house back to normal", "dry": "Dry run, nothing moved",
           "morning": "Good morning", "supplies": "Running low", "shopping": "Shopping list", "car_seat": "Car seat",
           "step": "Step {i} of {n}", "say_yes_no": "Say yes or no", "say_done": "Say done when you finish",
           "come_close": "Bring the phone to the guide", "bath": "Bath", "bath_on": "Keep a hand on the baby",
           "bath_note": "The camera never replaces your hand", "dog": "Dog near the baby", "answer": "Answer",
           "reminder": "Reminder", "tonight": "Tonight's plan", "house": "House", "meals": "Meals", "sitter": "Sitter",
           "door": "Door", "note": "Parenting agent", "got_it": "Got it", "cry": "He is crying",
           "pediatrician": "Pediatrician"},
    "es": {"red_flag": "Llamá al 911 ya", "urgent": "Pediatra o emergencia ya", "fever": "Fiebre en menos de 3 meses",
           "urgent_status": "Señal en recién nacido: actuar ya", "emergency": "Puede ser una emergencia",
           "tell": "Contales lo que ves", "no_reach": "Si no los ubicás: 911", "aap": "Guía pública de la AAP",
           "next_feed": "Próxima toma", "around": "Cerca de las {at}", "in": "en {m} min", "apart": "Cada {gap} más o menos",
           "on_duty": "Esta noche", "duty": "De turno: {name}", "you_duty": "Esta noche te toca a vos",
           "handover": "Cambio de turno", "night_feed": "Toma de noche", "nap_on": "Modo siesta", "nap_off": "Fin de la siesta",
           "sleep_on": "Modo noche", "nap_since": "{kind} desde las {at}", "nap": "Siesta", "sleep": "Sueño",
           "quiet": "La casa queda en silencio", "awake": "Se despertó, la casa vuelve a lo normal",
           "dry": "Prueba en seco, no se movió nada", "morning": "Buen día", "supplies": "Se está terminando",
           "shopping": "Lista de compras", "car_seat": "Silla del auto", "step": "Paso {i} de {n}",
           "say_yes_no": "Decí sí o no", "say_done": "Decí listo cuando termines",
           "come_close": "Acercá el teléfono a la guía", "bath": "Baño", "bath_on": "Una mano siempre en el bebé",
           "bath_note": "La cámara nunca reemplaza tu mano", "dog": "Perro cerca del bebé", "answer": "Respuesta",
           "reminder": "Recordatorio", "tonight": "Plan de esta noche", "house": "Casa", "meals": "Comidas",
           "sitter": "Cuidadora", "door": "Puerta", "note": "Agente de crianza", "got_it": "Entendido", "cry": "Está llorando",
           "pediatrician": "Pediatra"},
}

# The car seat coach's steps (carseat/coach.py plan()), in a glance: what to do, never "safe".
CAR_SEAT = {
    "harness_pinch": {"en": "Pinch test: slack at the collarbone?", "es": "Pellizco: ¿sobra arnés en la clavícula?"},
    "car_position": {"en": "Carrier on a rear seat, facing back?", "es": "¿Silla atrás, mirando hacia atrás?"},
    "lap_guides": {"en": "Lap belt in both side guides", "es": "Cinturón de cadera en las dos guías"},
    "buckle": {"en": "Buckle until it clicks", "es": "Abrochá hasta que haga clic"},
    "shoulder_guide": {"en": "Shoulder belt in the rear guide", "es": "Cinturón de hombro en la guía de atrás"},
    "tension": {"en": "Tighten lap belt, then shoulder belt", "es": "Tensá cadera, después hombro"},
    "no_twist": {"en": "Belt flat, no twist", "es": "Cinturón plano, sin giros"},
    "level_line": {"en": "Show me the level line", "es": "Mostrame la línea de nivel"},
    "handle": {"en": "Handle upright, car position", "es": "Manija arriba, posición de auto"},
    "belt_path_movement": {"en": "Moves under 2.5 cm at the belt path?", "es": "¿Se mueve menos de 2,5 cm en el cinturón?"},
    "summary": {"en": "Car seat check finished", "es": "Revisión de la silla terminada"},
}
CAR_SEAT_RESULT = {
    "pass": {"en": "Seen on camera: OK", "es": "Visto en cámara: bien"},
    "fail": {"en": "Fix this before driving", "es": "Corregilo antes de manejar"},
    "unseen": {"en": "Not seen, listed as not checked", "es": "No lo vi, queda sin revisar"},
    "unsure": {"en": "My two checks disagree: check by hand", "es": "Mis dos chequeos no coinciden: revisalo a mano"},
    "open": {"en": "Kept open in the summary", "es": "Queda abierto en el resumen"},
}
TECHNICIAN = {"en": "Not a verdict, see a technician", "es": "No es un veredicto: consultá a un técnico"}

# The routines that reach a parent on Telegram (channels/push.py), by (source, routine): the card's topic.
TOPICS = {
    ("family-push", "morning"): "morning", ("day-engine", "morning_brief"): "morning",
    ("rhythm", "next_feed"): "next_feed", ("night_feed", "handover"): "handover", ("night_feed", None): "night_feed",
    ("house-brain", "tonight"): "tonight", ("house-brain", "replan"): "tonight", ("house-brain", "plan_message"): "tonight",
    ("day-engine", "supplies"): "supplies", ("day-engine", "nap_mode"): "nap", ("day-engine", "floor_clean"): "house",
    ("day-engine", "parents_meals"): "meals", ("reminders", None): "reminder", ("sitter", "sitter_summary"): "sitter",
    ("house-plan", None): "house", ("laundry", None): "house", ("bath", None): "bath", ("house-sounds", "cry"): "cry",
    ("pediatrician", None): "pediatrician",
}
LOOKS = {  # (icon, title word) per topic
    "morning": ("cloudCrescentMoon", "morning"), "next_feed": ("clock", "next_feed"), "handover": ("person", "handover"),
    "on_duty": ("person", "on_duty"), "night_feed": ("lightBulb", "night_feed"), "tonight": ("bedSide", "tonight"),
    "supplies": ("cart", "supplies"), "shopping": ("cart", "shopping"), "nap": ("bedSide", "nap_on"),
    "house": ("house", "house"), "meals": ("forkKnife", "meals"), "reminder": ("bell", "reminder"),
    "sitter": ("threePeopleOverlapping", "sitter"), "bath": ("dropper", "bath"), "dog": ("exclamationTriangle", "dog"),
    "answer": ("speechBubble", "answer"), "note": ("iCircle", "note"), "door": ("bell", "door"),
    "cry": ("exclamationTriangle", "cry"), "pediatrician": ("calendar", "pediatrician"),
}


def lang_of(lang):
    return "es" if lang == "es" else "en"


def clean(text):
    """The text a lens may show: no "Test:" mark, no internal words. None when nothing is left."""
    text = TEST_MARK.sub("", " ".join(str(text or "").split()))
    if not text or INTERNAL.search(text) or final_guard.why_internal(text) or final_guard.ROTA.search(text):
        return None
    return text


def shorten(text, limit):
    """At most limit characters, cut at a word, with an ellipsis when cut."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:·-")
    return cut + "…"


def sentences(text):
    """The sentences of a text, each one cleaned: an internal sentence is dropped, the others kept."""
    out = []
    for part in SENTENCE.split(str(text or "")):
        part = clean(part)
        if part:
            out.append(part.rstrip())
    return out


def card(topic, icon, title, status, detail=None, meta=None, alert=False, sticky=False, lang="en"):
    """One display card, every line cut to fit the 600 x 600 display. A missing status means no card."""
    if icon not in ICONS:
        raise ValueError(f"{icon} is not in the Meta Ray-Ban Display icon catalog we use")
    status = clean(status)
    if not status:
        return None
    out = {"topic": topic, "icon": icon, "title": shorten(clean(title) or WORDS[lang_of(lang)]["note"], LIMITS["title"]),
           "status": shorten(status, LIMITS["status"]), "alert": bool(alert), "sticky": bool(sticky), "lang": lang_of(lang)}
    for key, value in (("detail", detail), ("meta", meta)):
        value = clean(value)
        if value:
            out[key] = shorten(value, LIMITS[key])
    return out


def from_text(topic, text, lang, meta=None, alert=False):
    """A card from a message: the topic's icon and title, the first sentence as the status, the next one as detail."""
    lang = lang_of(lang)
    icon, title = LOOKS.get(topic, LOOKS["note"])
    parts = sentences(text)
    if not parts:
        return None
    return card(topic, icon, WORDS[lang][title], parts[0], parts[1] if len(parts) > 1 else None, meta, alert=alert,
                lang=lang)


# Red flags: the safety gate's fixed lines (agent/rules.py EMERGENCY_REPLY and URGENT_REPLY), sticky and never dimmed.

def red_flag(flag, lang):
    lang = lang_of(lang)
    w = WORDS[lang]
    if flag == "emergency":
        return card("red_flag", "phoneHandsetArrowUpRight", w["red_flag"], w["emergency"], w["tell"], "911",
                    alert=True, sticky=True, lang=lang)
    status = w["fever"] if flag == "urgent_fever" else w["urgent_status"]
    return card("red_flag", "phoneHandsetArrowUpRight", w["urgent"], status, w["no_reach"], w["aap"], alert=True,
                sticky=True, lang=lang)


# The routines

NEXT_FEED = re.compile(r"(?:in about|en unos) (\d+) min, (?:around|cerca de las) (\d{1,2}:\d{2})\..*?(?:about|cada) "
                       r"(\d+ h \d{2} min|\d+ min)", re.I)


def next_feed(text, lang):
    lang = lang_of(lang)
    w = WORDS[lang]
    found = NEXT_FEED.search(text or "")
    if not found:
        return from_text("next_feed", text, lang)
    minutes, at, gap = found.groups()
    return card("next_feed", "clock", w["next_feed"], f"{w['around'].format(at=at)} · {w['in'].format(m=minutes)}",
                w["apart"].format(gap=gap), lang=lang)


MORNING_ORDER = ("duty", "night", "low", "today", "weather", "prep")
MORNING_LINE = {
    "duty": re.compile(r"^(You are on duty tonight|Esta noche te toca a vos)", re.I),
    "night": re.compile(r"^(Last night|Anoche):", re.I), "low": re.compile(r"^(Running low|Se está terminando):", re.I),
    "today": re.compile(r"^(Today|Hoy):", re.I), "weather": re.compile(r"^(Weather|Clima):", re.I),
    "prep": re.compile(r"^(Before he arrives|Antes de que llegue):", re.I),
}


def morning(text, lang):
    """The morning message, shortened: the hello as the title, then the two lines that matter most for this parent."""
    lang = lang_of(lang)
    lines = [line.strip() for line in str(text or "").splitlines() if clean(line)]
    if not lines:
        return None
    title = lines[0].rstrip(".") if re.match(r"^(Good morning|Buen día)", lines[0], re.I) else WORDS[lang]["morning"]
    rest = lines[1:] if title != WORDS[lang]["morning"] else lines
    ranked = sorted(rest, key=lambda line: next((i for i, k in enumerate(MORNING_ORDER) if MORNING_LINE[k].search(line)),
                                                len(MORNING_ORDER)))
    if not ranked:
        return card("morning", "cloudCrescentMoon", title, WORDS[lang]["morning"], lang=lang)
    return card("morning", "cloudCrescentMoon", title, ranked[0], ranked[1] if len(ranked) > 1 else None, lang=lang)


def nap_mode(step, lang, kind=None, since=None, live=False):
    """Nap mode on or off (day_engine nap_mode routine events). The house actions stay dry unless house.live."""
    lang = lang_of(lang)
    w = WORDS[lang]
    meta = None if live else w["dry"]
    if step == "on":
        title = w["sleep_on"] if kind == "sleep" else w["nap_on"]
        status = w["nap_since"].format(kind=w["sleep" if kind == "sleep" else "nap"], at=since) if since else w["quiet"]
        return card("nap", "bedSide", title, status, w["quiet"] if since else None, meta, lang=lang)
    if step == "off":
        return card("nap", "speakerWithTwoArcs", w["nap_off"], w["awake"], None, meta, lang=lang)
    return None


def car_seat(step, lang, index=None, total=None, result=None, ask=False, view=None):
    """One car seat coach step: what to do (say yes or no, say done, or come close to a guide), then what the camera
    saw. Never "safe"."""
    lang = lang_of(lang)
    w = WORDS[lang]
    words = CAR_SEAT.get(step)
    if words is None:
        return None
    if step == "summary":
        return card("car_seat", "carFrontView", w["car_seat"], words[lang], TECHNICIAN[lang], lang=lang)
    if result in CAR_SEAT_RESULT:
        detail = CAR_SEAT_RESULT[result][lang]
    else:
        detail = w["say_yes_no"] if ask else (w["come_close"] if view else w["say_done"])
    meta = w["step"].format(i=index, n=total) if index and total else None
    alert = result in ("fail", "unsure")
    return card("car_seat", "exclamationTriangle" if alert else "carFrontView", w["car_seat"], words[lang], detail, meta,
                alert=alert, lang=lang)


def bath(lang):
    lang = lang_of(lang)
    w = WORDS[lang]
    return card("bath", "dropper", w["bath"], w["bath_on"], w["bath_note"], lang=lang)


# Messages a parent got: a push (proactive, with its source and routine) or the answer to their own words

ON_DUTY = re.compile(r"(?:Esta noche está de turno|De turno:)\s*([^.]+)\.|([A-ZÁÉÍÓÚ][\wáéíóúñ]+) is on duty tonight", re.I)
SHOPPING = re.compile(r"shopping list|lista de compras", re.I)


def topic_of(source, routine):
    return TOPICS.get((source, routine)) or TOPICS.get((source, None)) or "note"


def from_push(event, lang):
    """The card for a proactive reply event (channels/push.py delivered a notify to this parent)."""
    text = event.get("text") or ""
    topic = topic_of(event.get("source"), event.get("routine"))
    if topic == "morning":
        return morning(text, lang)
    if topic == "next_feed":
        return next_feed(text, lang)
    if topic in ("handover", "tonight"):
        return on_duty(text, lang, topic)
    if topic == "supplies" and SHOPPING.search(text):
        return from_text("supplies", text, lang)
    if topic == "cry":
        return from_text("cry", text, lang, alert=bool(event.get("check_now")))
    return from_text(topic, text, lang)


def on_duty(text, lang, topic="on_duty"):
    lang = lang_of(lang)
    w = WORDS[lang]
    found = ON_DUTY.search(text or "")
    name = next((g for g in found.groups() if g), None) if found else None
    if not name:
        found = re.search(r"(?:On duty|De turno):\s*([^.\n]+)", text or "")
        name = found.group(1).strip() if found else None
    icon, title = LOOKS[topic]
    if name is None:
        return from_text(topic, text, lang)
    parts = sentences(text)
    detail = next((p for p in parts[1:] if not ON_DUTY.search(p)), None) if topic != "on_duty" else None
    return card(topic, icon, w[title], w["duty"].format(name=name.strip()), detail, lang=lang)


def from_reply(event, lang):
    """The card for the agent's answer to this parent's own words: a red flag first, then what the answer is about."""
    if event.get("flag"):
        return red_flag(event["flag"], lang)
    text = event.get("text") or ""
    if event.get("topic") == "on_duty" or ON_DUTY.search(text):
        return on_duty(text, lang)
    if SHOPPING.search(text):
        return from_text("shopping", text, lang)
    return from_text("answer", text, lang)
