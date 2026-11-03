"""What is real and what is mock. PA_WORLD=real or mock sets every part, PA_HOME, PA_CHANNEL and PA_LOG override one."""
import os
from dataclasses import dataclass, field

MODEL = "meta-models/muse-spark-open-1026"
BASE_URL = "https://inference.baseten.co/v1"
# The devices Muse may switch. A real test narrows this with PA_ALLOWED_DEVICES.
DEVICES = ("Tapo P110 - Dehumidifier", "Tapo P110 - Bottle Warmer")
# Sensor and how far it must move to wake Muse, so a reading that drifts by 0.1 costs nothing.
WATCH = {"sensor.nursery_climate_humidity": 2.0, "sensor.nursery_climate_temperature": 1.0}
SCHEDULE = (("07:30", "morning"), ("21:30", "evening"))


def watch():
    """WATCH, or every sensor at PA_WATCH_DELTA for a test that must not wait for the room to change."""
    delta = os.environ.get("PA_WATCH_DELTA")
    return {entity: float(delta) for entity in WATCH} if delta else WATCH


def part(name):
    return os.environ.get(f"PA_{name.upper()}", os.environ.get("PA_WORLD", "mock"))


@dataclass
class Settings:
    home: str = field(default_factory=lambda: os.environ.get("PA_HOME_ID", "home"))
    db_url: str = field(default_factory=lambda: os.environ.get("PA_DB_URL", "postgresql://agent@127.0.0.1:55432/agent"))
    ha_url: str = field(default_factory=lambda: os.environ.get("HA_URL", "http://127.0.0.1:18123"))
    ha_token: str = field(default_factory=lambda: os.environ.get("HA_MCP_TOKEN", ""))
    lang: str = field(default_factory=lambda: os.environ.get("PA_LANG", "es"))
    mock_port: int = field(default_factory=lambda: int(os.environ.get("PA_MOCK_PORT", "18124")))
    devices: tuple = field(default_factory=lambda: tuple(filter(None, os.environ.get("PA_ALLOWED_DEVICES", "").split("|"))) or DEVICES)
    pool_max: int = field(default_factory=lambda: int(os.environ.get("PA_DB_POOL", "6")))
    data_dir: str = field(default_factory=lambda: os.environ.get("PA_DATA_DIR", "data-core"))
