"""Review round 2 fixes on the public demo (issue #76): the cry reason from the log, the night rota tool that agrees with
the panel, a night summary that is always current, no invented bottle details, Theo as a boy everywhere, the link
preview tags, prep mode, and replies in the visitor's language. Fake or counting brains, no network.
"""
import datetime
import html.parser
import json
import re
import subprocess
import sys
import threading
import unittest
from pathlib import Path

from parenting_agent.agent import rules
from parenting_agent.demo import app as app_mod
from parenting_agent.demo.app import TZ, DemoApp
from parenting_agent.demo.babylog import DemoBabyLog
from parenting_agent.demo.server import serve
from parenting_agent.rhythm import patterns

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_demo import CountingBrain, settings  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "parenting_agent" / "demo" / "page.html"


def at(hour, minute=0, day=29):
    return datetime.datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def demo(brain=None, now=None):
    clock = {"now": now or at(15)}
    app = DemoApp(settings(), brain=brain, clock=lambda: clock["now"])
    return app, clock


class CryReason(unittest.TestCase):
    def test_crying_gets_a_reason_from_the_log_with_no_brain_call(self):
        brain = CountingBrain()
        app, _ = demo(brain)
        self.addCleanup(app.close)
        for text in ("she won't stop crying, why?", "Why is he crying?", "he's been fussy for an hour"):
            with self.subTest(text=text):
                status, body = app.message("v", True, text)
                self.assertEqual(status, 200)
                self.assertIn("never a diagnosis", body["reply"])
                self.assertNotIn("911", body["reply"])
                self.assertNotIn("pediatrician", body["reply"])
        self.assertEqual(brain.calls, 0)

    def test_a_long_gap_since_the_last_feed_reads_as_hungry(self):
        app, clock = demo(CountingBrain(), now=at(15))
        self.addCleanup(app.close)
        last = app.visitor("v").baby_log.entries("feeding", None, 1)[-1]
        clock["now"] = datetime.datetime.fromisoformat(last["ts"]) + datetime.timedelta(hours=4)
        status, body = app.message("v", True, "why is he crying?")
        self.assertIn("hungry", body["reply"])

    def test_red_flags_still_get_the_emergency_line(self):
        brain = CountingBrain()
        app, _ = demo(brain)
        self.addCleanup(app.close)
        for text in ("he is crying and not breathing", "she's crying and her lips are blue", "llora y no respira"):
            with self.subTest(text=text):
                reply = app.message("v", True, text)[1]["reply"]
                self.assertIn("911", reply)
                self.assertIn(reply, rules.EMERGENCY_REPLY.values())
        self.assertEqual(brain.calls, 0)

    def test_crying_with_a_health_question_gets_the_refusal(self):
        app, _ = demo(CountingBrain())
        self.addCleanup(app.close)
        reply = app.message("v", True, "he is crying and has a fever, should I give him medicine?")[1]["reply"]
        self.assertIn("pediatrician", reply)
        self.assertNotIn("never a diagnosis", reply)

    def test_page_has_the_cry_chip(self):
        self.assertIn(">Why is he crying?</button>", PAGE.read_text())


class NightRota(unittest.TestCase):
    def test_the_rota_tool_names_the_parent_on_the_panel(self):
        for hour in (1, 9, 15, 23):
            with self.subTest(hour=hour):
                app, _ = demo(now=at(hour))
                visitor = app.visitor("v")
                panel = visitor.proactive()["night_summary"]["on_duty"]
                self.assertIn(f"Next night wake-up: {panel}.", visitor.night_rota())
                self.assertIn("night_rota", app_mod.ALLOWED)
                self.assertIn("night_rota", visitor.agent.tools.items)
                app.close()


