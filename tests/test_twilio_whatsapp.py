"""WhatsApp through Twilio, with Twilio faked: the window, the signature, delivery only when Twilio says so, the fall back to Telegram."""
import base64
import hashlib
import hmac
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlencode

from parenting_agent.channels.messaging import MessagingError
from parenting_agent.channels.twilio_whatsapp import MAX_VOICE_BYTES, TwilioWhatsApp, signature
from parenting_agent.voice import audio, client as voice_client, screen

try:
    from starlette.testclient import TestClient
    from parenting_agent.core import server, sources, tools
    READY = True
except ImportError:
    READY = False

BASE = "https://whatsapp.home.example"
NOTE = Path(__file__).resolve().parent.parent / "results/voice/notes/es01.ogg"  # a synthetic voice, no family audio


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

    def test_the_sandbox_gets_its_3_seconds_between_messages_and_a_real_sender_doesnt(self):
        waits = []
        self.wa.wait = waits.append
        self.wa.heard("gonza")
        self.wa.send("gonza", "a")
        self.clock[0] += 1
        self.wa.send("gonza", "b")
        self.assertEqual(waits, [2])
        self.clock[0] += 3
        self.wa.send("gonza", "c")
        self.assertEqual(waits, [2])
        self.wa.sender = "whatsapp:+15550000000"
        self.wa.send("gonza", "d")
        self.assertEqual(waits, [2])

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


class Media(BaseHTTPRequestHandler):
    """Twilio's API and its CDN, on one port: the API takes basic auth and redirects, the CDN holds the bytes and takes no auth."""
    def log_message(self, *args):
        pass

    def answer(self, status, body=b"", **headers):
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        state = self.server.state
        state["seen"].append((self.path, self.headers.get("Authorization")))
        if self.path.startswith("/cdn/"):
            return self.answer(200, state["audio"], Content_Type=state["type"])
        if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"AC1:tok").decode():
            return self.answer(401)
        if state["not_ready"] > 0:
            state["not_ready"] -= 1
            return self.answer(404)
        self.answer(307, Location=state["location"])


@unittest.skipUnless(READY, "needs requirements-core.txt")
class FakeTwilio(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Media)
        port = self.server.server_address[1]
        self.server.state = {"seen": [], "audio": NOTE.read_bytes(), "type": "audio/ogg", "not_ready": 0, "location": f"http://localhost:{port}/cdn/note"}
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.api = f"http://127.0.0.1:{port}"
        self.url = f"{self.api}/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1"
        self.waits = []
        self.wa = TwilioWhatsApp("AC1", "tok", {"gonza": "59891111111"}, Path(folder.name) / "w.json", post=lambda f: {"sid": "x"}, media_api=self.api, media_cdn=("localhost",), wait=self.waits.append)


