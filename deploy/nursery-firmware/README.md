# Theo's room sensor: the firmware

An AHT30 on an ESP32-S3 (N16R8), on Meta's open source [Muse Gadget SDK](https://github.com/facebookincubator/muse-gadget-sdk) (Apache 2.0). `nursery-aht30.patch` is what we added on top of the SDK, at commit `1b894f5`:

- `esp32/main/aht30_sensor.c`: reads the sensor every 10 s and answers the SDK's `sensors.read` command. It also serves the same JSON read only at `GET /sensors`.
- The `nursery-climate` board profile, and a host test.

The board is not paired with Muse, because the Muse app isn't available in Uruguay. It joins WiFi with the SDK's own WiFi setting, Home Assistant reads it once a minute (`deploy/home-assistant/`), and both this agent and Meta Muse read it from there (`deploy/nursery-mcp/`).

## Build it

```sh
git clone https://github.com/facebookincubator/muse-gadget-sdk.git && cd muse-gadget-sdk
git checkout 1b894f5 && git am /path/to/nursery-aht30.patch
cd esp32
# WiFi goes in devices/sdkconfig.nursery-climate.local, never in git:
#   CONFIG_HOMEHUB_WIFI_SSID="..."
#   CONFIG_HOMEHUB_WIFI_PASSWORD="..."
tools/board.sh nursery-climate build
tools/board.sh nursery-climate flash <port>
```

Needs ESP-IDF 6.0.1. Wiring: 3V3 to VIN, GND to GND, GPIO5 to SCL, GPIO4 to SDA.
