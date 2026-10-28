# The Tesla (issue #31)

The family's car is a Tesla Model 3. It is part of the product now through a **simulated Model 3** that exposes the same entity ids and services as the official Home Assistant core integration `tesla_fleet`. When it arrives the agent switches to the real car with a config change and no code change. Built during the Meta hackathon, Oct 28 2026.

Anything about the car in demo output says "simulated Tesla". The drive data in the tests is synthetic and labeled so.

## What it does

| Automation | How it works | Who says yes |
|---|---|---|
| Cabin ready | "We leave in 15" (the brain calls `cabin_ready`) or a calendar entry with the baby coming up within 15 min. The target comes from the outside temperature in `weather.forecast_home`: 22 C below 12 C, 20 C above 26 C, 21 C in between. The seat under the car seat is set to off, never heated | The parent, every time. `precondition_car` is never on the allowed list |
| Car naps | The plug-in follows `sensor.<car>_shift_state`. When a drive on a trip with the baby ends (a cabin-ready yes in the 2 h before), it says "check the back seat" and asks whether the baby slept, from drive start to drive end. A stop in P shorter than 3 min does not split the drive. Drives under 10 min get only the back-seat reminder | The parent. The yes is what logs the sleep in Baby Buddy, `log_car_nap` is never on the allowed list |
| Child Left Alone Detection | Its status is in every cabin-ready proposal and in `car_status` | Nobody, it only reads |

Child Left Alone Detection came in Tesla software 2025.14.12 and only on some models. Nothing here says the 2027 Model 3 has it. The simulated car has a flag (`car.simulated.child_left_alone`). `tesla_fleet` has no entity for it, so the real car shows "not reported" until we check it in the car on Nov 5 and record the result on #31.

Every car command is a `car_command` event on the bus (service, entity, data, simulated or not). A command to the real car before Gonza's OK is a `car_dry` event and nothing is sent.

## Code

| File | What it holds |
|---|---|
| `parenting_agent/tesla/entities.py` | The `tesla_fleet` entity ids for one car, from the car's name and the integration's English names |
| `parenting_agent/tesla/car.py` | `Car`, the interface the agent uses, and its two backends: `SimulatedTesla` and Home Assistant |
| `parenting_agent/tesla/trips.py` | The `CarTrips` plug-in: tools `cabin_ready`, `car_status` (allowed), `precondition_car`, `log_car_nap` (always ask) |
| `parenting_agent/tesla/samples/drive-2026-10-24.synthetic.json` | A synthetic drive, one reading a minute in the shape `tesla_fleet` reports. Public places only, no home address |
| `tests/fixtures/tesla_fleet_strings.json` | A verbatim excerpt of `tesla_fleet/strings.json` at core commit ff2c6d4, the source the names are tested against |

Entity ids the agent reads or commands, for a car named "Model 3" in the Tesla app:

| Role | Entity id | Note |
|---|---|---|
| Location | `device_tracker.model_3_location` | Needs the vehicle location scope |
| Climate | `climate.model_3_climate` | `climate.turn_on`, `turn_off`, `set_temperature`, `set_preset_mode` (off, keep, dog, camp) |
| Inside, outside temperature | `sensor.model_3_inside_temperature`, `sensor.model_3_outside_temperature` | |
| Preconditioning | `binary_sensor.model_3_preconditioning` | Disabled by default in Home Assistant, enable it |
| Shift state | `sensor.model_3_shift_state` | p, d, r, n, unknown while the car sleeps |
| Speed | `sensor.model_3_speed` | Disabled by default, enable it |
| Battery | `sensor.model_3_battery_level`, `sensor.model_3_battery_range` | |
| Seat heaters | `select.model_3_seat_heater_front_left`, `_front_right`, `_rear_left`, `_rear_center`, `_rear_right` | `select.select_option` off, low, medium, high. Rear seats are disabled by default |

## Run

```bash
python -m parenting_agent.tesla                        # one trip with the baby on the simulated car, results/tesla/demo.json
.venv/bin/python -m unittest tests.test_tesla -v       # names, backend switch, cabin ready, car naps, the check
```

`config/agent.json` loads the plug-in with `"car": {"backend": "simulated"}` and allows `cabin_ready` and `car_status`.

## Nov 5 steps

Each step is done by hand, in this order. Nothing here was done before the car arrived: no developer app, no DNS change.

1. **Tesla developer app.** On developer.tesla.com, with the Tesla account that owns the car, create an app. Allowed origin `https://bygmv.com`. Redirect URI `https://my.home-assistant.io/redirect/oauth`. Scopes: vehicle information, vehicle location, vehicle commands, vehicle charging management. Keep the client id and secret in the git-ignored env file, never in git. Check the current monthly credit and command prices on the developer page before relying on them (the issue notes $10 a month per account).
2. **Start the integration.** On the Vostro Home Assistant, add the client id and secret under Application Credentials, then add the Tesla Fleet integration and log in. It detects the region, makes the private key in the Home Assistant config folder (`tesla_fleet.key`, it never leaves the Vostro) and shows the public key it wants hosted.
3. **Public key file on bygmv.com, walled off.** Serve that one file at `https://bygmv.com/.well-known/appspecific/com.tesla.3p.public-key.pem`, through the Cloudflare tunnel that already serves bygmv.com. Serve it from a static-only container that holds only that file, with no route to Home Assistant, the agent or the LAN, like every public app on the Vostro. Check from outside that the file loads and that nothing else on that container answers. Only the public key is public. Home Assistant itself stays private: the OAuth redirect goes through the browser and `tesla_fleet` polls Tesla's cloud.
4. **Register the domain.** Enter `bygmv.com` in the integration's domain step. It registers the domain with Tesla and checks that the hosted key matches its private key.
5. **Virtual key in the car.** On the phone with the Tesla app, open `https://www.tesla.com/_ak/bygmv.com` (the integration shows a QR code), approve it, and confirm with the key card in the car. Without this, commands are refused.
6. **Enable two entities.** In Home Assistant, enable Speed and Preconditioning for the car, and the rear seat heaters. Check the car's entity ids. If the car has another name than "Model 3", set `device_name` to that name.
7. **Child Left Alone Detection.** Look in the car's settings for it. Record on #31 whether this car has it, its software version, and whether it is on. If Home Assistant ever exposes it, set `child_left_alone_entity`.
8. **Config switch.** In `config/agent.json`:
   ```json
   "car": {"backend": "home_assistant", "device_name": "Model 3", "live_commands": false,
           "ha_url": "http://127.0.0.1:18123", "ha_token_env": "HA_MCP_TOKEN",
           "parent_channel": "telegram", "car_seat": "rear_center", "trip_calendar": null}
   ```
   With `live_commands` false the agent reads the real car and every command is a dry run. `car_seat` is where the baby's car seat sits.
9. **Gonza's OK, then one live command.** Only after Gonza says OK, set `live_commands` to true and run one cabin ready with his yes. Check the `car_command` event and the car's climate in Home Assistant, then comment the result on #31.
