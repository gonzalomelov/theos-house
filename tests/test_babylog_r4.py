"""Round 4 real-new-parent findings, from the judge's exact messages (issue #126).

meta-hackathon-2026 judges/rounds/r4/real-new-parent.json: "tomo 70 y vomito un poco" lost the 70 ml from the day total
in 3 of 3 runs, "sii lo mande dos veces sorry" got "No worries" in English, "a las 2 le di pecho 15 min" said at 15:00 was
logged at 02:00, "la última registrada de ayer fue a la 01:05" named a feed from today, and the demo's unusual lines and
one correction reply were wrong.
"""
import datetime
import tempfile
import unittest

from parenting_agent.agent import log_ops, rules
from parenting_agent.agent import memory as memory_mod
from parenting_agent.agent.brain import Reply
from parenting_agent.families import settings as settings_mod
from parenting_agent.families.service import Families
from parenting_agent.families.store import visitor_id
from parenting_agent.rhythm import patterns

from test_log_ops import LogOps, PARENT, TZ


class Talker:
    """Answers each call with the next queued reply: a (name, arguments) tool call or plain text."""
    name, model, destination = "scripted", "scripted-muse", "none"

    def __init__(self):
        self.queue, self.seen = [], []

    def step(self, system, transcript, tools):
        self.seen.append({"system": system, "text": transcript[-1]["text"]})
        item = self.queue.pop(0)
        if isinstance(item, str):
            return Reply(item, [], {"input_tokens": 10, "output_tokens": 10})
        return Reply("", [{"id": str(len(self.seen)), "name": item[0], "arguments": item[1]}],
                     {"input_tokens": 10, "output_tokens": 10})


