"""The belt's route in the car seat coach: the parent looks and answers. No model, no camera, no real picture."""
import json
import threading
import unittest
from pathlib import Path

try:
    from parenting_agent.bus import Bus
    from parenting_agent.carseat.coach import FORBIDDEN, LINES, Coach, plan
    READY = True
except ImportError:
    READY = False

ROOT = Path(__file__).resolve().parent.parent
SEAT = {"seat": "Seat", "steps": [], "limits": {}, "handle_car_position": 1}
CAR = {"car": "Car", "rules": []}
CFG = {"order": ["belt_routing"], "technician": "See a technician.", "technician_es": "Reservá una revisión con un técnico."}


class NoFrames:
    def latest(self, seq):
        raise AssertionError("the route is never read from a frame")


def run(lang, replies):
    bus = Bus()
    coach = Coach(CFG, bus, None, NoFrames(), SEAT, CAR, answer_timeout_s=0.5, lang=lang)
    thread = threading.Thread(target=coach.run, daemon=True)
    thread.start()
    pending = list(replies)
    while thread.is_alive():
        if coach.waiting and pending and pending[0] == "listo":
            pending.pop(0)
            coach.ready(coach.waiting)
        elif coach.asking and pending and pending[0] != "listo" and coach.asking not in coach.answers:
            coach.answer(coach.asking, pending.pop(0))
        thread.join(0.01)
    return [e["text"] for e in bus.history if e["kind"] == "voice"], coach.results["belt_routing"], bus


@unittest.skipUnless(READY, "needs the coach's dependencies")
class Route(unittest.TestCase):
    def test_wrong_then_fixed_in_spanish(self):
        lines, result, bus = run("es", ["no, lo tengo al revés", "listo", "sí, ahora sí"])
        es = LINES["es"]
        self.assertEqual(lines[1:4], [es["routing_fix"], es["routing_again"], es["routing_ok"]])
        self.assertIn(es["routing"], lines[0])
        self.assertEqual((result["kind"], result["result"]), ("hand", "pass"))
        self.assertIn("Esto no es un veredicto", lines[-1])
        self.assertIn("técnico", lines[-1])
        self.assertEqual(sum(e["kind"] == "carseat_step" for e in bus.history), 2)

    def test_right_the_first_time_in_english(self):
        lines, result, _ = run("en", ["yes"])
        self.assertEqual(lines[1], LINES["en"]["routing_ok"])
        self.assertEqual(result["result"], "pass")
        self.assertIn("not a verdict", lines[-1])

    def test_no_every_time_stays_failed_and_is_not_asked_for_ever(self):
        lines, result, _ = run("es", ["no", "listo", "no", "listo", "no"])
        self.assertEqual(result["result"], "fail")
        self.assertEqual(lines[-2], LINES["es"]["fix"])
        self.assertIn("para corregir", lines[-1])

    def test_no_answer_stays_open(self):
        lines, result, _ = run("es", [])
        self.assertEqual(result["result"], "open")
        self.assertIn("abiertos", lines[-1])

    def test_the_lines_say_look_at_the_manual_and_survive_the_core(self):
        from parenting_agent.core import safety
        for lang, guides in (("es", "guías azules"), ("en", "blue")):
            lines = LINES[lang]
            self.assertIn("manual", lines["routing"])
            self.assertIn(guides, lines["routing"])
            self.assertIn("manual", lines["routing_fix"])
            for key in ("routing", "routing_fix", "routing_again", "routing_ok"):
                said = set(lines[key].lower().replace(",", " ").replace(".", " ").replace("?", " ").split())
                self.assertFalse(said & set(FORBIDDEN), lines[key])
                self.assertEqual(safety.outbound(lines[key], lang), (lines[key], None))
            self.assertIn("belt_routing", [s["id"] for s in plan(CFG, SEAT, CAR, lang)])

    def test_the_longest_summary_reaches_the_parent_with_its_technician_line(self):
        from parenting_agent.carseat.coach import NAMES, SUMMARY
        from parenting_agent.core import server
        for lang, end in (("es", "Montevideo."), ("en", "Montevideo.")):
            coach = Coach(json.loads((ROOT / "skills/car-seat.json").read_text()), Bus(), None, NoFrames(), SEAT, CAR, lang=lang)
            for i, check in enumerate(NAMES[lang]):
                kind, result, _ = SUMMARY[lang][i % len(SUMMARY[lang])]
                coach.results[check] = {"kind": kind, "result": result}
            text = coach.summary()
            self.assertLess(len(text), server.COACH_LINE_MAX)
            self.assertTrue(text.endswith(end))


if __name__ == "__main__":
    unittest.main()
