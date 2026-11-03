"""What wakes the agent: Home Assistant's WebSocket state changes, the schedule, and Telegram messages. Each one only
dispatches an event, and Muse decides the rest."""
import asyncio
import datetime
import json
import os

import websockets

from ..channels.messaging import MessagingError
from ..channels.telegram import TelegramMessenger
from ..voice import client as voice_client
from ..voice import screen as voice_screen
from .runtime import TZ
from .settings import SCHEDULE, watch as watch_list
from .tools import PARENTS


def worth_waking(entity, state, last, watch):
    """True when a watched reading moved enough since the last one Muse saw. The first reading only sets the mark."""
    if entity not in watch or state in ("unavailable", "unknown", None):
        return False
    if entity not in last:
        last[entity] = state
        return False
    try:
        moved = abs(float(state) - float(last[entity])) >= watch[entity]
    except ValueError:
        moved = state != last[entity]
    if moved:
        last[entity] = state
    return moved


async def home_assistant(core, watch=None):
    """Stays subscribed to state changes, and reconnects. A rejected token stops it, Home Assistant bans an IP that retries."""
    url = core.settings.ha_url.replace("http", "ws", 1) + "/api/websocket"
    last, watch = {}, watch or watch_list()
    while True:
        try:
            async with websockets.connect(url, max_size=None) as ws:
                await ws.recv()
                await ws.send(json.dumps({"type": "auth", "access_token": core.settings.ha_token}))
                answer = json.loads(await ws.recv())
                if answer.get("type") != "auth_ok":
                    core.publish("error", error="Home Assistant rejected the token, not retrying")
                    return
                await ws.send(json.dumps({"id": 1, "type": "subscribe_events", "event_type": "state_changed"}))
                core.publish("source", name="home_assistant", status="connected")
                async for raw in ws:
                    data = json.loads(raw).get("event", {}).get("data", {})
                    entity, new = data.get("entity_id"), (data.get("new_state") or {}).get("state")
                    if worth_waking(entity, new, last, watch):
                        await core.dispatch("state_changed", {"entity_id": entity, "state": new}, source="home_assistant")
        except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as failure:
            core.publish("source", name="home_assistant", status=f"reconnecting after {type(failure).__name__}")
            await asyncio.sleep(10)


def next_time(now, schedule=SCHEDULE):
    """The next (moment, name) in the daily schedule."""
    def at(day, hhmm):
        return day.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0, microsecond=0)
    moments = [(at(now, t), name) for t, name in schedule] + [(at(now + datetime.timedelta(days=1), t), name) for t, name in schedule]
    return min((m for m in moments if m[0] > now), key=lambda m: m[0])


async def wakes(core, every=20):
    """What Muse asked to be woken for."""
    while True:
        await core.fire_wakes()
        await asyncio.sleep(every)


async def schedule(core, times=SCHEDULE):
    while True:
        moment, name = next_time(datetime.datetime.now(TZ), times)
        await asyncio.sleep((moment - datetime.datetime.now(TZ)).total_seconds())
        await core.dispatch("schedule", {"name": name}, source="schedule")


async def telegram(core):
    """Parents' text messages. Only one process can poll the bot, so this stays off while the old agent runs."""
    bot = TelegramMessenger(os.environ.get("TELEGRAM_BOT_TOKEN"))
    who = {os.environ[env]: parent for parent, env in PARENTS.items() if os.environ.get(env)}
    ears = voice_client.build({"service": os.environ["PA_VOICE_SERVICE"]}) if os.environ.get("PA_VOICE_SERVICE") else None
    offset = None
    while True:
        for item in await asyncio.to_thread(bot.poll, offset, 25):
            offset = item.update_id + 1
            if item.chat_id not in who:
                continue
            if item.text:
                await core.dispatch("message", {"from": who[item.chat_id], "channel": "telegram", "text": item.text}, source="telegram")
            elif item.voice_file_id:
                await core.dispatch(*await heard(bot, ears, item, who[item.chat_id]), source="telegram")


async def heard(bot, ears, item, parent):
    """The event for a voice note. Words the ear can't vouch for are never the parent's words, Muse is told it wasn't heard."""
    try:
        words = await asyncio.to_thread(lambda: ears.hear(bot.download(item.voice_file_id))) if ears else ""
        fine = words and voice_screen.screen(words, getattr(ears, "seconds", None))[0] == "ok"
    except (MessagingError, voice_client.VoiceError):
        fine = False
    if fine:
        return "message", {"from": parent, "channel": "a voice note", "text": words}
    return "voice_note_not_heard", {"from": parent}
