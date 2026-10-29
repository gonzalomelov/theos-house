"""Devices the house does not have yet, as dry-run stand-ins with the controls the real plug will expose (#110, #111).

A VirtualSwitch is a smart plug that turns a device on and off, such as the bottle warmer. A VirtualPowerPlug is a
smart plug that reports the power its device draws, such as the washer. Nothing is switched and nothing is read from a
real device: every change is a "virtual_device" event on the bus with dry true, so the automations can be tested and
simulated today. When the plug is bought and added to Home Assistant, the same automation reads and switches the real
entity through house_tools, behind house.live.

SHOPPING holds the plug to buy for each one, with the price checked on Oct 29 2026.
"""
import datetime

# Checked on Oct 29 2026 on shelly.com. The house already runs one Shelly Plus Plug IT (the bathroom plug), so the
# plug type fits the sockets and the core Shelly integration in Home Assistant is already set up, local, no cloud.
SHOPPING = {
    "bottle_warmer": {"plug": "Shelly Plus Plug IT", "price": "EUR 24.00 list on shelly.com (EUR 16.80 on sale, Oct 29 2026)",
                      "why": "16 A, local control through the core Shelly integration Home Assistant already runs, same "
                             "plug type as the bathroom plug. The warmer must start on power: a dial warmer, not a "
                             "push-button one"},
    "washer": {"plug": "Shelly Plus Plug IT", "price": "EUR 24.00 list on shelly.com (EUR 16.80 on sale, Oct 29 2026)",
               "why": "16 A with power metering, enough for a washer heating at about 2 kW (the 12 A Shelly Plug S "
                      "Gen3 at EUR 23.68 is too close to a washer's heater), local through the core Shelly integration"},
}


class VirtualSwitch:
    """A plug that switches one device, with a hard auto off after max_on_min that no setting can turn off."""

    def __init__(self, bus, entity_id, label, max_on_min, buy=None):
        if not max_on_min or max_on_min <= 0:
            raise ValueError("a virtual switch needs a positive max_on_min")
        self.bus, self.entity_id, self.label, self.max_on_min, self.buy = bus, entity_id, label, max_on_min, buy
        self.state, self.on_since, self.off_at = "off", None, None

    def _publish(self, action, reason, now):
        return self.bus.publish("virtual_device", device=self.label, entity=self.entity_id, action=action, state=self.state,
                                reason=reason, dry=True, at=now.isoformat(timespec="seconds"),
                                off_at=self.off_at.isoformat(timespec="seconds") if self.off_at else None)

    def on(self, now, reason=""):
        self.state, self.on_since = "on", now
        self.off_at = now + datetime.timedelta(minutes=self.max_on_min)
        return self._publish("on", reason, now)

    def off(self, now, reason=""):
        was_on = self.state == "on"
        self.state, self.on_since, self.off_at = "off", None, None
        return self._publish("off", reason, now) if was_on else None

    def tick(self, now):
        if self.state == "on" and now >= self.off_at:
            return self.off(now, f"auto off after {self.max_on_min} min")
        return None


class VirtualPowerPlug:
    """A plug that reports watts. The simulation or a test feeds it readings, a real plug will be read from Home
    Assistant (a sensor entity, read only)."""

    def __init__(self, entity_id, buy=None):
        self.entity_id, self.buy = entity_id, buy
        self.watts, self.at = None, None

    def feed(self, watts, now):
        self.watts, self.at = float(watts), now

    def read(self):
        return self.watts
