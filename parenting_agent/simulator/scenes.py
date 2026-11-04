"""Shortcuts for the moments in the video, in story order. Each one only dispatches the event the real home would send, and Muse
decides what follows: nothing here holds an outcome. A parent's words are input, in the language chosen.

The night of Dec 15 is Ceci's on the rota, so when she asks to sleep, the plan really has to change.
"""

import json
from pathlib import Path

HUMIDITY = "sensor.nursery_climate_humidity"
CRY_ROOM = {"en": "parents' bedroom, in Theo's crib beside their bed", "es": "dormitorio de los padres, en la cunita de Theo al lado de la cama"}

SCENES = (
    {"id": "evening", "at": "2026-12-15T21:30:00-03:00", "type": "schedule", "payload": {"name": "evening"}},
    {"id": "sleep", "at": "2026-12-15T21:45:00-03:00", "type": "message", "payload": {"from": "ceci", "channel": "the phone"},
     "text": {"en": "Tonight I need to sleep. Can Gonza take the night?", "es": "Esta noche necesito dormir. ¿Gonza puede quedarse con la noche?"}},
    {"id": "cry", "at": "2026-12-16T02:50:00-03:00", "type": "sound", "payload": {"kind": "baby crying"}, "room": CRY_ROOM},
    {"id": "feed", "at": "2026-12-16T03:20:00-03:00", "type": "message", "payload": {"from": "gonza", "channel": "a voice note, transcribed"},
     "text": {"en": "I gave him a 90 ml bottle at three.", "es": "Le di una mamadera de 90 ml a las tres."}},
    {"id": "morning", "at": "2026-12-16T07:30:00-03:00", "type": "schedule", "payload": {"name": "morning"}},
    {"id": "grandma", "at": "2026-12-16T11:00:00-03:00", "type": "message", "payload": {"from": "Grandma", "channel": "the kitchen Echo, out loud"},
     "text": {"en": "Baby agent, when did Theo last eat?", "es": "Agente del bebé, ¿cuándo comió Theo por última vez?"}},
    {"id": "humid", "at": "2026-12-16T15:10:00-03:00", "type": "state_changed", "payload": {"entity_id": HUMIDITY, "state": "71.2"}},
    {"id": "recipe", "at": "2026-12-16T16:30:00-03:00", "type": "message", "payload": {"from": "gonza", "channel": "the phone"},
     "text": {"en": "Grandma just told me her pumpkin puree: 300 g pumpkin and 100 g water, 20 min/100°C/speed 1, then 30 sec/speed 5. Her Cookidoo is in Uruguay. Can you turn it into a Thermomix recipe?",
              "es": "La abuela me acaba de pasar su puré de zapallo: 300 g de zapallo y 100 g de agua, 20 min/100°C/velocidad 1, después 30 seg/velocidad 5. Su Cookidoo es de Uruguay. ¿Lo pasás a receta de Thermomix?"}},
    {"id": "dry", "at": "2026-12-16T17:40:00-03:00", "type": "state_changed", "payload": {"entity_id": HUMIDITY, "state": "49.5"}},
    {"id": "carseat", "at": "2026-12-16T18:10:00-03:00", "type": "message", "payload": {"from": "gonza", "channel": "his Meta glasses kit, out loud"},
     "text": {"en": "Agent, help me install the car seat.", "es": "Agente, ayudame a instalar la silla del auto."}},
    {"id": "evening2", "at": "2026-12-16T21:30:00-03:00", "type": "schedule", "payload": {"name": "evening"}},
)
BY_ID = {scene["id"]: scene for scene in SCENES}
START = "2026-12-15T21:00:00-03:00"
# Theo's day before the first scene, so the log has something true to read.
LOG = (("2026-12-15T14:10:00-03:00", "feeding", {"amount_ml": 80, "method": "bottle"}),
       ("2026-12-15T14:40:00-03:00", "diaper", {"wet": True, "solid": False}),
       ("2026-12-15T17:30:00-03:00", "feeding", {"amount_ml": 85, "method": "bottle"}),
       ("2026-12-15T18:05:00-03:00", "diaper", {"wet": True, "solid": True}),
       ("2026-12-15T20:40:00-03:00", "feeding", {"amount_ml": 90, "method": "bottle"}))
FACTS = {"en": "Parents read English in this simulation: write every message and everything said out loud in English.",
         "es": "Los padres leen español rioplatense en esta simulación: escribí todo mensaje y todo lo que se dice en voz alta en español."}


# What a judge may send by hand. The entity ids are the real home's. The ranges only keep a reading physically possible.
READINGS = {HUMIDITY: (0, 100), "sensor.nursery_climate_temperature": (-10, 50)}
SWITCHES = ("switch.study_tapo_p110_dehumidifier", "switch.study_tapo_p110_bottle_warmer")
SOUNDS = ("baby crying", "dog barking")
SCHEDULES = ("morning", "evening")


def checked_event(kind, payload, lang):
    """The event as the home would send it, or None if it isn't one a judge can send."""
    if not isinstance(payload, dict):
        return None
    if kind == "state_changed":
        entity, state = payload.get("entity_id"), payload.get("state")
        if entity in SWITCHES and state in ("on", "off"):
            return {"entity_id": entity, "state": state}
        if entity in READINGS:
            try:
                value = float(state)
            except (TypeError, ValueError):
                return None
            low, high = READINGS[entity]
            return {"entity_id": entity, "state": str(round(value, 1))} if low <= value <= high else None
    if kind == "sound" and payload.get("kind") in SOUNDS:
        return {"kind": payload["kind"], "room": CRY_ROOM[lang]}
    if kind == "schedule" and payload.get("name") in SCHEDULES:
        return {"name": payload["name"]}
    return None


def event(scene, lang):
    payload = dict(scene["payload"])
    if "text" in scene:
        payload["text"] = scene["text"][lang]
    if "room" in scene:
        payload["room"] = scene["room"][lang]
    return scene["type"], payload


# What Meta's models made of real recordings, computed on the Mac by scripts/sim_senses.py. This container runs neither model.
SENSES_FILE = Path(__file__).parent / "static/senses/senses.json"
SENSES = json.loads(SENSES_FILE.read_text()) if SENSES_FILE.is_file() else {"audio": [], "frames": []}
HEARD = {"cry": "baby crying", "dog": "dog barking", "doorbell": "doorbell ringing", "splash": "water splashing"}
SAW = {"on": {"en": "a hand is on the baby", "es": "hay una mano sobre el bebé"},
       "off": {"en": "no hand is on the baby", "es": "ninguna mano está sobre el bebé"},
       "unsure": {"en": "it can't tell if a hand is on the baby", "es": "no puede saber si hay una mano sobre el bebé"}}
TABLE = {"en": "the changing table camera", "es": "la cámara del cambiador"}


def sense_event(sense_id, lang):
    """The event a saved result makes, with which model said so. None when there is no such result, or it would wake nobody."""
    for clip in SENSES["audio"]:
        if clip["id"] == sense_id and clip["heard"]:
            share = min(99.9, int(clip["scores"][clip["heard"]]["probability"] * 1000) / 10)
            return "sound", {"kind": f"{HEARD[clip['heard']]}, heard by Perception Encoder Audio at {share}%, computed earlier on a recording", "room": CRY_ROOM[lang]}
    for frame in SENSES["frames"]:
        if frame["id"] == sense_id:
            return "camera", {"camera": TABLE[lang], "model": "SAM 3.1", "saw": SAW[frame["verdict"]][lang], "hand_masks": frame["hands"], "note": "computed earlier on a generated clip"}
    return None
