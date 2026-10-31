"""Display cards on the glasses (Oct 30, Gonza: "use the HUD as much as possible for everything").

Everything the agent tells a parent that fits a glance becomes a card on that parent's glasses, in their language,
short, within Meta's display rules, and only on the glasses of the parent the Telegram copy went to. Offline: the
fake Telegram messenger, the real glasses endpoint on a free port with two wearers, and the family agent's plug-ins.
"""
import json
import tempfile
import threading
import time
import unittest
import urllib.request

from parenting_agent import hud_cards as cards
from parenting_agent.glasses import Glasses, GlassesHub
from tests.test_family_push import CECI, GONZA, Family, at

# Every IconName case in MWDATDisplay 1.0.1, read from the SDK's swiftinterface on Oct 30.
CATALOG = set("""airplane arrowDownShallowU arrowLeft arrowRight arrowULeft arrowUpShallowU avatar avatarOff bedSide bell
bellDiagonalRightDot bellOff bikeShare bug bullhorn bus calendar campfire caretDown caretLeft caretRight caretUp
carFrontView cart checkmark checkmarkCircle circle8RaysLarge circleHandle clock cloud cloudCrescentMoon cloudDotFourRays
cloudFiveDashes cloudHookSwirl cloudLightning cocktailGlass code coffeeCup compassNorthUpRed containerWithLid
crossBriefcase dropper envelopeOpen exclamationCircle exclamationTriangle eye forkKnife fourArcsUpFilled
fourArcsUpGrayscale fourCornerFrame gear globeWesternHemisphere graduationCap hashtag headphones heart house iCircle
lightBulb magicWand metaAi mountainSquare mountainSquareStacked museumBuilding musicNote nineSquaresGrid padlockClosed
padlockOpen palette paperAirplane pencil pencilSquare person personCircle phone phoneHandsetArrowDownLeft
phoneHandsetArrowUpRight phoneSlash pizzaSlice plus plusCircle shoppingBag slidersHorizontal smartGlasses smileyCircle
speakerOff speakerWithOneArc speakerWithThreeArcs speakerWithTwoArcs speechBubble speechBubbleOff stadium star
starCircleTriangleAi taxi threeDotsHorizontal threeDotSpeechBubble threeHorizontalLines
threeHorizontalLinesStackedDescending threePeopleOverlapping train tree triangleLeftVerticalLine triangleRight
triangleRightCircle triangleRightVerticalLine twoArrowsClockwise twoLinesParallel twoSquaresStackedRightDown
twoTrianglesLeft twoTrianglesRight videoCamera videoCameraOff wristband wristbandSlash x""".split())


def fits(card):
    return all(len(card.get(k) or "") <= limit for k, limit in cards.LIMITS.items())