class CurrentNight(unittest.TestCase):
    def test_during_the_night_the_summary_is_the_night_in_progress(self):
        app, _ = demo(now=at(1, 0))
        self.addCleanup(app.close)
        text = app.state("v", True)["proactive"]["night_summary"]["text"]
        self.assertTrue(text.startswith("Tonight so far, since Wed 28 22:00"), text)
        self.assertNotIn("Tue 27", text)

    def test_in_the_day_the_summary_is_last_night_with_both_dates(self):
        app, _ = demo(now=at(10, 0))
        self.addCleanup(app.close)
        text = app.state("v", True)["proactive"]["night_summary"]["text"]
        self.assertTrue(text.startswith("Last night, Wed 28 to Thu 29"), text)

    def test_the_week_is_relative_to_today_whatever_the_date(self):
        for day in (datetime.date(2026, 11, 20), datetime.date(2027, 3, 2)):
            now = datetime.datetime.combine(day, datetime.time(12), TZ)
            entries = DemoBabyLog(clock=lambda now=now: now).entries(None, None, 1000)
            self.assertEqual(entries[-1]["ts"][:10], day.isoformat())
            self.assertEqual(entries[0]["ts"][:10], (day - datetime.timedelta(days=6)).isoformat())

    def test_the_default_summary_keeps_its_old_shape(self):
        rows = DemoBabyLog(clock=lambda: at(9)).rhythm_rows()
        self.assertTrue(patterns.night_summary(rows, at(9), TZ, ["Parent A", "Parent B"])["text"].startswith("Night summary for Wed 28"))


class BottleAsSaid(unittest.TestCase):
    def test_bottle_120_ml_just_now_invents_nothing(self):
        app, clock = demo(None, now=at(0, 57))
        self.addCleanup(app.close)
        self.assertEqual(app.message("v", True, "bottle 120 ml just now")[0], 200)
        entry = app.visitor("v").baby_log.entries("feeding", None, 1)[-1]
        self.assertEqual(entry["details"]["amount_ml"], 120.0)
        self.assertIsNone(entry["details"]["type"])
        self.assertIsNone(entry["details"]["start"])
        self.assertIsNone(entry["details"]["duration_min"])
        self.assertEqual(entry["ts"], at(0, 57).isoformat(timespec="seconds"))

    def test_a_said_length_and_type_are_kept(self):
        log = DemoBabyLog(clock=lambda: at(12))
        entry = log.add("feeding", {"amount_ml": 90, "type": "formula", "duration_min": 20})
        self.assertEqual((entry["details"]["type"], entry["details"]["duration_min"]), ("formula", 20))


class Theo(unittest.TestCase):
    def test_the_page_says_theo_and_he_never_she(self):
        page = PAGE.read_text()
        visible = re.sub(r"<script>.*?</script>|<style>.*?</style>", "", page, flags=re.S)
        self.assertIn("Theo", visible)
        self.assertIn("SIMULATED BABY", visible)
        self.assertIsNone(re.search(r"\b(she|her|Demo Baby)\b", visible, re.I))

    def test_the_agent_knows_theo_is_a_simulated_boy(self):
        app, _ = demo()
        self.addCleanup(app.close)
        prompt = app.visitor("v").agent.system_prompt()
        self.assertIn("Theo (simulated)", prompt)
        self.assertIn("baby boy called Theo", prompt)
        self.assertNotIn("Demo Baby", prompt)


class PreviewTags(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.title, self._in_title = {}, "", False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and (a.get("property") or a.get("name")):
            self.meta[a.get("property") or a.get("name")] = a.get("content")
        self._in_title = tag == "title"

    def handle_data(self, data):
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag):
        self._in_title = False


