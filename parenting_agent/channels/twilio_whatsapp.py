"""WhatsApp through Twilio, next to Meta's own Cloud API in whatsapp.py. Chosen by WHATSAPP_BACKEND=twilio, for while Meta's business
review is pending. Plain HTTPS to Twilio's Messages API through the egress proxy, no library.

Free text works for 24 hours after the parent's last message. Outside that window there's no opener to send, so send() says so and
whoever calls this carries the words on Telegram. Twilio answers "queued" and reports what really happened later on the status webhook,
so a send proves nothing until confirmed() or failed(). The auth token only goes in the request header, never in a log or an error.

A voice note arrives as a URL on Twilio's API. The API takes the account's basic auth and answers with a redirect to a short-lived address on
its CDN, which takes none, so the auth stops at the first hop. urllib would carry it along on a redirect, which is why redirects are followed here.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path

from .messaging import MessagingError

SANDBOX = "whatsapp:+14155238886"
WEBHOOK = "https://whatsapp.home.example"
WINDOW_S = 24 * 3600
KEEP_SENT = 200
MAX_BODY = 1600  # Twilio's limit for one message
SANDBOX_GAP_S = 3  # Twilio's sandbox sends one message every 3 seconds
MEDIA_API = "https://api.twilio.com"
# Where Twilio's API sends a media request. Each host also has to be in deploy/egress/filter, or the proxy refuses it.
MEDIA_CDN = ("mms.twiliocdn.com", "media.twiliocdn.com", "s3-external-1.amazonaws.com")
VOICE_TYPES = ("audio/ogg", "audio/opus", "audio/mpeg", "audio/mp4", "audio/aac", "audio/amr", "audio/wav", "audio/x-wav")
MAX_VOICE_BYTES = 2 * 1024 * 1024  # about 8 minutes at the 32 kbit/s a voice note is at most
MAX_REDIRECTS = 3
NOT_READY_WAITS = (1, 2)  # the webhook can come before the media is there: Twilio answers 404 for a moment


def signature(token, url, params):
    """Twilio's X-Twilio-Signature: the full URL, then each parameter's name and value in name order, HMAC-SHA1, base64."""
    signed = url + "".join(name + params[name] for name in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), signed.encode(), hashlib.sha1).digest()).decode()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def takes_voice(content_type):
    return (content_type or "").split(";")[0].strip().lower() in VOICE_TYPES


def stored_as_audio(content_type):
    """What the CDN says it holds. The signed webhook already named the type, and a store may only know bytes. ffmpeg still has to read them as audio."""
    return takes_voice(content_type) or (content_type or "").split(";")[0].strip().lower() in ("application/octet-stream", "binary/octet-stream")


def host_of(url):
    return urllib.parse.urlsplit(url).hostname or "no host"


class TwilioWhatsApp:
    kind = "twilio"
    closed_note = "WhatsApp's 24 hour window is closed until the parent writes. Telegram carried it."

    def __init__(self, sid, token, numbers, path, sender=SANDBOX, webhook=WEBHOOK, post=None, now=time.time, media_api=MEDIA_API, media_cdn=MEDIA_CDN, wait=time.sleep):
        self.numbers = {parent: "".join(c for c in number if c.isdigit()) for parent, number in numbers.items() if number}
        self.parents = {number: parent for parent, number in self.numbers.items()}
        self.url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        self.auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        self.token, self.sender, self.webhook = token, sender, webhook
        self.path, self.post, self.now = Path(path), post or self._post, now
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"last_heard": {}}
        self.sent = OrderedDict()
        self.media_prefix = f"{media_api}/2010-04-01/Accounts/{sid}/Messages/"
        self.media_cdn, self.wait = media_cdn, wait
        self.sent_at = None
        self.opener = urllib.request.build_opener(NoRedirect)

    @classmethod
    def from_env(cls, data_dir):
        sid, token = os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")
        if not sid or not token:
            return None
        return cls(sid, token, {"gonza": os.environ.get("WHATSAPP_GONZA"), "ceci": os.environ.get("WHATSAPP_CECI")},
                   Path(data_dir) / "whatsapp-twilio.json", os.environ.get("TWILIO_WHATSAPP_FROM") or SANDBOX,
                   os.environ.get("TWILIO_WEBHOOK_BASE") or WEBHOOK)

    def _post(self, fields):
        request = urllib.request.Request(self.url, data=urllib.parse.urlencode(fields).encode(), method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {self.auth}"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                code = json.loads(error.read()).get("code")
            except ValueError:
                code = None
            raise MessagingError(f"Twilio HTTP {error.code}, code {code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise MessagingError(f"Twilio failed: {type(error).__name__}") from None

    def _fetch(self, url, auth):
        """(status, headers, up to one byte past the limit). A redirect or a refusal comes back as an answer, not an exception."""
        headers = {"Authorization": f"Basic {self.auth}"} if auth else {}
        try:
            with self.opener.open(urllib.request.Request(url, headers=headers), timeout=20) as response:
                return response.status, response.headers, response.read(MAX_VOICE_BYTES + 1)
        except urllib.error.HTTPError as error:
            return error.code, error.headers, b""
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise MessagingError(f"Twilio media at {host_of(url)} failed: {type(error).__name__}") from None

    def _next_hop(self, url, location):
        """Where a redirect goes, if that's one of Twilio's. Twilio has answered with plain http, and only https goes out."""
        hop = urllib.parse.urlsplit(urllib.parse.urljoin(url, location or ""))
        if hop.hostname not in self.media_cdn:
            raise MessagingError(f"Twilio media went to {hop.hostname or 'nowhere'}, which isn't an allowed host")
        return urllib.parse.urlunsplit(hop._replace(scheme="https")) if self.media_prefix.startswith("https:") else hop.geturl()

    def download(self, url):
        """The bytes of a voice note. Only from this account's media on Twilio's API, only audio, only up to the limit."""
        if not url.startswith(self.media_prefix) or "/Media/" not in url or ".." in url:
            raise MessagingError(f"a voice note's address on {host_of(url)} isn't this account's media on Twilio")
        auth, waits = True, list(NOT_READY_WAITS)
        for _ in range(MAX_REDIRECTS + 1 + len(NOT_READY_WAITS)):
            status, headers, data = self._fetch(url, auth)
            if status in (301, 302, 303, 307, 308):
                url, auth = self._next_hop(url, headers.get("Location")), False
            elif status == 404 and waits:
                self.wait(waits.pop(0))
            elif status != 200:
                raise MessagingError(f"Twilio media at {host_of(url)}: HTTP {status}")
            elif len(data) > MAX_VOICE_BYTES:
                raise MessagingError("the voice note is over the size limit")
            elif not data:
                raise MessagingError("the voice note came empty")
            elif not stored_as_audio(headers.get("Content-Type")):
                raise MessagingError("Twilio's media isn't an audio type this hears")
            else:
                return data
        raise MessagingError("Twilio media: too many redirects")

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = self.path.with_suffix(".tmp")
        fresh.write_text(json.dumps(self.state))
        fresh.replace(self.path)

    def window_open(self, parent):
        return self.now() - self.state["last_heard"].get(parent, 0) < WINDOW_S

    def send(self, parent, text):
        """'text' when Twilio took the words, which isn't delivery yet. 'closed' when the window is, and nothing was sent."""
        if not self.window_open(parent):
            return "closed"
        if self.sender == SANDBOX and self.sent_at is not None and self.now() - self.sent_at < SANDBOX_GAP_S:
            self.wait(SANDBOX_GAP_S - (self.now() - self.sent_at))
        self.sent_at = self.now()
        answer = self.post({"From": self.sender, "To": f"whatsapp:+{self.numbers[parent]}", "Body": text[:MAX_BODY],
                            "StatusCallback": f"{self.webhook}/twilio/status"})
        self.sent[answer.get("sid")] = (parent, text)
        while len(self.sent) > KEEP_SENT:
            self.sent.popitem(last=False)
        return "text"

    def heard(self, parent):
        """The parent wrote, so the window is open."""
        self.state["last_heard"][parent] = self.now()
        self._save()
        return 0

    def confirmed(self, message_id):
        """The parent of a message Twilio says was delivered, or None. The words stay until then, so a later failure can still carry them."""
        entry = self.sent.get(message_id)
        return entry[0] if entry else None

    def failed(self, message_id):
        """(parent, text) of a message Twilio took and then couldn't deliver, or None."""
        return self.sent.pop(message_id, None)
