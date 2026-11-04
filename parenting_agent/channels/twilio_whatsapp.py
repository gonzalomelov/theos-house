"""WhatsApp through Twilio, next to Meta's own Cloud API in whatsapp.py. Chosen by WHATSAPP_BACKEND=twilio, for while Meta's business
review is pending. Plain HTTPS to Twilio's Messages API through the egress proxy, no library.

Free text works for 24 hours after the parent's last message. Outside that window there's no opener to send, so send() says so and
whoever calls this carries the words on Telegram. Twilio answers "queued" and reports what really happened later on the status webhook,
so a send proves nothing until confirmed() or failed(). The auth token only goes in the request header, never in a log or an error.
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


def signature(token, url, params):
    """Twilio's X-Twilio-Signature: the full URL, then each parameter's name and value in name order, HMAC-SHA1, base64."""
    signed = url + "".join(name + params[name] for name in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), signed.encode(), hashlib.sha1).digest()).decode()


class TwilioWhatsApp:
    kind = "twilio"
    closed_note = "WhatsApp's 24 hour window is closed until the parent writes. Telegram carried it."

    def __init__(self, sid, token, numbers, path, sender=SANDBOX, webhook=WEBHOOK, post=None, now=time.time):
        self.numbers = {parent: "".join(c for c in number if c.isdigit()) for parent, number in numbers.items() if number}
        self.parents = {number: parent for parent, number in self.numbers.items()}
        self.url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        self.auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        self.token, self.sender, self.webhook = token, sender, webhook
        self.path, self.post, self.now = Path(path), post or self._post, now
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"last_heard": {}}
        self.sent = OrderedDict()

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
