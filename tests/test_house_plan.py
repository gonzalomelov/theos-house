"""Tests for the daily house plan (issue #29) and the white noise in it (issue #32), on the simulated week.

Offline: the simulated-week fixture, a simulated vacuum behind a fake Home Assistant, and recipes saved from one
read-only Cookidoo run (tests/fixtures/fast_recipes.json). The live check is scripts/house_plan_check.py.
"""
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent import house_plan as hp
from parenting_agent import meals
from parenting_agent.agent import build
from parenting_agent.agent import config as config_mod
from parenting_agent.bus import Bus
from parenting_agent.rhythm import patterns
from parenting_agent.rhythm.log import FixtureLog, parse, when
from parenting_agent.white_noise import CRIB_CAP_DB, SimulatedWhiteNoise, WhiteNoisePlan

TZ = datetime.timezone(datetime.timedelta(hours=-3))
ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests/fixtures/simweek.json"
RECIPES = ROOT / "tests/fixtures/fast_recipes.json"
WEEK_START = datetime.datetime(2026, 10, 20, tzinfo=TZ)
STEP = datetime.timedelta(minutes=5)


class SimVacuum:
    """A fake Home Assistant with one simulated vacuum and the shopping list."""

    def __init__(self, clock, run_min=31):
        self.clock, self.run_min = clock, run_min
        self.vacuum, self.until, self.calls, self.items = "docked", None, [], []

    def service(self, service, entity_id, data=None):
        self.calls.append((self.clock(), service, entity_id, data))
        if service in ("vacuum.start", "vacuum.clean_area"):
            self.vacuum, self.until = "cleaning", self.clock() + datetime.timedelta(minutes=self.run_min)
        elif service == "vacuum.pause":
            self.vacuum = "paused"
        elif service == "vacuum.return_to_base":
            self.vacuum = "returning"
        elif service == "todo.add_item":
            self.items.append(data["item"])
        return []

    def state(self, entity_id):
        if entity_id == hp.VACUUM:
            return self.vacuum
        return "home"

    def advance(self):
        if self.vacuum == "cleaning" and self.clock() >= self.until:
            self.vacuum = "docked"
        elif self.vacuum == "returning":
            self.vacuum = "docked"


def note(t, text):
    return {"kind": "note", "time": t.isoformat(), "note": text, "ref": f"note@{t.isoformat()}"}


def week_entries():
    entries = FixtureLog(FIXTURE).entries()
    day = lambda d, h, m=0: WEEK_START + datetime.timedelta(days=d, hours=h, minutes=m)
    entries += [note(day(0, 6, 5), "Stock: diapers 40"), note(day(0, 6, 6), "Stock: wipes 200"),
                note(day(2, 12, 40), "Food mess under the high chair"),
                note(day(3, 15, 0), "Out with the baby, a walk"), note(day(3, 15, 10), "Crumbs on the sofa"),
                note(day(3, 16, 30), "Back home")]
    return entries


def asleep_truth(entries, t):
    return any(e["kind"] == "sleep" and parse(e["start"]) <= t < parse(e["end"]) for e in entries)


def manual_runs(entries):
    """One run a day started by hand in the Xiaomi app 15 min before the first nap after 13:00, outside the agent."""
    naps, seen = [], set()
    for e in sorted((e for e in entries if e["kind"] == "sleep"), key=when):
        local = when(e).astimezone(TZ)
        if local.hour >= 13 and local.hour < 18 and local.date() not in seen and when(e) > WEEK_START + datetime.timedelta(days=1):
            seen.add(local.date())
            naps.append(when(e))
    return naps


