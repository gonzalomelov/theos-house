"""The root causes the held-out first month found (results/heldout-first-month, run-1), on the family agent with Baby
Buddy: the ops brain (log_ops.py) and a scripted Muse, the patterns of the failing items, never the items themselves.

1. corrections edit or delete the entry they mean, and the reply says exactly what changed
2. the entry keeps what the reply says: amount, colour, breast milk, minutes, side
3. red flags said as a reading ("tiene 38,2") get the fixed line
4. a red flag message still logs the feed or diaper it reports, after the line
5. an open sleep is read from Baby Buddy, two feeds in one message are both kept
6. English messages are answered in English in a family whose people block reads Spanish
"""
import datetime
import os
import tempfile
import unittest

from parenting_agent.agent import build, log_ops, rules
from parenting_agent.agent import config as config_mod
from parenting_agent.agent.brain import Reply

import fixed_clock
from fake_babybuddy import TOKEN, FakeBabyBuddy


class Scripted:
    """Answers each call with the next queued tool call, or a text, and keeps what it was shown."""
    name, model, destination = "scripted", "scripted-muse", "none"

    def __init__(self):
        self.queue, self.seen = [], []

    def step(self, system, transcript, tools):
        self.seen.append({"system": system, "text": transcript[-1]["text"], "tools": [t["name"] for t in tools]})
        item = self.queue.pop(0) if self.queue else ("text", "Dale.")
        if item[0] == "text":
            return Reply(item[1], [], {"input_tokens": 10, "output_tokens": 10})
        return Reply("", [{"id": str(len(self.seen)), "name": item[0], "arguments": item[1]}],
                     {"input_tokens": 10, "output_tokens": 10})


def ops(*items, reply="", **more):
    return "log_ops", {"ops": list(items), "reply": reply, **more}


class FamilyAgent(unittest.TestCase):
    def setUp(self):
        self.clock = fixed_clock.frozen()
        self.clock.start()
        self.server = FakeBabyBuddy(refuse_overlaps=True, per_endpoint_ids=True)
        os.environ["PA_TEST_BB_URL"], os.environ["PA_TEST_BB_TOKEN"] = self.server.url, TOKEN
        config = config_mod.load()
        config.update({"data_dir": tempfile.mkdtemp(), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                       "log_mode": "ops",
                       "allowed_tools": ["log_baby_event", "edit_baby_event", "delete_baby_event", "read_baby_log",
                                         "baby_summary", "remember", "current_time"],
                       "baby_log": {"provider": "babybuddy", "url_env": "PA_TEST_BB_URL",
                                    "token_env": "PA_TEST_BB_TOKEN", "child": "test-baby"},
                       "people": {"ceci": {"name": "Ceci", "lang": "es"}, "gonza": {"name": "Gonza", "lang": "es"}}})
        self.agent = build(config)
        self.brain = Scripted()
        self.agent.brain = self.brain
        self.agent.danger = None
        self.replies = []
        self.agent.bus.subscribe(self.replies.append, ["reply"])

    def tearDown(self):
        self.agent.memory.close()
        self.server.close()
        self.clock.stop()

    def say(self, text, *calls, person="ceci"):
        self.brain.queue += list(calls)
        start = len(self.replies)
        event = {"kind": "message", "channel": "telegram", "text": text, "person": person, "chat_id": "1"}
        self.agent.current_event = event
        try:
            self.agent.handle(event)
        finally:
            self.agent.current_event = None
        return [r["text"] for r in self.replies[start:]]

    def records(self, name):
        return self.server.all(name)

    def at(self, minutes_ago):
        return (datetime.datetime.now().astimezone() - datetime.timedelta(minutes=minutes_ago)).strftime("%H:%M")