class SymptomWithFeed(LogOps):
    JUDGE = "tomo 70 y vomito un poco"

    def feeds(self):
        return [(e["ts"][11:16], e["details"].get("amount_ml")) for e in self.log() if e["kind"] == "feeding"]

    def notes(self):
        return [e["details"]["text"] for e in self.log() if e["kind"] == "note"]

    def test_the_feed_and_the_note_are_both_logged_when_muse_proposes_only_the_note(self):
        reply = self.say("12:20", self.JUDGE, self.ops({"op": "add", "kind": "note", "text": self.JUDGE}))
        self.assertEqual(self.feeds(), [("12:20", 70.0)])
        self.assertEqual(self.notes(), [self.JUDGE])
        self.assertIn("70 ml", reply)
        self.assertNotIn(rules.NO_ADVICE["es"], reply)
        self.assertEqual(self.fam.log.summary(None, None)["feedings"]["total_ml"], 70)

    def test_muse_proposing_both_logs_each_once(self):
        self.say("12:20", self.JUDGE, self.ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 70},
                                               {"op": "add", "kind": "note", "text": "vomitó un poco"}))
        self.assertEqual(self.feeds(), [("12:20", 70.0)])
        self.assertEqual(len(self.notes()), 1)

    def test_muse_proposing_nothing_still_keeps_both(self):
        self.say("12:20", self.JUDGE, self.ops())
        self.assertEqual(self.feeds(), [("12:20", 70.0)])
        self.assertEqual(self.notes(), [self.JUDGE])

    def test_a_feed_already_logged_minutes_ago_is_not_added_twice(self):
        self.say("12:10", "tomo 70", self.ops({"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 70}))
        self.say("12:20", "vomito despues de la de 70", self.ops({"op": "add", "kind": "note", "text": "vomito"}))
        self.assertEqual(self.feeds(), [("12:10", 70.0)])

    def test_without_log_ops_plain_code_logs_the_feed_and_the_note(self):
        self.say("12:20", self.JUDGE, ("other", {}), ("other", {}))
        self.assertEqual(self.feeds(), [("12:20", 70.0)])
        self.assertEqual(self.notes(), [self.JUDGE])

    def test_a_red_flag_keeps_its_line_and_still_logs_the_feed(self):
        reply = self.say("12:45", "tomo 40 y vomito todo")
        self.assertTrue(reply.startswith(rules.URGENT_REPLY["red_flag"]["es"]), reply)
        self.assertEqual(self.feeds(), [("12:45", 40.0)])
        self.assertEqual(self.brain.seen, [])

    def test_a_question_still_gets_the_no_advice_line(self):
        reply = self.say("12:20", "tomo 70 y vomito un poco, es normal?")
        self.assertIn("pediatra", reply)

    def test_symptom_feed_reads_only_real_amounts(self):
        self.assertEqual(rules.symptom_feed(self.JUDGE), {"method": "bottle", "amount_ml": 70.0})
        self.assertEqual(rules.symptom_feed("le dio pecho 15 min y vomito"), {"method": "breast", "duration_min": 15})
        for text in ("vomitó dos veces", "vomito un poquito dsp de la toma", "tiene 38 de fiebre", "tiene tos hace 3 dias"):
            self.assertIsNone(rules.symptom_feed(text), text)


class FamilyLanguage(unittest.TestCase):
    def setUp(self):
        self.brain = Talker()
        self.clock = {"now": datetime.datetime(2026, 10, 29, 3, 40, tzinfo=TZ)}
        self.saved_now = memory_mod.now
        memory_mod.now = lambda: self.clock["now"].isoformat(timespec="seconds")
        env = {"PA_FAMILIES_BRAIN": "fake", "PA_FAMILIES_DATA_DIR": tempfile.mkdtemp(), "PA_FAMILIES_LOG_MODE": "ops"}
        self.app = Families(settings_mod.load(env), brain=self.brain, clock=lambda: self.clock["now"])
        code = self.app.store.create_invite(internal=True)
        for text in (f"/start {code}", "Benja", "12/9/2026", "si"):
            self.app.handle(PARENT, PARENT, text, "private", "es-UY")
        self.fam = self.app.family(self.app.store.parent(visitor_id(PARENT))["family_id"])
        self.fam.agent.brain.real = self.brain

    def tearDown(self):
        memory_mod.now = self.saved_now
        self.app.close()

    def say(self, hhmm, text, *queue):
        hour, minute = (int(x) for x in hhmm.split(":"))
        self.clock["now"] = self.clock["now"].replace(hour=hour, minute=minute)
        self.brain.queue += list(queue)
        return " ".join(t for _, t in self.app.handle(PARENT, PARENT, text, "private", "es-UY"))

    def test_a_spanish_family_saying_sorry_is_answered_in_spanish(self):
        self.say("03:45", "mamadera de formula 90ml",
                 ("log_ops", {"ops": [{"op": "add", "kind": "feeding", "method": "bottle", "amount_ml": 90}], "reply": ""}))
        reply = self.say("03:48", "sii lo mande dos veces sorry",
                         ("log_ops", {"ops": [], "reply": "Tranqui, quedó una sola mamadera a las 03:45."}))
        self.assertIn("Rioplatense Spanish", self.brain.seen[-1]["system"])
        self.assertEqual(reply, "Tranqui, quedó una sola mamadera a las 03:45.")

    def test_an_english_reply_in_a_spanish_chat_is_asked_again_in_spanish(self):
        reply = self.say("03:48", "sii lo mande dos veces sorry",
                         ("log_ops", {"ops": [], "reply": "No worries, left it as one bottle at 03:45."}),
                         ("log_ops", {"ops": [], "reply": "Tranqui, quedó una sola a las 03:45."}))
        self.assertEqual(reply, "Tranqui, quedó una sola a las 03:45.")

    def test_english_twice_is_never_sent(self):
        reply = self.say("03:48", "sii lo mande dos veces sorry",
                         ("log_ops", {"ops": [], "reply": "No worries, left it as one bottle at 03:45."}),
                         ("log_ops", {"ops": [], "reply": "No worries, I kept just the one at 03:45."}))
        self.assertNotIn("worries", reply)
        self.assertEqual(reply, "Dale.")

    def test_turn_lang(self):
        for text in ("sii lo mande dos veces sorry", "sorry era una sola", "ok, dale"):
            self.assertNotEqual(rules.turn_lang(text, "es"), "en", text)
        for text in ("gave her a 60 ml bottle", "his lips are blue", "she won't wake up"):
            self.assertEqual(rules.turn_lang(text, "es"), "en", text)


class BareClockHours(LogOps):
    def at(self):
        return self.log()[-1]["ts"][:16]

    def test_a_las_2_said_at_15_is_14(self):
        self.say("15:00", "me olvide de anotar, a las 2 le di pecho 15 min",
                 self.ops({"op": "add", "kind": "feeding", "method": "breast", "duration_min": 15, "at": "02:00"}))
        self.assertEqual(self.at(), "2026-10-29T14:00")

    def test_a_las_11_menos_cuarto_said_at_11_45_is_10_45(self):
        self.say("11:45", "le dimos 60 a las 11 menos cuarto",
                 self.ops({"op": "add", "kind": "feeding", "amount_ml": 60, "at": "22:45"}))
        self.assertEqual(self.at(), "2026-10-29T10:45")

    def test_a_named_half_of_the_day_is_kept(self):
        self.say("15:00", "a las 2 de la mañana tomo 90", self.ops({"op": "add", "kind": "feeding", "amount_ml": 90, "at": "02:00"}))
        self.assertEqual(self.at(), "2026-10-29T02:00")

    def test_after_midnight_the_night_reading_stays(self):
        self.say("00:50", "a las 12 y 40 le di 80", self.ops({"op": "add", "kind": "feeding", "amount_ml": 80, "at": "12:40"}))
        self.assertEqual(self.at(), "2026-10-29T00:40")

    def test_a_sleep_span_ends_now_and_starts_before_its_end(self):
        self.say("07:30", "durmio de 4 a 7 de corrido!!", self.ops({"op": "add", "kind": "sleep", "start": "16:00", "end": "19:00"}))
        sleep = self.log()[-1]
        self.assertEqual((sleep["details"]["start"][:16], sleep["ts"][:16]), ("2026-10-29T04:00", "2026-10-29T07:00"))

    def test_bare_hours(self):
        self.assertEqual(log_ops.bare_hours("a las 2 le di pecho 15 min"), {2})
        self.assertEqual(log_ops.bare_hours("ayer a las 3"), frozenset())
        self.assertEqual(log_ops.bare_hours("tomo 120 a las 14:30"), frozenset())
        self.assertEqual(log_ops.bare_hours("le di 90 de mamadera"), frozenset())


class YesterdayLabels(LogOps):
    def test_yesterday_never_names_a_feed_from_today(self):
        self.clock["now"] = datetime.datetime(2026, 10, 29, 15, 0, tzinfo=TZ)
        self.fam.log.add("feeding", {"method": "breast", "duration_min": 15}, ts="2026-10-29T14:00:00-03:00")
        self.clock["now"] = datetime.datetime(2026, 10, 30, 19, 0, tzinfo=TZ)
        self.fam.log.add("feeding", {"method": "both breasts", "duration_min": 30}, ts="2026-10-30T01:05:00-03:00")
        yesterday = self.fam.log.summary("2026-10-29T00:00:00-03:00", "2026-10-30T00:00:00-03:00")["feedings"]
        self.assertEqual((yesterday["last_at"], yesterday["last_date"]), ("14:00", "2026-10-29"))
        self.say("19:00", "cuantas mamaderas ayer", self.ops(reply="Ayer 1 toma."), day=30)
        shown = self.brain.seen[-1]["text"]
        self.assertIn("Yesterday (Thu 2026-10-29)", shown)
        self.assertIn('"last_at": "14:00"', shown.split("Yesterday (", 1)[1])


class Demo(unittest.TestCase):
    def test_unusual_lines_in_spanish(self):
        from test_rhythm import week
        es = patterns.unusual_notes(week(), datetime.timezone(datetime.timedelta(hours=-3)), lang="es")
        self.assertTrue(es)
        for note in es:
            self.assertEqual(rules.message_lang(note["text"]), "es", note["text"])
            self.assertNotRegex(note["text"], r"\b(of sleep|usual|apart|Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b")

    def test_state_unusual_follows_the_page_language(self):
        from test_redteam_r1 import demo
        app = demo()
        self.addCleanup(app.close)
        app.message("v", True, "hola", lang="es")
        state = app.state("v", True, "es")
        self.assertTrue(state["proactive"]["unusual"])
        for line in state["proactive"]["unusual"]:
            self.assertEqual(rules.message_lang(line), "es", line)
        for line in app.state("v", True, "en")["proactive"]["unusual"]:
            self.assertEqual(rules.message_lang(line), "en", line)


class StaleCorrection(unittest.TestCase):
    def test_the_reply_names_the_real_last_bottle(self):
        brain = Talker()
        clock = {"now": datetime.datetime(2026, 10, 29, 19, 15, tzinfo=TZ)}
        saved = memory_mod.now
        memory_mod.now = lambda: clock["now"].isoformat(timespec="seconds")
        self.addCleanup(setattr, memory_mod, "now", saved)
        env = {"PA_FAMILIES_BRAIN": "fake", "PA_FAMILIES_DATA_DIR": tempfile.mkdtemp(), "PA_FAMILIES_LOG_MODE": "guards"}
        app = Families(settings_mod.load(env), brain=brain, clock=lambda: clock["now"])
        self.addCleanup(app.close)
        code = app.store.create_invite(internal=True)
        for text in (f"/start {code}", "Benja", "12/9/2026", "si"):
            app.handle(PARENT, PARENT, text, "private", "es-UY")
        fam = app.family(app.store.parent(visitor_id(PARENT))["family_id"])
        fam.agent.brain.real = brain
        old = fam.log.add("feeding", {"method": "bottle", "amount_ml": 60}, ts="2026-10-29T12:12:00-03:00")
        fam.log.add("feeding", {"method": "bottle", "amount_ml": 100}, ts="2026-10-29T19:11:00-03:00")
        brain.queue += [("edit_baby_event", {"id": old["id"], "details": {"amount_ml": 70}}), "Listo."]
        reply = " ".join(t for _, t in app.handle(PARENT, PARENT, "nono la ultima fue de 70 no 60", "private", "es-UY"))
        self.assertIn("100 ml de las 19:11", reply)
        self.assertNotIn("12:12", reply)
        self.assertEqual(fam.log.get(old["id"])["details"]["amount_ml"], 60.0)


if __name__ == "__main__":
    unittest.main()
