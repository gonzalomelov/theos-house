"""WhatsApp, with Meta faked: the 24 hour window, the template, the fall back to Telegram, the webhook's checks."""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from parenting_agent.channels.messaging import MessagingError
from parenting_agent.channels.whatsapp import OUTSIDE_WINDOW, WINDOW_S, WhatsApp, WhatsAppRefused

try:
    from starlette.applications import Starlette
    from starlette.testclient import TestClient
    from parenting_agent.core import server, tools
    READY = True
except ImportError:
    READY = False


class Meta:
    def __init__(self):
        self.bodies, self.refuse = [], None

    def __call__(self, body):
        if self.refuse and body["type"] == "text":
            raise self.refuse
        self.bodies.append(body)
        return {"messages": [{"id": f"wamid.{len(self.bodies)}"}]}

    def types(self):
        return [b["type"] for b in self.bodies]


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "whatsapp.json"
        self.meta, self.at = Meta(), 1_000_000.0
        self.wa = self.make()

    def make(self):
        return WhatsApp("t", "1", {"gonza": "+598 91 111", "ceci": None}, self.path, post=self.meta, now=lambda: self.at)


class Window(Base):
    def test_only_a_parent_with_a_number_counts_and_numbers_are_digits(self):
        self.assertEqual(self.wa.numbers, {"gonza": "59891111"})
        self.assertEqual(self.wa.parents, {"59891111": "gonza"})

    def test_before_any_reply_only_the_template_goes_and_the_words_wait(self):
        self.assertEqual(self.wa.send("gonza", "Hola"), "template")
        self.assertEqual(self.meta.types(), ["template"])
        self.assertEqual(self.meta.bodies[0]["template"]["name"], "hello_world")

    def test_a_reply_opens_the_window_and_sends_what_waited(self):
        self.wa.send("gonza", "Hola")
        self.assertEqual(self.wa.heard("gonza"), 1)
        self.assertEqual(self.meta.bodies[-1]["text"]["body"], "Hola")
        self.assertEqual(self.wa.send("gonza", "Otra"), "text")
        self.assertEqual(self.meta.types(), ["template", "text", "text"])

    def test_the_window_closes_after_24_hours(self):
        self.wa.heard("gonza")
        self.at += WINDOW_S - 1
        self.assertEqual(self.wa.send("gonza", "a"), "text")
        self.at += 2
        self.assertEqual(self.wa.send("gonza", "b"), "template")

    def test_the_window_and_the_waiting_words_survive_a_restart(self):
        self.wa.send("gonza", "Hola")
        again = self.make()
        self.assertFalse(again.window_open("gonza"))
        self.assertEqual(again.heard("gonza"), 1)
        self.assertTrue(self.make().window_open("gonza"))

    def test_meta_saying_the_window_is_closed_falls_to_the_template(self):
        self.wa.heard("gonza")
        self.meta.refuse = WhatsAppRefused(OUTSIDE_WINDOW, "closed")
        self.assertEqual(self.wa.send("gonza", "a"), "template")

    def test_any_other_refusal_is_an_error_for_the_caller(self):
        self.wa.heard("gonza")
        self.meta.refuse = WhatsAppRefused(100, "bad")
        with self.assertRaises(MessagingError):
            self.wa.send("gonza", "a")

    def test_a_refusal_after_accepting_hands_the_words_back(self):
        self.wa.heard("gonza")
        self.wa.send("gonza", "a")
        self.assertEqual(self.wa.failed("wamid.1"), ("gonza", "a"))
        self.assertIsNone(self.wa.failed("wamid.1"))

    def test_no_app_yet_means_no_whatsapp(self):
        self.assertIsNone(WhatsApp.from_env(self.path.parent))