@unittest.skipUnless(READY, "needs requirements-core.txt")
class Download(FakeTwilio):
    def test_a_note_comes_through_the_redirect_and_the_auth_stops_at_the_api(self):
        self.assertEqual(self.wa.download(self.url), NOTE.read_bytes())
        (first, first_auth), (second, second_auth) = self.server.state["seen"]
        self.assertTrue(first.endswith("/Media/ME1") and first_auth)
        self.assertEqual((second, second_auth), ("/cdn/note", None))

    def test_only_this_accounts_media_is_asked_for_at_all(self):
        for url in ("https://evil.test/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1", f"{self.api}/2010-04-01/Accounts/AC2/Messages/MM1/Media/ME1", f"{self.api}/2010-04-01/Accounts/AC1/Messages/MM1.json",
                    f"{self.api}/2010-04-01/Accounts/AC1/Messages/../Media/ME1", f"{self.api}.evil.test/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1", "file:///etc/passwd"):
            with self.assertRaises(MessagingError):
                self.wa.download(url)
        self.assertEqual(self.server.state["seen"], [])

    def test_a_redirect_off_twilio_is_refused_and_named(self):
        self.server.state["location"] = "https://evil.test/note"
        with self.assertRaisesRegex(MessagingError, "evil.test"):
            self.wa.download(self.url)
        self.assertEqual(len(self.server.state["seen"]), 1)

    def test_the_real_list_is_twilios_and_https_goes_out_on_a_plain_http_redirect(self):
        real = TwilioWhatsApp("AC1", "tok", {}, self.wa.path, post=lambda f: {})
        self.assertEqual(real._next_hop(real.media_prefix, "http://mms.twiliocdn.com/x?sig=1"), "https://mms.twiliocdn.com/x?sig=1")
        with self.assertRaises(MessagingError):
            real._next_hop(real.media_prefix, "https://mms.twiliocdn.com.evil.test/x")
        self.assertTrue(real.media_prefix.startswith("https://api.twilio.com/2010-04-01/Accounts/AC1/"))

    def test_over_the_limit_is_refused(self):
        self.server.state["audio"] = b"x" * (MAX_VOICE_BYTES + 1)
        with self.assertRaisesRegex(MessagingError, "size limit"):
            self.wa.download(self.url)

    def test_what_isnt_audio_is_refused(self):
        self.server.state["type"] = "text/html"
        with self.assertRaisesRegex(MessagingError, "audio"):
            self.wa.download(self.url)

    def test_a_store_that_only_knows_bytes_still_counts(self):
        self.server.state["type"] = "application/octet-stream"
        self.assertTrue(self.wa.download(self.url))

    def test_media_that_isnt_there_yet_is_asked_for_again_and_then_gives_up(self):
        self.server.state["not_ready"] = 1
        self.assertTrue(self.wa.download(self.url))
        self.assertEqual(self.waits, [1])
        self.server.state["not_ready"] = 9
        with self.assertRaisesRegex(MessagingError, "HTTP 404"):
            self.wa.download(self.url)

    def test_no_error_says_the_token(self):
        self.server.state["location"] = "https://evil.test/note"
        try:
            self.wa.download(self.url)
        except MessagingError as failure:
            self.assertNotIn("tok", str(failure))
            self.assertNotIn(self.wa.auth, str(failure))

    def test_a_real_sample_converts_to_the_wav_the_ear_takes(self):
        wav = audio.to_wav(self.wa.download(self.url))
        self.assertGreater(screen.wav_seconds(wav), 1)


class Ears:
    """The real conversion with ffmpeg, and an ear that writes down what the test says."""
    seconds = None

    def __init__(self, words="Le di 90 ml de mamadera a las 3", fail=None):
        self.words, self.fail, self.heard = words, fail, []

    def hear(self, data):
        wav = audio.to_wav(data)
        self.seconds = screen.wav_seconds(wav)
        self.heard.append(len(wav))
        if self.fail:
            raise self.fail
        return self.words


