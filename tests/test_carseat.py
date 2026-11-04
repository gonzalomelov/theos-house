import datetime
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from parenting_agent.bus import Bus
from parenting_agent.carseat import checks, manual, outgrow
from parenting_agent.carseat.coach import Coach, is_ready, load_profiles, plan, step_ids
from parenting_agent.sources import Latest

ROOT = Path(__file__).resolve().parent.parent
MANUAL_PDF = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic/carseat/manuals/i-snug-2.pdf"
SKILL = json.loads((ROOT / "skills/car-seat.json").read_text())
SEAT, CAR = load_profiles(SKILL, ROOT)
PROMPTS = SKILL["prompts"]
# The rendered clips' mode: the whole install filmed from the door, judged at once, guides judged from the door
DOOR = {"closeup": False, "ready_timeout_s": 0.0}
ANSWERS = {"harness_pinch": "no", "car_position": "yes", "buckle": "yes", "belt_routing": "yes", "tension": "yes", "belt_path_movement": "yes"}

# The English belt-install part of the Joie i-Snug 2 manual as pdftotext -raw gives it, short excerpt for the parser.
EXCERPT = """To use this infant carrier module with vehicle belt, your child must meet the following requirements.
Child height 40cm-75cm/ Child weight ≤13kg (Child age ≤12months).
! Position 1- Position for car, hand or stroller transportation.
Detaching Canopy and Seat Pad
see images 24 - 29
Installation without base
! DO NOT install this infant carrier module on vehicle seats with Lap
Belts. 30
1. Place the infant carrier module onto the vehicle seat where you wish
to put it. Pull the vehicle safety belt out and lock it into the vehicle
buckle, sliding the vehicle lap belt into the side guides of the infant
carrier module. 32
2. Slide diagonal belt into the rear guide. 33
3. Pull the vehicle shoulder belt to fasten the infant carrier module
tightly and securely. 34
4. Level line on infant carrier module must be level to the ground when
the infant carrier module is installed. 35
! Tension the vehicle safety belt as much as possible, checking that it
is not loose or twisted.
see images 30 - 37
11
Your infant carrier module is designed to attach to certain Joie stroller models.
"""


class SeatManual(unittest.TestCase):
    def test_excerpt_gives_the_belt_steps_limits_and_handle_position(self):
        p = manual.profile_from_text(EXCERPT, "Joie i-Snug 2")
        self.assertEqual(len(p["steps"]), 4)
        self.assertTrue(p["steps"][0].startswith("Place the infant carrier module"))
        self.assertTrue(p["steps"][0].endswith("side guides of the infant carrier module."))
        self.assertEqual(p["steps"][1], "Slide diagonal belt into the rear guide.")
        self.assertIn("level to the ground", p["level_indicator"])
        self.assertEqual(p["limits"], {"height_cm": [40, 75], "max_weight_kg": 13.0, "max_age_months": 12})
        self.assertEqual(p["handle_car_position"], 1)
        self.assertIn("Tension the vehicle safety belt as much as possible, checking that it is not loose or twisted.", p["warnings"])
        self.assertFalse(any("stroller" in s.lower() for s in p["steps"] + p["warnings"]))

    def test_committed_profile_has_what_the_coach_needs(self):
        self.assertEqual(SEAT["seat"], "Joie i-Snug 2")
        self.assertTrue(SEAT["manual"]["url"].startswith("https://dl.joiebaby.com/"))
        self.assertEqual(len(SEAT["manual"]["sha256"]), 64)
        self.assertEqual(len(SEAT["steps"]), 4)

    @unittest.skipUnless(MANUAL_PDF.is_file(), "the maker's manual is not downloaded on this machine")
    def test_real_manual_reproduces_the_committed_profile(self):
        p = manual.profile_from_text(manual.pdf_text(MANUAL_PDF), SEAT["seat"], SEAT["manual"]["url"], SEAT["manual"]["sha256"])
        self.assertEqual(p, SEAT)


