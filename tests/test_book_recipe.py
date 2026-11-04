"""The first-month book's checks and the family recipe tool, offline."""
import asyncio
import json
import os
import unittest
from unittest import mock

try:
    from langchain_core.messages import AIMessage

    from parenting_agent.core import book, tools
    READY = True
except ImportError:
    READY = False

ENTRIES = [{"ts": "2026-12-15T10:00:00-03:00", "kind": "feeding", "details": {"amount_ml": 90}},
           {"ts": "2026-12-15T13:00:00-03:00", "kind": "feeding", "details": {"amount_ml": 80}},
           {"ts": "2026-12-15T13:05:00-03:00", "kind": "diaper", "details": {"wet": True}},
           {"ts": "2026-12-16T03:00:00-03:00", "kind": "feeding", "details": {"amount_ml": 90}}]


class Says:
    def __init__(self, text):
        self.text = text

    async def ainvoke(self, _):
        return AIMessage(content=self.text)


def made(text, **kwargs):
    return asyncio.run(book.write(Says(text), ENTRIES, **kwargs))


@unittest.skipUnless(READY, "needs requirements-core.txt")
class BookTest(unittest.TestCase):
    def test_days_come_from_the_log(self):
        self.assertEqual(book.days_of(ENTRIES)[0], {"day": "2026-12-15", "feeds": 2, "ml": 170, "diapers": 1, "sleeps": 0})

    def test_muses_page_stands_when_its_numbers_are_the_days(self):
        pages = made(json.dumps({"title": "Theo", "pages": [{"day": "2026-12-15", "text": "Two bottles, 170 ml in all, and the house stayed up with him."}]}))["pages"]
        self.assertEqual(pages[0]["by"], "muse")

    def test_a_number_the_log_doesnt_have_is_replaced_by_code(self):
        pages = made(json.dumps({"pages": [{"day": "2026-12-15", "text": "He drank 400 ml."}]}))["pages"]
        self.assertEqual(pages[0], {"day": "2026-12-15", "text": "2 feeds, 170 ml in all, 1 diapers.", "by": "code"})

    def test_a_number_in_words_counts_too(self):
        self.assertEqual(made(json.dumps({"pages": [{"day": "2026-12-15", "text": "Five quiet bottles."}]}))["pages"][0]["by"], "code")
        self.assertEqual(made(json.dumps({"pages": [{"day": "2026-12-15", "text": "Two quiet bottles."}]}))["pages"][0]["by"], "muse")

    def test_health_words_and_surnames_are_replaced(self):
        for text in ("He is healthy.", "He has a fever.", "Todo normal."):
            self.assertEqual(made(json.dumps({"pages": [{"day": "2026-12-15", "text": text}]}))["pages"][0]["by"], "code")

    def test_a_day_muse_skipped_or_a_broken_answer_still_gets_a_page(self):
        pages = made("not json")["pages"]
        self.assertEqual([p["by"] for p in pages], ["code", "code"])

    def test_an_empty_log_makes_no_pages(self):
        self.assertEqual(asyncio.run(book.write(Says("{}"), []))["pages"], [])


@unittest.skipUnless(READY, "needs requirements-core.txt")
class RecipeTest(unittest.TestCase):
    ARGS = {"name": "Puré", "ingredients": ["300 g zapallo"], "steps": [{"text": "Cocinar."}], "cookidoo_country": "uy"}

    def tool(self):
        return tools.recipe_tool()[0]

    def test_only_a_preview_exists_and_mock_touches_no_network(self):
        self.assertEqual([t.name for t in tools.recipe_tool()], ["preview_family_recipe"])
        with mock.patch.dict(os.environ, {"PA_RECIPE": "mock"}), mock.patch.object(tools, "recipe_call") as call:
            out = self.tool().invoke(self.ARGS)
        call.assert_not_called()
        self.assertIn("nothing was sent", out)

    def test_real_mode_calls_preview_and_never_send(self):
        with mock.patch.dict(os.environ, {"PA_RECIPE": "real"}), mock.patch.object(tools, "recipe_call", return_value="ok") as call:
            self.tool().invoke(self.ARGS)
        self.assertEqual(call.call_args[0][0], "preview_recipe")
        self.assertEqual(call.call_args[0][1]["cookidoo_country"], "UY")

    def test_a_recipe_with_no_steps_is_refused(self):
        self.assertIn("Refused", self.tool().invoke({**self.ARGS, "steps": []}))
