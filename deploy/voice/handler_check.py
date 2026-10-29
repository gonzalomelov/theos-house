"""The full voice-note handler on the Vostro, with a recorded file instead of a Telegram download.

Piped into a running container by hand, never part of an image:

    docker exec -i parenting-agent python - agent "$(base64 -w0 note.ogg)" < deploy/voice/handler_check.py
    docker exec -i pa-families python - families "$(base64 -w0 note.ogg)" < deploy/voice/handler_check.py

agent: the Telegram channel of config/agent.vostro.json, with its real messenger, so the answer goes to the
family's default chat (Gonza) as text and as a voice note. Only the download is replaced by the file. The note
should be a question, so nothing is written to Baby Buddy. Its own data folder in /tmp, so the agent's read
position and memory are not touched.
families: a temporary families service with one test family and a recording messenger. Nothing is sent.
Prints what was heard and the timings, never a secret.
"""
import base64
import json
import sys
import tempfile
import time

sys.path.insert(0, "/app")
MODE, OGG = sys.argv[1], base64.b64decode(sys.argv[2])


def agent_check():
    from parenting_agent.agent import build
    from parenting_agent.agent import config as config_mod
    from parenting_agent.channels.messaging import Incoming
    from parenting_agent.channels.telegram import Telegram
    config = config_mod.load("/app/config/agent.vostro.json")
    config.update(data_dir=tempfile.mkdtemp(dir="/tmp"), plugins=[])
    agent = build(config)
    channel = Telegram(agent, config)
    chat = channel.default_chat
    channel.messenger.poll = lambda offset, timeout: [Incoming(1, chat, "", "check", chat, "private", "es", "recorded")]
    channel.messenger.download = lambda file_id: OGG
    started = time.monotonic()
    channel.poll_once(timeout=0)
    message = next(e for e in agent.bus.history if e["kind"] == "message")
    agent.handle(message)
    if getattr(channel, "spoken_thread", None):
        channel.spoken_thread.join(180)
    events = [e for e in agent.bus.history if e["kind"] in ("voice_heard", "brain_call", "tool", "channel_sent", "channel_error")]
    for e in events:
        print(json.dumps({k: v for k, v in e.items() if k not in ("text", "chat_id")}, ensure_ascii=False))
    sent = [e for e in events if e["kind"] == "channel_sent"]
    print(f"heard: {message['text']!r}")
    print(f"sent {len(sent)} messages ({sum(1 for e in sent if e.get('voice'))} voice) in {time.monotonic() - started:.1f} s")
    agent.close()
    return 0 if len(sent) == 2 and any(e.get("voice") for e in sent) else 1


def families_check():
    import os
    from parenting_agent.channels.messaging import Incoming, Messenger
    from parenting_agent.families import settings as settings_mod
    from parenting_agent.families.bot import FamiliesBot
    from parenting_agent.families.service import Families
    from parenting_agent.voice import client as voice_client

    class Recorder(Messenger):
        sent, voices, at = [], [], {}

        def send(self, chat_id, text):
            self.sent.append(text)
            self.at.setdefault("text", time.monotonic() - started)
            return 1

        def download(self, file_id):
            return OGG

        def send_voice(self, chat_id, ogg):
            self.voices.append(len(ogg))
            self.at.setdefault("voice", time.monotonic() - started)
            return 1

    s = settings_mod.load({**os.environ, "PA_FAMILIES_DATA_DIR": tempfile.mkdtemp(dir="/tmp")})
    app = Families(s)
    code = app.store.create_invite(internal=True)
    for text in (f"/start {code}", "Tomi", "20/10/2026", "no"):
        app.handle(1, 1, text, "private", "es-UY")
    recorder = Recorder()
    bot = FamiliesBot(app, recorder, voice=voice_client.build({"service": s["voice"]}))
    started = time.monotonic()
    bot.poll_once_items([Incoming(9, "1", "", "check", "1", "private", "es-UY", "recorded")])
    if getattr(bot, "spoken_thread", None):
        bot.spoken_thread.join(180)
    print(f"replies: {recorder.sent}")
    print(f"voice replies: {recorder.voices} bytes, {time.monotonic() - started:.1f} s, brain {s['brain_name']}")
    if len(recorder.at) == 2:
        at = recorder.at
        print(f"text at {at['text']:.1f} s, voice at {at['voice']:.1f} s, voice {at['voice'] - at['text']:.1f} s after the text")
    app.close()
    return 0 if recorder.voices and recorder.sent and recorder.sent[0].startswith("«") else 1


sys.exit(agent_check() if MODE == "agent" else families_check())