@unittest.skipUnless(READY and shutil.which("ffmpeg"), "needs requirements-core.txt and ffmpeg")
class VoiceWebhook(FakeTwilio):
    def setUp(self):
        super().setUp()
        self.events, self.errors = [], []

        async def dispatch(type, payload=None, source="x", at=None, ask=False):
            self.events.append((type, payload, source))
            return 1, None
        core = SimpleNamespace(channel=SimpleNamespace(whatsapp=self.wa), dispatch=dispatch, publish=lambda kind, **f: self.errors.append(f))
        self.ears = Ears()
        patch = mock.patch.object(sources, "voice_ears", lambda: self.ears)
        patch.start()
        self.addCleanup(patch.stop)
        self.client = TestClient(server.echo_app(core))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def post(self, params, token="tok"):
        return self.client.post("/twilio", content=urlencode(params), headers={"Content-Type": "application/x-www-form-urlencoded", "X-Twilio-Signature": signature(token, BASE + "/twilio", params)})

    def note(self, sid="MM1", sender="whatsapp:+59891111111", kind="audio/ogg", url=None, **more):
        return {"From": sender, "MessageSid": sid, "Body": "", "NumMedia": "1", "MediaContentType0": kind, "MediaUrl0": url or self.url, **more}

    def settled(self, count=1):
        for _ in range(200):
            if len(self.events) >= count:
                return self.events
            time.sleep(0.02)
        self.fail(f"nothing after the webhook: {self.events}")

    def test_a_note_becomes_the_parents_words_on_the_same_path_as_telegram(self):
        self.assertEqual(self.post(self.note()).text, "<Response/>")
        self.assertEqual(self.settled(), [("message", {"from": "gonza", "channel": "a voice note", "text": "Le di 90 ml de mamadera a las 3"}, "whatsapp")])
        self.assertTrue(self.wa.window_open("gonza"))
        self.assertEqual(self.errors, [])

    def test_a_bad_signature_and_a_stranger_never_reach_twilio(self):
        self.assertEqual(self.post(self.note(), token="wrong").status_code, 403)
        self.assertEqual(self.post(self.note(sender="whatsapp:+1555")).status_code, 200)
        time.sleep(0.1)
        self.assertEqual((self.server.state["seen"], self.events), ([], []))

    def test_delivered_twice_is_heard_once(self):
        self.post(self.note())
        self.post(self.note())
        self.settled()
        time.sleep(0.1)
        self.assertEqual((len(self.events), len(self.ears.heard)), (1, 1))

    def test_the_webhook_doesnt_wait_for_the_ear(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.ears.hear = lambda data: gate.wait(10) and "tardó"
        self.assertEqual(self.post(self.note()).status_code, 200)
        self.assertEqual(self.events, [])
        gate.set()
        self.assertEqual(self.settled()[0][1]["text"], "tardó")

    def failed_with(self, reason):
        self.post(self.note())
        kind, payload, _ = self.settled()[0]
        self.assertEqual((kind, payload["from"]), ("voice_note_not_heard", "gonza"))
        self.assertIn(reason, payload["why"])
        self.assertIn(reason, self.errors[0]["error"])

    def test_a_redirect_off_twilio_ends_in_not_heard_and_names_the_host(self):
        self.server.state["location"] = "https://evil.test/x"
        self.failed_with("evil.test")

    def test_too_big_ends_in_not_heard(self):
        self.server.state["audio"] = b"x" * (MAX_VOICE_BYTES + 1)
        self.failed_with("size limit")

    def test_bytes_that_arent_audio_end_in_not_heard(self):
        self.server.state["audio"] = b"not audio at all"
        self.ears = EarsThatConvert()
        self.failed_with("ffmpeg")

    def test_a_broken_address_is_not_heard_and_nothing_is_asked(self):
        self.post(self.note(url="https://evil.test/2010-04-01/Accounts/AC1/Messages/MM1/Media/ME1"))
        self.assertEqual(self.settled()[0][0], "voice_note_not_heard")
        self.assertEqual(self.server.state["seen"], [])

    def test_the_ear_failing_or_hearing_nothing_is_not_heard(self):
        self.ears = Ears(fail=voice_client.VoiceError("ear: down"))
        self.post(self.note(sid="MM8"))
        self.assertEqual(self.settled()[0][0], "voice_note_not_heard")
        self.events.clear()
        self.ears = Ears(words="")
        self.post(self.note(sid="MM9"))
        self.assertEqual(self.settled()[0][0], "voice_note_not_heard")

    def test_something_unexpected_still_ends_in_not_heard(self):
        self.ears = Ears(fail=RuntimeError("boom"))
        self.post(self.note())
        self.assertEqual(self.settled()[0][0], "voice_note_not_heard")

    def test_an_ear_that_never_answers_ends_in_not_heard(self):
        gate = threading.Event()
        self.addCleanup(gate.set)
        self.ears.hear = lambda data: gate.wait(10) and "tarde"
        with mock.patch.object(server, "HEAR_NOTE_S", 0.1):
            self.post(self.note())
            self.assertEqual(self.settled()[0][0], "voice_note_not_heard")

    def test_with_voice_off_the_parent_still_hears_back(self):
        self.ears = None
        self.post(self.note())
        kind, payload, _ = self.settled()[0]
        self.assertEqual((kind, payload["why"]), ("voice_note_not_heard", "voice is off"))
        self.assertEqual(self.server.state["seen"], [])

    def test_audio_the_ear_cant_take_isnt_fetched(self):
        self.post(self.note(kind="audio/x-unknown"))
        self.assertEqual(self.settled()[0][0], "voice_note_not_heard")
        self.assertEqual(self.server.state["seen"], [])

    def test_a_photo_with_nothing_written_gets_a_plain_line_and_with_words_they_count(self):
        self.post(self.note(kind="image/jpeg"))
        self.assertEqual(self.settled()[0][:2], ("media_not_read", {"from": "gonza"}))
        self.events.clear()
        self.post(self.note(sid="MM2", kind="image/jpeg", Body="mirá esto"))
        self.assertEqual(self.settled()[0][:2], ("message", {"from": "gonza", "channel": "WhatsApp", "text": "mirá esto"}))
        self.assertEqual(self.server.state["seen"], [])


class EarsThatConvert(Ears):
    """Only the real conversion: what ffmpeg can't read raises what the voice service raises."""
    def hear(self, data):
        try:
            return super().hear(data)
        except audio.AudioError as failure:
            raise voice_client.VoiceError(str(failure)) from None


if __name__ == "__main__":
    unittest.main()
