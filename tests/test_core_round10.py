"""Round 10: a fever named as over doesn't fire, and any doubt still does; an open alarm isn't reassured away; a promise to read again comes back."""
import datetime
import unittest

from tests import test_langgraph_core as base
from tests.test_langgraph_core import READY, NoScreen, call, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.agent import rules
    from parenting_agent.core import runtime, safety, tools as tools_mod

NIGHT = datetime.datetime.fromisoformat("2026-12-16T03:12:00-03:00")
OVER_ES = ("la fiebre ya paso", "La fiebre ya pasó.", "ya se le pasó la fiebre", "se le fue la fiebre", "la fiebre se fue", "la fiebre ya se fue, duerme", "ya le bajó la fiebre", "ya no tiene fiebre", "no tiene más fiebre", "la fiebre de ayer ya pasó")
OVER_EN = ("the fever is gone", "The fever's gone.", "his fever broke", "the fever went away", "fever gone", "the fever is over", "no more fever", "he doesn't have a fever anymore", "the fever has passed", "fever's gone and he's asleep")
# Whatever else these say, it can't be read as over.
STILL_ES = ("la fiebre no pasó", "todavía no se le pasó la fiebre", "no se le fue la fiebre", "¿ya se le pasó la fiebre?", "¿la fiebre ya pasó", "si se le fue la fiebre le doy la mamadera", "la fiebre paso a 39", "la fiebre pasó de 38 a 39", "la fiebre se fue a 38,7",
            "la fiebre ya paso pero volvió", "se le fue la fiebre y volvió", "la fiebre ya pasó, ahora tiene 38,5", "la fiebre ya paso, 38,4", "la fiebre ya pasó pero sigue caliente", "la fiebre se fue, sigue caliente", "creo que la fiebre ya pasó", "parece que se le fue la fiebre",
            "la fiebre ya paso, tiene fiebre de nuevo", "la fiebre bajó a 38,2", "la fiebre bajó un poco", "le bajó un poco la fiebre", "la fiebre pasó la noche entera", "tiene fiebre", "tuvo fiebre anoche", "la fiebre ya paso. ¿puedo darle algo?", "cuando se le pasó la fiebre tenía 38,5",
            "la fiebre ya paso y le subió otra vez", "no sé si se le fue la fiebre", "ojalá se le fue la fiebre", "no baja la fiebre", "no sé si tiene fiebre")
STILL_EN = ("the fever is not gone", "the fever isn't gone", "is the fever gone?", "the fever's gone?", "if the fever is gone I'll feed him", "the fever is over 39", "the fever is over 38.5", "fever passed 39", "the fever is gone but he's still hot", "the fever went away and came back",
            "fever's gone, now 38.5", "the fever's gone, he's at 38,3", "I think the fever is gone", "maybe the fever is gone", "the fever came down to 38.2", "the fever came down a bit", "he had a fever yesterday", "he has a fever", "the fever never went away",
            "the fever is gone. Should I give him something?", "the fever is gone, is it ok to bathe him?", "I hope the fever is gone", "the fever is gone and back up again", "fever's gone, still warm", "not sure the fever is gone", "the fever went away for an hour but it's back")
