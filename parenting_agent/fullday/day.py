"""The day itself: seven steps from the plan page, each run through the real agent and checked.

A step returns what happened, on which channel, how long it took, what ran dry and whether it passed.
Steps that need the generated clips run the skills on them streamed in real time. Steps that need the
brain go through agent messages and observations, the same path a channel or a skill uses.
"""
import datetime
import importlib.util
import json
import queue
import statistics
import threading
import time
from pathlib import Path

from .. import config as skill_config
from .. import confirm as confirm_mod
from ..agent.plugins import Plugin
from ..agent.tools import Tool, schema
from ..bus import Bus
from ..reflex import MediaPipeReflex
from ..rhythm import patterns
from ..rhythm.engine import deliver
from ..skill import Skill, watch
from ..sources import VideoSource
from ..tracking import BabyBuddy, Tracker

ROOT = Path(__file__).resolve().parents[2]
TAG = "full-day-sim"
DRY = {
    "house": "Home Assistant dry run: the token is pending (#9), nothing was switched",
    "channel": "delivery logged only: Telegram, ear and speakers are pending (#3, #8)",
    "ears": "scripted sound event: the house sound detector is pending (#14)",
}
HOUSE_TOOLS = ("announce", "hold_notifications", "dim_lights")


def now():
    return datetime.datetime.now().astimezone()


def stamp(moment=None):
    return (moment or now()).isoformat(timespec="seconds")


