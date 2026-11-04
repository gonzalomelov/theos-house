"""WhatsApp through Meta's Cloud API, next to Telegram. Plain HTTPS to the Graph API through the egress proxy, no library.

WhatsApp allows free text only for 24 hours after the parent's last message. Outside that window only an approved template
goes through. So a text outside it sends the template and waits for the reply that opens the window, and whoever calls this
carries the words on Telegram meanwhile, so nothing is lost. Meta can also refuse later, in a delivery status: failed() hands
that text back. Tokens only ever go in the request header, never in a log or an error.
"""
import json
import os
import time
import urllib.error
import urllib.request
from collections import OrderedDict
from pathlib import Path

from .messaging import MessagingError

GRAPH = "https://graph.facebook.com/v23.0"
WINDOW_S = 24 * 3600
OUTSIDE_WINDOW = 131047  # Meta's code for free text sent outside the window
KEEP_QUEUED = 5
KEEP_SENT = 200


class WhatsApp:
    kind = "meta"
    closed_note = "WhatsApp's 24 hour window is closed: it got the template and this text waits for the reply. Telegram carried it now."

    def __init__(self, token, phone_id, numbers, path, template="hello_world", language="en_US", post=None, now=time.time):
        self.numbers = {parent: "".join(c for c in number if c.isdigit()) for parent, number in numbers.items() if number}
        self.parents = {number: parent for parent, number in self.numbers.items()}
        self.url = f"{GRAPH}/{phone_id}/messages"
        self.token, self.template, self.language = token, template, language
        self.path, self.post, self.now = Path(path), post or self._post, now
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {"last_heard": {}, "queued": {}}
        self.sent = OrderedDict()

    @classmethod
    def from_env(cls, data_dir):
        """None until the app on Meta for Developers exists, then Telegram is all there is."""
        token, phone_id = os.environ.get("WHATSAPP_TOKEN"), os.environ.get("WHATSAPP_PHONE_ID")
        if not token or not phone_id:
            return None
        return cls(token, phone_id, {"gonza": os.environ.get("WHATSAPP_GONZA"), "ceci": os.environ.get("WHATSAPP_CECI")},
                   Path(data_dir) / "whatsapp.json", os.environ.get("WHATSAPP_TEMPLATE") or "hello_world",
                   os.environ.get("WHATSAPP_TEMPLATE_LANGUAGE") or "en_US")

    def _post(self, body):
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                code = json.loads(error.read()).get("error", {}).get("code")
            except ValueError:
                code = None
            raise WhatsAppRefused(code, f"WhatsApp HTTP {error.code}, code {code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise MessagingError(f"WhatsApp failed: {type(error).__name__}") from None

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = self.path.with_suffix(".tmp")
        fresh.write_text(json.dumps(self.state))
        fresh.replace(self.path)

    def window_open(self, parent):
        return self.now() - self.state["last_heard"].get(parent, 0) < WINDOW_S

    def _text(self, parent, text):
        answer = self.post({"messaging_product": "whatsapp", "recipient_type": "individual", "to": self.numbers[parent],
                            "type": "text", "text": {"body": text[:4096]}})
        for message in answer.get("messages", []):
            self.sent[message.get("id")] = (parent, text)
        while len(self.sent) > KEEP_SENT:
            self.sent.popitem(last=False)

    def send(self, parent, text):
        """'text' when the words went on WhatsApp, 'template' when only the opener did and the words wait for the reply."""
        if self.window_open(parent):
            try:
                self._text(parent, text)
                return "text"
            except WhatsAppRefused as refused:
                if refused.code != OUTSIDE_WINDOW:
                    raise
        self.post({"messaging_product": "whatsapp", "recipient_type": "individual", "to": self.numbers[parent], "type": "template",
                   "template": {"name": self.template, "language": {"code": self.language}}})
        self.state["queued"][parent] = [*self.state["queued"].get(parent, []), text][-KEEP_QUEUED:]
        self._save()
        return "template"

    def heard(self, parent):
        """The parent wrote, so the window is open. The words that waited for it go now."""
        self.state["last_heard"][parent] = self.now()
        queued = self.state["queued"].pop(parent, [])
        self._save()
        for text in queued:
            self._text(parent, text)
        return len(queued)

    def failed(self, message_id):
        """(parent, text) of a message Meta accepted and then refused, or None."""
        return self.sent.pop(message_id, None)


class WhatsAppRefused(MessagingError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
