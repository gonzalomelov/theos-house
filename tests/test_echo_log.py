"""The Alexa skill's write mode (echo_log): a parent logs by voice at the Echo, and nothing is written before the yes.

Offline: Baby Buddy is the in-memory fake, the brain is the rule-based fake or a scripted one, nothing leaves 127.0.0.1.
"""
import datetime
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from parenting_agent import echo_log
from parenting_agent.agent.babybuddy import BabyBuddyLog
from parenting_agent.agent.tools import core_tools
from parenting_agent.spoken_time import natural_dates, when
from parenting_agent.voice_bridge import VoiceBridge
from tests.fake_babybuddy import TOKEN, FakeBabyBuddy
from tests.test_home_automations import ScriptedBrain, events, make_agent

TZ = datetime.timezone(datetime.timedelta(hours=-3))


class EchoWriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bb = FakeBabyBuddy()
        self.agent, self.config = make_agent(self.tmp.name)
        log = BabyBuddyLog(self.bb.url, TOKEN, "test-baby")
        self.agent.baby_log = log
        self.agent.tools = core_tools(self.agent.memory, log, self.config["allowed_tools"])
        self.config["baby"] = {"born": False, "name": "Theo"}
        self.config["voice_bridge"] = {
            "port": 0, "host": "127.0.0.1", "timeout_s": 10, "unknown_speaker": "guest",
            "token_file": str(Path(self.tmp.name) / "voice-token"),
            "skill": {"role": "echo_log", "token_file": str(Path(self.tmp.name) / "skill-token")}}
        self.bridge = VoiceBridge(self.agent, self.config, token="h" * 24, skill_token="s" * 24)
        self.agent.plugins = [self.bridge]
        self.agent.start()

    def tearDown(self):
        self.bridge.stop()
        self.agent.stop()
        self.agent.close()
        self.bb.close()
        self.tmp.cleanup()

    def say(self, words, lang="es"):
        return self.bridge.ask(words, "echo", via="skill", lang=lang)

    def yes(self, asked, lang="es"):
        return self.bridge.ask("", "echo", via="skill", lang=lang, confirm=asked["confirm"]["id"])

    def records(self, name):
        return self.bb.all(name)

    def now_words(self, lang="es"):
        return when(self.agent.baby_log.now(), self.agent.baby_log.now(), lang)

    def test_a_feed_is_asked_first_and_written_only_after_yes_tagged_echo(self):
        asked = self.say("le di 90 ml de mamadera")
        self.assertEqual(asked["reply"], f"¿Anoto 90 ml de mamadera {self.now_words()}? Decí sí.")
        self.assertEqual(asked["role"], "echo_log")
        self.assertEqual(self.records("feedings"), [])
        done = self.yes(asked)
        self.assertEqual(done["reply"], f"Listo, anoté 90 ml de mamadera {self.now_words()}.")
        [feed] = self.records("feedings")
        self.assertEqual((feed["amount"], feed["tags"]), (90.0, ["agent", "echo"]))
        self.assertEqual(done["written"], [{"op": "add", "kind": "feeding", "id": feed["id"], "timer": None}])
        self.assertEqual(events(self.agent, "echo_log", status="written")[-1]["written"][0]["id"], feed["id"])

    def test_no_writes_nothing_and_the_memory_says_so(self):
        asked = self.say("le di 90 ml de mamadera")
        cancelled = self.bridge.ask("", "echo", via="skill", lang="es", cancel=asked["confirm"]["id"])
        self.assertEqual(cancelled["reply"], "Listo, no anoté nada.")
        self.assertEqual(self.records("feedings"), [])
        said = [m["text"] for m in self.agent.memory.recent_messages(5) if m["role"] == "assistant"]
        self.assertEqual(said[-1], "No anoté nada.")
        self.assertFalse(any("Anoté" in text for text in said))

    def test_a_new_utterance_drops_the_old_question_and_its_yes_writes_nothing(self):
        first = self.say("le di 90 ml de mamadera")
        self.say("¿cuándo comió?")
        late = self.yes(first)
        self.assertEqual(late["reply"], "No tengo nada para anotar. Decímelo de nuevo.")
        self.assertEqual(self.records("feedings"), [])

    def test_a_yes_after_two_minutes_writes_nothing(self):
        clock = [0.0]
        self.bridge.writer.clock = lambda: clock[0]
        asked = self.say("le di 90 ml de mamadera")
        clock[0] = echo_log.PROPOSAL_S + 1
        self.assertIn("No tengo nada", self.yes(asked)["reply"])
        self.assertEqual(self.records("feedings"), [])

    def test_a_wrong_confirm_id_writes_nothing(self):
        self.say("le di 90 ml de mamadera")
        out = self.bridge.ask("", "echo", via="skill", lang="es", confirm="not-the-id")
        self.assertIn("No tengo nada", out["reply"])
        self.assertEqual(self.records("feedings"), [])

    def test_english_follows_the_request_locale(self):
        asked = self.say("fed 90 ml", lang="en")
        self.assertEqual(asked["reply"], f"Log a 90 ml bottle {self.now_words('en')}? Say yes.")
        self.assertEqual(self.yes(asked, "en")["reply"], f"Done, logged a 90 ml bottle {self.now_words('en')}.")

    def test_a_question_is_read_as_now_with_no_confirmation(self):
        self.bb.create("feedings", {"child": 1, "start": "2026-10-31T10:40:00-03:00", "end": "2026-10-31T10:55:00-03:00",
                                    "type": "formula", "method": "bottle", "amount": 90.0, "tags": ["agent"]})
        brain = ScriptedBrain([("read_baby_log", {"kind": "feeding", "limit": 1}), "Comió el 2026-10-31 a las 10:55."])
        self.agent.brain = brain
        out = self.say("¿cuánto tomó ayer?")
        self.assertNotIn("confirm", out)
        self.assertEqual(sorted(brain.seen[0]["tools"]), ["baby_summary", "current_time", "read_baby_log"])
        self.assertNotIn("2026", out["reply"])

    def test_the_echo_agent_has_the_log_tools_only_and_never_reaches_the_family_agent(self):
        brain = ScriptedBrain([("light_on", {"entity": "light.study"}), "Listo."])
        self.agent.brain = brain
        out = self.say("prendé la luz del estudio")
        self.assertEqual(sorted(brain.seen[0]["tools"]), sorted(echo_log.TOOLS))
        self.assertNotIn("confirm", out)
        self.assertEqual(events(self.agent, "message"), [])
        self.assertEqual(events(self.agent, "reply"), [])
        self.assertEqual(self.agent.pending, [])

    def test_the_same_feed_again_gets_the_duplicate_question_not_a_second_write(self):
        self.yes(self.say("le di 90 ml de mamadera"))
        again = self.say("le di 90 ml de mamadera")
        self.assertNotIn("confirm", again)
        self.assertIn("?", again["reply"])
        self.assertEqual(len(self.records("feedings")), 1)

    def test_a_correction_changes_the_echo_s_own_last_entry_after_yes(self):
        self.yes(self.say("le di 90 ml de mamadera"))
        self.agent.brain = ScriptedBrain([("edit_baby_event", {"last": True, "kind": "feeding",
                                                               "details": {"amount_ml": 100}}), "Corregido."])
        asked = self.say("perdón, eran 100 no 90")
        at = self.now_words().replace("a las ", "las ").replace("a la ", "la ")
        self.assertEqual(asked["reply"], f"¿Cambio la mamadera de {at} a 100 ml? Decí sí.")
        self.assertEqual(self.records("feedings")[0]["amount"], 90.0)
        done = self.yes(asked)
        self.assertEqual(done["reply"], f"Listo, cambié la mamadera de {at} a 100 ml.")
        self.assertEqual(self.records("feedings")[0]["amount"], 100.0)

    def test_an_entry_a_parent_logged_on_telegram_is_never_changed_from_the_echo(self):
        self.agent.baby_log.add("feeding", {"amount_ml": 90.0, "method": "bottle"})
        self.agent.brain = ScriptedBrain([("edit_baby_event", {"last": True, "details": {"amount_ml": 100}}),
                                          ("delete_baby_event", {"last": True}), "No pude.", "No pude.", "No pude."])
        out = self.say("perdón, eran 100 no 90")
        self.assertNotIn("confirm", out)
        self.assertEqual(self.records("feedings")[0]["amount"], 90.0)

    def test_sleep_start_and_wake_up(self):
        self.agent.brain = ScriptedBrain([("log_baby_event", {"kind": "sleep", "details": {"action": "start"}}), "Ok."])
        asked = self.say("se durmió")
        self.assertEqual(asked["reply"], f"¿Anoto que Theo se durmió {self.now_words()}? Decí sí.")
        self.yes(asked)
        self.assertEqual(len(self.records("timers")), 1)
        self.agent.brain = ScriptedBrain([("log_baby_event", {"kind": "sleep", "details": {"action": "end"}}), "Ok."])
        asked = self.say("se despertó")
        self.assertEqual(asked["reply"], f"¿Anoto que Theo se despertó {self.now_words()}? Decí sí.")
        self.yes(asked)
        self.assertEqual((len(self.records("timers")), len(self.records("sleep"))), (0, 1))
        self.assertEqual(self.records("sleep")[0]["tags"], ["agent", "echo"])

    def test_a_dirty_diaper(self):
        self.agent.brain = ScriptedBrain([("log_baby_event", {"kind": "diaper", "details": {"wet": False, "solid": True}}),
                                          "Ok."])
        asked = self.say("cambié un pañal sucio")
        self.assertEqual(asked["reply"], f"¿Anoto un pañal sucio {self.now_words()}? Decí sí.")
        self.yes(asked)
        self.assertEqual([(c["solid"], c["tags"]) for c in self.records("changes")], [(True, ["agent", "echo"])])

    def test_a_red_flag_gets_the_fixed_line_and_nothing_to_confirm(self):
        out = self.say("no respira")
        self.assertIn("911", out["reply"])
        self.assertNotIn("confirm", out)
        self.assertEqual(self.records("notes"), [])

    def test_the_red_flag_line_comes_before_the_question_when_there_is_something_to_note(self):
        self.agent.birth_date = lambda: self.agent.now().date()
        self.bridge.writer.agent.birth_date = self.agent.birth_date
        out = self.say("tiene 38.5 de fiebre")
        self.assertTrue(out["reply"].index("¿Anoto") > 0, out["reply"])
        self.assertIn("confirm", out)
        self.assertEqual(self.records("notes"), [])

    def test_the_skill_confirm_goes_through_http(self):
        self.bridge.start()
        url = f"http://127.0.0.1:{self.bridge.port}/ask"

        def post(body):
            request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
                "Authorization": "Bearer " + "s" * 24, "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read())

        asked = post({"text": "agente del bebé le di 90 ml de mamadera", "source": "echo", "lang": "es",
                      "request_id": "r1"})
        self.assertIn("Decí sí", asked["reply"])
        done = post({"confirm": asked["confirm"]["id"], "source": "echo", "lang": "es", "request_id": "r2"})
        self.assertTrue(done["reply"].startswith("Listo, anoté"))
        self.assertEqual(len(self.records("feedings")), 1)

    def test_home_assistant_s_echo_path_stays_a_read_only_guest(self):
        self.agent.brain = ScriptedBrain([("log_baby_event", {"kind": "feeding", "details": {"amount_ml": 90}}),
                                          "Anoté 90 ml."])
        out = self.bridge.ask("agente del bebé tomó 90 ml", "echo", "abuela", via="home-assistant")
        self.assertEqual(out["role"], "guest")
        self.assertNotIn("confirm", out)
        self.assertEqual(self.records("feedings"), [])
        with self.assertRaises(ValueError):
            self.bridge.ask("", "echo", via="home-assistant", confirm="x")


