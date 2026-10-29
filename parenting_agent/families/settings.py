"""Settings for the families service, walled off from Gonza's family agent and house.

Like the demo, the service never loads the family env file. It keeps three secrets at most: the brain key
(ANTHROPIC_API_KEY or BASETEN_API_KEY) and TELEGRAM_FAMILIES_BOT_TOKEN, the second bot. Everything else that
could open a route to the house is removed before anything starts, including Gonza's own bot token.
"""
import os
from pathlib import Path

from ..demo.settings import BRAINS, DEFAULT_BRAIN, HOUSE_VALUES, HOUSE_WORDS, PRICES, SAFE_NAMES

BOT_TOKEN = "TELEGRAM_FAMILIES_BOT_TOKEN"
BRAIN_KEYS = ("ANTHROPIC_API_KEY", "BASETEN_API_KEY")
KEEP = BRAIN_KEYS + (BOT_TOKEN,)
SAFE_PREFIXES = ("PA_FAMILIES_", "LC_", "__CF", "XPC_")
FAMILY_BOT_USERNAME = "home_agent_example_bot"


def forbidden_names(environ):
    """Names the service must not carry: anything not plainly safe that looks like a route to the house or a secret."""
    bad = []
    for name, value in environ.items():
        if name in KEEP or name in SAFE_NAMES or name.startswith(SAFE_PREFIXES):
            continue
        if HOUSE_WORDS.search(name) or HOUSE_VALUES.search(str(value)):
            bad.append(name)
    return sorted(bad)


def same_bot_as_family(environ):
    """True when the families token is Gonza's own family bot token: the service must refuse to start."""
    token = environ.get(BOT_TOKEN)
    return bool(token) and token == environ.get("TELEGRAM_BOT_TOKEN")


def scrub_environment(environ=None):
    """Remove every forbidden name. Returns the names removed, never their values."""
    environ = os.environ if environ is None else environ
    removed = forbidden_names(environ)
    for name in removed:
        environ.pop(name, None)
    return removed


def read_keys(path, environ=None):
    """Read only the brain keys and the families bot token from an env file. Returns the names read."""
    environ = os.environ if environ is None else environ
    path = Path(os.path.expanduser(str(path)))
    if not path.exists():
        return []
    read = []
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        key = key.strip()
        if sep and key in KEEP:
            environ.setdefault(key, value.strip().strip('"').strip("'"))
            read.append(key)
    return read


def _number(environ, name, default, cast=float):
    raw = environ.get(name)
    return cast(raw) if raw not in (None, "") else default


def _ids(raw):
    return {part.strip() for part in (raw or "").split(",") if part.strip()}


def load(environ=None):
    """The service settings, from PA_FAMILIES_* variables only. No URL in here points anywhere but the brain."""
    environ = os.environ if environ is None else environ
    brain_name = environ.get("PA_FAMILIES_BRAIN", DEFAULT_BRAIN)
    if brain_name not in BRAINS:
        raise ValueError(f"PA_FAMILIES_BRAIN must be one of {', '.join(BRAINS)}")
    brain = dict(BRAINS[brain_name])
    if environ.get("PA_FAMILIES_MODEL") and brain_name != "fake":
        brain["model"] = environ["PA_FAMILIES_MODEL"]
    price_in, price_out = PRICES[brain_name]
    if environ.get("PA_FAMILIES_PRICE_IN") or environ.get("PA_FAMILIES_PRICE_OUT"):
        brain.pop("price_in_per_mtok", None)  # an explicit price knob wins over the brain's own prices
    return {
        "brain_name": brain_name,
        "brain": brain,
        "data_dir": environ.get("PA_FAMILIES_DATA_DIR", "data/families"),
        "tz": environ.get("PA_FAMILIES_TZ", "America/Montevideo"),
        "bot_username": environ.get("PA_FAMILIES_BOT_USERNAME", ""),
        "internal_user_ids": _ids(environ.get("PA_FAMILIES_INTERNAL_USERS")),
        "max_messages_per_family_day": _number(environ, "PA_FAMILIES_MAX_MESSAGES", 150, int),
        "family_daily_usd": _number(environ, "PA_FAMILIES_FAMILY_USD", 0.50),
        "daily_usd_cap": _number(environ, "PA_FAMILIES_DAILY_USD", 3.0),
        "price_in_per_mtok": _number(environ, "PA_FAMILIES_PRICE_IN", price_in),
        "price_out_per_mtok": _number(environ, "PA_FAMILIES_PRICE_OUT", price_out),
        "max_input_chars": _number(environ, "PA_FAMILIES_MAX_INPUT", 500, int),
        "max_families": _number(environ, "PA_FAMILIES_MAX_FAMILIES", 20, int),
        "invite_days": _number(environ, "PA_FAMILIES_INVITE_DAYS", 7, int),
        "max_bad_codes_per_day": _number(environ, "PA_FAMILIES_MAX_BAD_CODES", 5, int),
        "reminder_lead_min": _number(environ, "PA_FAMILIES_REMINDER_LEAD_MIN", 10, int),
        "reminder_max_gap_h": _number(environ, "PA_FAMILIES_REMINDER_MAX_GAP_H", 8, float),
        "summary_hour": _number(environ, "PA_FAMILIES_SUMMARY_HOUR", 20, int),
        "poll_timeout_s": _number(environ, "PA_FAMILIES_POLL_S", 25, int),
        "tick_s": _number(environ, "PA_FAMILIES_TICK_S", 60, int),
        "max_steps": 5,
        "history": 16,
    }