def simulate(entries, approve=True, nobody_home_hours=((2, 8, 11),)):
    """Steps the week in 5 min ticks. A parent answers every vacuum question with yes right away, and once a day
    someone starts the vacuum by hand just before a nap."""
    now = [WEEK_START + datetime.timedelta(days=1)]
    clock = lambda: now[0]
    client = SimVacuum(clock)
    bus = Bus()
    white = WhiteNoisePlan(SimulatedWhiteNoise(bus), {"utc_offset_h": -3})
    plan = hp.HousePlan(bus, hp.HouseWriter(bus, client, live=True),
                        {"utc_offset_h": -3, "supplies": {}}, meals.FixtureRecipes(RECIPES), white,
                        read_state=lambda: client.vacuum)
    record = {"starts": [], "naps_while_cleaning": [], "docks": [], "bus": bus, "client": client, "cleaning_asleep": []}
    by_hand = {nap - datetime.timedelta(minutes=15): nap for nap in manual_runs(entries)}
    record["by_hand"] = list(by_hand.values())
    end = WEEK_START + datetime.timedelta(days=7)
    was_asleep = False
    while now[0] < end:
        t = now[0]
        local = t.astimezone(TZ)
        away = any(local.day == WEEK_START.day + d and a <= local.hour < b for d, a, b in nobody_home_hours)
        if any(start <= t < start + STEP for start in by_hand) and client.vacuum == "docked":
            client.vacuum, client.until = "cleaning", t + datetime.timedelta(minutes=client.run_min)
        cleaning_before = client.vacuum == "cleaning"
        asleep = asleep_truth(entries, t)
        before = len(bus.history)
        plan.tick(entries, t, {"nobody_home": away})
        new = list(bus.history)[before:]
        for event in new:
            if event["kind"] == "ask_parent" and approve:
                plan.start_vacuum(hp.as_of(entries, t), t, {}, event["reason"], event.get("area"), approved=True)
        for event in list(bus.history)[before:]:
            if event["kind"] == "vacuum_started":
                record["starts"].append({"at": t, "windows": hp.sleep_windows(entries, t, TZ), "event": event,
                                         "asleep": asleep})
            if event["kind"] == "vacuum_docked":
                record["docks"].append(t)
        if asleep and not was_asleep and cleaning_before:
            record["naps_while_cleaning"].append({"at": t, "docked": client.vacuum in ("returning", "docked")
                                                  and any(c[0] == t and c[1] == "vacuum.return_to_base" for c in client.calls)})
        if asleep and client.vacuum == "cleaning":
            record["cleaning_asleep"].append(t)
        was_asleep = asleep
        client.advance()
        now[0] = t + STEP
    return record


class WeekTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = week_entries()
        cls.week = simulate(cls.entries)
        cls.events = cls.week["bus"].history

    def kinds(self, kind):
        return [e for e in self.events if e["kind"] == kind]

    def test_no_vacuum_start_lands_in_a_predicted_nap_window(self):
        starts = self.week["starts"]
        print(f"vacuum starts in the week: {len(starts)}, alone {sum(s['event']['alone'] for s in starts)}")
        self.assertGreaterEqual(len(starts), 6)
        run = datetime.timedelta(minutes=hp.DEFAULTS["run_min"])
        for s in starts:
            self.assertIsNone(hp.in_window(s["at"], s["at"] + run, s["windows"]), s["at"])
            self.assertFalse(s["asleep"], f"started while he slept at {s['at']}")

    def test_a_nap_that_starts_during_a_run_pauses_and_docks_the_vacuum(self):
        calls = self.week["client"].calls
        naps = self.week["by_hand"]
        self.assertGreaterEqual(len(naps), 5)
        late = []
        for nap in naps:
            docked = [c[0] for c in calls if c[1] == "vacuum.return_to_base" and nap - datetime.timedelta(minutes=20) < c[0] <= nap + STEP]
            pause = [c[0] for c in calls if c[1] == "vacuum.pause" and nap - datetime.timedelta(minutes=20) < c[0] <= nap + STEP]
            if not docked or not pause:
                late.append(nap)
        print(f"runs started by hand just before a nap: {len(naps)}, paused and docked within one 5 min tick of falling asleep: {len(naps) - len(late)}")
        self.assertEqual(late, [])
        self.assertEqual(self.week["cleaning_asleep"], [], "the vacuum kept cleaning while he slept")
        calls = self.week["client"].calls
        for t in self.week["docks"]:
            names = [c[1] for c in calls if c[0] == t]
            self.assertIn("vacuum.return_to_base", names)

    def test_one_daily_run_per_day_at_the_quietest_awake_time(self):
        daily = [s for s in self.week["starts"] if s["event"]["reason"].startswith("daily run")]
        days = [s["at"].astimezone(TZ).date() for s in daily]
        self.assertEqual(len(days), len(set(days)))
        self.assertGreaterEqual(len(days), 5)
        for s in daily:
            self.assertTrue(8 <= s["at"].astimezone(TZ).hour < 19)
        slots = self.kinds("vacuum_slot")
        print("daily run slots:", [(e["day"], e["at"][11:16], e["minutes"], e["moved"]) for e in slots[:12]])
        self.assertTrue(any(e["moved"] for e in slots), "the slot never moved when the rhythm shifted")

    def test_the_vacuum_starts_alone_only_when_nobody_is_home_or_the_baby_is_out(self):
        for s in self.week["starts"]:
            local = s["at"].astimezone(TZ)
            out = local.day == 23 and (15, 0) <= (local.hour, local.minute) < (16, 30)
            away = local.day == 22 and 8 <= local.hour < 11
            if s["event"]["alone"]:
                self.assertTrue(out or away, s["at"])
            else:
                self.assertTrue(s["event"]["approved"])
                self.assertFalse(out or away, s["at"])
        alone = [(s["at"].astimezone(TZ).strftime("%a %H:%M"), s["event"]["reason"][:30]) for s in self.week["starts"] if s["event"]["alone"]]
        print("started alone:", alone)
        self.assertEqual(len(alone), 2)

    def test_a_logged_mess_under_the_high_chair_cleans_the_dining_room(self):
        rooms = [s for s in self.week["starts"] if s["event"]["area"]]
        self.assertTrue(rooms)
        self.assertEqual(rooms[0]["event"]["area"], "dining_room")
        call = [c for c in self.week["client"].calls if c[1] == "vacuum.clean_area"][0]
        self.assertEqual(call[3], {"cleaning_area_id": ["dining_room"]})

    def test_diapers_go_on_the_shopping_list_before_they_run_out(self):
        low = [e for e in self.kinds("supply_low") if e["item"] == "diapers"]
        self.assertEqual(len(low), 1)
        stock_at = WEEK_START + datetime.timedelta(hours=6, minutes=5)
        changes = sorted(when(e) for e in self.entries if e["kind"] == "change" and when(e) >= stock_at)
        ran_out = changes[39]
        added = datetime.datetime.fromisoformat(low[0]["at"])
        print(f"diapers added {added:%a %H:%M} with {low[0]['left']} left, the 40th diaper is used {ran_out:%a %H:%M}")
        self.assertLess(added, ran_out - datetime.timedelta(hours=24))
        self.assertGreater(low[0]["left"], 0)
        self.assertIn("Diapers", self.week["client"].items)
        writes = {c[2] for c in self.week["client"].calls if c[1].startswith("todo.")}
        self.assertEqual(writes, {hp.SHOPPING})

    def test_a_bad_night_adds_a_fast_recipe_draft_and_writes_nothing_to_cookidoo(self):
        drafts = self.kinds("meal_plan_draft")
        print("meal drafts:", [(d["day"], d["night"]["wakeups"], [r["name"] for r in d["recipes"]]) for d in drafts])
        self.assertTrue(drafts)
        for d in drafts:
            self.assertFalse(d["written_to_cookidoo"])
            self.assertTrue(all(r["total_time_seconds"] <= 30 * 60 for r in d["recipes"]))
            self.assertTrue(patterns.no_advice(d["text"]))
        good_days = {"2026-10-22", "2026-10-23"}
        self.assertFalse(good_days & {d["day"] for d in drafts})
        self.assertFalse(any("cookidoo" in c[2] or "thermomix" in c[1] for c in self.week["client"].calls))

    def test_dinner_reminder_lands_in_an_awake_window(self):
        reminders = self.kinds("dinner_reminder")
        self.assertGreaterEqual(len(reminders), 5)
        for r in reminders:
            t = datetime.datetime.fromisoformat(r["at"])
            self.assertFalse(asleep_truth(self.entries, t))
            self.assertTrue(17 <= t.astimezone(TZ).hour < 21)

    def test_white_noise_runs_on_the_rhythm_under_the_cap(self):
        noise = self.kinds("white_noise")
        ons = [e for e in noise if e["action"] == "on"]
        print(f"white noise in the week: {len(ons)} on, max {max(e['crib_db'] for e in noise)} dB at the crib")
        self.assertGreaterEqual(len(ons), 7 * 3)
        self.assertTrue(any("bedtime" in e["reason"] for e in ons))
        self.assertTrue(any(e["reason"].startswith("nap expected") for e in ons))
        self.assertTrue(all(e["crib_db"] <= CRIB_CAP_DB for e in noise))

    def test_every_text_is_free_of_advice(self):
        for e in self.kinds("notify"):
            self.assertTrue(patterns.no_advice(e["text"]), e["text"])