class Corrections(FamilyAgent):
    def test_an_amount_correction_edits_the_feed_and_says_what_changed(self):
        self.say("le di 120 de mamadera", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 120}))
        feed = self.records("feedings")[0]
        reply = self.say("no perdón, fueron 100", ops({"op": "edit", "id": feed["id"], "kind": "feeding", "amount_ml": 100}))
        self.assertEqual([r["amount"] for r in self.records("feedings")], [100.0])
        self.assertIn("120 ml → 100 ml", reply[0])
        self.assertNotIn("no puedo cambiar", reply[0])

    def test_a_delete_names_the_kind_so_a_diaper_and_a_feed_with_the_same_id_stay_apart(self):
        self.say("le di 80", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 80}))
        self.say("pañal con pis", ops({"op": "add", "kind": "diaper", "wet": True, "solid": False}))
        self.assertEqual((self.records("feedings")[0]["id"], self.records("changes")[0]["id"]), (1, 1))
        reply = self.say("borrá el último pañal", ops({"op": "delete", "id": 1, "kind": "diaper"}))
        self.assertEqual((len(self.records("feedings")), len(self.records("changes"))), (1, 0))
        self.assertRegex(reply[0], r"^Borré el pañal de las \d\d:\d\d\.$")

    def test_the_wrong_kind_is_a_delete_and_an_add(self):
        self.say("anotá una toma de 70", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 70}))
        reply = self.say("perdón no era una toma, era un pañal con caca",
                         ops({"op": "delete", "id": 1, "kind": "feeding"}, {"op": "add", "kind": "diaper", "wet": False,
                                                                           "solid": True}))
        self.assertEqual((len(self.records("feedings")), len(self.records("changes"))), (0, 1))
        self.assertIn("Borré la mamadera de 70 ml", reply[0])
        self.assertIn("pañal sucio", reply[0])

    def test_a_bottle_that_was_a_breast_feed_keeps_no_ml(self):
        self.say("le di 60", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 60}))
        self.say("era pecho izquierdo no mamadera", ops({"op": "edit", "id": 1, "kind": "feeding", "method": "left breast"}))
        feed = self.records("feedings")[0]
        self.assertEqual((feed["method"], feed["type"], feed.get("amount")), ("left breast", "breast milk", None))

    def test_a_diaper_gets_its_solid_and_its_colour_fixed(self):
        self.say("pañal con pis", ops({"op": "add", "kind": "diaper", "wet": True, "solid": False}))
        reply = self.say("ah y tenía caca verde también", ops({"op": "edit", "id": 1, "kind": "diaper", "solid": True,
                                                               "color": "verde"}))
        change = self.records("changes")[0]
        self.assertEqual((change["wet"], change["solid"], change["color"], len(self.records("changes"))),
                         (True, True, "green", 1))
        self.assertIn("mojado → mojado y sucio", reply[0])
        self.assertIn("sin color → verde", reply[0])

    def test_a_sleep_start_that_never_happened_is_deleted(self):
        self.say("se durmió", ops({"op": "sleep_start"}))
        self.assertEqual(len(self.records("timers")), 1)
        self.assertIsNotNone(self.agent.baby_log.open_sleep())
        reply = self.say("borrá eso, falsa alarma, está despierto", ops({"op": "delete", "id": "open-sleep"}))
        self.assertEqual(self.records("timers"), [])
        self.assertTrue(reply[0].startswith("Borré el sueño"), reply)

    def test_a_failed_edit_says_nothing_changed_never_that_the_log_cannot_change(self):
        reply = self.say("el de las 4 fueron 20 min", ops({"op": "edit", "id": 99, "kind": "feeding", "duration_min": 20}))
        self.assertIn("No pude cambiar el registro", reply[0])

    def test_a_sleep_end_correction_moves_the_end(self):
        self.say("durmió de 13:10 a 15:00", ops({"op": "add", "kind": "sleep", "start": self.at(110), "end": self.at(5)}))
        sleep = self.records("sleep")[0]
        reply = self.say("en realidad se despertó antes", ops({"op": "edit", "id": sleep["id"], "kind": "sleep",
                                                               "end": self.at(25)}))
        self.assertEqual(self.records("sleep")[0]["end"][11:16], self.at(25))
        self.assertIn("→", reply[0])


