"""Round 8, the last fixes before the judges: a guard can't hold a message up, an alarm nobody answered stays open, readings about Theo count and other children don't,
one record of who is on duty, and the home says only what it did."""
import datetime
import re
import unittest
from pathlib import Path

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.agent import rules
    from parenting_agent.core import agent as agent_mod, book, runtime, safety, tools as tools_mod

STATIC = Path(__file__).resolve().parent.parent / "parenting_agent/simulator/static"
NIGHT = datetime.datetime.fromisoformat("2026-12-16T00:10:00-03:00")
DAY = NIGHT.replace(hour=14)
MORNING = NIGHT.replace(hour=7, minute=30)
RECIPE = "Grandma's pumpkin puree: 300 g pumpkin and 100 g water, 20 min/100°C/speed 1. Her Cookidoo is in Uruguay. Can you turn it into a Thermomix recipe?"
PREVIEW = {"name": "Pumpkin puree", "ingredients": ["300 g pumpkin", "100 g water"], "steps": [{"text": "Cook 20 min/100°C/speed 1"}], "cookidoo_country": "UY"}


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Words(unittest.TestCase):
    def gate(self, text, lang="en"):
        return safety.gate(text, NoScreen(), lang)

    def test_the_words_the_recipe_guard_asks_for_pass_it(self):
        for text in ("I can't say whether it is right for him, his pediatrician can.", "No puedo decir si es buena para él.", "Ask his pediatrician when it's ok for him.", "It isn't suitable for a newborn.", "Todavía no es apta para Theo."):
            self.assertFalse(safety.says_suits(text), text)
        for text in ("It's perfect for Theo!", "Ideal para el bebé.", "Great for babies. Later on too."):
            self.assertTrue(safety.says_suits(text), text)

    def test_the_prompt_asks_for_nothing_a_guard_refuses(self):
        self.assertNotIn("Muse app", agent_mod.PROMPT)
        self.assertIsNone(safety.outbound("A real send is theirs, from Meta's app.", "en")[1])

    def test_a_reading_about_him_counts_without_the_word_fever(self):
        for text in ("Took his temp, 38,04 under the arm", "second reading now 38,04", "Tomé la temperatura, 38,2 en la axila", "38,04", "now 38.5", "He's at 38.04", "Just measured him, 38.3", "his forehead scan says 38,4"):
            self.assertEqual(self.gate(text)[0], "urgent", text)
        self.assertTrue(rules.names_fever("Le tomé la temperatura: 38,04"))

    def test_a_reading_of_something_else_or_below_fever_doesnt(self):
        for text in ("Humidity reading is 40", "The bath water is 38,04", "Took his temp, 37,04", "Reading the book, 39 pages"):
            self.assertFalse(rules.names_fever(text), text)

    def test_other_children_stay_out(self):
        for text in ("my sister's son Mateo, 3 years old, has a fever of 39", "Mateo, 3 years old, has a fever of 39", "Mateo has a fever of 39", "Sofía tiene fiebre", "My nephew's kid has 39", "El hijo de mi hermana tiene 38,5 de fiebre", "Mi sobrino de 4 años tiene fiebre"):
            self.assertIsNone(self.gate(text), text)

    def test_theo_still_fires_next_to_another_child(self):
        for text in ("Mateo has a fever and now Theo has 38,5 too", "Tonight he has a fever", "Todavía tiene fiebre", "Temperature has gone up to 38.5", "Recién tiene 38,3", "Theo, 3 weeks old, has a fever of 39"):
            self.assertIsNotNone(self.gate(text), text)

    def test_a_room_question_is_about_the_room(self):
        for text in ("The room feels hot, what's the temperature in there?", "Is it cold in the nursery?", "¿Qué temperatura hay en el cuarto?", "Hace mucho calor en el cuarto, ¿cuánto marca?"):
            self.assertIsNone(self.gate(text), text)
        for text in ("The room feels hot and Theo has a fever", "What's a safe temperature for his fever?"):
            self.assertIsNotNone(self.gate(text), text)

    def test_hard_to_wake_and_grey_lips_are_the_emergency_line_in_code(self):
        for text in ("He's hard to wake", "Theo is hard to wake for the feed", "es difícil despertarlo", "Grey lips", "his lips look grey", "labios grises", "lips gray"):
            self.assertEqual(self.gate(text)[0], "emergency", text)
        for text in ("He's not hard to wake", "lips not grey"):
            self.assertNotEqual((self.gate(text) or ("",))[0], "emergency", text)

    def test_false_alarm_reaches_muse(self):
        self.assertIsNone(self.gate("False alarm, ped says it's nothing"))
        self.assertIsNone(self.gate("Falsa alarma, la pediatra dice que no es nada"))
        self.assertEqual(self.gate("False alarm, but now he isn't breathing")[0], "emergency")

    def test_the_duty_line_is_one_function(self):
        facts = {tools_mod.duty_key(NIGHT.date() - datetime.timedelta(days=1)): "gonza"}
        line = runtime.duty_line(NIGHT, facts)
        self.assertIn("On duty that night: gonza", line)
        self.assertIn("The next night", line)
        by_day = runtime.duty_line(DAY, facts)
        self.assertIn("last night gonza", by_day)
        self.assertNotIn("on_duty_", runtime.describe({"type": "schedule", "payload": {"name": "evening"}}, DAY, facts))

    def test_a_wake_about_one_thing_has_a_topic(self):
        self.assertEqual(safety.topic_of("check the dehumidifier is working: read the humidity"), "air")
        self.assertEqual(safety.topic_of(runtime.RECHECK_ROOM), "room")
        self.assertEqual(safety.topic_of("prewarm the bottle"), "warmer")
        self.assertEqual(safety.topic_of("see if the room is still warm"), "room")
        self.assertIsNone(safety.topic_of("ask about the shopping"))

    def test_the_book_doesnt_claim_the_seat_was_fitted(self):
        day = {"day": "2026-12-16", "feeds": 0, "ml": 0, "diapers": 0, "sleeps": 0, "moments": []}
        self.assertFalse(book.page_is_true("Gonza fitted the car seat.", day))
        self.assertFalse(book.page_is_true("Gonza instaló la silla del auto.", day))
        self.assertTrue(book.page_is_true("Gonza asked for help with the car seat.", day))


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class Round8(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core

    async def event(self, core, type, payload, at):
        _, done = await core.dispatch(type, payload, at=at.isoformat())
        return await done

    async def facts(self, core):
        return await tools_mod.facts(core.store, core.settings.home)

    def to(self, core, parent):
        return [m["text"] for m in core.channel.sent if m["to"] == parent]

    # 1. A guard can't hold a message up
    async def test_three_refused_tries_then_a_plain_line_and_muse_stops(self):
        bad = lambda: call("notify", parent="gonza", text="It's perfect for Theo!")
        model = scripted(bad(), bad(), bad(), call("notify", parent="gonza", text="never reached"), AIMessage("x"))
        core = await self.run_core(model)
        await self.event(core, "message", {"from": "gonza", "text": RECIPE}, DAY)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(self.to(core, "gonza"), [runtime.READ_LINE["es"]])
        self.assertEqual(len([a for a in await core.actions() if a["tool"] == "notify"]), 3)

    async def test_the_plain_line_is_what_the_record_and_the_trace_say(self):
        bad = lambda: call("notify", parent="gonza", text="It's perfect for Theo!")
        core = await self.run_core(scripted(bad(), bad(), bad(), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": RECIPE}, DAY)
        last = [a for a in await core.actions() if a["tool"] == "notify"][0]
        self.assertEqual(last["arguments"]["text"], runtime.READ_LINE["es"])
        self.assertTrue(last["result"].startswith("Sent"))

    async def test_a_parent_already_waiting_gets_the_plain_line_at_the_first_refusal(self):
        core = await self.run_core(scripted(AIMessage("x")))
        core.sender, core.began = "gonza", 0
        self.assertTrue((await core.refused("gonza", "words", "Refused, nothing was sent: no.", True)).startswith("Sent"))
        self.assertEqual(len(self.to(core, "gonza")), 1)

    async def test_a_parent_asleep_gets_no_plain_line(self):
        bad = lambda: call("notify", parent="ceci", text="Se despertó.")
        core = await self.run_core(scripted(bad(), bad(), bad(), AIMessage("x")))
        night = NIGHT if runtime.on_duty(NIGHT) == "gonza" else NIGHT + datetime.timedelta(days=1)
        await self.event(core, "wake", {"why": "see how the room is"}, night)
        self.assertEqual(self.to(core, "ceci"), [])

    async def test_a_second_ask_carries_the_parents_words(self):
        model = scripted(AIMessage("nothing"), AIMessage("still nothing"))
        core = await self.run_core(model)
        await self.event(core, "message", {"from": "gonza", "text": "Comprá pañales por favor"}, DAY)
        self.assertIn("Comprá pañales por favor", str(model.calls[1][-1].content))
        self.assertEqual(self.to(core, "gonza"), [runtime.READ_LINE["es"]])  # not "I lost my connection": it didn't

    async def test_i_didnt_catch_your_message_is_never_sent(self):
        core = await self.run_core(scripted(call("notify", parent="gonza", text="Hey, I didn't catch your last message."), AIMessage("x"), call("notify", parent="gonza", text="Anotado, comprar pañales."), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": "Comprá pañales por favor"}, DAY)
        self.assertEqual(self.to(core, "gonza"), ["Anotado, comprar pañales."])

    async def test_the_recipe_reaches_the_phone_in_one_message_from_code_if_muse_leaves_it_out(self):
        core = await self.run_core(scripted(call("preview_family_recipe", **PREVIEW), call("notify", parent="gonza", text="Listo, la armé."), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": RECIPE}, DAY)
        fixed = self.to(core, "gonza")[-1]
        for words in ("300 g pumpkin", "20 min/100°C/speed 1", "Cookidoo"):
            self.assertIn(words, fixed)
        self.assertRegex(fixed, safety.LATER_ON)
        self.assertEqual(len(self.to(core, "gonza")), 2)

    async def test_a_recipe_muse_showed_gets_nothing_more(self):
        text = "Puré: 300 g de pumpkin y 100 g de water. No puedo enviarla a Cookidoo desde acá. Es para ustedes por ahora."
        core = await self.run_core(scripted(call("preview_family_recipe", **PREVIEW), call("notify", parent="gonza", text=text), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": RECIPE}, DAY)
        self.assertEqual(self.to(core, "gonza"), [text])

    # 2. An alarm stays open until someone answers
    async def test_an_unanswered_alarm_is_carried_to_the_morning_once(self):
        core = await self.run_core(scripted(*[AIMessage("x")] * 12))
        evening = DAY.replace(hour=21, minute=30)
        await self.event(core, "message", {"from": "gonza", "text": "Theo no respira"}, DAY)
        await self.event(core, "schedule", {"name": "evening"}, evening)
        self.assertTrue([k for k in await self.facts(core) if k.startswith("alarm_")])
        morning = MORNING + datetime.timedelta(days=1)
        await self.event(core, "schedule", {"name": "morning"}, morning)
        said = self.to(core, "ceci")[-1]
        self.assertIn("Theo no respira", said)
        facts = await self.facts(core)
        self.assertNotIn(runtime.OPEN_ALARM, runtime.describe({"type": "schedule", "payload": {"name": "evening"}}, DAY, facts))  # known to the panel and to an answer, and no check asks again
        self.assertFalse([k for k in facts if k.startswith("alarm_")])
        self.assertTrue([k for k in facts if k.startswith(runtime.OPEN_ALARM)])
        before = len(core.channel.sent)
        await self.event(core, "schedule", {"name": "evening"}, evening + datetime.timedelta(days=1))
        self.assertFalse(any("no respira" in m["text"] for m in core.channel.sent[before:]))

    async def test_an_answered_alarm_is_said_once_more_and_closed(self):
        core = await self.run_core(scripted(*[AIMessage("x")] * 8))
        await self.event(core, "message", {"from": "gonza", "text": "Theo no respira"}, DAY)
        await self.event(core, "message", {"from": "ceci", "text": "Ya está bien, habló la doctora"}, DAY + datetime.timedelta(minutes=5))
        self.assertEqual([w for w in await core.wakes() if w["why"].startswith(runtime.FOLLOW_UP)], [])
        await self.event(core, "schedule", {"name": "evening"}, DAY.replace(hour=21, minute=30))
        self.assertIn("no respira", self.to(core, "gonza")[-1])
        facts = await self.facts(core)
        self.assertEqual([k for k in facts if "alarm" in k], [])

    async def test_false_alarm_closes_it_and_stops_the_asks(self):
        core = await self.run_core(scripted(AIMessage("x"), call("notify", parent="ceci", text="Dale, queda cerrado."), AIMessage("x"), *[AIMessage("x")] * 4))
        await self.event(core, "message", {"from": "ceci", "text": "Theo tiene 38,5"}, DAY)
        self.assertTrue(await core.wakes())
        await self.event(core, "message", {"from": "ceci", "text": "False alarm, ped says it's nothing"}, DAY + datetime.timedelta(minutes=5))
        self.assertEqual(await core.wakes(), [])
        facts = await self.facts(core)
        self.assertEqual([k for k in facts if "alarm" in k or k == "fever_reported"], [])
        before = len(core.channel.sent)
        await self.event(core, "schedule", {"name": "evening"}, DAY.replace(hour=21, minute=30))
        self.assertFalse(any("38,5" in m["text"] for m in core.channel.sent[before:]))

    async def test_one_ask_then_the_other_parent_once_by_day(self):
        core = await self.run_core(scripted(call("notify", parent="gonza", text="¿Cómo está Theo?"), AIMessage("x"), call("notify", parent="ceci", text="Gonza no contestó."), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": "Theo no respira"}, DAY)
        for _, done in await core.fire_wakes(DAY + datetime.timedelta(minutes=41)):
            await done
        whys = [w["why"] for w in await core.wakes()]
        self.assertIn(f"{runtime.UNANSWERED}:gonza: how Theo is, after an alarm", whys)
        for _, done in await core.fire_wakes(DAY + datetime.timedelta(minutes=56)):
            await done
        self.assertEqual(self.to(core, "ceci")[-1], "Gonza no contestó.")
        self.assertEqual([w for w in await core.wakes() if w["why"].startswith(runtime.UNANSWERED)], [])

    async def test_no_question_by_night_reaches_the_other_parent(self):
        night = NIGHT if runtime.on_duty(NIGHT) == "gonza" else NIGHT + datetime.timedelta(days=1)
        core = await self.run_core(scripted(call("notify", parent="gonza", text="¿Cómo está Theo?"), AIMessage("x")))
        await self.event(core, "message", {"from": "gonza", "text": "Theo no respira"}, night)
        for _, done in await core.fire_wakes(night + datetime.timedelta(minutes=41)):
            await done
        self.assertEqual([w for w in await core.wakes() if w["why"].startswith(runtime.UNANSWERED)], [])

    async def test_a_chain_of_checks_stops_after_one_unanswered(self):
        at = DAY + datetime.timedelta(hours=1)
        told = call("notify", parent="gonza", text="El cuarto sigue en 30 grados.")
        rewake = call("wake_me_at", at=(at + datetime.timedelta(hours=1)).isoformat(), why="check the room again")
        core = await self.run_core(scripted(told, rewake, AIMessage("x"), call("notify", parent="gonza", text="El cuarto sigue en 30 grados, ¿todo bien?"), AIMessage("x"), rewake, AIMessage("x")))
        await self.event(core, "wake", {"why": "check the room again"}, DAY)
        self.assertEqual(len(self.to(core, "gonza")), 1)
        await self.event(core, "wake", {"why": "check the room again"}, at)
        self.assertEqual(len(self.to(core, "gonza")), 1)

    async def test_a_parent_writing_makes_the_next_one_news(self):
        core = await self.run_core(scripted(call("notify", parent="gonza", text="El cuarto marca 30."), AIMessage("x"), AIMessage("x"), call("notify", parent="gonza", text="Ahora marca 29."), AIMessage("x")))
        await self.event(core, "wake", {"why": "check the room again"}, DAY)
        await self.event(core, "message", {"from": "gonza", "text": "Ya abrí la ventana"}, DAY + datetime.timedelta(minutes=10))
        await self.event(core, "wake", {"why": "check the room again"}, DAY + datetime.timedelta(hours=1))
        self.assertIn("Ahora marca 29.", self.to(core, "gonza"))

    async def test_two_chains_about_one_thing_are_one_wake(self):
        core = await self.run_core(scripted(AIMessage("x")))
        self.assertIsNone(await core.add_wake(DAY, "check the dehumidifier is working: read the humidity"))
        self.assertEqual(await core.add_wake(DAY + datetime.timedelta(minutes=30), "I'll check again in an hour whether the humidity came down"), DAY)
        self.assertIsNone(await core.add_wake(DAY + datetime.timedelta(hours=2), "check the humidity again"))
        self.assertIsNone(await core.add_wake(DAY, f"{tools_mod.REMINDER}:gonza: the humidity meter's battery"))
        self.assertEqual(len(await core.wakes()), 3)

    # 4. One record of who is on duty, and appointments ahead of time
    async def test_muse_cant_keep_its_own_version_of_who_is_on(self):
        core = await self.run_core(scripted(call("remember", key="tonight", value="Gonza is on duty tonight"), call("remember", key="pediatrician", value="Friday 10:30, Dr. Ruiz"), AIMessage("x")))
        await self.event(core, "schedule", {"name": "evening"}, DAY.replace(hour=21, minute=30))
        facts = await self.facts(core)
        self.assertNotIn("tonight", facts)
        self.assertIn("pediatrician", facts)

    async def test_an_appointment_can_be_reminded_ahead_and_a_reminder_for_a_time_cant(self):
        core = await self.run_core(scripted(AIMessage("x")))
        core.heard = "We have the vaccine appointment at 15:00"
        self.assertIsNone(core.early_reminder(DAY.replace(hour=13), "vaccine appointment at 15:00, leave in time"))
        core.heard = "Remind me at 15:00 to call my mother"
        self.assertIn("Refused", core.early_reminder(DAY.replace(hour=13), "remind Gonza at 15:00 to call his mother"))

    # 6. A fact Muse says changed what it did shows up as such
    async def test_the_memory_that_changed_a_decision_is_published(self):
        core = await self.run_core(scripted(call("remember", key="nap plan", value="Keep the dehumidifier off until 16:00"), call("notify", parent="ceci", text="Dale."), AIMessage("kept"), AIMessage("Left the dehumidifier off because of nap plan.")))
        await self.event(core, "message", {"from": "ceci", "text": "Keep the dehumidifier off during his nap"}, DAY)
        await self.event(core, "state_changed", {"entity_id": "sensor.nursery_climate_humidity", "state": "71"}, DAY + datetime.timedelta(minutes=30))
        used = [item for item in core.recent if item["kind"] == "memory_used"]
        self.assertEqual([u["key"] for u in used], ["nap_plan"])
        self.assertIn("off until 16:00", used[0]["value"])


class ThePage(unittest.TestCase):
    def test_the_architecture_needs_nothing_the_csp_blocks(self):
        svg = (STATIC / "architecture.svg").read_text()
        self.assertNotIn("<style", svg)
        self.assertNotIn("style=", svg)
        self.assertNotIn("class=", svg)

    def test_the_phone_with_both_has_no_asleep_line(self):
        js = (STATIC / "page.js").read_text()
        self.assertNotIn('x.querySelector(".asleep").textContent', js)
        self.assertIn("if (asleep &&", js)

    def test_who_they_are_is_above_the_fold(self):
        html = (STATIC / "index.html").read_text()
        self.assertLess(html.index('id="who"'), html.index('class="story"'))
        js = (STATIC / "page.js").read_text()
        for words in ("Gonza and Ceci are first-time parents", "Gonza y Ceci son padres primerizos"):
            self.assertIn(words, js)

    def test_a_press_shows_activity_on_every_phone(self):
        html = (STATIC / "index.html").read_text()
        self.assertEqual(html.count('class="typing"'), 3)
        self.assertIn("body.busy .typing", (STATIC / "page.css").read_text())

    def test_a_returning_judge_gets_a_clear_choice(self):
        js, css = (STATIC / "page.js").read_text(), (STATIC / "page.css").read_text()
        self.assertIn('classList.add("returning")', js)
        self.assertIn("body.returning .stage", css)

    def test_the_story_is_shorter_and_page_and_server_agree(self):
        from parenting_agent.simulator import scenes
        js = (STATIC / "page.js").read_text()
        self.assertEqual(re.findall(r'^  \["(\w+)", "\d\d:\d\d"', js, re.M), [s["id"] for s in scenes.SCENES])
        self.assertLessEqual(len(scenes.SCENES), 10)
