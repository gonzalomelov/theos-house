"""The Mac's listener for the car seat coach, with a fake link and a fake coach. No model, no camera."""
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

try:
    spec = importlib.util.spec_from_file_location("coach_listener", Path(__file__).resolve().parent.parent / "scripts/coach_listener.py")
    listener = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(listener)
    READY = True
except ImportError:
    READY = False


class FakeLink:
    def __init__(self):
        self.posts = []

    def post(self, path, body):
        self.posts.append((path, body))


class Thing:
    def close(self):
        pass


@unittest.skipUnless(READY, "needs the coach's dependencies")
class ListenerTest(unittest.TestCase):
    def make(self):
        self.link = FakeLink()
        return listener.Listener(self.link, "clip.mp4", make_vision=Thing, make_source=Thing)

    def test_the_sse_lines_become_items(self):
        lines = [b": ping\n", b"event: done\n", b'data: {"kind": "done"}\n', b"data: not json\n", b"\n"]
        self.assertEqual(list(listener.events(lines)), [{"kind": "done"}])

    def test_only_an_accepted_start_starts_it(self):
        one = self.make()
        with mock.patch.object(one, "start") as start:
            one.handle({"kind": "tool_call", "tool": "start_car_seat_coach", "arguments": {"parent": "gonza"}})
            one.handle({"kind": "tool_result", "tool": "start_car_seat_coach", "arguments": {"parent": "x"}, "result": "Refused: parent is gonza or ceci."})
            start.assert_not_called()
            one.handle({"kind": "tool_result", "tool": "start_car_seat_coach", "arguments": {"parent": "ceci", "lang": "en"}, "result": "running"})
            start.assert_called_once_with("ceci", "en")

    def test_each_line_goes_back_to_the_parent_who_asked(self):
        one = self.make()
        one.parent = "ceci"
        one.line({"text": "Paso uno", "step": "lap_guides"})
        self.assertEqual(self.link.posts, [("/coach", {"parent": "ceci", "text": "Paso uno", "step": "lap_guides"})])

    def test_only_the_asking_parents_answers_reach_the_coach(self):
        one = self.make()
        one.parent, one.coach = "gonza", mock.Mock(waiting=None, asking="buckle", answers={})
        one.running = lambda: True
        one.handle({"kind": "event", "type": "message", "payload": {"from": "ceci", "text": "sí"}})
        one.coach.answer.assert_not_called()
        one.handle({"kind": "event", "type": "message", "payload": {"from": "gonza", "text": "cuánto falta para la cena"}})
        one.coach.answer.assert_not_called()
        one.handle({"kind": "event", "type": "message", "payload": {"from": "gonza", "text": "Sí, hizo clic"}})
        one.coach.answer.assert_called_once_with("buckle", "Sí, hizo clic")
        one.coach.asking, one.coach.waiting = None, "lap_guides"
        one.handle({"kind": "event", "type": "message", "payload": {"from": "gonza", "text": "Listo"}})
        one.coach.ready.assert_called_once_with("lap_guides")


if __name__ == "__main__":
    unittest.main()