def rect(shape, x0, y0, x1, y1):
    m = np.zeros(shape, bool)
    m[y0:y1, x0:x1] = True
    return m


def scene(belt_through=True, twist=False, level_deg=0.0, handle_upright=True, guides=True, seat=True):
    """Masks for a simple view: near guide low, far guide high on the same column, rear guide to the left."""
    shape = (400, 600)
    near, far, rear = rect(shape, 290, 300, 320, 330), rect(shape, 290, 100, 320, 130), rect(shape, 100, 80, 130, 110)
    belt = np.zeros(shape, bool)
    if belt_through:
        belt |= rect(shape, 295, 60, 315, 380)
        if twist:
            belt[200:215, 295:315] = False
            belt[200:215, 303:307] = True
    else:
        belt |= rect(shape, 400, 60, 420, 380)
    belt |= rect(shape, 60, 85, 200, 105)  # shoulder belt through the rear guide
    level = np.zeros(shape, bool)
    for x in range(200, 260):
        y = int(350 - (x - 230) * np.tan(np.radians(level_deg)))
        level[y - 2:y + 2, x] = True
    handle = rect(shape, 220, 40, 235, 250) if handle_upright else rect(shape, 150, 240, 360, 255)
    found = {PROMPTS["belt"]: [(0.5, belt)], PROMPTS["level"]: [(0.9, level)], PROMPTS["handle"]: [(0.4, handle)],
             PROMPTS["guide"]: [(0.7, near), (0.7, far), (0.7, rear)] if guides else [],
             PROMPTS["seat"]: [(0.8, rect(shape, 80, 60, 360, 380))] if seat else []}
    return found, shape


def closeup_scene(belt_through=True):
    """One guide filling the view, as with the phone 30 to 50 cm from it: the belt through it, or running beside it."""
    shape = (400, 600)
    guide = rect(shape, 260, 160, 340, 240)
    belt = rect(shape, 0, 180, 600, 220) if belt_through else rect(shape, 0, 330, 600, 370)
    return {PROMPTS["guide"]: [(0.9, guide)], PROMPTS["belt"]: [(0.8, belt)]}, shape


class VisibleChecks(unittest.TestCase):
    def results(self, **kw):
        found, shape = scene(**kw)
        return {k: v["result"] for k, v in checks.analyze(found, PROMPTS, shape).items()}

    def test_a_correct_view_passes_every_check(self):
        self.assertEqual(set(self.results().values()), {"pass"})

    def test_each_mistake_fails_its_own_check(self):
        self.assertEqual(self.results(belt_through=False)["lap_guides"], "fail")
        self.assertEqual(self.results(twist=True)["no_twist"], "fail")
        self.assertEqual(self.results(level_deg=15)["level_line"], "fail")
        self.assertEqual(self.results(handle_upright=False)["handle"], "fail")

    def test_a_level_line_steeper_than_any_install_is_unseen_not_fail(self):
        self.assertEqual(self.results(level_deg=20)["level_line"], "fail")
        self.assertEqual(self.results(level_deg=60)["level_line"], "unseen")

    def test_no_guides_in_view_means_unseen_never_pass(self):
        r = self.results(guides=False)
        for check in ("lap_guides", "shoulder_guide", "no_twist"):
            self.assertEqual(r[check], "unseen")

    def test_the_handle_needs_only_the_car_seat_in_view_not_the_guides(self):
        self.assertEqual(self.results(guides=False)["handle"], "pass")
        self.assertEqual(self.results(guides=False, handle_upright=False)["handle"], "fail")
        self.assertEqual(self.results(guides=False, seat=False)["handle"], "unseen", "a handle with no car seat in view")

    def test_a_guide_up_close_is_judged_and_one_from_the_door_is_not(self):
        found, shape = closeup_scene()
        self.assertEqual(checks.closeup(found, PROMPTS, shape)["result"], "pass")
        found, shape = closeup_scene(belt_through=False)
        self.assertEqual(checks.closeup(found, PROMPTS, shape)["result"], "fail")
        found, shape = scene()  # guides 30 px wide from the door: too small to judge
        self.assertEqual(checks.closeup(found, PROMPTS, shape)["result"], "unseen")
        found, shape = scene(belt_through=False)
        self.assertEqual(checks.closeup(found, PROMPTS, shape)["result"], "unseen", "never a fail from the door")

    def test_nothing_found_is_all_unseen(self):
        r = checks.analyze({}, PROMPTS, (400, 600))
        self.assertEqual(set(v["result"] for v in r.values()), {"unseen"})


