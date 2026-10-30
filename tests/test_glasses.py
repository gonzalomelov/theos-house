"""The Ray-Ban Meta glasses endpoint: token on every request, private addresses only, frames in memory, and the
agent's replies and the skill's chime and voice reaching the app."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

import cv2
import numpy as np

from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.glasses import GlassesHub, check_host, to_app
from parenting_agent.sources import open_source


def jpeg(shape=(360, 640, 3)):
    ok, data = cv2.imencode(".jpg", np.zeros(shape, np.uint8))
    return data.tobytes()


def call(hub, path, body=None, token=None, kind="image/jpeg"):
    headers = {"Content-Type": kind}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(hub.url + path, data=body, method="POST" if body is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class Events:
    """Reads the app's event stream in a thread, like the iPhone app does."""

    def __init__(self, hub):
        request = urllib.request.Request(hub.url + "events", headers={"Authorization": f"Bearer {hub.token}"})
        self.response = urllib.request.urlopen(request, timeout=10)
        self.seen = []
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            for raw in self.response:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    self.seen.append(json.loads(line[6:]))
        except (OSError, ValueError):
            pass

    def wait(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(predicate(e) for e in self.seen):
                return True
            time.sleep(0.02)
        return False


class Hosts(unittest.TestCase):
    def test_only_loopback_home_network_and_tailscale(self):
        for host in ("127.0.0.1", "192.0.2.10", "192.0.2.10", "192.0.2.10", "100.64.0.1"):
            self.assertEqual(check_host(host), host)
        for host in ("0.0.0.0", "8.8.8.8", "169.254.1.1", "glasses.example.com"):
            with self.assertRaises(ValueError):
                check_host(host)


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.heard = []
        self.hub = GlassesHub(port=0, host="127.0.0.1", token="test-token", on_say=self.heard.append)

    def tearDown(self):
        self.hub.close()

    def test_every_request_needs_the_token(self):
        self.assertEqual(call(self.hub, "frame", jpeg())[0], 401)
        self.assertEqual(call(self.hub, "frame", jpeg(), token="wrong")[0], 401)
        self.assertEqual(call(self.hub, "health", token="wrong")[0], 401)
        self.assertEqual(call(self.hub, "events")[0], 401)
        self.assertIsNone(self.hub.latest(0))
        self.assertEqual(self.hub.rejected, 4)

    def test_a_frame_becomes_the_newest_frame_in_memory(self):
        self.assertEqual(call(self.hub, "frame", jpeg(), token="test-token")[0], 204)
        frame, seq, _ = self.hub.latest(0)
        self.assertEqual((seq, frame.shape), (1, (360, 640, 3)))
        self.assertEqual(call(self.hub, "frame", b"not a jpeg", token="test-token")[0], 400)
        status, body = call(self.hub, "health", token="test-token")
        self.assertEqual((status, json.loads(body)["frames"]), (200, 1))

    def test_too_big_a_frame_is_refused(self):
        try:
            status = call(self.hub, "frame", b"x" * 2_000_001, token="test-token")[0]
        except urllib.error.URLError:
            status = "closed before the body was sent"
        self.assertIn(status, (413, "closed before the body was sent"))
        self.assertIsNone(self.hub.latest(0))

    def test_what_the_parent_says_reaches_the_agent(self):
        body = json.dumps({"text": " changing time "}).encode()
        self.assertEqual(call(self.hub, "say", body, token="test-token", kind="application/json")[0], 204)
        self.assertEqual(self.heard, ["changing time"])
        self.assertEqual(call(self.hub, "say", b"{}", token="test-token", kind="application/json")[0], 400)

    def test_a_skill_view_closes_without_dropping_the_phone(self):
        view = self.hub.view()
        call(self.hub, "frame", jpeg(), token="test-token")
        self.assertIsNotNone(view.latest(0))
        view.close()
        self.assertTrue(view.stopped)
        self.assertIsNone(view.latest(0))
        self.assertFalse(self.hub.stopped)
        self.assertEqual(call(self.hub, "frame", jpeg(), token="test-token")[0], 204)

    def test_events_reach_the_app(self):
        events = Events(self.hub)
        self.assertTrue(events.wait(lambda e: e["kind"] == "hello"))
        self.hub.view().push({"kind": "voice", "text": "hand"})
        self.assertTrue(events.wait(lambda e: e == {"kind": "voice", "text": "hand"}))


class AppEvents(unittest.TestCase):
    def test_bus_events_shown_in_the_app(self):
        self.assertEqual(to_app({"kind": "reply", "text": "Watching."}), {"kind": "reply", "text": "Watching."})
        self.assertEqual(to_app({"kind": "frame", "state": "lifted", "hands": 1, "lift_cm": 2.4, "stream_s": 3.2}),
                         {"kind": "state", "state": "lifted", "hands": 1, "lift_cm": 2.4, "stream_s": 3.2})
        self.assertEqual(to_app({"kind": "skill_armed", "skill": "changing-table"})["kind"], "skill")
        self.assertIsNone(to_app({"kind": "brain_call"}))

    def test_hud_events(self):
        """Every check the HUD card shows comes from a bus event the agent really publishes."""
        self.assertEqual(to_app({"kind": "changing_armed", "via": "brain", "since_words_s": 3.1}),
                         {"kind": "armed", "by": "brain", "seconds": 3.1, "tool": "start_changing_table"})
        self.assertNotIn("tool", to_app({"kind": "changing_armed", "via": "phrase fallback", "since_words_s": 12}))
        self.assertEqual(to_app({"kind": "alarm", "action": "raise", "state": "lifted", "episode": 2, "stream_s": 4.0}),
                         {"kind": "alarm", "state": "lifted", "episode": 2, "stream_s": 4.0})
        self.assertEqual(to_app({"kind": "alarm", "action": "reraise", "episode": 2})["state"], "off")
        self.assertEqual(to_app({"kind": "alarm", "action": "cancel", "episode": 2, "stream_s": 5})["kind"], "clear")
        self.assertEqual(to_app({"kind": "confirm", "verdict": "off", "episode": 2})["verdict"], "off")
        self.assertIsNone(to_app({"kind": "anchor", "based": True, "hands": 1}), "a resting anchor is not shown")
        held = to_app({"kind": "anchor", "based": True, "held": True, "objects": ["diaper"], "stream_s": 1.0})
        self.assertEqual((held["kind"], held["verdict"], held["object"]), ("held", "on", "diaper"))
        self.assertEqual(to_app({"kind": "anchor", "based": False, "held": True, "objects": []})["verdict"], "off")
        logged = to_app({"kind": "change_read_back", "id": 212, "time": "2026-10-30T22:15:00Z", "wet": False, "solid": True})
        self.assertEqual((logged["kind"], logged["contents"], logged["entry"]), ("logged", ["dirty"], 212))
        self.assertRegex(logged["at"], r"^\d\d:\d\d$")
        dog = to_app({"kind": "dog_watch", "verdict": "near", "ratio": 0.13, "dog_score": 0.94, "baby_score": 0.9, "sam_s": 1.2,
                      "stream_s": 40.0})
        self.assertEqual((dog["kind"], dog["verdict"], dog["dog_score"], dog["stream_s"]), ("dog", "near", 0.94, 40.0))

    def test_frame_events_carry_the_frame_arrival_time(self):
        hub = GlassesHub(port=0, host="127.0.0.1", token="t")
        try:
            events = Events(hub)
            self.assertTrue(events.wait(lambda e: e["kind"] == "hello"))
            before = time.time()
            self.assertEqual(call(hub, "frame", jpeg(), token="t")[0], 204)
            _, _, stream_s = hub.latest(0)
            hub.push({"kind": "alarm", "state": "off", "stream_s": round(stream_s, 3)})
            hub.push({"kind": "reply", "text": "no frame"})
            self.assertTrue(events.wait(lambda e: e["kind"] == "reply"))
            alarm = next(e for e in events.seen if e["kind"] == "alarm")
            self.assertGreaterEqual(alarm["frame_unix"], round(before, 3) - 0.001)
            self.assertNotIn("frame_unix", next(e for e in events.seen if e["kind"] == "reply"))
            hub.push({"kind": "alarm", "state": "off", "stream_s": 999.0})
            self.assertTrue(events.wait(lambda e: e["kind"] == "alarm" and e["stream_s"] == 999.0))
            self.assertIsNone(events.seen[-1]["frame_unix"], "an unknown frame has no arrival time")
        finally:
            hub.close()


class GlassesChannel(unittest.TestCase):
    """The whole loop with the offline brain: the parent's words in, frames in, the skill's voice and the agent's reply out."""

    def test_changing_table_on_glasses_frames(self):
        from tests.test_changing_table import FakeReflex
        from parenting_agent.changing_table import ChangingTable
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load(None)
            config.update({"data_dir": tmp, "env_file": f"{tmp}/none.env", "glasses": {"port": 0, "host": "127.0.0.1", "token": "t"},
                           "plugins": ["parenting_agent.glasses:Glasses"],
                           "changing_table": {"source": "glasses", "channel": "glasses"}})
            agent = build(config)
            channel = agent.plugins[0]
            hub = channel.hub
            try:
                agent.start()
                channel.start()
                table = ChangingTable(agent, {**config, "changing_table": {"source": f"glasses:{hub.port}", "channel": "glasses"}},
                                      reflex=FakeReflex(on_frames=3), confirm_detector=None, quiet=True)
                table.skill_cfg["confirm"] = {"provider": "none"}
                table.skill_cfg["tracking"] = {"provider": "none"}
                events = Events(hub)
                body = json.dumps({"text": "hello"}).encode()
                self.assertEqual(call(hub, "say", body, token="t", kind="application/json")[0], 204)
                self.assertTrue(events.wait(lambda e: e["kind"] == "reply", timeout=10))
                self.assertEqual(table.arm(), "watching the changing table")
                for _ in range(12):
                    call(hub, "frame", jpeg(), token="t")
                    time.sleep(0.25)
                self.assertTrue(events.wait(lambda e: e["kind"] == "chime"))
                self.assertTrue(events.wait(lambda e: e["kind"] == "voice" and e["text"] == "hand"))
                voice = next(e for e in events.seen if e["kind"] == "voice")
                self.assertIsNotNone(voice["frame_unix"], "the voice carries the arrival time of its frame")
                self.assertTrue(events.wait(lambda e: e["kind"] == "state" and e["state"] == "off"))
                self.assertTrue(events.wait(lambda e: e["kind"] == "alarm" and e["state"] == "off"))
                self.assertEqual(table.finish(), "diaper change logged")
                self.assertTrue(events.wait(lambda e: e["kind"] == "skill" and "closed" in e["text"]))
                self.assertFalse(hub.stopped)
            finally:
                channel.stop()
                agent.stop()
                agent.close()

    def test_phrases_arm_and_finish_as_a_logged_fallback_when_the_brain_does_not(self):
        from tests.test_changing_table import FakeReflex
        from parenting_agent.changing_table import ChangingTable
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load(None)
            config.update({"data_dir": tmp, "env_file": f"{tmp}/none.env"})
            agent = build(config)
            hub = GlassesHub.shared(0, host="127.0.0.1", token="t")
            try:
                table = ChangingTable(agent, {**config, "changing_table": {"source": f"glasses:{hub.port}", "phrase_fallback_s": 0.3}},
                                      reflex=FakeReflex(on_frames=100), quiet=True)
                table.skill_cfg["confirm"] = {"provider": "none"}
                table.skill_cfg["tracking"] = {"provider": "none"}
                agent.bus.publish("message", channel="glasses", text="Done.")
                time.sleep(0.2)
                self.assertEqual(agent.bus.count("phrase"), 0)
                agent.bus.publish("message", channel="glasses", text="Changing time!")
                deadline = time.monotonic() + 10
                while "watch is on" not in agent.memory.facts()["changing-table"]["value"] and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertIn("watch is on", agent.memory.facts()["changing-table"]["value"])
                agent.bus.publish("message", channel="glasses", text="done")
                deadline = time.monotonic() + 10
                while agent.bus.count("skill_closed") == 0 and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(agent.bus.count("skill_closed"), 1)
                self.assertIn("off", agent.memory.facts()["changing-table"]["value"])
                self.assertEqual([e["action"] for e in agent.bus.history if e["kind"] == "phrase_fallback"], ["arm", "finish"])
                armed = next(e for e in agent.bus.history if e["kind"] == "changing_armed")
                self.assertEqual(armed["via"], "phrase fallback")
                self.assertGreaterEqual(armed["since_words_s"], 0.3)
            finally:
                hub.close()
                agent.close()

    def test_open_source_shares_one_endpoint(self):
        hub = GlassesHub.shared(0, host="127.0.0.1", token="t")
        try:
            first, second = open_source(f"glasses:{hub.port}"), open_source(f"glasses:{hub.port}")
            self.assertIs(first.hub, second.hub)
            self.assertIs(first.hub, hub)
        finally:
            hub.close()


if __name__ == "__main__":
    unittest.main()
