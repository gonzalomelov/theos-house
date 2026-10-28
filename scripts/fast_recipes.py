"""Fast Thermomix dinners from Cookidoo, read only, through home-agents (issue #29).

Runs inside the home-agents virtual environment, which has the fridge_plan package and the cookidough MCP client:
    ~/Engineering/gonza/home-agents/.venv/bin/python scripts/fast_recipes.py --max-min 30
It reuses fridge_plan's Cookidoo client with its read-only allowlist (writes are refused in code), its recipe parser
and its dinner filter. It prints {"recipes": [...]} as JSON on stdout. It never writes to Cookidoo.
"""
import argparse
import asyncio
import json
import sys

from fridge_plan.candidates import recipe_from_details
from fridge_plan.cookidoo import Cookidoo, CookidooError
from fridge_plan.planner import is_dinner

QUERIES = ("rápido", "rápida", "15 minutos", "salteado", "tortilla")
# Sweet or frozen things that fridge_plan's dinner filter lets through by name in other languages.
NOT_DINNER = ("gelado", "helado", "sorvete", "batido", "smoothie", "mousse", "bolo", "galleta")


async def fast_recipes(max_min, limit, per_query):
    found = {}
    async with Cookidoo() as cookidoo:  # allow_writes stays False: only the read allowlist is reachable
        for query in QUERIES:
            for hit in await cookidoo.call("search_recipes", query=query, limit=per_query) or []:
                seconds = hit.get("total_time_seconds")
                if hit["id"] in found or not seconds or seconds > max_min * 60:
                    continue
                try:
                    recipe = recipe_from_details(await cookidoo.call("get_recipe_details", recipe_id=hit["id"]), False)
                except CookidooError:
                    continue
                if is_dinner(recipe) and not any(w in recipe.name.lower() for w in NOT_DINNER):
                    found[hit["id"]] = {"id": recipe.id, "name": recipe.name, "url": recipe.url,
                                        "total_time_seconds": recipe.total_time_seconds, "rating": hit.get("rating"),
                                        "ingredients": [i.name for i in recipe.ingredients], "query": query}
                if len(found) >= limit:
                    return list(found.values()), cookidoo.calls
    return list(found.values()), cookidoo.calls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-min", type=int, default=30)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--per-query", type=int, default=8)
    args = parser.parse_args()
    recipes, calls = asyncio.run(fast_recipes(args.max_min, args.limit, args.per_query))
    json.dump({"recipes": recipes, "cookidoo_calls": sorted(set(calls)), "max_min": args.max_min}, sys.stdout,
              ensure_ascii=False)


if __name__ == "__main__":
    main()
