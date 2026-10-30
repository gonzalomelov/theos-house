"""The night feed's awake signal from a parent's message is about the baby, in English and Spanish, never about the
parent or the dog. Before Oct 30 it was an English word list: "I woke up to pee" and "the dog is up" fired it, and
"se despertó", "está llorando", "se levantó" and "llora" did not. The study light is live on the family agent, so a
wrong signal turns a real light on at night.
"""
import tempfile
import unittest

from parenting_agent.house_tools import HouseTools
from parenting_agent.night_feed import NightFeed, awake_message
from tests.test_home_automations import Clock, FakeHA, at, events, make_agent, night_log

PARENTS = ("Gonza", "Ceci")


class AwakeMessageTest(unittest.TestCase):
    def check(self, phrases, expected):
        for text in phrases:
            with self.subTest(text=text):
                self.assertEqual(awake_message(text, PARENTS), expected)

    def test_spanish_about_him_is_a_signal(self):
        self.check(("se despertó", "está llorando", "se levantó", "llora", "Theo se despertó", "él se despertó",
                    "el bebé está llorando", "se desperto", "Theo llora", "está despierto"), "awake")

    def test_english_about_him_is_a_signal(self):
        self.check(("he's up", "he's awake", "he woke up", "Theo is crying", "the baby woke up", "baby awake",
                    "I woke up, he is crying"), "awake")

    def test_a_parent_waking_is_not_a_signal(self):
        self.check(("I woke up to pee", "I'm up", "me desperté", "me levanté", "Ceci se levantó", "Gonza woke up",
                    "she woke up", "lloro"), None)

    def test_the_dog_is_not_a_signal(self):
        self.check(("the dog is up", "the dog woke up", "el perro se despertó", "la perra llora", "the dog is crying",
                    "feeding the dog"), None)

    def test_questions_and_not_yet_are_not_a_signal(self):
        self.check(("is he up?", "¿se despertó?", "he's still asleep", "no se despertó", "sigue durmiendo",
                    "cuándo come", "good night", "buenas noches"), None)

    def test_a_feed_starting_in_both_languages(self):
        self.check(("starting a bottle", "le estoy dando la mamadera", "preparando la mamadera", "dando de mamar"), "feed")


class AwakeOnTheNightFeedTest(unittest.TestCase):
    """End to end: the message on the bus at night, the night feed decides, the house goes ready or stays put."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name)
        self.config["people"] = {"gonza": {"name": "Gonza", "rota": "Parent A"},
                                 "ceci": {"name": "Ceci", "rota": "Parent B"}}
        self.clock = Clock(at(21, 1, 0))
        self.house = HouseTools(self.agent, self.config, client=FakeHA())
        self.feed = NightFeed(self.agent, self.config, log=night_log(), clock=self.clock)
        self.agent.plugins = [self.house, self.feed]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def say(self, text):
        self.agent.bus.publish("message", channel="telegram", text=text)

    def test_the_parent_and_the_dog_leave_the_house_alone(self):
        for text in ("I woke up to pee", "the dog is up", "el perro se despertó", "Ceci se levantó"):
            self.say(text)
        self.assertEqual(events(self.agent, "night_feed", step="prepare"), [])

    def test_se_desperto_gets_the_house_ready(self):
        self.say("se despertó")
        prepare = events(self.agent, "night_feed", step="prepare")
        self.assertEqual((len(prepare), prepare[0]["trigger"]), (1, "parent"))


if __name__ == "__main__":
    unittest.main()