class SkillRoleTest(unittest.TestCase):
    def test_echo_log_is_a_valid_role_and_others_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, config = make_agent(tmp)
            for role in ("guest", "parent", "echo_log"):
                config["voice_bridge"] = {"host": "127.0.0.1", "skill": {"role": role, "token_file": f"{tmp}/s"}}
                bridge = VoiceBridge(agent, config, token="h" * 24)
                self.assertEqual(bridge.writer is not None, role == "echo_log")
            config["voice_bridge"] = {"host": "127.0.0.1", "skill": {"role": "admin"}}
            with self.assertRaises(ValueError):
                VoiceBridge(agent, config, token="h" * 24)
            agent.close()

    def test_the_vostro_skill_is_in_write_mode(self):
        config = json.loads((Path(__file__).resolve().parent.parent / "config" / "agent.vostro.json").read_text())
        self.assertEqual(config["voice_bridge"]["skill"], {"role": "echo_log"})
        self.assertFalse(config["house"]["live"])


class SpokenDatesTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 1, 9, 30, tzinfo=TZ)

    def test_iso_dates_are_said_as_people_say_them(self):
        self.assertEqual(natural_dates("La última fue el 2026-10-31 a las 10:55.", self.NOW, "es"),
                         "La última fue ayer a las 10:55.")
        self.assertEqual(natural_dates("Comió 2026-10-31T10:55:00-03:00.", self.NOW, "es"), "Comió ayer a las 10:55.")
        self.assertEqual(natural_dates("Hoy es 2026-11-01.", self.NOW, "es"), "Hoy es hoy.")
        self.assertEqual(natural_dates("Fue el 2026-10-28.", self.NOW, "es"), "Fue el 28 de octubre.")
        self.assertEqual(natural_dates("It was on 2026-10-31 at 10:55.", self.NOW, "en"), "It was yesterday at 10:55.")
        self.assertEqual(natural_dates("It was on 2026-10-28.", self.NOW, "en"), "It was on October 28.")

    def test_the_last_feed_line_and_leading_zeros(self):
        self.assertEqual(natural_dates("La última toma fue la mamadera de 90 ml de las 10:55 del 31/10.", self.NOW, "es"),
                         "La última toma fue la mamadera de 90 ml de las 10:55 de ayer.")
        self.assertEqual(natural_dates("a las 07:50 y a las 01:05", self.NOW, "es"), "a las 7:50 y a la 1:05")
        self.assertEqual(natural_dates("The last feed was the 10:55 bottle on 31/10.", self.NOW, "en"),
                         "The last feed was the 10:55 bottle yesterday.")
        self.assertEqual(natural_dates("90 ml, 3 de 4", self.NOW, "es"), "90 ml, 3 de 4")

    def test_when(self):
        self.assertEqual(when(self.NOW.replace(hour=7, minute=50), self.NOW, "es"), "a las 7:50")
        self.assertEqual(when(self.NOW - datetime.timedelta(days=1), self.NOW, "es"), "ayer a las 9:30")
        self.assertEqual(when(self.NOW.replace(hour=1, minute=5), self.NOW, "en"), "at 1:05")


if __name__ == "__main__":
    unittest.main()