class Cards(unittest.TestCase):
    def test_every_icon_is_in_metas_catalog(self):
        self.assertLessEqual(cards.ICONS, CATALOG)
        with self.assertRaises(ValueError):
            cards.card("note", "baby", "t", "s")

    def test_the_app_draws_every_icon_a_card_names(self):
        """DAT's IconName raw values are not its case names, so the app maps each name to its case by hand."""
        import re
        from pathlib import Path
        swift = (Path(__file__).resolve().parent.parent / "apps/glasses/ParentingGlasses/HUD/DisplayHUD.swift").read_text()
        mapped = set(re.findall(r'"(\w+)": \.(\w+),', swift))
        self.assertTrue(all(name == case for name, case in mapped))
        self.assertLessEqual(cards.ICONS, {name for name, _ in mapped})

    def test_red_flag_is_sticky_and_in_the_parents_language(self):
        es, en = cards.red_flag("emergency", "es"), cards.red_flag("emergency", "en")
        self.assertEqual((es["title"], es["alert"], es["sticky"]), ("Llamá al 911 ya", True, True))
        self.assertEqual(en["title"], "Call 911 now")
        fever = cards.red_flag("urgent_fever", "es")
        self.assertTrue(fever["sticky"])
        self.assertIn("911", fever["detail"])
        self.assertLess(cards.KEEPALIVE_S, cards.DIM_S, "the red flag is refreshed before the display dims")

    def test_internal_text_never_reaches_a_card(self):
        self.assertIsNone(cards.clean("invalid answer not a JSON object"))
        self.assertIsNone(cards.clean("house_dry switch.gonza_s_echo_dot_do_not_disturb"))
        self.assertIsNone(cards.from_text("note", "start_changing_table() returned", "en"))
        card = cards.from_text("answer", "Test: Comió a las 10:40. finish_reason length", "es")
        self.assertEqual(card["status"], "Comió a las 10:40.")
        self.assertNotIn("detail", card)

    def test_lines_are_cut_to_fit_the_display(self):
        long = "Esta es una respuesta muy larga " * 10
        card = cards.from_text("answer", long + ". " + long, "es")
        self.assertTrue(fits(card))
        self.assertTrue(card["status"].endswith("…"))

    def test_next_feed_in_both_languages(self):
        es = cards.next_feed("Próxima toma en unos 20 min, cerca de las 11:40. Las tomas vienen cada 3 h 05 min más o menos.", "es")
        self.assertEqual((es["title"], es["status"], es["detail"]),
                         ("Próxima toma", "Cerca de las 11:40 · en 20 min", "Cada 3 h 05 min más o menos"))
        en = cards.next_feed("Next feed in about 18 min, around 14:05. Feeds have been about 2 h 50 min apart.", "en")
        self.assertEqual(en["status"], "Around 14:05 · in 18 min")

    def test_morning_message_shortened_to_what_matters(self):
        text = ("Buen día, Gonza.\nAnoche: 2 tomas, el sueño más largo 3.5 h, te levantaste 2 veces.\n"
                "Clima: soleado, 12 a 21 C.\nEsta noche te toca a vos.\nAntes de que llegue: faltan 40 días.")
        card = cards.morning(text, "es")
        self.assertEqual(card["title"], "Buen día, Gonza")
        self.assertEqual(card["status"], "Esta noche te toca a vos.")
        self.assertTrue(card["detail"].startswith("Anoche"))
        self.assertTrue(fits(card))

    def test_nap_mode_on_and_off(self):
        on = cards.nap_mode("on", "es", "nap", "11:30")
        self.assertEqual((on["title"], on["status"], on["meta"]),
                         ("Modo siesta", "Siesta desde las 11:30", "Prueba en seco, no se movió nada"))
        self.assertNotIn("meta", cards.nap_mode("off", "en", live=True))
        self.assertIsNone(cards.nap_mode("night_wake_stays_quiet", "en"))

    def test_car_seat_steps_never_say_safe(self):
        for step in cards.CAR_SEAT:
            for lang in ("en", "es"):
                for result in (None, *cards.CAR_SEAT_RESULT):
                    card = cards.car_seat(step, lang, 2, 8, result)
                    words = json.dumps(card, ensure_ascii=False).lower()
                    self.assertNotRegex(words, r"\bsafe\b|\bsegur[oa]\b")
                    self.assertTrue(fits(card))
        fail = cards.car_seat("lap_guides", "es", 2, 8, "fail")
        self.assertEqual((fail["status"], fail["detail"], fail["meta"], fail["alert"]),
                         ("Cinturón de cadera en las dos guías", "Corregilo antes de manejar", "Paso 2 de 8", True))
        self.assertEqual(cards.car_seat("car_position", "es", 1, 8, ask=True)["detail"], "Decí sí o no")

    def test_push_topics(self):
        handover = cards.from_push({"source": "night_feed", "routine": "handover",
                                    "text": "Ceci pidió dormir esta noche, así que esta noche estás de turno vos, Gonza."}, "es")
        self.assertEqual(handover["title"], "Cambio de turno")
        tonight = cards.from_push({"source": "house-brain", "routine": "tonight",
                                   "text": "Plan de esta noche. De turno: Gonza.\nCalentador a las 02:30."}, "es")
        self.assertEqual(tonight["status"], "De turno: Gonza")
        supplies = cards.from_push({"source": "day-engine", "routine": "supplies",
                                    "text": "Pañales: solo anotado para la lista de compras (prueba en seco), no se agregó nada."}, "es")
        self.assertEqual((supplies["icon"], supplies["title"]), ("cart", "Se está terminando"))
        night = cards.from_push({"source": "night_feed", "text": "Se despertó, lloró en el cuarto. Luz del estudio tenue."}, "es")
        self.assertEqual(night["title"], "Toma de noche")
        rota = cards.from_reply({"text": "Esta noche está de turno Gonza. Lo decide la rota.", "topic": "on_duty"}, "es")
        self.assertEqual(rota["status"], "De turno: Gonza")
        shop = cards.from_reply({"text": "Listo, pañales en la lista de compras (prueba en seco)."}, "es")
        self.assertEqual(shop["title"], "Lista de compras")


