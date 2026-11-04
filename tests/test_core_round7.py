"""What a review agent playing a parent asked for (Nov 4): a frightened parent reaches the other parent with the doctor first, a quiet night stays quiet, a warmer says when it ends,
messages read like a person and not a log, the hand alert is light, a recipe knows Theo's age, and the page leads with the feeling and keeps its honesty one link away."""
import datetime
import json
import re
import unittest
from pathlib import Path

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.agent import rules
    from parenting_agent.core import book, runtime, safety, tools as tools_mod
    from parenting_agent.simulator import scenes, sessions as sessions_mod

NIGHT = datetime.datetime.fromisoformat("2026-12-16T00:10:00-03:00")
DAY = NIGHT.replace(hour=14)
STATIC = Path(__file__).resolve().parent.parent / "parenting_agent/simulator/static"
WARMER = "Tapo P110 - Bottle Warmer"
HUMIDITY = "sensor.nursery_climate_humidity"


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Words(unittest.TestCase):
    def test_a_hot_baby_who_refuses_the_bottle_is_urgent(self):
        for text in ("He feels hot and won't take the bottle", "He's hot, I'm scared and he won't take the bottle", "Está caliente y no quiere la mamadera", "Lo siento caliente y no quiere la mamadera",
                     "Theo se siente caliente y no toma la mamadera", "He feels warm and won't take the bottle"):
            self.assertEqual(safety.gate(text, NoScreen(), "en")[0], "urgent", text)

    def test_a_hot_bottle_or_room_is_no_fever(self):
        for text in ("The bottle feels hot, is that ok?", "The water is hot and he won't take the bottle", "La mamadera está caliente", "The room is hot and he's fine", "He won't take the bottle"):
            self.assertFalse(rules.names_fever(text), text)

    def test_the_other_parent_gets_their_words_whole(self):
        said = safety.because("gonza", "He feels hot and won't take the bottle", "LINE", "en")
        self.assertIn("He feels hot and won't take the bottle", said)

    def test_only_a_scared_parent_with_a_sign_is_frightened(self):
        self.assertTrue(safety.frightened("I'm scared, he seems off tonight"))
        self.assertFalse(safety.frightened("I'm scared I'm doing this all wrong"))
        self.assertFalse(safety.frightened("He seems off"))
        self.assertFalse(safety.frightened("I'm scared, my mom has a fever"))

    def test_dates_read_as_dates(self):
        out = lambda text, lang="en": safety.outbound(text, lang)[0]
        self.assertEqual(out("Ceci passed you tonight (2026-12-15), you're on."), "Ceci passed you tonight, you're on.")
        self.assertEqual(out("You're on the night of 2026-12-16."), "You're on the night of Dec 16.")
        self.assertEqual(out("Te toca la noche del 2026-12-16.", "es"), "Te toca la noche del 16 de dic.")
        self.assertEqual(out("Gonza is on tonight (03 Nov)."), "Gonza is on tonight.")
        self.assertNotIn("**", out("**Grandma's puree**"))

    def test_how_a_log_reads(self):
        for text in ("3 feeds (255 ml total), 1 wet only", "255 ml en total", "2 pañales y 3 tomas (255 ml)", "Total: 255 ml"):
            self.assertRegex(text, safety.LOG_LIKE, text)
        for text in ("He ate at 00:12 and 03:00.", "Comió a las 3, 90 ml.", "Theo had 2 feeds overnight at 00:00 and 03:00."):
            self.assertNotRegex(text, safety.LOG_LIKE, text)

    def test_no_scorekeeping(self):
        for text in ("Same plan tonight, or does Ceci take it back?", "Last night you covered for Gonza", "o la retoma", "Gonza owes you a night"):
            self.assertRegex(text, safety.SCOREKEEP, text)
        self.assertNotRegex("Same plan tonight?", safety.SCOREKEEP)

    def test_the_prompt_no_longer_teaches_it(self):
        from parenting_agent.core.agent import PROMPT
        self.assertNotIn("take it back", PROMPT)

    def test_the_hand_alert_is_a_nudge(self):
        for line in runtime.CAMERA_OFF.values():
            self.assertNotRegex(line, safety.WATCHING)
            self.assertRegex(line, "(?i)nudge|aviso")
        for text in ("I'm watching the changing table", "You left him", "te vi", "Dejaste a Theo"):
            self.assertRegex(text, safety.WATCHING, text)

    def test_the_book_writes_no_iso_date(self):
        days = [{"day": "2026-12-15", "feeds": 1, "ml": 90, "diapers": 0, "sleeps": 0, "moments": []}]
        self.assertEqual(safety.plain_dates("Tonight (2026-12-15) he ate", "en"), "Tonight he ate")
        self.assertTrue(book.page_is_true("He ate", days[0]))


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Round7(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        base.CoreTest.setUp(self)

    run_core = base.CoreTest.run_core

    async def event(self, core, type, payload, at):
        _, done = await core.dispatch(type, payload, at=at.isoformat())
        return await done

    def feeds(self, core, last, gap=3, n=5):
        core.moment = last + datetime.timedelta(minutes=1)
        for i in range(n - 1, -1, -1):
            core.log.add("feeding", {"amount_ml": 90, "method": "bottle"}, (last - datetime.timedelta(hours=gap * i)).isoformat())

    async def test_a_frightened_parent_reaches_both_without_muse(self):
        model = scripted()
        core = await self.run_core(model)
        self.feeds(core, NIGHT - datetime.timedelta(hours=1))
        out = await self.event(core, "message", {"from": "gonza", "text": "He feels hot and won't take the bottle"}, NIGHT)
        self.assertEqual(out["status"], "gated")
        told = {m["to"]: m for m in core.channel.sent}
        self.assertEqual(set(told), {"gonza", "ceci"})
        self.assertFalse(any(m.get("quiet") for m in core.channel.sent))
        self.assertIn("He feels hot and won't take the bottle", told["ceci"]["text"])
        self.assertIn("911", told["gonza"]["text"])
        self.assertNotRegex(told["gonza"]["text"] + told["ceci"]["text"], r"\bml\b(?! )|\bfeeds?\b")

    async def test_a_scared_parent_past_the_gate_gets_who_to_call_and_no_amounts(self):
        amounts = call("notify", parent="gonza", text="Comió a las 22:00, 90 ml. Llamá a su pediatra.")
        no_doctor = call("notify", parent="gonza", text="Estoy con vos, mirá cómo está.")
        right = call("notify", parent="gonza", text="Llamá a su pediatra ahora, o al 911 si no puede esperar.")
        core = await self.run_core(scripted(amounts, no_doctor, right, AIMessage("x"), AIMessage("x"), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": "I'm scared, he seems off tonight"}, NIGHT)
        said = [m for m in core.channel.sent if m["to"] == "gonza"]
        self.assertEqual([m["text"] for m in said], ["Llamá a su pediatra ahora, o al 911 si no puede esperar."])
        other = [m for m in core.channel.sent if m["to"] == "ceci"]
        self.assertEqual(len(other), 1, "the fixed line, since Muse didn't tell her")
        self.assertIn("seems off", other[0]["text"])
        self.assertFalse(other[0].get("quiet"))

    async def test_muse_can_tell_the_other_parent_itself(self):
        core = await self.run_core(scripted(call("notify", parent="gonza", text="Llamá a su pediatra."), call("notify", parent="ceci", text="Gonza está asustado por Theo, llamen a su pediatra.", emergency=True), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": "I'm scared, he seems off tonight"}, NIGHT)
        self.assertEqual(len([m for m in core.channel.sent if m["to"] == "ceci"]), 1)

    async def test_a_warmer_ending_at_night_makes_no_sound(self):
        core = await self.run_core(scripted(AIMessage("nothing")))
        until = NIGHT.isoformat()
        await core.store.aput((*tools_mod.FACTS, core.settings.home), "warmer_off_at", {"value": until})
        await self.event(core, "device_ended", {"key": "warmer_off_at", "until": until, "late": False}, NIGHT)
        self.assertEqual(len(core.channel.sent), 1)
        self.assertTrue(core.channel.sent[0]["quiet"])

    async def test_a_reading_at_night_makes_no_sound_even_if_muse_doesnt_ask_for_quiet(self):
        duty = runtime.who_is_on(NIGHT, {})
        core = await self.run_core(scripted(call("notify", parent=duty, text="Prendí el deshumidificador."), AIMessage("x")))
        await self.event(core, "state_changed", {"entity_id": HUMIDITY, "state": "71"}, NIGHT)
        self.assertTrue(core.channel.sent[0]["quiet"])

    async def test_a_reading_by_day_keeps_its_sound(self):
        duty = runtime.who_is_on(DAY, {})
        core = await self.run_core(scripted(call("notify", parent=duty, text="Prendí el deshumidificador."), AIMessage("x")))
        await self.event(core, "state_changed", {"entity_id": HUMIDITY, "state": "71"}, DAY)
        self.assertFalse(core.channel.sent[0].get("quiet"))

    async def test_a_cry_a_hot_room_and_a_wake_for_a_reminder_keep_their_sound(self):
        duty = runtime.who_is_on(NIGHT, {})
        core = await self.run_core(scripted(call("notify", parent=duty, text="Theo llora.", quiet=True), AIMessage("x")))
        await self.event(core, "sound", {"kind": "baby crying", "room": "bedroom"}, NIGHT)
        self.assertFalse(core.channel.sent[0].get("quiet"), "a cry is what the parent on duty is there for")
        core = await self.run_core(scripted(call("notify", parent=duty, text="El cuarto marca 31 grados, fijate."), AIMessage("x")))
        await self.event(core, "state_changed", {"entity_id": "sensor.nursery_climate_temperature", "state": "31"}, NIGHT)
        self.assertFalse(core.channel.sent[0].get("quiet"))
        core = await self.run_core(scripted(call("notify", parent="gonza", text="Recordatorio: la vacuna."), AIMessage("x")))
        await self.event(core, "wake", {"why": f"{tools_mod.REMINDER}:gonza: la vacuna"}, NIGHT)
        self.assertFalse(core.channel.sent[0].get("quiet"))

    async def test_the_warmer_says_when_it_ends_and_that_it_ends_by_itself(self):
        duty = runtime.who_is_on(NIGHT, {})
        self.feeds = self.feeds
        core = await self.run_core(scripted(call("HassTurnOn", name=WARMER), call("notify", parent=duty, text="Prendí el calentador.", quiet=True), AIMessage("x"), AIMessage("x"), AIMessage("x")))
        self.feeds(core, NIGHT - datetime.timedelta(hours=3))
        await self.event(core, "wake", {"why": "warm the bottle before the feed"}, NIGHT)
        said = " ".join(m["text"] for m in core.channel.sent)
        self.assertIn("00:40", said)
        self.assertRegex(said, safety.ENDS_ALONE)
        self.assertTrue(all(m.get("quiet") for m in core.channel.sent))

    async def test_the_warmer_stays_off_long_before_a_feed(self):
        core = await self.run_core(scripted(call("HassTurnOn", name=WARMER), AIMessage("x")))
        self.feeds(core, NIGHT - datetime.timedelta(minutes=10))
        await self.event(core, "wake", {"why": "warm the bottle before the feed"}, NIGHT)
        self.assertEqual(core.mock.state("switch.study_tapo_p110_bottle_warmer"), "off")
        refused = [a["result"] for a in await core.actions() if a["tool"] == "HassTurnOn"]
        self.assertIn("Refused, the warmer stayed off", refused[0])

    async def test_a_parent_asking_for_the_warmer_still_gets_it(self):
        core = await self.run_core(scripted(call("HassTurnOn", name=WARMER), call("notify", parent="gonza", text="Prendido, se apaga solo a las 14:30."), AIMessage("x")))
        self.feeds(core, DAY - datetime.timedelta(minutes=10))
        await self.event(core, "message", {"from": "gonza", "text": "Prendé el calentador"}, DAY)
        self.assertEqual(core.mock.state("switch.study_tapo_p110_bottle_warmer"), "on")

    async def test_a_log_like_message_goes_back_unless_asked(self):
        duty = runtime.who_is_on(DAY, {})
        log = call("notify", parent=duty, text="3 feeds (255 ml total), 1 wet only.")
        core = await self.run_core(scripted(log, call("notify", parent=duty, text="Comió bien de noche, a las 03:00 y 06:00."), AIMessage("x"), AIMessage("x")))
        await self.event(core, "schedule", {"name": "morning"}, DAY.replace(hour=7, minute=30))
        self.assertNotIn("255", " ".join(m["text"] for m in core.channel.sent))
        core = await self.run_core(scripted(log, AIMessage("x")))
        await self.event(core, "message", {"from": duty, "text": "How many feeds and how much in total today?"}, DAY)
        results = [a["result"] for a in await core.actions() if a["tool"] == "notify"]
        self.assertFalse(any("reads like a log" in r for r in results))

    async def test_scorekeeping_and_a_named_check_go_back(self):
        duty = runtime.who_is_on(DAY, {})
        core = await self.run_core(scripted(call("notify", parent=duty, text="Morning check, same plan or does she take it back?"), call("notify", parent=duty, text="Same plan tonight?"), AIMessage("x"), AIMessage("x")))
        await self.event(core, "schedule", {"name": "morning"}, DAY.replace(hour=7, minute=30))
        self.assertEqual([m["text"] for m in core.channel.sent][0], "Same plan tonight?")

    async def test_the_hand_alert_goes_back_when_it_sounds_like_watching(self):
        duty = runtime.who_is_on(DAY, {})
        core = await self.run_core(scripted(call("notify", parent=duty, text="I'm watching: you left him."), call("say_on_echo", text="Una mano sobre Theo."), AIMessage("x"), AIMessage("x")))
        await self.event(core, "camera", {"camera": "c", "model": "SAM 3.1", "saw": "no hand", "verdict": "off"}, DAY)
        self.assertNotIn("watching", " ".join(m["text"] for m in core.channel.sent))

    async def test_a_recipe_knows_how_old_theo_is(self):
        preview = call("preview_family_recipe", name="Puré", ingredients=["300 g zapallo"], steps=[{"text": "cocinar"}], cookidoo_country="UY")
        core = await self.run_core(scripted(preview, call("notify", parent="gonza", text="No puedo enviarla a Cookidoo desde acá."), AIMessage("x"), AIMessage("x"), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": "Pasá este puré a receta de Thermomix"}, DAY)
        said = " ".join(m["text"] for m in core.channel.sent)
        self.assertIn("recién nacido", said)
        self.assertRegex(said, "más adelante")
        self.assertNotRegex(said, safety.SUITS)
        self.assertNotRegex(said, safety.ADVICE_OUT)

    async def test_the_memory_panel_shows_only_the_night_at_hand(self):
        facts = {"on_duty_2026-12-15": "gonza", "on_duty_2026-12-16": "ceci", "plan": "the vaccine", "language": "x", "On_duty_2026_12_15": "gonza"}
        before_seven = sessions_mod.shown_facts(facts, datetime.datetime.fromisoformat("2026-12-16T03:00:00-03:00"))
        self.assertIn("on_duty_2026-12-15", before_seven)
        after = sessions_mod.shown_facts(facts, datetime.datetime.fromisoformat("2026-12-16T07:30:00-03:00"))
        self.assertEqual(set(after), {"on_duty_2026-12-16", "plan"})


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class ThePage(unittest.TestCase):
    JS, HTML, CSS, BOOK = (STATIC / "page.js").read_text(), (STATIC / "index.html").read_text(), (STATIC / "page.css").read_text(), (STATIC / "book.js").read_text()

    def plain_words(self, lang):
        """The labels a visitor reads before opening the link: everything in that language's table but what belongs behind it."""
        table = self.JS.split(f"\n  {lang}: {{", 1)[1].split("\n  es: {" if lang == "en" else "\n};", 1)[0]
        behind = ("builtLive", "builtPrivacy", "foot:", "models:", "muse:", "pe:", "sam:", "gadget:", "tts:", "metaLead", "seNote", "seBy", "seT", "toSenses", "by:", "byIn", "atHome:", "coachBy", "decided", "computed", "camera:", "sensorOld")
        keep = table
        for name in behind:
            keep = re.sub(rf'\b{re.escape(name.rstrip(":"))}: (?:\[[^\]]*\]|\{{[^}}]*\}}|[a-z]+ => `[^`]*`|\([^)]*\) => `[^`]*`|"(?:[^"\\]|\\.)*")', "", keep)
        return keep

    def test_the_first_screen_leads_with_the_feeling(self):
        self.assertIn('lead: "Your home takes the night shift with you, so you can sleep"', self.JS)
        self.assertIn("toBuilt: \"How it's built, for the curious\"", self.JS)
        self.assertIn('id="lead"', self.HTML)

    def test_model_names_stay_behind_the_link(self):
        for lang in ("en", "es"):
            words = self.plain_words(lang)
            for name in ("Muse Spark", "SAM 3", "Perception Encoder", "MMS-TTS", "Gadget SDK", "Baseten"):
                self.assertNotIn(name, words, f"{lang}: {name}")

    def test_the_honest_labels_stay_reachable(self):
        self.assertIn('simulated: "Simulated, nothing here reaches a real house"', self.JS)
        for card in ("m-muse", "m-pe", "m-sam", "m-gadget", "m-tts", "/static/architecture.svg", 'id="built"', 'id="deep"'):
            self.assertIn(card, self.HTML)
        self.assertLess(self.HTML.index('id="built"'), self.HTML.index('id="m-muse"'))
        self.assertIn("openBuilt()", self.JS)

    def test_privacy_is_true_to_the_code(self):
        en = self.JS.split('privacy: "', 1)[1].split('", atHome2', 1)[0]
        for fact in ("own machines", "only a label", "leave the house", "model provider", "voice notes"):
            self.assertIn(fact, en)
        self.assertIn("isn't a product you can install", self.JS)
        self.assertIn("our own home's agent", self.JS)
        listener = (STATIC.parent.parent.parent / "scripts/ear_listener.py").read_text()
        self.assertIn('{"kind": KIND[label], "room": self.room}', listener, "only a label leaves the Mac")

    def test_the_phone_bar_stays_small_and_the_story_stays_still(self):
        self.assertRegex(self.CSS, r"\.runbar\{position:sticky;top:0[^}]*height:56px")
        self.assertIn("if (top >= 0 && top < innerHeight * 0.35) return;", self.JS)
        self.assertIn("-webkit-line-clamp:2", self.CSS)

    def test_both_parents_are_reachable_at_phone_width(self):
        self.assertIn('id="tab-both"', self.HTML)
        self.assertIn('id="phone-both"', self.HTML)
        self.assertIn('phone = "both"', self.JS)
        self.assertIn("fromParent: p =>", self.JS)

    def test_a_message_with_no_sound_says_so_and_doesnt_buzz(self):
        self.assertIn('quiet: "no sound"', self.JS)
        self.assertIn("mail.slice(seen[p]).some(m => !m.quiet)", self.JS)

    def test_the_labels_are_plain_with_details_on_hover(self):
        for old in ("Send a home event", "events left", "Stop Theo's simulated feeds", "Clock +6 hours", "Clock +1 hour", "Enviar un evento", "Reloj +6"):
            self.assertNotIn(old, self.JS)
        for new in ("Try something in the house", "tries left", "Stop logging feeds", "Skip 6 hours", "hover: {", ".title = w.hover[key]"):
            self.assertIn(new, self.JS)

    def test_no_iso_date_on_the_page(self):
        self.assertIn("toLocaleDateString(t.locale", self.BOOK)
        self.assertNotIn("day.textContent = item.day", self.BOOK)
        self.assertIn("datesIn(v)", self.JS)

    def test_the_clip_names_its_one_exception(self):
        self.assertIn('recLang: "Spoken in Spanish, as recorded. In English:"', self.JS)
        self.assertIn('recLang: ""', self.JS)
        self.assertIn('id="rec-lang"', self.HTML)
