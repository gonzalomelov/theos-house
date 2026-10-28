"""Tests for the Telegram channel (issue #3) and channel picking (issue #8).

Offline: the fake brain, a fake messenger and a fake Home Assistant. The real checks run with
python scripts/channels_check.py.
"""
import queue
import tempfile
import time
import unittest

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.channels import router as router_mod
from parenting_agent.channels.messaging import Incoming, Messenger
from parenting_agent.channels.router import Router, Situation, pick, presence_from_states
from parenting_agent.channels.telegram import Telegram, TelegramMessenger

FAMILY, STRANGER = "111", "999"


class FakeMessenger(Messenger):
    def __init__(self):
        self.inbox, self.sent, self.next_id = [], [], 1

    def push(self, chat_id, text):
        self.inbox.append(Incoming(len(self.inbox) + 100, chat_id, text, "someone"))

    def poll(self, offset, timeout):
        return [m for m in self.inbox if m.update_id >= offset]

    def send(self, chat_id, text):
        self.sent.append((chat_id, text))
        self.next_id += 1
        return self.next_id


class FakeHA:
    def __init__(self, states=None):
        self.states = {"notify.gonza_s_echo_dot_announce": "2026-10-28T10:00:00+00:00", **(states or {})}
        self.calls = []

    def service(self, service, entity_id, data=None):
        self.calls.append((service, entity_id, data))
        if service == "notify.send_message":
            self.states[entity_id] = "2026-10-28T10:00:05+00:00"
        return []

    def state(self, entity_id):
        return self.states.get(entity_id)

    def attributes(self, entity_id):
        return {"volume_level": 0.47}


def make_agent(tmp):
    config = config_mod.load()
    config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"},
                   "telegram": {"allowed_chat_ids": [FAMILY]}})
    return build(config), config


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TelegramChannel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, config = make_agent(self.tmp.name)
        self.messenger = FakeMessenger()
        self.channel = Telegram(self.agent, config, messenger=self.messenger)
        self.agent.plugins = [self.channel]
        self.agent.start()

    def tearDown(self):
        self.agent.stop()
        self.agent.close()
        self.tmp.cleanup()

    def test_a_message_gets_an_answer_from_the_same_agent_and_memory(self):
        self.messenger.push(FAMILY, "bottle, 120 ml")
        self.channel.poll_once(0)
        self.assertTrue(wait_for(lambda: len(self.messenger.sent) == 1))
        self.messenger.push(FAMILY, "when did she last eat?")
        self.channel.poll_once(0)
        self.assertTrue(wait_for(lambda: len(self.messenger.sent) == 2))
        chat, answer = self.messenger.sent[1]
        print(f"\ntelegram round trip: {self.messenger.sent}")
        self.assertEqual(chat, FAMILY)
        self.assertIn("last feed was at", answer)
        channels = {m["channel"] for m in self.agent.memory.recent_messages(10)}
        self.assertEqual(channels, {"telegram"})

    def test_other_accounts_are_ignored_and_logged(self):
        self.messenger.push(STRANGER, "bottle, 120 ml")
        accepted = self.channel.poll_once(0)
        time.sleep(0.2)
        self.assertEqual(accepted, [])
        self.assertEqual(self.messenger.sent, [])
        self.assertEqual(self.agent.bus.count("channel_ignored"), 1)
        self.assertEqual(self.agent.memory.recent_messages(10), [])

    def test_offset_is_kept_so_a_message_is_handled_once(self):
        self.messenger.push(FAMILY, "bottle, 90 ml")
        self.assertEqual(len(self.channel.poll_once(0)), 1)
        self.assertEqual(self.channel.poll_once(0), [])

    def test_agent_started_messages_go_to_the_default_family_chat(self):
        self.channel.default_chat = FAMILY
        self.agent.bus.publish("reply", channel="telegram", text="Next feed around 15:00.")
        self.assertEqual(self.messenger.sent, [(FAMILY, "Next feed around 15:00.")])


class TelegramAdapter(unittest.TestCase):
    def test_updates_become_incoming_messages(self):
        messenger = TelegramMessenger("not-a-real-token", api="http://127.0.0.1:9")
        messenger._call = lambda method, params, timeout: [
            {"update_id": 7, "message": {"chat": {"id": 111}, "from": {"username": "g"}, "text": "hi"}},
            {"update_id": 8, "message": {"chat": {"id": 222}, "from": {"first_name": "x"}}}]
        items = messenger.poll(0, 1)
        self.assertEqual([(i.update_id, i.chat_id, i.text) for i in items], [(7, "111", "hi"), (8, "222", "")])


