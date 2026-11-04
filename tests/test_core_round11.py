"""Round 11: WhatsApp is what the video shows. A note nobody could hear gets a plain line with no Muse in it, and the rehearsal's rules hold for a parent moved to WhatsApp."""
import datetime
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_langgraph_core import READY, NoScreen, scripted

if READY:
    from langchain_core.messages import AIMessage
    from parenting_agent.channels.twilio_whatsapp import TwilioWhatsApp
    from parenting_agent.core import tools as tools_mod
    from parenting_agent.core.runtime import Core
    from parenting_agent.core.settings import Settings


def real_channel(numbers, folder):
    posts, telegram = [], []
    channel = tools_mod.RealChannel.__new__(tools_mod.RealChannel)
    channel.whatsapp = TwilioWhatsApp("AC1", "tok", numbers, Path(folder) / "w.json", post=lambda fields: posts.append(fields) or {"sid": f"SM{len(posts)}"})
    channel.by_telegram = lambda parent, text, quiet=False: telegram.append((parent, text, quiet))
    for parent in numbers:
        channel.whatsapp.heard(parent)
    return channel, posts, telegram


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class NoWords(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.model = scripted()

    def settings(self, lang="es"):
        import uuid
        return Settings(home="t-" + uuid.uuid4().hex[:10], mock_port=0, data_dir=self.folder.name, lang=lang)

    async def run_event(self, kind, payload, lang="es"):
        async with Core(self.settings(lang), self.model) as core:
            core.screen = NoScreen()
            _, done = await core.dispatch(kind, payload, source="whatsapp", at="2026-12-16T15:00:00-03:00")
            out = await done
            actions = await core.actions(out.get("id"))
            sent = list(core.channel.sent)
            await core.forget()
        return out, sent, actions

    async def test_a_cry_with_nothing_in_the_log_tells_muse_so_and_a_feed_is_named(self):
        for feeds, says in (([], "The log has no feed to name."), (["2026-12-16T01:45:00-03:00"], "at 01:45")):
            model = scripted(AIMessage(content="ok"))
            async with Core(self.settings(), model) as core:
                core.moment = datetime.datetime.fromisoformat("2026-12-16T02:00:00-03:00")
                for at in feeds:
                    core.log.add("feeding", {"amount_ml": 90}, at)
                _, done = await core.dispatch("sound", {"kind": "baby crying"}, at="2026-12-16T02:50:00-03:00")
                await done
                await core.forget()
            self.assertIn(says, str(model.calls[0]))

    async def test_a_note_not_heard_gets_a_plain_line_and_muse_isnt_woken(self):
        out, sent, _ = await self.run_event("voice_note_not_heard", {"from": "gonza", "why": "ffmpeg failed"})
        self.assertEqual((out["status"], [m["to"] for m in sent]), ("done", ["gonza"]))
        self.assertIn("audio", sent[0]["text"])
        self.assertNotIn("ffmpeg", sent[0]["text"])
        self.assertEqual(self.model.calls, [])

    async def test_in_english_too(self):
        _, sent, _ = await self.run_event("voice_note_not_heard", {"from": "ceci"}, "en")
        self.assertEqual([m["to"] for m in sent], ["ceci"])
        self.assertIn("voice note", sent[0]["text"])

    async def test_media_nobody_can_read_gets_its_own_line(self):
        _, sent, actions = await self.run_event("media_not_read", {"from": "gonza"})
        self.assertIn("texto y audios", sent[0]["text"])
        self.assertTrue(any(a["tool"] == "notify" for a in actions))

    async def test_nobody_is_told_when_it_came_from_nobody(self):
        out, sent, _ = await self.run_event("voice_note_not_heard", {})
        self.assertEqual((out["outcome"], sent), ("Nothing done.", []))


@unittest.skipUnless(READY, "needs requirements-core.txt and PA_DB_URL")
class RehearsalOnWhatsApp(unittest.TestCase):
    """What the docs say about WHATSAPP_CECI, with Twilio's post and Telegram both faked. Nothing leaves this process."""
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.channel, self.posts, self.telegram = real_channel({"gonza": "598911", "ceci": "598922"}, folder.name)
        patch = mock.patch.dict(os.environ, {"PA_REHEARSAL": "1"})
        patch.start()
        self.addCleanup(patch.stop)

    def at(self, hour):
        return mock.patch.object(tools_mod, "rehearsal_night", lambda now=None: hour >= 22 or hour < 7)

    def test_by_day_ceci_hears_on_whatsapp_and_it_says_ensayo(self):
        with self.at(15):
            self.channel.send("ceci", "hola")
        self.assertEqual((self.posts[0]["To"], self.posts[0]["Body"]), ("whatsapp:+598922", "Simulated Theo: hola"))
        self.assertEqual(self.telegram, [])

    def test_at_night_nothing_goes_to_ceci_on_any_channel(self):
        with self.at(23):
            note = self.channel.send("ceci", "hola")
        self.assertEqual((self.posts, self.telegram), ([], []))
        self.assertIn("nothing was sent", note)

    def test_at_night_gonza_stays_on_telegram_with_no_sound_and_says_ensayo(self):
        with self.at(2):
            self.channel.send("gonza", "hola")
        self.assertEqual(self.posts, [])
        self.assertEqual(self.telegram, [("gonza", "Simulated Theo: hola", True)])

    def test_by_day_gonza_is_on_whatsapp_and_a_quiet_one_stays_on_telegram(self):
        with self.at(15):
            self.channel.send("gonza", "uno")
            self.channel.send("gonza", "dos", True)
        self.assertEqual([p["Body"] for p in self.posts], ["Simulated Theo: uno"])
        self.assertEqual(self.telegram, [("gonza", "Simulated Theo: dos", True)])

    def test_with_no_number_for_ceci_she_stays_on_telegram(self):
        with tempfile.TemporaryDirectory() as folder, self.at(15):
            channel, posts, telegram = real_channel({"gonza": "598911"}, folder)
            channel.send("ceci", "hola")
        self.assertEqual((posts, telegram), ([], [("ceci", "Simulated Theo: hola", False)]))

    def test_a_whatsapp_failure_at_night_doesnt_reach_ceci_on_telegram(self):
        channel = tools_mod.RealChannel.__new__(tools_mod.RealChannel)
        carried = []
        channel.telegram = type("Telegram", (), {"send": lambda self, chat, text, quiet=False: carried.append(text)})()
        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "1", "TELEGRAM_CECI_CHAT_ID": "2"}), mock.patch.object(tools_mod, "silent_night", lambda now=None: True):
            self.assertIn("kept from Ceci", channel.by_telegram("ceci", "hola"))
            channel.by_telegram("gonza", "hola")
        self.assertEqual(carried, ["hola"])

    def test_a_closed_window_for_ceci_goes_on_telegram_by_day(self):
        self.channel.whatsapp.state["last_heard"]["ceci"] = 0
        with self.at(15):
            note = self.channel.send("ceci", "hola")
        self.assertEqual((self.posts, self.telegram), ([], [("ceci", "Simulated Theo: hola", False)]))
        self.assertIn("window", note)


if __name__ == "__main__":
    unittest.main()