class LinkPreview(unittest.TestCase):
    def test_open_graph_and_twitter_tags(self):
        tags = PreviewTags()
        tags.feed(PAGE.read_text())
        self.assertEqual(tags.title, "Theo's agent, a simulated baby")
        self.assertEqual(tags.meta["og:title"], "Theo's agent, a simulated baby")
        self.assertEqual(tags.meta["twitter:card"], "summary_large_image")
        self.assertEqual(tags.meta["og:image"], "https://baby.bygmv.com/og.png")
        for name in ("og:description", "og:url", "twitter:image", "twitter:title", "description"):
            self.assertTrue(tags.meta.get(name), name)

    def test_the_card_image_is_served_as_a_1200_by_630_png(self):
        s = settings(PA_DEMO_HOST="127.0.0.1")
        app = DemoApp(s)
        server = serve(app, s)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(app.close)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        conn.request("GET", "/og.png")
        res = conn.getresponse()
        data = res.read()
        conn.close()
        self.assertEqual((res.status, res.getheader("Content-Type")), (200, "image/png"))
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")), (1200, 630))


class PrepMode(unittest.TestCase):
    def test_hospital_bag_goes_to_prep_mode_from_either_tab(self):
        app, _ = demo(CountingBrain())
        self.addCleanup(app.close)
        status, body = app.message("v", True, "hospital bag")
        self.assertEqual((status, body["mode"]), (200, "prep"))
        status, body = app.message("v", True, "what is next?", mode="prep")
        self.assertEqual(body["mode"], "prep")

    def test_a_message_goes_where_its_intent_is(self):
        # Round 3 red team: "dim the nursery light" went to prep mode, "add diapers to the hospital bag" to the baby log.
        app, _ = demo(CountingBrain())
        self.addCleanup(app.close)
        cases = {"dim the nursery light": "baby", "turn off the light in the nursery": "baby",
                 "apagá la luz del cuarto del bebé": "baby", "pause the vacuum in the nursery": "baby",
                 "add diapers to the hospital bag": "prep", "agregá pañales al bolso": "prep",
                 "put wipes on the car seat list": "prep", "is the nursery ready?": "prep",
                 "wet diaper": "baby", "she had 120 ml": "baby"}
        for text, mode in cases.items():
            with self.subTest(text=text):
                self.assertEqual(app.message("v", True, text)[1]["mode"], mode)

    def test_the_prep_tools_run_on_simulated_lists_with_a_due_date_from_today(self):
        app, _ = demo(now=at(15))
        self.addCleanup(app.close)
        prep = app.visitor("v").prep()
        names = set(prep.agent.tools.items)
        self.assertTrue({"prep_next", "prep_list", "prep_check", "nursery_plan", "add_appointment"} <= names)
        self.assertNotIn("prep_to_home_assistant", names)
        status, bag = prep.agent.tools.run("prep_list", {"list": "hospital_bag"})
        self.assertEqual(status, "ran")
        self.assertEqual(bag["title"], "Hospital bag")
        self.assertGreaterEqual(len(bag["items"]), 10)
        state = app.state("v", True)["prep"]
        self.assertIn(f"{app_mod.PREP_DUE_IN_DAYS} days to the due date", state["countdown"])
        later, _ = demo(now=at(15, day=29) + datetime.timedelta(days=30))
        self.addCleanup(later.close)
        self.assertIn(f"{app_mod.PREP_DUE_IN_DAYS} days", later.state("v", True)["prep"]["countdown"])
        self.assertFalse(any(i["late"] for i in later.state("v", True)["prep"]["items"]))

    def test_prep_mode_shows_no_real_name_or_house_device(self):
        app, _ = demo()
        self.addCleanup(app.close)
        prep = app.visitor("v").prep()
        text = json.dumps([prep.plugin.list(name) for name in ("hospital_bag", "nursery", "white_noise", "car_seat")]
                          + [prep.agent.tools.run("nursery_plan", {})[1]])
        for word in ("Ceci", "Gonza buys", "light.wiz", "switch.shelly", "192_168"):
            self.assertNotIn(word, text)

    def test_an_appointment_with_an_address_is_not_kept(self):
        app, _ = demo()
        self.addCleanup(app.close)
        tools = app.visitor("v").prep().agent.tools
        status, result = tools.run("add_appointment", {"title": "Hospital tour", "when": "2026-11-03T10:00",
                                                       "place": "Av. Italia 1234 apto 5"})
        if rules.personal_detail("Av. Italia 1234 apto 5"):
            self.assertEqual(status, "error")

    def test_the_prep_chip_is_on_the_page(self):
        self.assertIn(">Show the hospital bag list</button>", PAGE.read_text())

    def test_the_demo_never_loads_the_house_client(self):
        code = "import sys, parenting_agent.demo.app; print('parenting_agent.house' in sys.modules)"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.strip(), "False")