class FakeVision:
    def __init__(self, found):
        self.found = found

    def masks(self, frame, prompts):
        return {p: self.found.get(p, []) for p in prompts}, 0.01


class SequenceVision:
    """Each SAM call returns the next view in order, then `then` for every later call."""

    def __init__(self, views, then=None):
        self.views, self.then = list(views), then

    def masks(self, frame, prompts):
        found = self.views.pop(0) if self.views else (self.then if self.then is not None else {})
        return {p: found.get(p, []) for p in prompts}, 0.01


class FrameFeed(Latest):
    def __init__(self, frames=400, step=0.02):
        super().__init__()
        self.started = time.monotonic()
        blank = np.zeros((400, 600, 3), np.uint8)
        threading.Thread(target=self._feed, args=(blank, frames, step), daemon=True).start()

    def _feed(self, blank, frames, step):
        for n in range(frames):
            if self.stopped:
                return
            self.put(blank, n * step)
            time.sleep(step)
        self.stopped = True


def run_coach(found, answers, timeout=1.0):
    bus = Bus()
    cfg = {**SKILL, **DOOR, "step_timeout_s": timeout}
    coach = Coach(cfg, bus, FakeVision(found), FrameFeed(), SEAT, CAR, answer_timeout_s=0.3)
    for check, text in answers.items():
        coach.answer(check, text)
    results = coach.run()
    return bus, results


class CoachRun(unittest.TestCase):
    def test_steps_follow_the_manual_and_the_car(self):
        ids = [s["id"] for s in plan(SKILL, SEAT, CAR)]
        self.assertEqual(ids, ["harness_pinch", "car_position", "lap_guides", "buckle", "shoulder_guide", "belt_routing",
                               "tension", "no_twist", "level_line", "handle", "belt_path_movement"])
        self.assertEqual(ids, step_ids(SKILL))
        steps = {s["id"]: s for s in plan(SKILL, SEAT, CAR)}
        self.assertIn("airbag", steps["car_position"]["say"])
        self.assertTrue(plan(SKILL, SEAT, CAR)[0]["say"].startswith("Coaching the Joie i-Snug 2"))

    def test_correct_view_passes_and_the_summary_never_says_safe(self):
        found, _ = scene()
        bus, results = run_coach(found, ANSWERS)
        self.assertTrue(all(r["result"] == "pass" for r in results.values()))
        spoken = [e["text"] for e in bus.history if e["kind"] == "voice"]
        self.assertTrue(all(" safe " not in f" {t.lower()} " for t in spoken))
        self.assertIn("certified child passenger safety technician", spoken[-1])
        self.assertIn("This is not a verdict on the install.", spoken[-1])

    def test_hand_checks_are_asked_and_logged_and_stay_open_without_an_answer(self):
        found, _ = scene()
        bus, results = run_coach(found, {"car_position": "yes"})
        asked = [e["step"] for e in bus.history if e["kind"] == "voice" and e.get("step") in ("belt_path_movement", "harness_pinch")]
        self.assertIn("belt_path_movement", asked)
        self.assertIn("harness_pinch", asked)
        logged = {e["check"]: e["result"] for e in bus.history if e["kind"] == "carseat_check" and e.get("check_kind") == "hand"}
        self.assertEqual(logged["belt_path_movement"], "open")
        self.assertEqual(logged["harness_pinch"], "open")
        summary = next(e["text"] for e in bus.history if e["kind"] == "carseat_summary")
        self.assertIn("Hand checks still open", summary)

    def test_a_pinchable_harness_is_a_failed_hand_check(self):
        found, _ = scene()
        _, results = run_coach(found, {**ANSWERS, "harness_pinch": "yes"})
        self.assertEqual(results["harness_pinch"]["result"], "fail")

    def test_a_mistake_is_spoken_and_nothing_seen_is_listed_as_not_checked(self):
        found, _ = scene(belt_through=False)
        bus, results = run_coach(found, ANSWERS)
        self.assertEqual(results["lap_guides"]["result"], "fail")
        self.assertTrue(any("The lap belt is not in the near and far side guides." == e["text"] for e in bus.history if e["kind"] == "voice"))
        bus, results = run_coach({}, ANSWERS, timeout=0.3)
        self.assertEqual({results[c]["result"] for c in ("lap_guides", "level_line", "handle")}, {"unseen"})
        summary = next(e["text"] for e in bus.history if e["kind"] == "carseat_summary")
        self.assertIn("Visible checks I could not see", summary)

    def test_the_coach_refuses_to_say_safe(self):
        coach = Coach(SKILL, Bus(), FakeVision({}), FrameFeed(frames=1), SEAT, CAR)
        with self.assertRaises(ValueError):
            coach.say("The seat is safe.")