class PolicyTest(unittest.TestCase):
    def setUp(self):
        self.entries = FixtureLog(FIXTURE).entries()
        self.bus = Bus()
        self.now = [datetime.datetime(2026, 10, 24, 12, 0, tzinfo=TZ)]
        self.client = SimVacuum(lambda: self.now[0])
        self.plan = hp.HousePlan(self.bus, hp.HouseWriter(self.bus, self.client, live=True), {"utc_offset_h": -3},
                                 read_state=lambda: self.client.vacuum)

    def awake_moment(self):
        t = datetime.datetime(2026, 10, 24, 9, 0, tzinfo=TZ)
        while not self.plan.run_fits(self.entries, t)[0]:
            t += STEP
        return t

    def test_nap_start_pauses_and_sends_the_vacuum_home(self):
        nap = next(e for e in self.entries if e["kind"] == "sleep" and parse(e["start"]).astimezone(TZ).hour == 13)
        t = parse(nap["start"]) + datetime.timedelta(minutes=1)
        self.client.vacuum = "cleaning"
        self.plan.tick(self.entries, t)
        self.assertEqual([c[1] for c in self.client.calls], ["vacuum.pause", "vacuum.return_to_base"])
        self.assertIn("vacuum_docked", [e["kind"] for e in self.bus.history])

    def test_at_home_with_the_baby_it_asks_and_starts_nothing(self):
        t = self.awake_moment()
        event = self.plan.start_vacuum(self.entries, t, {"nobody_home": False}, "test")
        self.assertEqual(event["kind"], "ask_parent")
        self.assertEqual(self.client.calls, [])
        asks = [e for e in self.bus.history if e["kind"] == "notify"]
        self.assertIn("Reply yes", asks[-1]["text"])

    def test_nobody_home_it_starts_alone(self):
        t = self.awake_moment()
        self.plan.start_vacuum(self.entries, t, {"nobody_home": True}, "test")
        self.assertEqual(self.client.calls[0][1], "vacuum.start")

    def test_a_yes_never_overrides_a_predicted_nap(self):
        nap = next(e for e in self.entries if e["kind"] == "sleep" and parse(e["start"]).astimezone(TZ).hour == 13)
        t = parse(nap["start"]) - datetime.timedelta(minutes=10)
        entries = [e for e in self.entries if when(e) < t]
        event = self.plan.start_vacuum(entries, t, {"nobody_home": True}, "test", approved=True)
        self.assertEqual(event["kind"], "vacuum_hold", event)
        self.assertEqual(self.client.calls, [])

    def test_a_room_clean_without_clean_area_support_asks_for_the_whole_house(self):
        self.plan.s["clean_area"] = False
        event = self.plan.start_vacuum(self.entries, self.awake_moment(), {"nobody_home": True}, "test", area="dining_room")
        self.assertEqual(event["kind"], "ask_parent")
        self.assertEqual(self.client.calls, [])
        self.assertIn("whole house", [e for e in self.bus.history if e["kind"] == "notify"][-1]["text"])

    def test_unknown_presence_is_never_nobody_home(self):
        self.assertFalse(hp.nobody_home({"person.gonza": "not_home", "person.ceci": "unknown"}))
        self.assertTrue(hp.nobody_home({"person.gonza": "not_home", "person.ceci": "work"}))
        self.assertFalse(hp.nobody_home({}))

    def test_baby_out_from_the_log(self):
        t = datetime.datetime(2026, 10, 24, 15, 0, tzinfo=TZ)
        entries = self.entries + [note(t, "Out with the baby to the park")]
        self.assertTrue(hp.baby_out(entries, t + STEP))
        entries.append(note(t + datetime.timedelta(hours=1), "Back home"))
        self.assertFalse(hp.baby_out(entries, t + datetime.timedelta(hours=2)))


class WriterTest(unittest.TestCase):
    def test_only_policy_writes_and_never_the_thermomix(self):
        writer = hp.HouseWriter(Bus())
        for service, entity in [("vacuum.start", "vacuum.other"), ("todo.add_item", "todo.cookidoo_shopping_list"),
                                ("calendar.create_event", "calendar.cookidoo_meal_plan"), ("switch.turn_on", "switch.thermomix"),
                                ("todo.add_item", "todo.pantry"), ("light.turn_on", "light.wiz_824512_192_0_2_10")]:
            with self.assertRaises(PermissionError, msg=f"{service} {entity}"):
                writer.call(service, entity)

    def test_dry_run_publishes_the_exact_request_and_sends_nothing(self):
        bus = Bus()
        event = hp.HouseWriter(bus, client=None, live=True).call("vacuum.pause", hp.VACUUM, None, "nap")
        self.assertEqual(event["kind"], "house_dry")
        self.assertEqual(event["request"], {"method": "POST", "path": "/api/services/vacuum/pause",
                                            "body": {"entity_id": hp.VACUUM}})

    def test_the_cookidoo_bridge_stays_read_only(self):
        source = (ROOT / "scripts/fast_recipes.py").read_text()
        self.assertNotIn("allow_writes", source.replace("# allow_writes stays False", ""))
        for tool in ("add_recipes_to_calendar", "add_custom_recipes_to_calendar", "add_additional_items"):
            self.assertNotIn(tool, source)
        self.assertNotIn("cookidoo", json.dumps(hp.ALLOWED_WRITES).lower())