class PlainReplies(unittest.TestCase):
    def test_markdown_and_em_dashes_never_reach_the_page(self):
        reply = "Here is the list \u2014 logistics only:\n\n**Hospital bag**\n* IDs \u2014 by 2026-11-17"
        self.assertEqual(app_mod.plain_reply(reply), "Here is the list, logistics only:\n\nHospital bag\n- IDs, by 2026-11-17")
        app, _ = demo()
        self.addCleanup(app.close)
        visitor = app.visitor("v")
        self.assertIn(app_mod.plain_reply, visitor.agent.reply_guards)
        self.assertIn(app_mod.plain_reply, visitor.prep().agent.reply_guards)


class VisitorLanguage(unittest.TestCase):
    def test_a_spanish_fever_question_gets_the_spanish_urgent_line(self):
        # The demo baby has no birth date, so a fever gets the under 3 months line: call the pediatrician now.
        brain = CountingBrain()
        app, _ = demo(brain)
        self.addCleanup(app.close)
        reply = app.message("v", True, "tiene 38 de fiebre le doy algo?")[1]["reply"]
        self.assertTrue(reply.startswith(rules.URGENT_REPLY["fever"]["es"]), reply)
        self.assertIn("pediatra", reply)
        self.assertEqual(brain.calls, 0)

    def test_an_english_health_question_stays_english_on_a_spanish_page(self):
        app, _ = demo(CountingBrain())
        self.addCleanup(app.close)
        self.assertTrue(app.message("v", True, "he has a fever, can I give him something?", lang="es")[1]["reply"]
                        .startswith(rules.URGENT_REPLY["fever"]["en"]))

    def test_a_spanish_emergency_gets_the_spanish_line(self):
        app, _ = demo(CountingBrain())
        self.addCleanup(app.close)
        self.assertEqual(app.message("v", True, "se puso azul")[1]["reply"], rules.EMERGENCY_REPLY["es"])

    def test_nono_eran_70_edits_and_answers_in_spanish(self):
        # The brain makes the edit call as Muse did live. The reply is the agent's own, from the log, in Spanish.
        from test_one_message_one_entry import ScriptedBrain
        brain = ScriptedBrain([[{"name": "log_baby_event", "arguments": {"kind": "feeding", "details": {"amount_ml": 90}}}], "Anotado."],
                              [[{"name": "edit_baby_event", "arguments": {"last": True, "kind": "feeding",
                                                                          "details": {"amount_ml": 70}}}], "Fixed it."])
        app, clock = demo(brain, now=at(1, 7))
        self.addCleanup(app.close)
        app.message("v", True, "mamadera 90 ml")
        clock["now"] = at(1, 9)
        self.assertTrue(rules.is_edit_request("nono eran 70"))
        reply = app.message("v", True, "nono eran 70")[1]["reply"]
        self.assertEqual(app.visitor("v").baby_log.entries("feeding", None, 1)[-1]["details"]["amount_ml"], 70.0)
        self.assertEqual(reply, "Corregí la mamadera de las 01:07: 90 ml → 70 ml.")

    def test_crying_in_spanish_gets_the_spanish_reason(self):
        brain = CountingBrain()
        app, _ = demo(brain)
        self.addCleanup(app.close)
        reply = app.message("v", True, "no para de llorar, por qué?")[1]["reply"]
        self.assertIn("nunca un diagnóstico", reply)
        self.assertNotIn("911", reply)
        self.assertEqual(brain.calls, 0)

    def test_the_spanish_panel_text(self):
        app, _ = demo(now=at(1))
        self.addCleanup(app.close)
        state = app.state("v", True, lang="es")
        self.assertTrue(state["proactive"]["night_summary"]["text"].startswith("Esta noche hasta ahora, desde mié 28"))
        self.assertIn("Le toca:", state["proactive"]["night_summary"]["text"])
        self.assertIn("días para la fecha de parto", state["prep"]["countdown"])

    def test_the_spanish_prep_tab_shows_the_lists_in_spanish(self):
        app, _ = demo()
        self.addCleanup(app.close)
        state = app.state("v", True, lang="es")["prep"]
        self.assertEqual(state["lists"]["hospital_bag"]["title"], "Bolso para el sanatorio")
        self.assertTrue(all(item["text"] == app_mod.prep_text_es(item["list"], item["id"], item["text"])
                            and item["text"] != app_mod.PREP_ITEMS_ES[(item["list"], item["id"])][0]
                            for item in state["items"]))
        english = app.state("v", True, lang="en")["prep"]
        self.assertEqual(english["lists"]["hospital_bag"]["title"], "Hospital bag")
        self.assertEqual([i["id"] for i in english["items"]], [i["id"] for i in state["items"]])

    def test_every_seeded_prep_item_has_spanish_without_a_real_name(self):
        prep = demo()[0]
        self.addCleanup(prep.close)
        rows = prep.visitor("v").prep().plugin.rows()
        for row in rows:
            spanish = app_mod.prep_text_es(row["list"], row["item_id"], row["text"])
            self.assertNotEqual(spanish, row["text"], row["item_id"])
            for word in ("Ceci", "Gonza", "Parent", "light.wiz"):
                self.assertNotIn(word, spanish)
        self.assertIn("Las cédulas de los dos y el carné de la mutualista", [
            app_mod.prep_text_es(r["list"], r["item_id"], r["text"]) for r in rows])

    def test_a_spanish_message_reads_the_lists_in_spanish_and_ticks_by_spanish_words(self):
        app, _ = demo(CountingBrain())
        self.addCleanup(app.close)
        prep = app.visitor("v").prep()
        prep.reply_lang = "es"
        status, bag = prep.agent.tools.run("prep_list", {"list": "hospital_bag"})
        self.assertEqual(bag["title"], "Bolso para el sanatorio")
        self.assertIn("Cargadores del celular y un cable largo", [i["text"] for i in bag["items"]])
        self.assertIn("Ropa para Persona B", json.dumps(bag, ensure_ascii=False))
        status, done = prep.agent.tools.run("prep_check", {"item": "cargadores"})
        self.assertEqual(status, "ran")
        self.assertTrue(done.startswith("done: Phone chargers"))
        prep.reply_lang = "en"
        self.assertEqual(prep.agent.tools.run("prep_list", {"list": "hospital_bag"})[1]["title"], "Hospital bag")

    def test_an_item_the_visitor_added_keeps_their_words(self):
        self.assertEqual(app_mod.prep_text_es("hospital_bag", "chargers", "my own words"), "my own words")
        self.assertEqual(app_mod.prep_text_es("hospital_bag", "new_item", "pañuelos"), "pañuelos")

    def test_the_footer_claims_what_is_built(self):
        page = PAGE.read_text()
        self.assertNotIn("Never medical advice", page)
        self.assertNotIn("Nunca consejo médico", page)
        self.assertEqual(page.count("Built to refuse medical advice. Red flags get: call 911 now."), 2)
        self.assertEqual(page.count("Hecho para no dar consejos médicos. Ante una señal de alarma: llamá al 911 ya."), 2)

    def test_the_page_switches_to_es_uy_with_voseo_chips(self):
        page = PAGE.read_text()
        self.assertIn('document.documentElement.lang = "es-UY"', page)
        self.assertIn('data-es="Mamadera 120 ml"', page)
        self.assertIn('data-es="¿Por qué llora?"', page)
        self.assertNotIn("biberón", page)
        self.assertIn("lang: LANG", page)


if __name__ == "__main__":
    unittest.main()
