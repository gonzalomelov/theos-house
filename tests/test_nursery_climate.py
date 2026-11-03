"""Theo's room sensor (Nov 1): the AHT30 reading, the 16 to 20 °C guide with its source, and room questions answered.

Offline: Home Assistant is a fake with fixed states. No network, no house.
"""
import datetime
import tempfile
import unittest

from parenting_agent.agent import rules
from parenting_agent.nursery_climate import GUIDE, NurseryClimate, against_guide, answer, reading
from tests.test_family_push import CECI, GONZA, Family, at
from test_one_message_one_entry import ScriptedBrain

NOW = datetime.datetime(2026, 11, 1, 3, 0, tzinfo=datetime.timezone.utc)
TEMP, HUM = "sensor.nursery_climate_temperature", "sensor.nursery_climate_humidity"
# Words the agent never says about the room or the baby.
NEVER_SAID = ("too hot", "too cold", "safe", "dangerous", "the baby is", "demasiado", "segur", "peligro", "el bebé está")


def state(value, minutes_ago=1, now=NOW):
    stamp = (now - datetime.timedelta(minutes=minutes_ago)).isoformat()
    return {"state": str(value), "attributes": {}, "last_updated": stamp, "last_reported": stamp}


class FakeHA:
    def __init__(self, temp=19.4, hum=58.2, minutes_ago=1, now=NOW):
        self.states = {TEMP: state(temp, minutes_ago, now), HUM: state(hum, minutes_ago, now)}
        self.gets = []

    def entity(self, entity_id):
        self.gets.append(entity_id)
        if entity_id not in self.states:
            raise OSError("not found")
        return self.states[entity_id]


class Reading(unittest.TestCase):
    def test_fresh_reading(self):
        r = reading(FakeHA(19.4, 58.2), NOW)
        self.assertEqual((r["temp_c"], r["humidity"], r["ok"]), (19.4, 58.2, True))

    def test_old_reading_is_a_gap(self):
        r = reading(FakeHA(minutes_ago=12), NOW)
        self.assertFalse(r["ok"])
        self.assertEqual(r["age_min"], 12.0)

    def test_unavailable_and_impossible_values_are_gaps(self):
        for temp, hum in (("unavailable", 50), (19, "unknown"), (61.0, 50), (-3, 50), (19, 140)):
            self.assertFalse(reading(FakeHA(temp, hum), NOW)["ok"], (temp, hum))

    def test_failed_read_is_a_gap(self):
        ha = FakeHA()
        ha.states.clear()
        self.assertEqual(reading(ha, NOW), {"temp_c": None, "humidity": None, "age_min": None, "ok": False})

    def test_last_reported_wins_over_last_updated(self):
        # A steady room keeps the same value, so last_updated grows old while the sensor still reports every minute.
        ha = FakeHA()
        ha.states[TEMP]["last_updated"] = (NOW - datetime.timedelta(hours=2)).isoformat()
        self.assertTrue(reading(ha, NOW)["ok"])


class Guide(unittest.TestCase):
    def test_the_guide_is_lullaby_and_nhs_16_to_20(self):
        self.assertEqual((GUIDE["low_c"], GUIDE["high_c"]), (16.0, 20.0))
        self.assertIn("lullabytrust.org.uk", GUIDE["url"])

    def test_edges(self):
        self.assertEqual(against_guide(16.0), ("inside", 0.0))
        self.assertEqual(against_guide(20.0), ("inside", 0.0))
        self.assertEqual(against_guide(21.34), ("above", 1.3))
        self.assertEqual(against_guide(15.2), ("below", 0.8))