def start_live(found, order, ready=(), vision=None, **cfg):
    """The live coach (waits for "listo", close-ups for the guides) on some steps, in a thread. `ready` steps had their
    "listo" said before they start."""
    bus = Bus()
    coach = Coach({**SKILL, "order": order, "ready_timeout_s": 30.0, "step_timeout_s": 1.0, "closeup_timeout_s": 0.5, **cfg},
                  bus, vision or FakeVision(found), FrameFeed(frames=5000, step=0.01), SEAT, CAR, answer_timeout_s=0.3,
                  lang="es")
    for step in ready:
        coach.ready(step)
    thread = threading.Thread(target=coach.run, daemon=True)
    thread.start()
    return bus, coach, thread


def voices(bus, step=None):
    return [e for e in bus.history if e["kind"] == "voice" and (step is None or e.get("step") == step)]


def wait_for(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


class LiveFlow(unittest.TestCase):
    """Nov 1, a real install video: every step timed out after 8 s while the parent was still working, the guides were
    never seen from the door, the handle waited on the guides, two steps were missing and the harness came last."""

    def test_a_step_waits_for_listo_and_never_says_a_fail_before_it(self):
        found, _ = scene(handle_upright=False)
        bus, coach, thread = start_live(found, ["handle"])
        self.assertTrue(wait_for(lambda: coach.waiting == "handle"))
        time.sleep(1.5)  # longer than the old fixed window, the parent is still working
        self.assertEqual([e.get("result") for e in voices(bus, "handle")], [None], "only the step itself was said")
        self.assertTrue(any(e["kind"] == "carseat_frame" and e["phase"] == "act" for e in bus.history), "it was watching")
        self.assertEqual(coach.ready(), "ready for handle")
        thread.join(timeout=5)
        self.assertEqual(coach.results["handle"]["result"], "fail")
        self.assertIn("La manija no está hacia arriba. Movela a la posición 1.", [e["text"] for e in voices(bus)])

    def test_a_check_that_passes_on_its_own_moves_on_without_listo(self):
        found, _ = scene()
        bus, coach, thread = start_live(found, ["no_twist", "level_line", "handle"])
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual({k: v["result"] for k, v in coach.results.items()},
                         {"no_twist": "pass", "level_line": "pass", "handle": "pass"})

    def test_without_listo_a_long_fallback_then_judges(self):
        found, _ = scene(handle_upright=False)
        bus, coach, thread = start_live(found, ["handle"], ready_timeout_s=0.4)
        thread.join(timeout=5)
        self.assertEqual(coach.results["handle"]["result"], "fail")
        self.assertEqual(Coach.__init__.__defaults__[-1], "en")
        self.assertEqual(SKILL["ready_timeout_s"], 180.0, "the live fallback is minutes, never a fixed 8 s")

    def test_each_side_guide_is_asked_up_close_and_judged_there(self):
        found, _ = closeup_scene()
        bus, coach, thread = start_live(found, ["lap_guides"], ready=["lap_guides"])
        thread.join(timeout=5)
        texts = [e["text"] for e in voices(bus, "lap_guides")]
        self.assertIn("Veo el cinturón en la guía azul del lado de la puerta.", texts)
        self.assertIn("Veo el cinturón en la guía azul del otro lado.", texts)
        self.assertEqual(coach.results["lap_guides"]["result"], "pass")
        self.assertEqual(set(coach.results["lap_guides"]["views"]), {"near", "far"})

    def test_close_up_asks_when_the_parent_is_done_and_fails_a_guide_the_belt_misses(self):
        found, _ = closeup_scene(belt_through=False)
        bus, coach, thread = start_live(found, ["shoulder_guide"])
        self.assertTrue(wait_for(lambda: coach.waiting == "shoulder_guide"))
        time.sleep(0.3)
        self.assertEqual(len(voices(bus)), 1, "the step only: no fail said while the parent works")
        coach.ready()
        thread.join(timeout=5)
        texts = [e["text"] for e in voices(bus, "shoulder_guide")]
        self.assertIn("Acercá el teléfono a la guía azul de atrás.", texts)
        self.assertIn("El cinturón no está en la guía azul de atrás.", texts)
        self.assertEqual(coach.results["shoulder_guide"]["result"], "fail")

    def test_a_guide_needs_two_close_frames_that_agree(self):
        through, _ = closeup_scene()
        apart, _ = closeup_scene(belt_through=False)
        bus, coach, thread = start_live({}, ["shoulder_guide"], ready=["shoulder_guide"],
                                        vision=SequenceVision([apart, through, through]))
        thread.join(timeout=5)
        self.assertEqual(coach.results["shoulder_guide"]["result"], "pass", "one noisy close frame is not a verdict")
        bus, coach, thread = start_live({}, ["shoulder_guide"], ready=["shoulder_guide"], closeup_timeout_s=0.3,
                                        vision=SequenceVision([apart, through], then={}))
        thread.join(timeout=5)
        self.assertEqual(coach.results["shoulder_guide"]["result"], "unsure")
        self.assertTrue(any(e["text"].startswith("Mis dos chequeos no coinciden") for e in voices(bus)))

    def test_one_close_frame_alone_is_not_a_verdict(self):
        apart, _ = closeup_scene(belt_through=False)
        bus, coach, thread = start_live({}, ["shoulder_guide"], ready=["shoulder_guide"], closeup_timeout_s=0.3,
                                        vision=SequenceVision([apart], then={}))
        thread.join(timeout=5)
        self.assertEqual(coach.results["shoulder_guide"]["result"], "unseen")
        self.assertIn("No pude ver de cerca la guía azul de atrás. Lo dejo como no revisado.",
                      [e["text"] for e in voices(bus, "shoulder_guide")])

    def test_guides_seen_only_from_the_door_stay_unseen(self):
        found, _ = scene(belt_through=False)
        bus, coach, thread = start_live(found, ["lap_guides"], ready=["lap_guides"])
        thread.join(timeout=5)
        self.assertEqual(coach.results["lap_guides"]["result"], "unseen")
        texts = [e["text"] for e in voices(bus, "lap_guides")]
        self.assertIn("No pude ver de cerca la guía azul del lado de la puerta. Lo dejo como no revisado.", texts)
        self.assertFalse([t for t in texts if t.startswith("El cinturón")], "never a fail from a door view")

    def test_harness_first_then_buckle_and_tension_in_the_real_order(self):
        steps = plan(SKILL, SEAT, CAR, "es")
        ids = [s["id"] for s in steps]
        self.assertEqual(ids[0], "harness_pinch")
        self.assertIn("mirando hacia vos", steps[0]["say"])
        self.assertLess(ids.index("lap_guides"), ids.index("buckle"))
        self.assertLess(ids.index("buckle"), ids.index("shoulder_guide"))
        self.assertLess(ids.index("shoulder_guide"), ids.index("tension"))
        self.assertLess(ids.index("tension"), ids.index("no_twist"))
        say = {s["id"]: s["say"] for s in steps}
        self.assertIn("hasta que haga clic", say["buckle"])
        self.assertIn("Tensá primero el cinturón de cadera y después el de hombro", say["tension"])
        for camera in ("lap_guides", "shoulder_guide", "no_twist", "level_line", "handle"):
            self.assertIn("Decime listo", say[camera])

    def test_listo_and_ya_are_ready_words_and_other_words_are_not(self):
        for text in ("Listo", "ya", "¡Ya!", "listo.", "done", "Ya está"):
            self.assertTrue(is_ready(text), text)
        for text in ("sí", "no", "ya comió el bebé hace un rato", "", "espera"):
            self.assertFalse(is_ready(text), text)


class OutgrowWatch(unittest.TestCase):
    def growth(self):
        rows = json.loads((ROOT / "tests/fixtures/simweek-growth.json").read_text())
        pick = lambda kind: [(datetime.date.fromisoformat(r["date"]), r[kind]) for r in rows if r["kind"] == kind]
        return pick("weight"), pick("height")

    def test_simulated_week_is_far_from_the_limits_and_height_comes_first(self):
        weights, heights = self.growth()
        result = outgrow.watch(weights, heights, SEAT["limits"], datetime.date(2026, 10, 27), seat=SEAT["seat"], name="Test Baby")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["first_limit"], "height")
        self.assertEqual(result["height"]["latest"], 54.8)
        self.assertAlmostEqual(result["height"]["per_day"], 0.1333, places=3)
        self.assertGreater(result["height"]["days_left"], 100)
        self.assertNotIn("safe", result["text"].lower().split())

    def test_heads_up_weeks_before_and_reached_at_the_limit(self):
        day = datetime.date(2027, 6, 1)
        heights = [(day - datetime.timedelta(days=14), 71.0), (day, 72.4)]
        result = outgrow.watch([], heights, SEAT["limits"], day, seat=SEAT["seat"])
        self.assertEqual(result["status"], "heads_up")
        self.assertIn("Heads up", result["text"])
        result = outgrow.watch([(day, 10.2)], [], SEAT["limits"], day, seat=SEAT["seat"])
        self.assertEqual(result["status"], "no_data")
        result = outgrow.watch([(day - datetime.timedelta(days=7), 12.9), (day, 13.1)], [], SEAT["limits"], day, seat=SEAT["seat"])
        self.assertEqual(result["status"], "reached")


class PluginTools(unittest.TestCase):
    def test_tools_are_registered(self):
        from parenting_agent.agent import build
        from parenting_agent.agent import config as config_mod
        from parenting_agent.carseat.plugin import CarSeatCoach
        with tempfile.TemporaryDirectory() as tmp:
            config = config_mod.load()
            config.update({"data_dir": str(Path(tmp) / "data"), "env_file": "/nonexistent", "brain": {"provider": "fake"},
                           "plugins": [], "car_seat": {"skill": str(ROOT / "skills/car-seat.json")}})
            agent = build(config)
            cwd = Path.cwd()
            try:
                import os
                os.chdir(ROOT)
                plugin = CarSeatCoach(agent, config, vision=FakeVision({}), source=FrameFeed(frames=1), quiet=True)
            finally:
                os.chdir(cwd)
            for name in ("start_car_seat_coach", "answer_car_seat_check", "car_seat_outgrow"):
                self.assertIn(name, agent.tools.names())
            self.assertEqual(plugin.answer("harness_pinch", "no"), "the car seat coach is not running")
            self.assertIn("Baby Buddy", plugin.outgrow())
            agent.close()


if __name__ == "__main__":
    unittest.main()