class WhatIsStored(FamilyAgent):
    def test_colour_breast_milk_and_minutes_are_stored_and_the_reply_comes_from_them(self):
        reply = self.say("caca mostaza", ops({"op": "add", "kind": "diaper", "wet": False, "solid": True, "color": "mostaza"}))
        self.assertEqual(self.records("changes")[0]["color"], "yellow")
        self.assertIn("pañal sucio con caca amarilla", reply[0])
        reply = self.say("tomó 70 de la leche que me saqué", ops({"op": "add", "kind": "feeding", "method": "bottle",
                                                                 "amount_ml": 70, "type": "breast milk", "at": self.at(30)}))
        self.assertEqual(self.records("feedings")[0]["type"], "breast milk")
        self.assertIn("70 ml de leche materna", reply[0])
        self.say("teta derecha 20 min", ops({"op": "add", "kind": "feeding", "method": "right breast", "duration_min": 20}))
        feed = self.records("feedings")[-1]
        start, end = (datetime.datetime.fromisoformat(feed[k]) for k in ("start", "end"))
        self.assertEqual((feed["method"], round((end - start).total_seconds() / 60)), ("right breast", 20))

    def test_a_length_nobody_said_is_never_in_the_reply(self):
        reply = self.say("le di 60", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 60,
                                          "at": self.at(60)}))
        self.assertNotIn("min", reply[0])
        self.assertIsNone(self.agent.baby_log.entries("feeding")[0]["details"]["duration_min"])
        reply = self.say("teta izquierda", ops({"op": "add", "kind": "feeding", "method": "left breast"}))
        self.assertNotIn("min", reply[0])
        self.say("fueron 12 min", ops({"op": "edit", "id": 2, "kind": "feeding", "duration_min": 12}))
        self.assertEqual(self.agent.baby_log.entries("feeding")[-1]["details"]["duration_min"], 12)

    def test_a_milk_type_nobody_said_is_never_in_the_reply(self):
        reply = self.say("le di 90", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 90}))
        self.assertNotIn("fórmula", reply[0])
        reply = self.say("era leche materna", ops({"op": "edit", "id": 1, "kind": "feeding", "type": "breast milk"}))
        self.assertIn("sin tipo de leche → leche materna", reply[0])
        self.assertEqual(self.records("feedings")[0]["type"], "breast milk")

    def test_a_health_question_gets_the_fixed_line_never_the_brains_words(self):
        reply = self.say("caca verde, eso está bien?", ops({"op": "add", "kind": "diaper", "solid": True, "color": "green"},
                                                          reply="Es normal en recién nacidos."))
        self.assertNotIn("normal", reply[0])
        self.assertIn(rules.NO_ADVICE["es"], reply[0])
        reply = self.say("he sneezes a lot", ops(reply="Sneezing is common in newborns.", health=True), person="gonza")
        self.assertEqual(reply, [rules.NO_ADVICE["en"]])

    def test_a_colour_that_is_not_a_stool_colour_is_left_out(self):
        self.say("pañal con caca rara", ops({"op": "add", "kind": "diaper", "solid": True, "color": "pálida"}))
        self.assertNotIn("color", self.records("changes")[0])

    def test_two_feeds_in_one_message_are_both_kept(self):
        reply = self.say("le di 50 de leche materna y después otra de 30 de fórmula",
                         ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 50, "type": "breast milk"},
                             {"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 30, "type": "formula"}))
        self.assertEqual(sorted((r["amount"], r["type"]) for r in self.records("feedings")),
                         [(30.0, "formula"), (50.0, "breast milk")])
        self.assertIn("50 ml", reply[0])
        self.assertIn("30 ml", reply[0])

    def test_two_feeds_named_at_one_time_are_both_kept(self):
        self.say("a las 2 le di 50 de leche materna y otra de 30 de fórmula",
                 ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 50, "at": self.at(20)},
                     {"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 30, "at": self.at(20)}))
        self.assertEqual(sorted(r["amount"] for r in self.records("feedings")), [30.0, 50.0])
        self.assertEqual(max(r["end"] for r in self.records("feedings"))[11:16], self.at(20))

    def test_how_much_to_give_is_a_health_question(self):
        self.assertTrue(log_ops.asks_health("le doy 90 o 120?"))
        self.assertTrue(log_ops.asks_health("cuanto le tengo que dar a esta edad"))
        self.assertFalse(log_ops.asks_health("cuanto tomo hoy"))

    def test_the_brain_sees_the_open_sleep_and_the_milk_totals(self):
        self.say("se durmió", ops({"op": "sleep_start", "at": self.at(70)}))
        self.say("tomó 90 de fórmula", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 90,
                                            "type": "formula", "at": self.at(120)}))
        self.say("sigue dormido", ops())
        seen = self.brain.seen[-1]["text"]
        self.assertRegex(seen, r"Open sleep \(id open-sleep\): asleep since \w+ \d\d:\d\d, 1 h 10 min so far")
        self.assertIn("bottles of formula: 1, 90 ml", seen)
        self.assertEqual(len(self.records("timers")), 1)

    def test_the_prompt_reads_intentions_sequences_and_corrections(self):
        for words in ("le voy a dar", "sigue dormido", "Se despertó llorando", "the log cannot be changed: it can",
                      "leche materna", "mostaza", '"id": "open-sleep"'):
            self.assertIn(words, log_ops.OPS_SYSTEM)


