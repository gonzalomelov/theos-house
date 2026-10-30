"""The shopping list goes live (Oct 30).

When diapers, wipes or formula run low, or a parent asks, the item goes on the Home Assistant shopping list for real
through the per-action allowlist (shopping_list_add in house.live_actions). The list is read first so nothing lands
twice, there is a cap per day, and removing an item stays a dry run.

Offline: Home Assistant is a recording fake with a shopping list. No network, no house.
"""
import json
import tempfile
import unittest
from pathlib import Path

from parenting_agent import day_engine as de
from parenting_agent import house_live as hl
from parenting_agent.bus import Bus
from parenting_agent.house_plan import dry_reply
from tests.test_day_engine import at, make, run
from tests.test_home_automations import Clock, events, make_agent
from tests.test_house_tools import FakeHA

ROOT = Path(__file__).resolve().parent.parent


class ShopHA(FakeHA):
    """The fake Home Assistant with todo.shopping_list: its state is the open item count, like the real one."""

    def __init__(self, items=(), broken=False):
        super().__init__()
        self.items = [{"summary": s, "status": "needs_action"} for s in items]
        self.broken = broken
        self.reads = 0

    def service(self, service, entity_id, data=None):
        if service == "todo.add_item":
            self.items.append({"summary": data["item"], "status": "needs_action"})
        return super().service(service, entity_id, data)

    def state(self, entity_id):
        if entity_id == hl.SHOPPING:
            return str(sum(1 for i in self.items if i["status"] != "completed"))
        return super().state(entity_id)

    def response(self, service, entity_id, data=None):
        self.reads += 1
        if self.broken:
            raise OSError("connection refused")
        assert service == "todo.get_items" and entity_id == hl.SHOPPING
        return {"service_response": {hl.SHOPPING: {"items": list(self.items)}}}

    def adds(self):
        return [c for c in self.calls if c[0] == "todo.add_item"]


def gate(ha, listed=("shopping_list_add",)):
    bus = Bus()
    return hl.LiveGate(bus, {"live_actions": list(listed)}, ha), bus


class GateTest(unittest.TestCase):
    def test_a_low_supply_is_added_for_real(self):
        ha = ShopHA()
        g, _ = gate(ha)
        event = g.write("supplies", "todo.add_item", hl.SHOPPING, {"item": "Diapers", "description": "About 8 left",
                                                                    "rgb": 1}, "low", "supplies_low")
        self.assertEqual(event["status"], "ran")
        self.assertEqual(ha.adds(), [("todo.add_item", hl.SHOPPING, {"item": "Diapers", "description": "About 8 left"})])

    def test_a_parent_ask_is_added_for_real(self):
        ha = ShopHA()
        g, _ = gate(ha)
        self.assertEqual(g.write("shopping", "todo.add_item", hl.SHOPPING, {"item": "Toallitas"}, "asked",
                                 "parent_asked")["status"], "ran")

    def test_never_twice_on_the_list_in_either_language(self):
        ha = ShopHA(items=["Pañales", "leche de fórmula"])
        g, bus = gate(ha)
        for item in ("Diapers", "pañales", "  PAÑALES ", "Formula"):
            event = g.write("supplies", "todo.add_item", hl.SHOPPING, {"item": item}, "low", "supplies_low")
            self.assertEqual(event["status"], "already_listed", item)
        self.assertEqual(ha.adds(), [])
        self.assertEqual(g.used("shopping_list_add"), 0, "an item already there uses none of the cap")

    def test_a_done_item_does_not_count_as_listed(self):
        ha = ShopHA(items=["Diapers"])
        ha.items[0]["status"] = "completed"
        g, _ = gate(ha)
        self.assertEqual(g.write("supplies", "todo.add_item", hl.SHOPPING, {"item": "Diapers"}, "low",
                                 "supplies_low")["status"], "ran")

    def test_a_cap_per_day(self):
        ha = ShopHA()
        g, bus = gate(ha)
        now = at(0, 10, 0)
        for n in range(6):
            self.assertEqual(g.write("shopping", "todo.add_item", hl.SHOPPING, {"item": f"item {n}"}, "asked",
                                     "parent_asked", now)["status"], "ran")
        self.assertIsNone(g.write("shopping", "todo.add_item", hl.SHOPPING, {"item": "one more"}, "asked",
                                  "parent_asked", now))
        self.assertEqual(len(ha.adds()), 6)
        self.assertEqual([e["status"] for e in bus.history if e["kind"] == "house_live"][-1], "rate_limited")

    def test_removing_stays_dry_and_other_routines_never_add(self):
        ha = ShopHA(items=["Diapers"])
        g, bus = gate(ha)
        self.assertIsNone(g.write("supplies", "todo.remove_item", hl.SHOPPING, {"item": "Diapers"}, "x", "supplies_low"))
        self.assertIsNone(g.write("nap_mode", "todo.add_item", hl.SHOPPING, {"item": "Wipes"}, "x", "supplies_low"))
        self.assertIsNone(g.write("supplies", "todo.add_item", hl.SHOPPING, {"item": "Wipes"}, "x", "a guess"))
        self.assertIsNone(g.write("supplies", "todo.add_item", "todo.family_to_do_list",
                                  {"item": "Wipes"}, "x", "supplies_low"))
        self.assertEqual(ha.calls, [])
        self.assertEqual(ha.items, [{"summary": "Diapers", "status": "needs_action"}])

    def test_unlisted_stays_dry(self):
        ha = ShopHA()
        g, _ = gate(ha, listed=("night_feed_light",))
        self.assertIsNone(g.write("supplies", "todo.add_item", hl.SHOPPING, {"item": "Diapers"}, "low", "supplies_low"))
        self.assertEqual(ha.reads, 0)

    def test_a_list_that_cannot_be_read_gets_nothing(self):
        ha = ShopHA(broken=True)
        g, _ = gate(ha)
        event = g.write("supplies", "todo.add_item", hl.SHOPPING, {"item": "Diapers"}, "low", "supplies_low")
        self.assertEqual(event["status"], "error")
        self.assertEqual(ha.adds(), [])

    def test_the_reply_says_for_real_only_after_a_real_add(self):
        ha = ShopHA()
        g, _ = gate(ha)
        reply = "Listo, agregué pañales a la lista de compras."
        self.assertIn("Dry run", dry_reply(reply, g.claims()))
        g.write("shopping", "todo.add_item", hl.SHOPPING, {"item": "Pañales"}, "asked", "parent_asked")
        self.assertIn("Added to the shopping list for real", dry_reply(reply, g.claims()))