class VoiceTest(unittest.TestCase):
    def make(self, tmp):
        config = config_mod.load()
        config.update({"data_dir": tmp, "env_file": "/nonexistent", "brain": {"provider": "fake"}, "plugins": [],
                       "rhythm": {"source": "fixture", "fixture": str(FIXTURE)},
                       "house_plan": {"live": True, "recipes": None}})
        agent = build(config)
        clock = lambda: datetime.datetime(2026, 10, 24, 9, 0, tzinfo=TZ)
        client = SimVacuum(clock)
        plugin = hp.HousePlanPlugin(agent, config, client=client, clock=clock)
        return agent, plugin, client

    def test_clean_under_the_high_chair_is_a_dining_room_clean(self):
        self.assertEqual(hp.room_for("clean under the high chair"), "dining_room")
        self.assertEqual(hp.room_for("vacuum the kitchen please"), "kitchen")
        self.assertIsNone(hp.room_for("clean the garage"))
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, client = self.make(tmp)
            plugin.clock = lambda: self.fitting_moment(plugin)
            reply = plugin.start_from_tool("under the high chair")
            self.assertIn("cleaning the dining room", reply)
            self.assertEqual(client.calls[-1][1:], ("vacuum.clean_area", hp.VACUUM, {"cleaning_area_id": ["dining_room"]}))
            agent.close()

    def fitting_moment(self, plugin):
        t = datetime.datetime(2026, 10, 24, 9, 0, tzinfo=TZ)
        while not plugin.plan.run_fits(plugin.log.entries(), t)[0]:
            t += STEP
        return t

    def test_the_brain_cannot_start_the_vacuum_without_a_yes(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, client = self.make(tmp)
            status, _ = agent.tools.run("vacuum_start", {"place": "under the high chair"})
            self.assertEqual(status, "ask_parent")
            self.assertEqual(client.calls, [])
            agent.close()

    def test_house_plan_today_lists_the_vacuum_and_white_noise_under_the_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent, plugin, client = self.make(tmp)
            plugin.clock = lambda: datetime.datetime(2026, 10, 24, 7, 0, tzinfo=TZ)
            items = plugin.today()
            print("house plan for Sat 24 from 07:00:", [(i["at"], i["what"]) for i in items])
            whats = [i["what"] for i in items]
            self.assertIn("vacuum", whats)
            self.assertGreaterEqual(whats.count("white_noise_on"), 4)
            self.assertTrue(any("bedtime" in i["detail"] for i in items))
            self.assertTrue(all(i.get("crib_db", 0) <= CRIB_CAP_DB for i in items))
            agent.close()


class MealsTest(unittest.TestCase):
    def test_bad_night_rule_on_the_week(self):
        entries = FixtureLog(FIXTURE).entries()
        bad = []
        for d in range(21, 27):
            night = meals.last_night(entries, datetime.datetime(2026, 10, d, 7, 30, tzinfo=TZ), TZ)
            if meals.is_bad(night):
                bad.append(night["night_of"])
        print("bad nights:", bad)
        self.assertIn("2026-10-24", bad)
        self.assertLessEqual(len(bad), 3)

    def test_draft_is_a_message_with_fast_recipes(self):
        night = {"night_of": "2026-10-24", "wakeups": 4, "longest_h": 1.9, "computed_from": ["x"]}
        plan = meals.draft(night, meals.FixtureRecipes(RECIPES).fast(30), datetime.date(2026, 10, 25))
        print("Telegram:", plan["text"])
        self.assertIn("nothing was added to Cookidoo", plan["text"])
        self.assertLessEqual(len(plan["recipes"]), 2)


if __name__ == "__main__":
    unittest.main()