# A sign beside it is what the gate answers.
SIGN_BESIDE = ("la fiebre ya paso. no respira", "La fiebre ya pasó y se puso azul", "la fiebre ya paso, no reacciona", "the fever is gone. he isn't breathing", "the fever's gone and his lips are blue", "fever's gone. he won't wake up", "the fever is gone. he won't feed", "la fiebre ya pasó. no quiere comer", "la fiebre se fue. vomitó verde", "the fever is gone, he had a seizure")


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class FeverOver(unittest.TestCase):
    def gate(self, text, lang="es"):
        return safety.gate(text, NoScreen(), lang)

    def test_a_fever_named_as_over_doesnt_fire(self):
        for text in (*OVER_ES, *OVER_EN):
            self.assertIsNone(self.gate(text), text)

    def test_the_message_that_lost_its_feed_and_question(self):
        self.assertIsNone(self.gate("la fiebre ya paso, el medico lo vio ayer y dijo que era un virus, esta bien. le di 70 ml recien. cuanto tomo en total hoy?"))
        self.assertIsNone(self.gate("The fever is gone, the doctor saw him yesterday. I gave him 70 ml just now. How much has he had today?", "en"))

    def test_any_doubt_fires(self):
        for text in (*STILL_ES, *STILL_EN):
            self.assertIsNotNone(self.gate(text), text)

    def test_a_sign_beside_it_fires(self):
        for text in SIGN_BESIDE:
            self.assertIsNotNone(self.gate(text), text)

    def test_only_the_words_about_the_fever_go(self):
        self.assertEqual(safety.without_fever_over("la fiebre ya paso. no respira").strip(" ."), "no respira")
        for text in ("tiene fiebre", "the fever is over 39", "Le di 70 ml"):
            self.assertEqual(safety.without_fever_over(text), text)

    def test_the_screen_doesnt_read_the_over_words(self):
        read = []

        class Reads(NoScreen):
            def screen(self, text, bus=None):
                read.append(text)
                return False, "test"
        safety.gate("the fever is gone, he looks a bit pale to me today", Reads(), "en")
        self.assertTrue(read and "fever" not in read[0] and "pale" in read[0])

    def test_it_doesnt_wake_the_other_parent(self):
        self.assertFalse(safety.worth_waking("la fiebre ya paso. le di 70 ml"))
        self.assertTrue(safety.worth_waking("la fiebre ya paso pero volvió"))
        self.assertTrue(safety.worth_waking("tiene fiebre"))


FEVER = 'At Wednesday 03:12 ceci wrote "tiene fiebre", and both parents were told.'
EVENING = NIGHT.replace(hour=21, minute=30)
MORNING = NIGHT.replace(hour=7, minute=30)
QUIET = "Respond with notify, or say Done."


def quiet_model(*replies):
    return scripted(*replies, *[AIMessage(QUIET) for _ in range(40)])