SITUATIONS = [
    ("changing the diaper at home", Situation("home", skill_active=True), "ear"),
    ("at home, hands free", Situation("home"), "home_speaker"),
    ("at home, the baby is asleep", Situation("home", baby_asleep=True), "ear"),
    ("away from home", Situation("away"), "telegram"),
    ("away, a skill left armed", Situation("away", skill_active=True), "telegram"),
    ("presence unknown", Situation("unknown"), "telegram"),
    ("help needed during a change", Situation("home", skill_active=True, help_needed=True), "partner"),
    ("help needed while away", Situation("away", help_needed=True), "partner"),
]


class ChannelPicking(unittest.TestCase):
    def test_eight_scripted_situations(self):
        print()
        passed = 0
        for label, situation, expected in SITUATIONS:
            channel, reason = pick(situation)
            ok = channel == expected
            passed += ok
            print(f"  {'PASS' if ok else 'FAIL'} {label:32} -> {channel:13} ({reason})")
        print(f"routing: {passed} of {len(SITUATIONS)}")
        self.assertEqual(passed, 8)

    def test_presence_from_home_assistant_states(self):
        self.assertEqual(presence_from_states("home", "not_home"), "home")
        self.assertEqual(presence_from_states("not_home", "home"), "away")
        self.assertEqual(presence_from_states("Work", None), "away")
        self.assertEqual(presence_from_states("unknown", "home"), "home")
        self.assertEqual(presence_from_states("unavailable", "unknown"), "unknown")


class Skill:
    kind, skill = "skill", None


class RouterDelivery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, config = make_agent(self.tmp.name)
        self.messenger = FakeMessenger()
        self.telegram = Telegram(self.agent, config, messenger=self.messenger)
        self.telegram.default_chat = FAMILY
        self.ha, self.ear, self.where = FakeHA(), [], "home"
        self.router = Router(self.agent, config, client=self.ha, presence=lambda: self.where,
                             outputs={"ear": lambda text: self.ear.append(text) or {"played": True}})
        self.router.outputs["home_speaker"].cfg["restore_after_s"] = 0
        self.skill = Skill()
        self.agent.plugins = [self.telegram, self.router, self.skill]

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def test_reminder_in_the_ear_during_a_change_and_on_telegram_when_away(self):
        reminder = "Reminder: next feed around 15:00."
        self.skill.skill = object()
        self.agent.bus.publish("notify", text=reminder)
        self.assertEqual(self.ear, [reminder])
        self.skill.skill, self.where = None, "away"
        self.agent.bus.publish("notify", text=reminder)
        self.assertEqual(self.messenger.sent, [(FAMILY, reminder)])
        self.assertEqual([e["channel"] for e in self.agent.bus.history if e["kind"] == "routed"], ["ear", "telegram"])

    def test_home_speaker_announces_low_and_restores_the_volume(self):
        channel, result = self.router.deliver("Test: hello", Situation("home"))
        self.assertEqual(channel, "home_speaker")
        self.assertTrue(result["confirmed"])
        self.assertTrue(wait_for(lambda: len(self.ha.calls) == 3))
        volume, announce, restore = self.ha.calls
        self.assertEqual(volume, ("media_player.volume_set", "media_player.gonza_s_echo_dot", {"volume_level": 0.2}))
        self.assertEqual(announce, ("notify.send_message", "notify.gonza_s_echo_dot_announce", {"message": "Test: hello"}))
        self.assertEqual(restore[2], {"volume_level": 0.47})

    def test_agent_replies_on_auto_are_routed(self):
        self.where = "away"
        self.agent.bus.publish("reply", channel="auto", text="Night summary ready.")
        self.assertEqual(self.messenger.sent, [(FAMILY, "Night summary ready.")])

    def test_partner_is_a_stub_that_sends_nothing(self):
        self.router.deliver("Can you take over?", Situation("home", help_needed=True))
        self.assertEqual(self.agent.bus.count("partner_stub"), 1)
        self.assertEqual(self.messenger.sent, [])

    def test_speaker_outside_the_allowed_list_or_loud_is_refused(self):
        with self.assertRaises(ValueError):
            router_mod.HomeSpeaker(self.ha, {"notify": "notify.lg_webos_tv_oled55b3psa"}, self.agent.bus)
        with self.assertRaises(ValueError):
            router_mod.HomeSpeaker(self.ha, {"volume": 0.8}, self.agent.bus)


if __name__ == "__main__":
    unittest.main()