def kr222_table():
    """scripts/kr222_table.py holds the clip loop and the scoring the KR uses, reuse them as is."""
    spec = importlib.util.spec_from_file_location("kr222_table", ROOT / "scripts" / "kr222_table.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HouseTools(Plugin):
    """House tools for the day while Home Assistant tools (#9) are not built: the allowed ones run dry and say so,
    replying to a visitor or calling the partner is never allowed alone and waits for the parent's yes."""
    name = "house-dry"

    def __init__(self, agent, config):
        super().__init__(agent, config)
        add = agent.tools.add
        add(Tool("announce", "Say something on the house speaker. When someone is at the door and the parent's hands are on "
                 "the baby, use it right away to say 'one moment please', it is allowed without asking.",
                 schema({"text": {"type": "string"}, "where": {"type": "string"}}, ["text"]), self.dry("announce")))
        add(Tool("hold_notifications", "Hold phone and speaker notifications while the parent's hands are on the baby.",
                 schema({}), self.dry("hold_notifications")))
        add(Tool("dim_lights", "Dim the lights in a room, for night feeds.",
                 schema({"room": {"type": "string"}, "level": {"type": "integer"}}), self.dry("dim_lights")))
        add(Tool("reply_to_visitor", "Answer the person at the door through the door speaker. It always needs the parent's yes: "
                 "when someone is at the door, call it with what you would tell them and the parent is asked before it runs.",
                 schema({"text": {"type": "string"}}, ["text"]), self.dry("reply_to_visitor")))
        add(Tool("call_partner", "Ask the other parent to come and help.",
                 schema({"text": {"type": "string"}}, ["text"]), self.dry("call_partner")))

    def dry(self, action):
        def run(**arguments):
            self.agent.bus.publish("house_dry", action=action, arguments=arguments)
            return f"{action}: {DRY['house']}"
        return run


class TaggedBabyBuddy(BabyBuddy):
    """The skill tracker's Baby Buddy client, tagging what it writes so a run can be wiped."""

    def post(self, path, data):
        return super().post(path, {**data, "tags": [TAG]})


class Day:
    def __init__(self, agent, env, clips_dir, run_dir, video=True, rhythm_log=None, week_log=None):
        self.agent, self.env, self.clips_dir, self.run_dir = agent, env, Path(clips_dir).expanduser(), Path(run_dir)
        self.video, self.rhythm_log, self.week_log = video, rhythm_log, week_log
        self.created = []
        add = agent.baby_log.add

        def recording_add(kind, details, ts=None):
            entry = add(kind, details, ts)
            self.created.append(entry)
            return entry

        agent.baby_log.add = recording_add
        self.dirty_diaper = None
        self.evidence = {"table": None, "voice": [], "reminders": []}

    # agent paths ---------------------------------------------------------------------------------------------------

    def ask(self, channel, text, kind="message", timeout=120):
        """Send a message or an observation and wait for the agent's reply on that channel."""
        replies = queue.Queue()
        self.agent.bus.subscribe(replies.put, ["reply"])
        mark = len(self.agent.bus.history)
        if kind == "message":
            self.agent.bus.publish("message", channel=channel, text=text)
        else:
            self.agent.bus.publish("observation", channel=channel, source="ears", text=text)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = replies.get(timeout=max(0.1, deadline - time.monotonic()))
            if event.get("channel") == channel:
                return event["text"], list(self.agent.bus.history)[mark:]
        raise TimeoutError(text)

    def voice_entry(self, utterance, expected, spoken_at, records):
        for record in records:
            if "id" in record:
                back = self.agent.baby_log.get(record["kind"], record["id"])
                self.evidence["voice"].append({"utterance": utterance, "expected_type": expected, "spoken_at": spoken_at,
                                               "babybuddy": {"id": back["id"], "type": back["kind"], "time": back["ts"],
                                                             "details": back["details"]}})

    def new_records(self, since):
        return self.created[since:]

    # skills on the clips ------------------------------------------------------------------------------------------

    def run_skill(self, skill_file, clips, passes, confirm=True):
        k = kr222_table()
        cfg = skill_config.load(str(ROOT / skill_file))
        cfg = {**cfg, "tracking": {**cfg["tracking"], "on_closed": None if cfg["name"] == "changing-table" else cfg["tracking"]["on_closed"]}}
        run_dir = self.run_dir / cfg["name"]
        run_dir.mkdir(parents=True, exist_ok=True)
        loop, segments, period = k.build_loop(clips, run_dir)
        bus = Bus(run_dir / "events.jsonl")
        detector = confirm_mod.build(cfg["confirm"]) if confirm else confirm_mod.NoConfirm()
        client = None
        if self.env.get("BABYBUDDY_URL") and self.env.get("BABYBUDDY_TOKEN"):
            client = TaggedBabyBuddy(self.env["BABYBUDDY_URL"], self.env["BABYBUDDY_TOKEN"])
        tracker = Tracker(cfg["tracking"], bus, client=client)
        skill = Skill(cfg, bus, MediaPipeReflex(cfg["contact"]), confirm_detector=detector, tracker=tracker)
        source = VideoSource(str(loop), loops=True)
        while source.started is None and not source.stopped:
            time.sleep(0.01)
        heard = {"voice": [], "chime": []}

        def on_alert(event):
            heard[event["kind"]].append({"stream_s": event["stream_s"], "heard_mono": time.monotonic(),
                                         "capture_mono": source.started + event["stream_s"]})

        bus.subscribe(on_alert, ["voice", "chime"])
        skill.arm()
        stop = threading.Event()
        timer = threading.Timer(period * passes + 0.5, stop.set)
        timer.start()
        worker = threading.Thread(target=watch, args=(skill, source), daemon=True)
        worker.start()
        stop.wait()
        source.close()
        worker.join(timeout=10)
        skill.close()
        bus.close()
        moments = k.score(heard["voice"], segments, period, passes)
        chimes = k.score(heard["chime"], segments, period, passes)
        dry = sorted({f"{e['kind']}:{e.get('action', e.get('entry', ''))}" for e in bus.history
                      if e["kind"] in ("house_dry", "ask_parent", "track_dry")})
        tracked = [e for e in bus.history if e["kind"] in ("tracked", "track_error", "track_dry")]
        return {"moments": moments, "chimes": chimes, "segments": segments, "period": period, "dry": dry,
                "tracked": tracked, "confirm": getattr(detector, "name", "none"), "skill": cfg["name"]}

    # the seven steps ----------------------------------------------------------------------------------------------

    def bottle(self):
        start = len(self.created)
        spoken = stamp()
        reply, _ = self.ask("ear", "bottle, 120 ml")
        records = self.new_records(start)
        self.voice_entry("bottle, 120 ml", "feeding", spoken, records)
        feeds = [r for r in records if r["kind"] == "feeding" and float(r["details"].get("amount_ml") or 0) == 120]
        return {"channel": "ear", "input": "voice: bottle, 120 ml", "action": "logged a 120 ml bottle in Baby Buddy",
                "reply": reply, "passed": bool(feeds), "dry": [DRY["channel"]],
                "evidence": {"records": [{"id": r.get("id"), "kind": r["kind"], "ts": r["ts"]} for r in records]}}

    def changing_table(self):
        if not self.video:
            return {"channel": "ear", "input": "head camera", "status": "pending", "dry": [],
                    "action": "skipped, run without --no-video to stream the clips"}
        k = kr222_table()
        clips = k.table_clips(self.clips_dir, json.loads((self.clips_dir / "cues.json").read_text()))
        run = self.run_skill("skills/changing-table.json", clips, passes=1)
        off = [m for m in run["moments"] if m["kind"] == "both_hands_off"]
        one = [m for m in run["moments"] if m["kind"] == "one_hand"]
        latencies = [m["latency_s"] for m in off if m["latency_s"] is not None]
        start = len(self.created)
        spoken = stamp()
        reply, _ = self.ask("ear", "that was a dirty diaper")
        records = self.new_records(start)
        self.voice_entry("that was a dirty diaper", "diaper", spoken, records)
        dirty = [r for r in records if r["kind"] == "diaper" and r["details"].get("solid")]
        self.dirty_diaper = dirty[-1] if dirty else None
        self.evidence["table"] = {"source": "live_stream", "skill": run["skill"], "confirm": run["confirm"], "passes": 1,
                                  "loop_s": round(run["period"], 3), "moments": run["moments"]}
        passed = all(m["spoken"] and m["latency_s"] <= 2.5 for m in off) and not any(m["spoken"] for m in one) and bool(dirty)
        return {"channel": "ear", "input": "head camera: the changing-table clips streamed live, then voice: that was a dirty diaper",
                "action": f"hand spoken {sum(m['spoken'] for m in off)} of {len(off)}, one hand silent "
                          f"{sum(not m['spoken'] for m in one)} of {len(one)}, dirty diaper logged",
                "reply": reply, "passed": passed, "dry": [DRY["house"] + f" ({', '.join(run['dry'])})", DRY["channel"]],
                "evidence": {"max_latency_s": max(latencies, default=None), "confirm": run["confirm"],
                             "diaper": {"id": dirty[-1].get("id"), "ts": dirty[-1]["ts"]} if dirty else None}}

    def doorbell(self):
        text = ("The doorbell just rang at the front door and a courier says there is a package to sign for. The parent "
                "is in the middle of a diaper change at the changing table with both hands on the baby.")
        reply, events = self.ask("ear", text, kind="observation")
        announced = [e for e in events if e["kind"] == "house_dry" and e["action"] == "announce"]
        asked = [e for e in events if e["kind"] == "ask_parent" and e.get("name") in ("reply_to_visitor", "call_partner")]
        replied_alone = [e for e in events if e["kind"] == "house_dry" and e["action"] == "reply_to_visitor"]
        # Asking first: a reply_to_visitor call held for the parent's yes, or a reply that offers to answer and waits for it.
        offered = "?" in reply or "say yes" in reply.lower() or "want me to" in reply.lower()
        passed = bool(announced) and (bool(asked) or offered) and not replied_alone
        return {"channel": "speaker and ear", "input": "sound: doorbell during a change",
                "action": ("announced " + repr(announced[0]["arguments"].get("text", "")) if announced else "no announcement")
                          + ("; asked the parent before replying to the visitor" if asked or offered else "; did not offer to reply"),
                "reply": reply, "passed": passed, "dry": [DRY["ears"], DRY["house"], DRY["channel"]],
                "evidence": {"tools": [e.get("name") for e in events if e["kind"] == "tool"],
                             "ask_parent": [e.get("name") for e in asked]}}

    def nap_note(self, extra_min=40):
        usual = usual_nap_min(self.week_log.entries()) if self.week_log else None
        if not usual:
            return {"channel": "telegram", "input": "a long nap", "status": "fail", "passed": False, "dry": [],
                    "action": "no usual nap length in the simulated week", "reply": ""}
        nap_min, longer = usual + extra_min, extra_min
        end = now()
        record = self.agent.baby_log.add("sleep", {"start": stamp(end - datetime.timedelta(minutes=nap_min)), "end": stamp(end)})
        text = f"Today's nap was {nap_min} min, about {longer} min longer than the usual {usual} min. Just a note."
        refs = [f"sleep/{record.get('id')}"]
        ok = longer >= 0.2 * usual and patterns.no_advice(text)
        event = deliver(self.agent, {"kind": "unusual_day", "text": text, "computed_from": refs, "channel": "telegram"})
        self.evidence["reminders"].append({"text": text, "computed_from": refs, "channel": "telegram",
                                           "delivered_at": event["ts"], "asked": False, "kind": "unusual_day"})
        return {"channel": "telegram", "input": f"nap logged, {nap_min} min", "action": text, "reply": text, "passed": ok,
                "dry": [DRY["channel"]], "evidence": {"usual_nap_min": usual, "sleep_id": record.get("id")}}

    def bath(self):
        if not self.video:
            return {"channel": "ear", "input": "head camera", "status": "pending", "dry": [],
                    "action": "skipped, run without --no-video to stream the clip"}
        # The bath clips folder (docs/bath.md) holds the clip with the scene going on after the hands leave.
        bath_dir = self.clips_dir.parent.parent / "bath" / "clips"
        bath_dir = bath_dir if (bath_dir / "cues.json").exists() else self.clips_dir
        clip = bath_dir / "bath-handoff-01.mp4"
        cues = json.loads((bath_dir / "cues.json").read_text())
        if not clip.exists() or "bath-handoff-01" not in cues:
            return {"channel": "ear", "input": "bath clip", "status": "pending", "passed": False, "dry": [],
                    "action": "no generated bath clip, bath skill pending #10"}
        start = len(self.created)
        run = self.run_skill("skills/bath.json", [("bath-handoff-01", clip, "both_hands_off", cues["bath-handoff-01"])],
                             passes=1, confirm=False)
        voice, chime = run["moments"][0], run["chimes"][0]
        passed = chime["spoken"] and chime["latency_s"] <= 1.0 and voice["spoken"] and voice["latency_s"] <= 2.5
        bath_logged = [e for e in run["tracked"] if e["kind"] == "tracked"]
        return {"channel": "ear and partner phone", "input": "head camera: the bath clip streamed live",
                "action": f"chime {chime['latency_s']} s and hand {voice['latency_s']} s after both hands left, "
                          "calling the partner waits for a yes",
                "reply": "hand", "passed": passed and bool(bath_logged),
                "dry": [DRY["house"] + f" ({', '.join(run['dry'])})", DRY["channel"]],
                "evidence": {"chime_s": chime["latency_s"], "voice_s": voice["latency_s"],
                             "bath_note": [e.get("id") for e in bath_logged], "new_agent_records": len(self.created) - start}}

    def question(self):
        reply, events = self.ask("telegram", "When was the last dirty diaper?")
        expected = self.dirty_diaper["ts"][11:16] if self.dirty_diaper else None
        passed = bool(expected) and expected in reply
        return {"channel": "telegram", "input": "question: When was the last dirty diaper?",
                "action": f"answered from Baby Buddy, expected {expected}", "reply": reply, "passed": passed,
                "dry": [DRY["channel"]], "evidence": {"tools": [e.get("name") for e in events if e["kind"] == "tool"]}}

    def night_feed(self):
        reply_dim, events = self.ask("ear", "Night feed starting in the nursery. The lights are on full and the baby is awake.",
                                     kind="observation")
        dimmed = [e for e in events if e["kind"] == "house_dry" and e["action"] == "dim_lights"]
        start = len(self.created)
        spoken = stamp()
        reply, _ = self.ask("ear", "night feed, 90 ml bottle")
        records = self.new_records(start)
        self.voice_entry("night feed, 90 ml bottle", "feeding", spoken, records)
        fed = [r for r in records if r["kind"] == "feeding" and float(r["details"].get("amount_ml") or 0) == 90]
        current = now()
        tz = current.tzinfo
        entries = self.rhythm_log.entries() if self.rhythm_log else []
        on_duty = patterns.night_summary(entries, current, tz, ["Parent A", "Parent B"])["on_duty"]
        self.agent.baby_log.add("note", {"text": f"Night wake-up handled by {on_duty}"})
        # The day's clock is compressed, so the feed rhythm comes from the simulated week and is put on the day's clock.
        week = self.week_log.entries() if self.week_log else []
        nxt = patterns.next_feed(week, max(patterns.when(e) for e in week)) if week else None
        sim_next = None
        if nxt:
            sim_next = (datetime.datetime(2000, 1, 1, 2, 30) + datetime.timedelta(minutes=nxt["gap_min"])).strftime("%H:%M")
        text = (f"Logged 90 ml. Next feed around {sim_next}, feeds have been about {nxt['gap_min']} min apart. "
                f"Next night wake-up: {on_duty}.") if nxt else ""
        if nxt:
            event = deliver(self.agent, {"kind": "next_feed", "text": text, "computed_from": nxt["computed_from"], "channel": "ear"})
            self.evidence["reminders"].append({"text": text, "computed_from": nxt["computed_from"], "channel": "ear",
                                               "delivered_at": event["ts"], "asked": False, "kind": "next_feed"})
        passed = bool(dimmed) and bool(fed) and bool(nxt)
        return {"channel": "ear", "input": "night feed starts, then voice: night feed, 90 ml bottle",
                "action": ("dimmed the nursery lights; " if dimmed else "did not dim the lights; ") + text,
                "reply": reply_dim + " / " + reply, "passed": passed, "dry": [DRY["house"], DRY["channel"]],
                "evidence": {"on_duty": on_duty, "next_feed_day_clock": sim_next, "gap_min": nxt["gap_min"] if nxt else None}}


STEPS = [
    ("06:10", "bottle", "Bottle by voice"),
    ("06:40", "changing_table", "Changing table"),
    ("09:15", "doorbell", "Doorbell during a change"),
    ("13:00", "nap_note", "Unusual nap note"),
    ("18:30", "bath", "Bath"),
    ("20:00", "question", "Question answered from the log"),
    ("02:30", "night_feed", "Night feed and night shift"),
]


def usual_nap_min(entries):
    """Median length in minutes of daytime naps (start between 08:00 and 20:00) in the simulated week."""
    lengths = []
    for e in entries:
        if e["kind"] == "sleep" and e.get("start") and e.get("end"):
            start = patterns.parse(e["start"]).astimezone()
            if 8 <= start.hour < 20:
                lengths.append((patterns.parse(e["end"]) - patterns.parse(e["start"])).total_seconds() / 60)
    return round(statistics.median(lengths)) if lengths else None


def run(day):
    report = []
    for sim_time, method, title in STEPS:
        started, mono = stamp(), time.monotonic()
        try:
            result = getattr(day, method)()
        except Exception as error:  # a broken step is a failed step, the day goes on
            result = {"channel": "", "input": "", "action": f"error: {error}", "passed": False, "dry": [], "reply": ""}
        status = result.pop("status", None) or ("pass" if result.get("passed") else "fail")
        result.pop("passed", None)
        report.append({"sim_time": sim_time, "step": title, "status": status, "real_ts": started,
                       "seconds": round(time.monotonic() - mono, 1), **result})
        print(f"{sim_time}  {status.upper():7} {title}: {result.get('action', '')}", flush=True)
    return report