def sent_to(core, who):
    return [m["text"] for m in core.channel.sent if m["to"] == who]


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class OpenAlarm(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core
    event = base.CoreTest.event

    async def opened(self, core):
        await core.store.aput((*tools_mod.FACTS, core.settings.home), f"open_alarm_{NIGHT:%Y%m%d%H%M}", {"value": f"{FEVER} Nobody has said how Theo is since."})

    def test_words(self):
        for text in ("Esta noche te toca a vos. Descansá tranquilo.", "All good, get some rest.", "Que descanses.", "Don't worry about tonight."):
            self.assertTrue(safety.reassures(text), text)
        for text in ("¿Todo bien con Theo?", 'Ceci escribió: "está tranquilo". ¿Cómo sigue?', "Esta noche te toca a vos.", "His feed is due soon."):
            self.assertFalse(safety.reassures(text), text)
        self.assertTrue(safety.only_asks("¿Cuánto tomó hoy?"))
        self.assertTrue(safety.only_asks("how much did he have?"))
        self.assertFalse(safety.only_asks("Está mejor. ¿Cuánto tomó?"))
        self.assertFalse(safety.only_asks("Está mejor"))

    def test_which_facts_count(self):
        self.assertTrue(runtime.unanswered_alarm({"open_alarm_202612160312": FEVER}))
        self.assertTrue(runtime.unanswered_alarm({"alarm_202612160312": FEVER}))
        self.assertFalse(runtime.unanswered_alarm({"alarm_202612160312": FEVER, runtime.ANSWERED: "yes"}))
        self.assertFalse(runtime.unanswered_alarm({runtime.ANSWERED: "yes"}))
        self.assertFalse(runtime.unanswered_alarm({"fever_reported": "x", "plan_202612160312": "y"}))

    async def test_the_evening_refuses_calm_while_it_is_open(self):
        core = await self.run_core(quiet_model(call("notify", parent="gonza", text="Esta noche te toca a vos. Descansá tranquilo."), call("notify", parent="gonza", text="Esta noche te toca a vos."), AIMessage("Done.")))
        await self.opened(core)
        await self.event(core, "schedule", {"name": "evening"}, at=EVENING.isoformat())
        results = [a["result"] for a in reversed(await core.actions()) if a["tool"] == "notify"]
        self.assertIn("nobody has said how Theo is since the alarm", results[0])
        self.assertEqual(sent_to(core, "gonza"), ["Esta noche te toca a vos."])

    async def test_once_a_parent_said_how_he_is_calm_is_fine(self):
        core = await self.run_core(quiet_model(call("notify", parent="ceci", text="Dale."), AIMessage("x"), call("notify", parent="gonza", text="Esta noche te toca a vos. Descansá tranquilo."), AIMessage("x")))
        await self.opened(core)
        await self.event(core, "message", {"from": "ceci", "text": "Theo está mejor, le bajó"}, at=NIGHT.replace(hour=14).isoformat())
        await self.event(core, "schedule", {"name": "evening"}, at=EVENING.isoformat())
        self.assertIn("Esta noche te toca a vos. Descansá tranquilo.", sent_to(core, "gonza"))

    async def test_a_question_doesnt_answer_it(self):
        core = await self.run_core(quiet_model(call("notify", parent="ceci", text="Hoy lleva 300 ml."), AIMessage("x")))
        await self.opened(core)
        await self.event(core, "message", {"from": "ceci", "text": "¿Cuánto tomó hoy?"}, at=NIGHT.replace(hour=14).isoformat())
        self.assertTrue(runtime.unanswered_alarm(await tools_mod.facts(core.store, core.settings.home)))

    async def test_saying_the_fever_is_over_answers_it(self):
        core = await self.run_core(quiet_model(call("notify", parent="ceci", text="Dale."), AIMessage("x")))
        await self.opened(core)
        await self.event(core, "message", {"from": "ceci", "text": "anotá que la fiebre ya paso"}, at=NIGHT.replace(hour=14).isoformat())
        self.assertFalse(runtime.unanswered_alarm(await tools_mod.facts(core.store, core.settings.home)))

    async def test_the_next_morning_says_it_is_open_when_muse_leaves_it_out(self):
        core = await self.run_core(quiet_model(call("notify", parent="gonza", text="Buen día."), call("notify", parent="ceci", text="Buen día, Ceci."), AIMessage("x")))
        await self.opened(core)
        await self.event(core, "schedule", {"name": "morning"}, at=(MORNING + datetime.timedelta(days=1)).isoformat())
        for who in ("gonza", "ceci"):
            words = " ".join(sent_to(core, who))
            self.assertIn("tiene fiebre", words)
            self.assertIn("Nadie dijo", words)
        self.assertTrue(runtime.unanswered_alarm(await tools_mod.facts(core.store, core.settings.home)))

    async def test_muse_may_say_it_on_that_morning_and_not_that_evening(self):
        core = await self.run_core(quiet_model(call("notify", parent="gonza", text='A las 03:12 Ceci escribió "tiene fiebre". Nadie dijo cómo está. ¿Cómo está?'), call("notify", parent="ceci", text='A las 03:12 escribiste "tiene fiebre". Nadie dijo cómo está. ¿Cómo está?'), AIMessage("x"),
                                               call("notify", parent="gonza", text='Hoy: "tiene fiebre".'), AIMessage("x")))
        await self.opened(core)
        core.closed_signs.add("tiene fiebre")
        await self.event(core, "schedule", {"name": "morning"}, at=(MORNING + datetime.timedelta(days=1)).isoformat())
        self.assertEqual(len([t for t in sent_to(core, "gonza") if "Nadie dijo" in t]), 1)
        await self.event(core, "schedule", {"name": "evening"}, at=(EVENING + datetime.timedelta(days=1)).isoformat())
        self.assertFalse([t for t in sent_to(core, "gonza") if t.startswith("Hoy")])

    async def test_a_first_morning_that_only_quotes_it_still_says_it_is_open(self):
        core = await self.run_core(quiet_model(call("notify", parent="gonza", text='A las 03:12 Ceci escribió "tiene fiebre".'), call("notify", parent="ceci", text='A las 03:12 escribiste "tiene fiebre".'), AIMessage("x")))
        await core.store.aput((*tools_mod.FACTS, core.settings.home), f"alarm_{NIGHT:%Y%m%d%H%M}", {"value": FEVER})
        await self.event(core, "schedule", {"name": "morning"}, at=MORNING.isoformat())
        for who in ("gonza", "ceci"):
            self.assertEqual(sent_to(core, who)[-1], "Nadie dijo todavía cómo está Theo después de eso. ¿Cómo está ahora?")

    async def test_it_lasts_one_more_morning_from_any_hour_and_then_goes(self):
        core = await self.run_core(quiet_model())
        at = NIGHT.replace(hour=7, minute=40)
        await core.store.aput((*tools_mod.FACTS, core.settings.home), f"open_alarm_{at:%Y%m%d%H%M}", {"value": FEVER})
        self.assertTrue(still_there := runtime.still_open(await core.tidy_facts(at + datetime.timedelta(hours=48))), still_there)
        self.assertFalse(runtime.still_open(await core.tidy_facts(at + datetime.timedelta(hours=61))))


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class ReadAgain(unittest.IsolatedAsyncioTestCase):
    setUp = base.CoreTest.setUp
    run_core = base.CoreTest.run_core
    event = base.CoreTest.event
    HUM = "sensor.nursery_climate_humidity"
    PLUG = "switch.study_tapo_p110_dehumidifier"
    AT = NIGHT.replace(hour=18, minute=15)

    def test_a_follow_up_about_the_air_isnt_about_him(self):
        for why in ("follow up on the humidity reading", "follow-up: check the dehumidifier", "followup room temperature"):
            self.assertFalse(safety.wake_about_him(why), why)
        for why in ("follow up with Ceci", "follow up on the fever", "check on Theo", "how is Theo now", "ask how he is and read the humidity", "reached the doctor?"):
            self.assertTrue(safety.wake_about_him(why), why)

    async def test_the_wake_muse_asks_for_comes(self):
        core = await self.run_core(quiet_model(call("wake_me_at", at=(self.AT + datetime.timedelta(hours=1)).isoformat(), why="follow up on the humidity reading"), AIMessage("x")))
        await self.event(core, "state_changed", {"entity_id": self.HUM, "state": "60"}, at=self.AT.isoformat())
        result = next(a["result"] for a in await core.actions() if a["tool"] == "wake_me_at")
        self.assertTrue(result.startswith("You will get an event"), result)

    async def test_a_jump_gets_one_wake_after_the_hold(self):
        core = await self.run_core(quiet_model())
        core.mock.set_state(self.HUM, "53.9")
        await self.event(core, "state_changed", {"entity_id": self.PLUG, "state": "off"}, at=self.AT.isoformat())
        await self.event(core, "state_changed", {"entity_id": self.HUM, "state": "88"}, at=(self.AT + datetime.timedelta(minutes=2)).isoformat())
        wakes = [w for w in await core.wakes() if w["why"] == runtime.RECHECK_AIR]
        self.assertEqual(len(wakes), 1)
        self.assertEqual(wakes[0]["at"].astimezone(self.AT.tzinfo).strftime("%H:%M"), "20:16")

    async def test_with_no_hold_it_comes_in_half_an_hour_and_a_new_ask_merges(self):
        core = await self.run_core(quiet_model(AIMessage("x"), call("wake_me_at", at=(self.AT + datetime.timedelta(minutes=40)).isoformat(), why="read the humidity again"), AIMessage("x")))
        core.mock.set_state(self.HUM, "53.9")
        await self.event(core, "state_changed", {"entity_id": self.HUM, "state": "53"}, at=self.AT.isoformat())
        await self.event(core, "state_changed", {"entity_id": self.HUM, "state": "88"}, at=(self.AT + datetime.timedelta(minutes=2)).isoformat())
        wakes = await core.wakes()
        self.assertEqual(len(wakes), 1)
        self.assertEqual(wakes[0]["at"].astimezone(self.AT.tzinfo).strftime("%H:%M"), "18:47")

    async def test_no_jump_no_wake(self):
        core = await self.run_core(quiet_model())
        await self.event(core, "state_changed", {"entity_id": self.HUM, "state": "53"}, at=self.AT.isoformat())
        await self.event(core, "state_changed", {"entity_id": self.HUM, "state": "55"}, at=(self.AT + datetime.timedelta(minutes=2)).isoformat())
        self.assertEqual(await core.wakes(), [])

    async def test_a_turn_on_refused_by_the_hold_wakes_when_it_ends(self):
        core = await self.run_core(quiet_model(AIMessage("x"), call("HassTurnOn", name="Tapo P110 - Dehumidifier"), AIMessage("x")))
        await self.event(core, "state_changed", {"entity_id": self.PLUG, "state": "off"}, at=self.AT.isoformat())
        await self.event(core, "state_changed", {"entity_id": self.HUM, "state": "75"}, at=(self.AT + datetime.timedelta(minutes=30)).isoformat())
        self.assertEqual([w["at"].astimezone(self.AT.tzinfo).strftime("%H:%M") for w in await core.wakes() if w["why"] == runtime.RECHECK_AIR], ["20:16"])
