"""Agent config (config/agent.json) and secrets from a git-ignored env file.

Secrets are read into the process environment and never printed or written anywhere else.
"""
import json
import os
from pathlib import Path

DEFAULTS = {
    "data_dir": "data",
    "env_file": ".env",
    "brain": {"provider": "fake"},
    "allowed_tools": ["log_baby_event", "read_baby_log", "baby_summary", "remember", "current_time"],
    "baby_log": {"provider": "local"},
    "plugins": [],
    "max_steps": 6,
}


def load(path=None):
    config = json.loads(json.dumps(DEFAULTS))
    if path and Path(path).exists():
        config.update(json.loads(Path(path).read_text()))
    return config


def load_env(path):
    path = Path(os.path.expanduser(path))
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        loaded.append(key.strip())
    return loaded
