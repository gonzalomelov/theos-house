"""Parents get fed (issue #29): after a bad night, a draft of fast Thermomix dinners from Cookidoo, read only.

Cookidoo is reached through home-agents (a private repo, fridge-plan), which talks to the local cookidough
MCP server with a hard-coded allowlist of read tools. scripts/fast_recipes.py runs inside the home-agents virtual
environment, searches Cookidoo and prints the recipes that take at most max_min minutes. Nothing here writes to
Cookidoo: the meal plan suggestion is a draft and a Telegram-ready message. Adding it to the Cookidoo calendar needs a
write tool that home-agents keeps locked, and widening that allowlist is a separate decision for Gonza.

The Thermomix itself is never controlled. Vorwerk allows no remote start, a person presses the dial.
"""
from .rhythm.patterns import hours_words
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

from .rhythm import patterns
from .rhythm.log import ordered, parse, when

ROOT = Path(__file__).resolve().parent.parent
HOME_AGENTS = Path(os.environ.get("HOME_AGENTS_DIR", Path.home() / "Engineering/gonza/home-agents"))
BRIDGE = ROOT / "scripts/fast_recipes.py"
BAD_NIGHT = {"wakeups": 4, "longest_h": 1.5}


def last_night(entries, now, tz):
    """Wake-ups and the longest sleep of the night before now (22:00 to 06:00), from the log only."""
    local = now.astimezone(tz)
    end = local.replace(hour=patterns.NIGHT_END, minute=0, second=0, microsecond=0)
    if local < end:
        end -= datetime.timedelta(days=1)
    start = end - datetime.timedelta(hours=24 - patterns.NIGHT_START + patterns.NIGHT_END)
    seen = ordered(entries, now)
    wakes = [w for w in patterns.night_wakeups(seen, tz) if start <= w["at"] < end]
    sleeps = [e for e in seen if e["kind"] == "sleep" and e.get("end") and start <= when(e) < end and parse(e["end"]) <= now]
    longest = max(((parse(e["end"]) - parse(e["start"])).total_seconds() / 3600 for e in sleeps), default=None)
    return {"night_of": start.date().isoformat(), "wakeups": len(wakes), "longest_h": longest,
            "computed_from": [w["ref"] for w in wakes] + [e["ref"] for e in sleeps]}


def is_bad(night, rule=None):
    rule = {**BAD_NIGHT, **(rule or {})}
    if night["longest_h"] is None and not night["wakeups"]:
        return False
    return night["wakeups"] >= rule["wakeups"] or (night["longest_h"] is not None and night["longest_h"] < rule["longest_h"])


def fast_only(recipes, max_min):
    return sorted((r for r in recipes if r.get("total_time_seconds") and r["total_time_seconds"] <= max_min * 60),
                  key=lambda r: (r["total_time_seconds"], -(r.get("rating") or 0)))


class FixtureRecipes:
    """Recipes from a JSON file in the bridge's shape, for tests and the simulated week."""

    def __init__(self, path):
        self.path = Path(path)

    def fast(self, max_min):
        return fast_only(json.loads(self.path.read_text())["recipes"], max_min)


class HomeAgentsRecipes:
    """Fast recipes from Cookidoo through home-agents' read-only client, run in its own virtual environment."""

    def __init__(self, home_agents=HOME_AGENTS, timeout_s=180):
        self.home_agents, self.timeout_s = Path(home_agents), timeout_s

    def fast(self, max_min):
        python = self.home_agents / ".venv/bin/python"
        if not python.exists():
            raise RuntimeError(f"home-agents is not set up at {self.home_agents} (run uv sync there)")
        out = subprocess.run([str(python), str(BRIDGE), "--max-min", str(max_min)], cwd=self.home_agents,
                             capture_output=True, text=True, timeout=self.timeout_s, check=False)
        if out.returncode != 0:
            raise RuntimeError(f"fast_recipes failed: {out.stderr.strip()[-300:]}")
        return fast_only(json.loads(out.stdout)["recipes"], max_min)


def draft(night, recipes, day, count=2):
    """The meal plan draft for tonight and the Telegram-ready message. Writes nothing anywhere."""
    picks = recipes[:count]
    if not picks:
        return None
    lines = [f"{r['name']}, {round(r['total_time_seconds'] / 60)} min, {r['url']}" for r in picks]
    longest = f", longest sleep {hours_words(night['longest_h'])}" if night["longest_h"] is not None else ""
    text = (f"Rough night: {night['wakeups']} wake-ups{longest}. Fast Thermomix dinners for tonight: "
            + ". ".join(lines) + ". This is a draft, nothing was added to Cookidoo.")
    if not patterns.no_advice(text):
        raise ValueError("meal draft text failed the no-advice guard")
    return {"day": day.isoformat(), "slot": "dinner", "recipes": picks, "text": text,
            "night": night, "written_to_cookidoo": False}


def main(argv=None):
    """python -m parenting_agent.meals: print tonight's fast recipes from Cookidoo, read only."""
    max_min = int((argv or sys.argv[1:] or ["30"])[0])
    print(json.dumps(HomeAgentsRecipes().fast(max_min), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
