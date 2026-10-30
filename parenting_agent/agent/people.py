"""The family's people: who they are, what the night rota calls them, and their chats.

From the "people" block of the agent config:
    "people": {"gonza": {"name": "Gonza", "rota": "Parent A", "chat_ids_env": "TELEGRAM_CHAT_ID", "lang": "es"},
               "ceci": {"name": "Ceci", "rota": "Parent B", "chat_ids_env": "TELEGRAM_CECI_CHAT_ID", "lang": "es"}}
The night rota (rhythm/patterns.py) and the house brain name parents with rota labels ("Parent A"), so the log and the
Muse prompt keep no names. Everything a parent reads says the name instead, in the person's "lang" ("es" or "en"):
a push that carries "texts" ({"en": ..., "es": ...}) reaches each person in their own language (channels/push.py). A person with no name shows as the key
capitalized, a rota label with no person stays the label.
"""
import re


class People:
    def __init__(self, people=None):
        self.spec = {key: dict(value or {}) for key, value in (people or {}).items()}

    def __bool__(self):
        return bool(self.spec)

    def keys(self):
        return list(self.spec)

    def name(self, person):
        spec = self.spec.get(person)
        if spec is None:
            return None
        return spec.get("name") or person.capitalize()

    def lang(self, person):
        """The language a person reads, "es" or "en", from "lang" in the people block. None when it is not set."""
        lang = (self.spec.get(person) or {}).get("lang")
        return lang if lang in ("es", "en") else None

    def family_lang(self):
        """The family's language when every person sets the same one, else None."""
        langs = {self.lang(p) for p in self.spec}
        return langs.pop() if len(langs) == 1 else None

    def label(self, person):
        return (self.spec.get(person) or {}).get("rota")

    def person(self, who):
        """The person key for a key, a name or a rota label, or None."""
        text = str(who or "").strip().lower()
        if not text:
            return None
        for key, spec in self.spec.items():
            if text in (key.lower(), str(spec.get("name") or "").lower(), str(spec.get("rota") or "").lower()):
                return key
        return None

    def rota_label(self, who):
        """The rota label for a key, a name or a label: "handled by Ceci" in the log counts for Parent B."""
        person = self.person(who)
        return (self.label(person) or who) if person else who

    def display(self, who):
        """What a parent reads for a key, a name or a rota label: the name when it is known."""
        person = self.person(who)
        return self.name(person) if person else who

    def named(self, text):
        """The text with every rota label replaced by the person's name: "For Parent A" becomes "For Gonza"."""
        for person, spec in self.spec.items():
            if spec.get("rota"):
                text = re.sub(rf"\b{re.escape(spec['rota'])}\b", self.name(person), text)
        return text