class Listener:
    """One parent's glasses app reading the event stream with their own token."""

    def __init__(self, hub, token):
        request = urllib.request.Request(hub.url + "events", headers={"Authorization": f"Bearer {token}"})
        self.response = urllib.request.urlopen(request, timeout=10)
        self.seen = []
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            for raw in self.response:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    self.seen.append(json.loads(line[6:]))
        except (OSError, ValueError):
            pass

    def cards(self):
        return [e["card"] for e in self.seen if e["kind"] == "card"]

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(predicate(e) for e in list(self.seen)):
                return True
            time.sleep(0.02)
        return False


class Routing(unittest.TestCase):
    """Two wearers on one endpoint: each card reaches only the parent the Telegram copy went to."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        people = {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID", "lang": "es"},
                  "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID", "lang": "en"}}
        self.family = Family(self.tmp.name, at(30, 11, 0), extra={"people": people,
                             "glasses": {"port": 0, "host": "127.0.0.1", "wearers": ["gonza", "ceci"]}})
        self.family.agent.people = None
        self.glasses = Glasses(self.family.agent, self.family.config)
        self.family.agent.plugins.append(self.glasses)
        self.hub = self.glasses.hub
        tokens = {person: token for token, person in self.hub.tokens.items() if person}
        self.gonza = Listener(self.hub, tokens["gonza"])
        self.ceci = Listener(self.hub, tokens["ceci"])
        self.tokens = tokens
        self.assertTrue(self.gonza.wait(lambda e: e.get("wearer") == "gonza" and e.get("lang") == "es"))
        self.assertTrue(self.ceci.wait(lambda e: e.get("wearer") == "ceci"))

    def tearDown(self):
        self.hub.close()
        self.family.close()
        self.tmp.cleanup()

    def test_tokens_are_per_wearer_and_written_to_their_own_file(self):
        self.assertEqual(sorted(self.hub.wearers_live()), ["ceci", "gonza"])
        for person in ("gonza", "ceci"):
            path = f"{self.tmp.name}/glasses-token-{person}"
            with open(path) as handle:
                self.assertEqual(handle.read().strip(), self.tokens[person])

    def test_a_push_to_one_parent_is_a_card_on_their_glasses_only_and_telegram_still_gets_it(self):
        self.family.agent.bus.publish("notify", text="Recordá la vacuna.", texts={"en": "Remember the shot.",
                                      "es": "Recordá la vacuna."}, person="gonza", source="reminders")
        self.assertEqual(self.family.sent_to(GONZA), ["Recordá la vacuna."])
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "card" and e["card"]["status"] == "Recordá la vacuna."))
        time.sleep(0.2)
        self.assertEqual(self.ceci.cards(), [])

    def test_a_shared_push_reaches_both_in_each_language(self):
        self.family.agent.bus.publish("notify", source="rhythm", routine="next_feed", texts={
            "en": "Next feed in about 20 min, around 11:40. Feeds have been about 3 h 05 min apart.",
            "es": "Próxima toma en unos 20 min, cerca de las 11:40. Las tomas vienen cada 3 h 05 min más o menos."},
            text="Next feed in about 20 min, around 11:40. Feeds have been about 3 h 05 min apart.")
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "card" and e["card"]["title"] == "Próxima toma"))
        self.assertTrue(self.ceci.wait(lambda e: e["kind"] == "card" and e["card"]["title"] == "Next feed"))
        self.assertEqual(len(self.family.sent_to(GONZA)), 1)
        self.assertEqual(len(self.family.sent_to(CECI)), 1)

    def test_a_red_flag_on_telegram_is_a_sticky_card_for_the_parent_who_wrote(self):
        self.family.say(CECI, "He is not breathing and turning blue")
        self.assertIn("911", self.family.sent_to(CECI)[0])
        self.assertTrue(self.ceci.wait(lambda e: e["kind"] == "card" and e["card"]["sticky"]
                                       and e["card"]["title"] == "Call 911 now"))
        time.sleep(0.2)
        self.assertEqual(self.gonza.cards(), [])
        logged = [e for e in self.family.agent.bus.history if e["kind"] == "glasses_card"]
        self.assertEqual([(e["person"], e["topic"], e["shown"]) for e in logged], [("ceci", "red_flag", True)])

    def test_the_rota_answer_on_telegram(self):
        self.family.say(GONZA, "¿Quién está de turno esta noche?")
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "card" and e["card"]["status"].startswith("De turno:")))

    def test_a_question_on_the_glasses_is_answered_on_those_glasses_only(self):
        body = json.dumps({"text": "Entendido"}).encode()
        request = urllib.request.Request(self.hub.url + "say", data=body, method="POST", headers={
            "Authorization": f"Bearer {self.tokens['gonza']}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 204)
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "heard" and e["text"] == "Entendido"))
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "red_flag_clear"))
        message = next(e for e in self.family.agent.bus.history if e["kind"] == "message" and e["channel"] == "glasses")
        self.assertEqual((message["person"], message["chat_id"]), ("gonza", "gonza"))
        self.family.agent.current_event = message
        self.family.agent.say("glasses", "Comió a las 10:40, 90 ml de mamadera.")
        self.family.agent.current_event = None
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "card" and e["card"]["title"] == "Respuesta"))
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "reply"))
        time.sleep(0.2)
        self.assertFalse([e for e in self.ceci.seen if e["kind"] in ("card", "reply", "heard")])

    def test_nap_mode_follows_the_push_routing(self):
        self.family.agent.bus.publish("routine", name="nap_mode", step="on", sleep="nap", since=at(30, 10, 55).isoformat())
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "card" and e["card"]["title"] == "Modo siesta"))
        self.assertTrue(self.ceci.wait(lambda e: e["kind"] == "card" and e["card"]["title"] == "Nap mode on"))
        self.family.clock.moment = at(30, 23, 30)  # at night only the parent on duty
        duty = self.family.push.people.person(self.family.push.on_duty(self.family.clock()))
        self.assertIn(duty, ("gonza", "ceci"))
        before = {p: len(l.cards()) for p, l in (("gonza", self.gonza), ("ceci", self.ceci))}
        self.family.agent.bus.publish("routine", name="nap_mode", step="off", sleep="sleep")
        listener = self.gonza if duty == "gonza" else self.ceci
        other = self.ceci if duty == "gonza" else self.gonza
        self.assertTrue(listener.wait(lambda e: e["kind"] == "card" and e["card"]["topic"] == "nap"
                                      and e["card"]["icon"] == "speakerWithTwoArcs"))
        time.sleep(0.2)
        self.assertEqual(len(other.cards()), before["ceci" if duty == "gonza" else "gonza"])

    def test_no_card_when_that_parents_glasses_are_not_live(self):
        self.ceci.response.close()
        deadline = time.monotonic() + 15
        while self.hub.live("ceci") and time.monotonic() < deadline:
            self.hub.push({"kind": "ping"}, "ceci")  # a write to the closed stream ends that listener
            time.sleep(0.1)
        self.assertFalse(self.hub.live("ceci"))
        self.family.agent.bus.publish("notify", text="Hola Ceci.", person="ceci", source="reminders")
        self.assertEqual(self.family.sent_to(CECI), ["Hola Ceci."], "the Telegram copy is never dropped")
        logged = [e for e in self.family.agent.bus.history if e["kind"] == "glasses_card"]
        self.assertEqual([(e["person"], e["shown"]) for e in logged], [("ceci", False)])

    def test_car_seat_coach_step_by_step_on_the_camera_wearers_glasses(self):
        self.hub.camera_person = "gonza"
        bus = self.family.agent.bus
        bus.publish("carseat_step", step="car_position", step_kind="ask")
        bus.publish("voice", skill="car-seat", step="car_position", text="Coaching the seat. Is the carrier on a rear seat?")
        bus.publish("carseat_step", step="lap_guides", step_kind="camera")
        bus.publish("voice", skill="car-seat", step="lap_guides", text="Slide the lap belt into both side guides.")
        bus.publish("voice", skill="car-seat", step="lap_guides", result="pass", text="I can see the lap belt in both side guides.")
        self.assertTrue(self.gonza.wait(lambda e: e["kind"] == "card" and e["card"].get("detail") == "Visto en cámara: bien"))
        steps = [c for c in self.gonza.cards() if c["topic"] == "car_seat"]
        self.assertEqual([c["meta"] for c in steps], ["Paso 1 de 8", "Paso 2 de 8", "Paso 2 de 8"])
        self.assertEqual(steps[0]["detail"], "Decí sí o no")
        bus.publish("voice", episode=1, text="hand")  # the changing table's "hand" is not a car seat card
        time.sleep(0.2)
        self.assertEqual(len([c for c in self.gonza.cards() if c["topic"] == "car_seat"]), 3)
        self.assertEqual(self.ceci.cards(), [])


class CarSeatAnswers(unittest.TestCase):
    """Oct 30 rehearsal: "sí" on the glasses went to Muse, which answered in its own words, and the step stayed open."""

    def test_a_yes_or_no_on_the_coach_channel_answers_the_open_step(self):
        from parenting_agent.carseat.coach import Coach
        from parenting_agent.carseat.plugin import COACHING_NOTE, CarSeatCoach
        with tempfile.TemporaryDirectory() as tmp:
            family = Family(tmp, at(30, 12, 0))
            try:
                plugin = CarSeatCoach(family.agent, {**family.config, "car_seat": {"channel": "glasses"}}, quiet=True)
                coach = Coach(plugin.skill_cfg, family.agent.bus, None, None, plugin.seat, plugin.car)
                plugin.coach = coach
                coach.asking = "car_position"
                agent = family.agent
                self.assertIsNone(plugin.take_answer({"channel": "telegram"}, "sí"), "another channel's yes is not for the coach")
                self.assertIsNone(plugin.take_answer({"channel": "glasses"}, "¿cuánto falta?"))
                self.assertNotIn("car_position", coach.answers)
                message = agent.bus.publish("message", channel="glasses", text="Sí.", person="gonza", chat_id="gonza")
                agent.current_event = message
                agent.handle(message)
                agent.current_event = None
                self.assertEqual(coach.answers["car_position"], "Sí.")
                replies = [e["text"] for e in agent.bus.history if e["kind"] == "reply"]
                self.assertEqual(replies, ["Anotado: sí."], "the agent says the coach took it, never that nothing waited")
                self.assertIsNone(plugin.take_answer({"channel": "glasses"}, "sí"), "a step is answered once")
                self.assertTrue(COACHING_NOTE)
            finally:
                family.close()


class LegacyHub(unittest.TestCase):
    def test_a_single_token_with_no_wearer_still_works(self):
        heard = []
        hub = GlassesHub(port=0, host="127.0.0.1", token="t", on_say=heard.append)
        try:
            body = json.dumps({"text": "hola"}).encode()
            request = urllib.request.Request(hub.url + "say", data=body, method="POST",
                                             headers={"Authorization": "Bearer t", "Content-Type": "application/json"})
            urllib.request.urlopen(request, timeout=5).close()
            self.assertEqual(heard, ["hola"])
            self.assertFalse(hub.live("gonza"))
        finally:
            hub.close()


if __name__ == "__main__":
    unittest.main()
