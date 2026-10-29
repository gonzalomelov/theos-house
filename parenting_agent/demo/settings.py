"""Settings for the public demo, walled off from the family's house.

The demo reads only the brain key and its own PA_DEMO_* knobs. It never loads the family env file the
way the agent does (config.load_env reads every line into the environment). Before the server starts,
scrub_environment() drops anything that could open a route to the house: Home Assistant, Baby Buddy,
Telegram, tunnels, and every other token or key. The container gets the brain key and nothing else.
"""
import os
import re
from pathlib import Path

BRAIN_KEYS = ("ANTHROPIC_API_KEY", "BASETEN_API_KEY")
SAFE_NAMES = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TZ", "LANG", "LC_ALL", "LC_CTYPE", "PWD", "TMPDIR",
              "HOSTNAME", "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE", "VIRTUAL_ENV",
              "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy", "SSL_CERT_FILE"}
SAFE_PREFIXES = ("PA_DEMO_", "LC_", "__CF", "XPC_")
HOUSE_WORDS = re.compile(r"(HA_|HASS|HOME_ASSISTANT|HOMEASSISTANT|BABYBUDDY|BABY_BUDDY|TELEGRAM|TAILSCALE|CLOUDFLARE|"
                         r"VOSTRO|TOKEN|SECRET|PASSWORD|PASSWD|_KEY|CREDENTIAL|SSH_|AWS_|GITHUB|GH_)", re.I)
HOUSE_VALUES = re.compile(r"(babybuddy|homeassistant|home-assistant|:8123\b|:8790\b|:18790\b|vostro|\.local\b|"
                          r"\b10\.\d+\.\d+\.\d+|\b192\.168\.\d+\.\d+|\b172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+)",
                          re.I)

# USD per million tokens, input and output. Claude Haiku 5.5 from the Anthropic pricing page, read 2026-10-28.
# Muse Spark Open from the Baseten model library page, read 2026-10-28. It always reasons, so output runs long.
PRICES = {"claude": (0.10, 0.50), "baseten": (1.25, 4.25), "fake": (0.0, 0.0)}
CLAUDE = {"provider": "claude", "model": "claude-haiku-5-5", "max_tokens": 400,
          "price_in_per_mtok": PRICES["claude"][0], "price_out_per_mtok": PRICES["claude"][1]}
# Muse Spark Open is the brain. Claude answers only when a Muse call errors, and each time is a brain_fallback event.
BRAINS = {
    "claude": CLAUDE,
    "baseten": {"provider": "openai_compatible", "model": "meta-models/muse-spark-open-1026",
                "base_url": "https://inference.baseten.co/v1", "key_env": "BASETEN_API_KEY", "max_tokens": 2048,
                "reasoning_effort": "low", "timeout_s": 45,
                "price_in_per_mtok": PRICES["baseten"][0], "price_out_per_mtok": PRICES["baseten"][1],
                "fallback": CLAUDE},
    "fake": {"provider": "fake"},
}
DEFAULT_BRAIN = "baseten"
# Charged when a provider reports no usage, so a missing number never makes a call free.
FALLBACK_TOKENS = (4000, 400)


def forbidden_names(environ):
    """Environment names the demo must not carry: anything that is not plainly safe and looks like a route or a secret."""
    bad = []
    for name, value in environ.items():
        if name in BRAIN_KEYS:
            continue
        if name in SAFE_NAMES or name.startswith(SAFE_PREFIXES):
            continue
        if HOUSE_WORDS.search(name) or HOUSE_VALUES.search(str(value)):
            bad.append(name)
    return sorted(bad)


def scrub_environment(environ=None):
    """Remove every forbidden name from the environment. Returns the names removed, never their values."""
    environ = os.environ if environ is None else environ
    removed = forbidden_names(environ)
    for name in removed:
        environ.pop(name, None)
    return removed


def read_brain_key(path, environ=None):
    """Read only the brain keys from an env file, ignoring every other line. Returns the names read."""
    environ = os.environ if environ is None else environ
    path = Path(os.path.expanduser(str(path)))
    if not path.exists():
        return []
    read = []
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        key = key.strip()
        if sep and key in BRAIN_KEYS:
            environ.setdefault(key, value.strip().strip('"').strip("'"))
            read.append(key)
    return read


# The secret in the address /internal/<secret> that marks a browser as Gonza's own. Shorter than this, the
# feature is off and every /internal address is a 404.
INTERNAL_SECRET = "PA_DEMO_INTERNAL_SECRET"
INTERNAL_SECRET_MIN = 32


def _number(environ, name, default, cast=float):
    raw = environ.get(name)
    return cast(raw) if raw not in (None, "") else default


def load(environ=None):
    """The demo settings, from PA_DEMO_* variables only. No URL in here points anywhere but the brain."""
    environ = os.environ if environ is None else environ
    brain_name = environ.get("PA_DEMO_BRAIN", DEFAULT_BRAIN)
    if brain_name not in BRAINS:
        raise ValueError(f"PA_DEMO_BRAIN must be one of {', '.join(BRAINS)}")
    brain = dict(BRAINS[brain_name])
    if environ.get("PA_DEMO_MODEL") and brain_name != "fake":
        brain["model"] = environ["PA_DEMO_MODEL"]
    price_in, price_out = PRICES[brain_name]
    if environ.get("PA_DEMO_PRICE_IN") or environ.get("PA_DEMO_PRICE_OUT"):
        brain.pop("price_in_per_mtok", None)  # an explicit price knob wins over the brain's own prices
    return {
        "brain_name": brain_name,
        "brain": brain,
        "data_dir": environ.get("PA_DEMO_DATA_DIR", "data"),
        "host": environ.get("PA_DEMO_HOST", "127.0.0.1"),
        "port": _number(environ, "PA_DEMO_PORT", 8765, int),
        "secure_cookie": environ.get("PA_DEMO_SECURE_COOKIE", "0") == "1",
        "internal_secret": secret if len(secret := environ.get(INTERNAL_SECRET, "").strip()) >= INTERNAL_SECRET_MIN else "",
        "max_messages_per_visitor": _number(environ, "PA_DEMO_MAX_MESSAGES", 25, int),
        "max_messages_per_day": _number(environ, "PA_DEMO_MAX_DAILY_MESSAGES", 1500, int),
        "daily_usd_cap": _number(environ, "PA_DEMO_DAILY_USD", 2.0),
        "price_in_per_mtok": _number(environ, "PA_DEMO_PRICE_IN", price_in),
        "price_out_per_mtok": _number(environ, "PA_DEMO_PRICE_OUT", price_out),
        "max_input_chars": _number(environ, "PA_DEMO_MAX_INPUT", 300, int),
        "max_body_bytes": 4096,
        "max_visitors_in_memory": _number(environ, "PA_DEMO_MAX_VISITORS", 1000, int),
        "visitor_idle_s": _number(environ, "PA_DEMO_IDLE_S", 6 * 3600, int),
        "max_parallel_brain": _number(environ, "PA_DEMO_PARALLEL", 4, int),
        "max_steps": 5,
        "history": 16,
    }
