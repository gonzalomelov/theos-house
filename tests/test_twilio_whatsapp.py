"""WhatsApp through Twilio, with Twilio faked: the window, the signature, delivery only when Twilio says so, the fall back to Telegram."""
import base64
import hashlib
import hmac
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from parenting_agent.channels.messaging import MessagingError
from parenting_agent.channels.twilio_whatsapp import TwilioWhatsApp, signature

try:
    from starlette.testclient import TestClient
    from parenting_agent.core import server, tools
    READY = True
except ImportError:
    READY = False

BASE = "https://whatsapp.home.example"


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.posts, self.clock = [], [1e9]

        def post(fields):
            self.posts.append(fields)
            return {"sid": f"SM{len(self.posts)}"}
        self.wa = TwilioWhatsApp("AC1", "tok", {"gonza": "+598 91 111 111", "ceci": None}, Path(folder.name) / "w.json", post=post, now=lambda: self.clock[0])


class Window(Base):
    def test_closed_until_the_parent_writes_and_nothing_is_sent(self):
        self.assertEqual(self.wa.send("gonza", "a"), "closed")
        self.assertEqual(self.posts, [])

    def test_open_after_they_write_then_closes_a_day_later(self):
        self.wa.heard("gonza")
        self.assertEqual(self.wa.send("gonza", "a"), "text")
        self.assertEqual(self.posts[0]["To"], "whatsapp:+59891111111")
        self.assertEqual(self.posts[0]["StatusCallback"], f"{BASE}/twilio/status")
        self.clock[0] += 24 * 3600
        self.assertEqual(self.wa.send("gonza", "b"), "closed")

    def test_the_window_survives_a_restart(self):
        self.wa.heard("gonza")
        again = TwilioWhatsApp("AC1", "tok", {"gonza": "598"}, self.wa.path, post=lambda f: {"sid": "x"}, now=lambda: self.clock[0])
        self.assertEqual(again.send("gonza", "a"), "text")

    def test_the_signature_is_the_url_then_sorted_names_and_values(self):
        expected = base64.b64encode(hmac.new(b"tok", b"https://x.test/twilioBodyhiFrom+1", hashlib.sha1).digest()).decode()
        self.assertEqual(signature("tok", "https://x.test/twilio", {"From": "+1", "Body": "hi"}), expected)


@unittest.skipUnless(READY, "needs requirements-core.txt")
class Record(Base):
    def channel(self):
        out = tools.RealChannel.__new__(tools.RealChannel)
        out.whatsapp, out.sent = self.wa, []
        out.by_telegram = lambda parent, text, quiet=False: out.sent.append((parent, text))
        return out

    def test_handed_over_is_not_delivered(self):
        self.wa.heard("gonza")
        channel = self.channel()
        self.assertNotIn("delivered", channel.deliver("gonza", "a").replace("not confirmed", ""))
        self.assertEqual(channel.sent, [])

    def test_a_closed_window_says_so_and_telegram_carries_it(self):
        channel = self.channel()
        self.assertIn("window is closed", channel.deliver("gonza", "a"))
        self.assertEqual(channel.sent, [("gonza", "a")])

    def test_twilio_failing_at_once_never_loses_it(self):
        self.wa.heard("gonza")
        self.wa.post = lambda fields: (_ for _ in ()).throw(MessagingError("Twilio HTTP 400, code 63007"))
        channel = self.channel()
        self.assertIn("63007", channel.deliver("gonza", "a"))
        self.assertEqual(channel.sent, [("gonza", "a")])


@unittest.skipUnless(READY, "needs requirements-core.txt")
class Webhook(Base):
    def setUp(self):
        super().setUp()
        import os
        os.environ["PARENTING_AGENT_VOICE_TOKEN"] = "t" * 32
        self.addCleanup(os.environ.pop, "PARENTING_AGENT_VOICE_TOKEN")
        self.events, self.errors, self.telegram, self.statuses = [], [], [], []

        async def dispatch(type, payload=None, source="x", at=None, ask=False):
            self.events.append((type, payload, source))
            return 1, None

        async def whatsapp_status(parent, status):
            self.statuses.append((parent, status))
        channel = SimpleNamespace(whatsapp=self.wa, by_telegram=lambda parent, text: self.telegram.append((parent, text)))
        core = SimpleNamespace(channel=channel, dispatch=dispatch, whatsapp_status=whatsapp_status, publish=lambda kind, **f: self.errors.append(f))
        self.client = TestClient(server.echo_app(core))

    def post(self, path, params, token="tok"):
        return self.client.post(path, content=urlencode(params), headers={"Content-Type": "application/x-www-form-urlencoded",
                                                                           "X-Twilio-Signature": signature(token, BASE + path, params)})

    def said(self, sid="SMa", body="hola", sender="whatsapp:+59891111111", **more):
        return self.post("/twilio", {"From": sender, "MessageSid": sid, "Body": body, **more})

    def test_a_parents_words_wake_muse_and_open_the_window(self):
        self.assertEqual(self.said().status_code, 200)
        self.assertEqual(self.events, [("message", {"from": "gonza", "channel": "WhatsApp", "text": "hola"}, "whatsapp")])
        self.assertTrue(self.wa.window_open("gonza"))

    def test_a_bad_signature_and_a_stranger_do_nothing(self):
        self.assertEqual(self.post("/twilio", {"From": "whatsapp:+59891111111", "MessageSid": "x", "Body": "hola"}, token="wrong").status_code, 403)
        self.assertEqual(self.said(sender="whatsapp:+1555").status_code, 200)
        self.assertEqual(self.events, [])

    def test_twilio_delivering_twice_counts_once(self):
        self.said()
        self.said()
        self.assertEqual(len(self.events), 1)

    def test_a_voice_note_isnt_taken_as_words(self):
        self.said(body="", MediaContentType0="audio/ogg", NumMedia="1")
        self.assertEqual(self.events[0][0], "voice_note_not_heard")

    def test_only_the_status_says_delivered(self):
        self.wa.heard("gonza")
        self.wa.send("gonza", "a")
        self.post("/twilio/status", {"MessageSid": "SM1", "MessageStatus": "sent"})
        self.assertEqual(self.statuses, [])
        self.post("/twilio/status", {"MessageSid": "SM1", "MessageStatus": "delivered"})
        self.assertEqual(self.statuses, [("gonza", "delivered")])
        self.assertEqual(self.telegram, [])

    def test_a_refusal_goes_on_telegram_and_on_record(self):
        self.wa.heard("gonza")
        self.wa.send("gonza", "a")
        self.post("/twilio/status", {"MessageSid": "SM1", "MessageStatus": "undelivered", "ErrorCode": "63016"})
        self.assertEqual(self.telegram, [("gonza", "a")])
        self.assertIn("63016", self.statuses[0][1])
        self.assertIn("63016", self.errors[0]["error"])

    def test_an_unsigned_status_is_refused(self):
        response = self.client.post("/twilio/status", content="MessageSid=SM1&MessageStatus=failed", headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