class SuppliesRoutineTest(unittest.TestCase):
    def engine(self, ha, listed=("shopping_list_add",)):
        engine, house, bus, entries = make()
        engine.writer.gate = hl.LiveGate(bus, {"live_actions": list(listed)}, ha)
        return engine, house, bus, entries

    def test_low_supplies_go_on_the_real_list_once(self):
        ha = ShopHA()
        engine, house, bus, entries = self.engine(ha)
        run(engine, house, entries, at(0, 6, 0), at(1, 6, 0))
        self.assertEqual(sorted(c[2]["item"] for c in ha.adds()), ["Diapers", "Formula"])
        texts = [e["text"] for e in bus.history if e["kind"] == "notify" and e["routine"] == "supplies"]
        self.assertEqual(len(texts), 2)
        for text in texts:
            self.assertIn("added to the shopping list for real", text)

    def test_already_on_the_real_list_is_not_added_or_told(self):
        ha = ShopHA(items=["pañales", "Formula"])
        engine, house, bus, entries = self.engine(ha)
        run(engine, house, entries, at(0, 6, 0), at(1, 6, 0))
        self.assertEqual(ha.adds(), [])
        self.assertEqual([e for e in bus.history if e["kind"] == "notify" and e["routine"] == "supplies"], [])

    def test_dry_says_so(self):
        engine, house, bus, entries = make()
        run(engine, house, entries, at(0, 6, 0), at(1, 6, 0))
        texts = [e["text"] for e in bus.history if e["kind"] == "notify" and e["routine"] == "supplies"]
        self.assertTrue(texts)
        for text in texts:
            self.assertIn("dry run", text)
            self.assertNotIn("for real", text)


class ParentAskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.agent, self.config = make_agent(self.tmp.name, extra_allowed=("add_to_shopping_list",))
        self.config["house"] = {"live_actions": ["shopping_list_add"]}
        self.ha = ShopHA(items=["Leche"])
        self.plugin = de.DayEnginePlugin(self.agent, self.config, client=self.ha, log=None, clock=Clock(at(0, 10, 0)))

    def tearDown(self):
        self.agent.close()
        self.tmp.cleanup()

    def ask(self, item):
        return self.agent.tools.items["add_to_shopping_list"].handler(item=item)

    def test_a_parent_ask_adds_once_and_says_for_real(self):
        self.assertEqual(self.ask("pañales"), "pañales added to the shopping list for real.")
        self.assertEqual(self.ask("Diapers"), "Diapers is already on the shopping list, nothing added.")
        self.assertEqual(self.ask("leche"), "leche is already on the shopping list, nothing added.")
        self.assertEqual([c[2]["item"] for c in self.ha.adds()], ["pañales"])
        self.assertEqual(events(self.agent, "house_live", status="ran")[0]["signal"], "parent_asked")

    def test_a_code_never_goes_on_the_list(self):
        self.assertIn("refused", self.ask("PIN 482913"))
        self.assertEqual(self.ha.adds(), [])


class VostroConfigTest(unittest.TestCase):
    def test_the_family_agent_lists_the_shopping_list(self):
        config = json.loads((ROOT / "config" / "agent.vostro.json").read_text())
        self.assertIn("shopping_list_add", config["house"]["live_actions"])
        self.assertIn("add_to_shopping_list", config["allowed_tools"])
        self.assertFalse(config["house"]["live"])


if __name__ == "__main__":
    unittest.main()
