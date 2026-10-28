"""Telegram adapter: long polling over plain HTTPS to the Bot API, no library and no public webhook.

Config block "telegram" in the agent config:
    {"token_env": "TELEGRAM_BOT_TOKEN", "allowed_chat_ids_env": "TELEGRAM_CHAT_ID", "allowed_chat_ids": [],
     "poll_timeout_s": 25, "prefix": ""}
The token is read from the env file and only ever used in the request URL, never logged. Text messages
for now, voice notes come later.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

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
                                str(sender.get("id", "")), chat.get("type") or "", sender.get("language_code") or ""))
        return out

    def me(self):
        """The bot's own username, from getMe. Never the token."""
        return self._call("getMe", {}, timeout=15).get("username") or ""

    def send(self, chat_id, text):
        return self._call("sendMessage", {"chat_id": chat_id, "text": text}, timeout=15)["message_id"]


class Telegram(MessagingChannel):
    name = "telegram"

    def __init__(self, agent, config, messenger=None):
        config.setdefault("telegram", {})
        config["telegram"] = {"token_env": "TELEGRAM_BOT_TOKEN", "allowed_chat_ids_env": "TELEGRAM_CHAT_ID", **config["telegram"]}
        super().__init__(agent, config, messenger)

    def make_messenger(self):
        return TelegramMessenger(os.environ.get(self.cfg["token_env"], ""))
