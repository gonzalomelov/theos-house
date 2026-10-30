"""One short morning message per parent (Oct 30, Gonza: store as much context as possible, show only what is relevant).

Before, each parent got three messages each morning: the day engine's brief and the house brain's night explanation at
07:30, and the prep nudge at 08:00. Now the family push holds the first two, adds the prep lines, and sends each parent
one message with only what is theirs:

| Line | Who reads it |
|---|---|
| Last night: feeds, longest sleep, how many times you were up | both, only when the log has a night feed or a wake-up |
| You are on duty tonight | only the parent the night rota names for tonight |
| Weather, supplies running low, today's appointments and Cookidoo meals | both |
| What the house did overnight (the house brain's explanation) | only the parent on duty last night, and only when it has overnight events |
| Prep: the countdown, the next appointment, the next items | both |

Everything else stays in the event log: the full brief, the full explanation, the kitchen temperature, the next feed
guess. The "morning_message" event keeps the facts and each parent's text.

A scheduled push goes out at most once a day per parent, across restarts: the day and the people it went to are kept
in data/scheduled-pushes.json (Sent below). On Oct 29 restarts sent the morning brief 6 times and tonight's plan 5 times.
"""
import json
import threading
from pathlib import Path

SKY = {"en": {"sunny": "sunny", "clear-night": "clear", "partlycloudy": "partly cloudy", "cloudy": "cloudy",
              "rainy": "rain", "pouring": "heavy rain", "fog": "fog", "windy": "windy", "windy-variant": "windy",
              "lightning-rainy": "storms", "lightning": "storms", "snowy": "snow", "snowy-rainy": "sleet", "hail": "hail"},
       "es": {"sunny": "soleado", "clear-night": "despejado", "partlycloudy": "parcialmente nublado", "cloudy": "nublado",
              "rainy": "lluvia", "pouring": "lluvia fuerte", "fog": "niebla", "windy": "viento", "windy-variant": "viento",
              "lightning-rainy": "tormentas", "lightning": "tormentas", "snowy": "nieve", "snowy-rainy": "aguanieve",
              "hail": "granizo"}}
SUPPLY = {"en": {"diapers": "Diapers", "wipes": "Wipes", "formula": "Formula"},
          "es": {"diapers": "Pañales", "wipes": "Toallitas", "formula": "Fórmula"}}
WORDS = {
    "en": {"hello": "Good morning, {name}.", "night": "Last night: {feeds} feed{s}, longest sleep {h} h, you were up {times}.",
           "night_none": "Last night: {feeds} feed{s}, longest sleep {h} h, you were not up.",
           "times": ("once", "{n} times"), "duty": "You are on duty tonight.", "weather": "Weather: {sky}, {low} to {high} C{rain}.",
           "rain": ", {mm:g} mm of rain", "low": "Running low: {items}.", "left": "{name} (about {d:.1f} days left)",
           "today": "Today: {items}.", "meals": "Cookidoo meal plan: {items}.", "house": "The house overnight: {text}",
           "prep": "Before he arrives: {line}"},
    "es": {"hello": "Buen día, {name}.", "night": "Anoche: {feeds} toma{s}, el sueño más largo {h} h, te levantaste {times}.",
           "night_none": "Anoche: {feeds} toma{s}, el sueño más largo {h} h, no te levantaste.",
           "times": ("una vez", "{n} veces"), "duty": "Esta noche te toca a vos.", "weather": "Clima: {sky}, {low} a {high} C{rain}.",
           "rain": ", {mm:g} mm de lluvia", "low": "Se está terminando: {items}.", "left": "{name} (quedan unos {d:.1f} días)",
           "today": "Hoy: {items}.", "meals": "Menú de Cookidoo: {items}.", "house": "La casa de noche: {text}",
           "prep": "Antes de que llegue: {line}"},
}


def compose(lang, name, label, brief=None, explain=None, prep=(), tonight=None, last_night=None):
    """One parent's morning message. label is the parent's rota label ("Parent A"), tonight and last_night the rota
    labels on duty. brief and explain are the facts of the two notify events, prep the prep lines. Pure."""
    lang = "es" if lang == "es" else "en"
    w = WORDS[lang]
    lines = [w["hello"].format(name=name)]
    night = (brief or {}).get("night") or {}
    up = (night.get("wakeups") or {}).get(label, 0)
    if night.get("feeds") or any((night.get("wakeups") or {}).values()):
        feeds = night.get("feeds", 0)
        times = w["times"][0] if up == 1 else w["times"][1].format(n=up)
        line = w["night"] if up else w["night_none"]
        lines.append(line.format(feeds=feeds, s="" if feeds == 1 else "s", h=f"{night.get('longest_h') or 0:.1f}",
                                 times=times))
    if tonight and tonight == label:
        lines.append(w["duty"])
    weather = (brief or {}).get("weather")
    if weather and SKY[lang].get(weather.get("sky")):
        rain = w["rain"].format(mm=weather["rain_mm"]) if weather.get("rain_mm") else ""
        lines.append(w["weather"].format(sky=SKY[lang][weather["sky"]], low=weather["low"], high=weather["high"], rain=rain))
    low = [w["left"].format(name=SUPPLY[lang].get(r["item"], r["item"]), d=r["days_left"])
           for r in (brief or {}).get("low") or [] if r.get("days_left") is not None]
    if low:
        lines.append(w["low"].format(items=", ".join(low)))
    if (brief or {}).get("appointments"):
        lines.append(w["today"].format(items=", ".join(brief["appointments"])))
    if (brief or {}).get("meals"):
        lines.append(w["meals"].format(items=", ".join(brief["meals"])))
    facts = (explain or {}).get("facts") or {}
    # Only a night the house really got ready for (a night feed, a device moved) is worth a line, and only for the
    # parent who was on duty. Muse writes the explanation in English: a Spanish parent reads the same facts in Spanish.
    relevant = facts.get("night_feeds", facts.get("events", 1)) or facts.get("real")
    if explain and explain.get("text") and relevant and (last_night in (None, label)):
        text = explain["text"].strip() if lang == "en" else house_es(facts)
        if text:
            lines.append(w["house"].format(text=text))
    if prep:
        lines.append(w["prep"].format(line=prep[0]))
        lines.extend(prep[1:])
    return "\n".join(lines)


def house_es(facts):
    """The house's night in Spanish, from the explanation's facts only."""
    feeds, real = facts.get("night_feeds") or 0, facts.get("real") or 0
    if not feeds and not real:
        return ""
    parts = [f"se preparó para {feeds} toma{'s' if feeds != 1 else ''} nocturna{'s' if feeds != 1 else ''}"] if feeds else []
    parts.append(f"{real} acción{'es' if real != 1 else ''} de verdad, el resto solo anotado (prueba en seco)" if real
                 else "todo solo anotado (prueba en seco)")
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."


class Sent:
    """Which scheduled pushes went to whom today, kept on disk so a restart never sends one twice."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def read(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def sent(self, routine, person, day):
        return (self.read().get(routine) or {}).get(person) == day

    def mark(self, routine, people, day):
        with self.lock:
            data = self.read()
            data.setdefault(routine, {}).update({p: day for p in people})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, sort_keys=True))
            tmp.replace(self.path)