@unittest.skipUnless(READY, "needs requirements-core.txt")
class Channel(Base):
    def channel(self):
        out = tools.RealChannel.__new__(tools.RealChannel)
        out.whatsapp, out.sent = self.wa, []
        out.by_telegram = lambda parent, text: out.sent.append((parent, text))
        return out

    def test_inside_the_window_only_whatsapp_carries_it(self):
        self.wa.heard("gonza")
        channel = self.channel()
        self.assertEqual(channel.send("gonza", "a"), "On WhatsApp.")
        self.assertEqual(channel.sent, [])

    def test_outside_it_telegram_carries_the_words_and_the_record_says_so(self):
        channel = self.channel()
        self.assertIn("window is closed", channel.send("gonza", "a"))
        self.assertEqual(channel.sent, [("gonza", "a")])

    def test_whatsapp_failing_never_loses_a_message(self):
        self.wa.heard("gonza")
        self.meta.refuse = MessagingError("down")
        channel = self.channel()
        self.assertIn("failed", channel.send("gonza", "a"))
        self.assertEqual(channel.sent, [("gonza", "a")])

    def test_a_parent_with_no_number_stays_on_telegram(self):
        channel = self.channel()
        self.assertIsNone(channel.send("ceci", "a"))
        self.assertEqual(channel.sent, [("ceci", "a")])
        self.assertEqual(self.meta.bodies, [])


@unittest.skipUnless(READY, "needs requirements-core.txt")
class Webhook(Base):
    def setUp(self):
        super().setUp()
        os.environ.update(WHATSAPP_VERIFY_TOKEN="v", WHATSAPP_APP_SECRET="s", PARENTING_AGENT_VOICE_TOKEN="t" * 32)
        for name in ("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "PARENTING_AGENT_VOICE_TOKEN"):
            self.addCleanup(os.environ.pop, name)
        self.events, self.errors, self.telegram = [], [], []

        async def dispatch(type, payload=None, source="x", at=None, ask=False):
            self.events.append((type, payload, source))
            return 1, None
        channel = SimpleNamespace(whatsapp=self.wa, by_telegram=lambda parent, text: self.telegram.append((parent, text)))
        core = SimpleNamespace(channel=channel, dispatch=dispatch, publish=lambda kind, **f: self.errors.append(f))
        self.client = TestClient(server.echo_app(core))

    def post(self, value, secret="s"):
        raw = json.dumps({"entry": [{"changes": [{"value": value}]}]}).encode()
        signed = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return self.client.post("/whatsapp", content=raw, headers={"X-Hub-Signature-256": signed})

    def text(self, sender="59891111", id="m1"):
        return {"messages": [{"from": sender, "id": id, "type": "text", "text": {"body": "Hola"}}]}

    def test_meta_check_needs_the_verify_token(self):
        good = self.client.get("/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "v", "hub.challenge": "42"})
        self.assertEqual((good.status_code, good.text), (200, "42"))
        self.assertEqual(self.client.get("/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "x"}).status_code, 403)

    def test_a_body_without_the_right_signature_does_nothing(self):
        self.assertEqual(self.post(self.text(), secret="wrong").status_code, 403)
        self.assertEqual(self.client.post("/whatsapp", content=b"{}").status_code, 403)
        self.assertEqual(self.events, [])

    def test_a_parents_words_wake_muse_and_open_the_window(self):
        self.assertEqual(self.post(self.text()).status_code, 200)
        self.assertEqual(self.events, [("message", {"from": "gonza", "channel": "WhatsApp", "text": "Hola"}, "whatsapp")])
        self.assertTrue(self.wa.window_open("gonza"))

    def test_a_stranger_is_ignored(self):
        self.post(self.text(sender="1234"))
        self.assertEqual(self.events, [])
        self.assertFalse(self.wa.window_open("gonza"))

    def test_the_same_message_delivered_twice_wakes_muse_once(self):
        self.post(self.text())
        self.post(self.text())
        self.assertEqual(len(self.events), 1)

    def test_a_voice_note_is_not_taken_as_words(self):
        self.post({"messages": [{"from": "59891111", "id": "m2", "type": "audio"}]})
        self.assertEqual(self.events, [("voice_note_not_heard", {"from": "gonza"}, "whatsapp")])

    def test_a_refusal_in_a_status_goes_on_telegram_and_on_record(self):
        self.wa.heard("gonza")
        self.wa.send("gonza", "a")
        self.post({"statuses": [{"id": "wamid.1", "status": "failed", "errors": [{"code": OUTSIDE_WINDOW}]}]})
        self.assertEqual(self.telegram, [("gonza", "a")])
        self.assertIn(str(OUTSIDE_WINDOW), self.errors[0]["error"])


if __name__ == "__main__":
    unittest.main()
