"""Telegram adapter: long polling over plain HTTPS to the Bot API, no library and no public webhook.

Config block "telegram" in the agent config:
    {"token_env": "TELEGRAM_BOT_TOKEN", "allowed_chat_ids_env": "TELEGRAM_CHAT_ID", "allowed_chat_ids": [],
     "poll_timeout_s": 25, "prefix": ""}
The token is read from the env file and only ever used in the request URL, never logged. Text messages
and voice notes: a voice note is downloaded with getFile and heard by the agent's ear (parenting_agent/voice).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .messaging import Incoming, MessagingChannel, Messenger, MessagingError

API = "https://api.telegram.org"


class TelegramMessenger(Messenger):
    name = "telegram"

    def __init__(self, token, api=API):
        if not token:
            raise MessagingError("no Telegram bot token in the environment")
        self._base = f"{api}/bot{token}/"

    def _call(self, method, params, timeout):
        request = urllib.request.Request(self._base + method, data=json.dumps(params).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise MessagingError(f"Telegram {method} HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise MessagingError(f"Telegram {method} failed: {type(error).__name__}") from None
        if not body.get("ok"):
            raise MessagingError(f"Telegram {method}: {body.get('description', 'not ok')}")
        return body["result"]

    def poll(self, offset, timeout):
        updates = self._call("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
                             timeout=timeout + 10)
        out = []
        for update in updates:
            message = update.get("message") or {}
            sender = message.get("from") or {}
            chat = message.get("chat") or {}
            out.append(Incoming(update["update_id"], str(chat.get("id", "")),
                                message.get("text") or "", sender.get("username") or sender.get("first_name") or "",
                                str(sender.get("id", "")), chat.get("type") or "", sender.get("language_code") or "",
                                (message.get("voice") or message.get("audio") or {}).get("file_id") or ""))
        return out

    def download(self, file_id, limit=20 * 1024 * 1024):
        """The bytes of a file the family sent, such as a voice note. Bot API files are at most 20 MB."""
        path = self._call("getFile", {"file_id": file_id}, timeout=15).get("file_path")
        if not path:
            raise MessagingError("Telegram getFile: no file path")
        try:
            with urllib.request.urlopen(self._base.replace("/bot", "/file/bot", 1) + path, timeout=30) as response:
                data = response.read(limit + 1)
        except urllib.error.HTTPError as error:
            raise MessagingError(f"Telegram file download HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise MessagingError(f"Telegram file download failed: {type(error).__name__}") from None
        if len(data) > limit:
            raise MessagingError("Telegram file is too large")
        return data

    def send_voice(self, chat_id, ogg):
        """Sends OGG Opus audio as a voice note, multipart/form-data as the Bot API wants for uploads."""
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"voice\"; filename=\"reply.ogg\"\r\n"
                f"Content-Type: audio/ogg\r\n\r\n").encode() + ogg + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(self._base + "sendVoice", data=body, method="POST",
                                         headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                reply = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise MessagingError(f"Telegram sendVoice HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise MessagingError(f"Telegram sendVoice failed: {type(error).__name__}") from None
        if not reply.get("ok"):
            raise MessagingError(f"Telegram sendVoice: {reply.get('description', 'not ok')}")
        return reply["result"]["message_id"]

    def me(self):
        """The bot's own username, from getMe. Never the token."""
        return self._call("getMe", {}, timeout=15).get("username") or ""

    def send(self, chat_id, text, quiet=False):
        fields = {"chat_id": chat_id, "text": text, **({"disable_notification": True} if quiet else {})}
        return self._call("sendMessage", fields, timeout=15)["message_id"]


class Telegram(MessagingChannel):
    name = "telegram"

    def __init__(self, agent, config, messenger=None):
        config.setdefault("telegram", {})
        config["telegram"] = {"token_env": "TELEGRAM_BOT_TOKEN", "allowed_chat_ids_env": "TELEGRAM_CHAT_ID", **config["telegram"]}
        super().__init__(agent, config, messenger)

    def make_messenger(self):
        return TelegramMessenger(os.environ.get(self.cfg["token_env"], ""))