class Alerts(FamilyAgent):
    def test_a_red_flag_gets_the_line_first_and_then_the_feed_it_reported(self):
        replies = self.say("le di 50 de mamadera y se puso todo flojito, no reacciona",
                           ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 50},
                               {"op": "add", "kind": "note", "text": "flojito, no reacciona"}))
        self.assertEqual(replies[0], rules.EMERGENCY_REPLY["es"])
        self.assertEqual([r["amount"] for r in self.records("feedings")], [50.0])
        self.assertIn("50 ml", replies[1])

    def test_with_no_log_ops_answer_the_plain_rules_log_the_feed_after_the_line(self):
        replies = self.say("le di 30 ml y no reacciona", ("text", "not a log_ops call"), ("text", "still not"))
        self.assertEqual(replies[0], rules.EMERGENCY_REPLY["es"])
        self.assertEqual([r["amount"] for r in self.records("feedings")], [30.0])

    def test_the_line_stays_when_the_log_after_it_breaks(self):
        self.agent.log_reported = lambda text: 1 / 0
        replies = self.say("no reacciona", ("text", "not a log_ops call"), ("text", "still not"))
        self.assertEqual(replies, [rules.EMERGENCY_REPLY["es"]])

    def test_not_feeding_for_hours_is_a_red_flag_in_any_words(self):
        for text in ("dirty diaper but he hasnt fed since 9am and wont latch", "no se prende a la teta desde la mañana",
                     "no toma nada desde las 7"):
            self.assertEqual(rules.newborn_red_flag(text), "red_flag", text)
        self.assertIsNone(rules.newborn_red_flag("he fed at 9am and latched fine"))

    def test_a_reading_said_as_a_number_is_a_fever(self):
        for text in ("tiene 38,2 que le doy", "le di la mamadera y está calentito, le tomé y tiene 38.3", "he's at 38.4"):
            self.assertEqual(rules.newborn_red_flag(text), "fever", text)
        for text in ("el agua del baño tiene 38", "tiene 37.4, es fiebre?", "le di 38 ml", "has 38 ml left"):
            self.assertIsNone(rules.newborn_red_flag(text), text)


class Languages(FamilyAgent):
    def test_an_english_message_is_answered_in_english_in_a_spanish_family(self):
        reply = self.say("still asleep", ops(reply="OK, he is still asleep, nothing changed."), person="gonza")
        self.assertEqual(reply, ["OK, he is still asleep, nothing changed."])
        self.assertIsNone(self.replies[-1]["guard_lang"])  # either language: the message is English, Ceci's is Spanish

    def test_a_spanish_correction_with_no_accents_is_answered_in_spanish(self):
        self.assertEqual(rules.message_lang("no perdon eran 60"), "es")
        self.assertEqual(rules.message_lang("borra eso"), "es")
        self.assertEqual(rules.message_lang("HELP hes blue"), "en")
        reply = self.say("borra eso", ops({"op": "delete", "id": 5, "kind": "diaper"}))
        self.assertIn("No pude cambiar el registro", reply[0])


class HandOff(FamilyAgent):
    def test_a_message_for_another_tool_goes_to_the_guarded_loop(self):
        self.agent.tools.add(type(self.agent.tools.items["remember"])(
            "remind_me", "Set a reminder for the parent.", {"type": "object", "properties": {}}, lambda: "ok"))
        self.brain.queue.append(ops({"op": "handoff"}))
        self.assertIsNone(log_ops.decide(self.agent, "telegram", "recordame en 3 horas la vitamina"))
        self.assertIn("remind_me", self.brain.seen[-1]["system"])

    def test_a_log_only_agent_has_no_hand_off(self):
        self.say("le di 90", ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 90}))
        self.assertNotIn('"op": "handoff"', self.brain.seen[-1]["system"])


if __name__ == "__main__":
    unittest.main()