class Answer(unittest.TestCase):
    def ok(self, temp, hum=58.0):
        return {"temp_c": temp, "humidity": hum, "age_min": 1.0, "ok": True}

    def test_spanish_inside(self):
        text = answer(self.ok(18.6, 61.4), "es")
        self.assertEqual(text, "Cuarto de Theo: 18,6 °C y 61 % de humedad. La guía de Lullaby Trust y NHS para el cuarto "
                               "donde duerme un bebé es de 16 a 20 °C: está dentro de la guía. "
                               "https://www.lullabytrust.org.uk/")

    def test_english_above_and_below(self):
        self.assertIn("22.4 °C and 58 % humidity", answer(self.ok(22.4), "en"))
        self.assertIn("16 to 20 °C: 2.4 °C above it.", answer(self.ok(22.4), "en"))
        self.assertIn("16 a 20 °C: está 1,5 °C abajo.", answer(self.ok(14.5), "es"))

    def test_a_gap_gives_no_number(self):
        text = answer({"temp_c": None, "humidity": None, "age_min": 42.0, "ok": False}, "es")
        self.assertEqual(text, "Cuarto de Theo: el sensor no tiene una lectura reciente. La última fue hace 42 min. "
                               "No digo una temperatura que no sé.")
        self.assertNotIn("°C", answer({"temp_c": 30.0, "humidity": 50.0, "age_min": 9.0, "ok": False}, "en"))

    def test_never_advice(self):
        for temp in (12.0, 18.0, 27.0):
            for lang in ("en", "es"):
                text = answer(self.ok(temp), lang).lower().replace(GUIDE["url"].split("://")[1], "")
                for word in NEVER_SAID:
                    self.assertNotIn(word, text, (temp, lang))


class RoomQuestion(unittest.TestCase):
    ROOM = ["¿qué temperatura hay en el cuarto?", "que temperatura hay en el cuarto de Theo", "¿Cuánta humedad hay en la pieza?",
            "¿hace frío en el cuarto?", "what's the temperature in the nursery?", "how warm is Theo's room?",
            "is the room too hot?", "¿qué temperatura tiene el cuarto?"]
    NOT_ROOM = ["tiene 38 y el cuarto está caliente", "¿está caliente el cuarto? tiene la frente caliente",
                "¿cómo lo abrigo si el cuarto está a 17 grados?", "does he have a fever? the room is warm",
                "el cuarto está a 22", "¿qué temperatura es fiebre?", "is the bath water too hot?",
                "what layers should he wear in a cold room?", "¿le pongo el saco de dormir con el cuarto frío?"]

    def test_room_questions(self):
        for text in self.ROOM:
            self.assertTrue(rules.asks_room_climate(text), text)

    def test_body_and_advice_stay_with_the_gate(self):
        for text in self.NOT_ROOM:
            self.assertFalse(rules.asks_room_climate(text), text)


class OnTheFamilyAgent(unittest.TestCase):
    """A parent asks on Telegram: the reading comes from plain code, no brain call, and a fever still gets the gate."""

    def family(self, tmp, ha):
        brain = ScriptedBrain(["(brain)"])
        family = Family(tmp, at(31, 22, 0), brain=brain, plugins=())
        family.nursery = NurseryClimate(family.agent, family.config, client=ha, clock=lambda: NOW)
        family.agent.plugins.append(family.nursery)
        return family, brain

    def test_room_question_is_answered_by_the_sensor(self):
        with tempfile.TemporaryDirectory() as tmp:
            ha = FakeHA(21.3, 64.0)
            family, brain = self.family(tmp, ha)
            try:
                family.say(CECI, "¿qué temperatura hay en el cuarto?")
                sent = family.sent_to(CECI)
                self.assertEqual(len(sent), 1)
                self.assertIn("Cuarto de Theo: 21,3 °C y 64 % de humedad", sent[0])
                self.assertIn("está 1,3 °C arriba", sent[0])
                self.assertIn("https://www.lullabytrust.org.uk/", sent[0])  # the source survives the final guard
                self.assertEqual(brain.plans, [["(brain)"]])  # the brain never ran
                self.assertEqual(ha.gets, [TEMP, HUM])
                guards = [e["status"] for e in family.agent.bus.history if e["kind"] == "guard"]
                self.assertIn("nursery_climate", guards)
                self.assertNotIn("health_refused", guards)
            finally:
                family.close()

    def test_a_fever_question_never_gets_the_room_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            ha = FakeHA()
            family, _ = self.family(tmp, ha)
            try:
                family.say(GONZA, "¿qué temperatura es fiebre para un bebé?")
                self.assertEqual(ha.gets, [])
                self.assertNotIn("Cuarto de Theo", " ".join(family.sent_to(GONZA)))
            finally:
                family.close()

    def test_the_tool_reads_the_same(self):
        with tempfile.TemporaryDirectory() as tmp:
            family, _ = self.family(tmp, FakeHA(17.0, 55.0))
            try:
                self.assertEqual(family.nursery.answer("en")[:45], "Theo's room: 17.0 °C and 55 % humidity. The L")
                self.assertIn("nursery_climate", family.agent.tools.items)
            finally:
                family.close()


if __name__ == "__main__":
    unittest.main()
