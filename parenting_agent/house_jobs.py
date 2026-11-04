"""Every device gets a job in the baby's day (issues #9 and #29).

DEVICES maps each useful Home Assistant device to the entities the agent uses and its jobs. Each job names the
routine in parenting_agent/day_engine.py that runs it (or "read" when the job only feeds a routine or a brief) and the
policy it runs under, the same three lists as docs/house-policy.md:

- alone: runs on the engine's word, in dry run until house.live is on
- ask: waits for Gonza's yes
- read: reads a state, changes nothing
- never: listed so nobody adds it by mistake

MISSING is what the house lacks and is cheap to buy, each with the job it unlocks.
"""

DEVICES = [
    {"device": "Xiaomi Robot Vacuum S40 Pro", "area": "home",
     "entities": ["vacuum.xiaomi_ov71gl_0681_robot_cleaner", "input_boolean.xiaomi_vacuum_run_active",
                  "input_datetime.xiaomi_vacuum_run_start", "calendar.xiaomi_s40_pro",
                  "sensor.xiaomi_ov71gl_0681_battery_level"],
     "jobs": [
         ("nap_mode", "alone", "A nap starts: pause and send it to its base, remember how much of the run was left"),
         ("nap_mode", "alone", "The nap ends: resume the run it paused, only if the rest fits before the next predicted nap"),
         ("floor_clean", "ask", "Clean the floor before tummy time, only while he is out or awake in another room, never into a predicted nap"),
         ("read", "read", "Run length from its own run calendar (32 runs logged, median 16 min, whole house 31 min) for the fit check"),
     ]},
    {"device": "Gonza's Echo Dot", "area": "home",
     "entities": ["media_player.gonza_s_echo_dot", "notify.gonza_s_echo_dot_announce",
                  "switch.gonza_s_echo_dot_do_not_disturb", "binary_sensor.gonza_s_echo_dot_motion",
                  "sensor.gonza_s_echo_dot_temperature", "sensor.gonza_s_echo_dot_illuminance"],
     "jobs": [
         ("nap_mode", "alone", "Do not disturb on for every sleep, back to how it was when he wakes"),
         ("morning_brief", "alone", "Speak the morning brief at low volume, built only from numbers and fixed words"),
         ("morning_brief", "read", "Motion: the brief is spoken only when someone moved in the kitchen in the last 10 min"),
         ("door", "alone", "Say 'Someone is at the door' when he is awake"),
         ("morning_brief", "read", "Temperature: the kitchen reading goes in the brief (the only room thermometer today)"),
         ("read", "read", "Light level: tells a dark kitchen at a night feed, for the study light dimming"),
     ]},
    {"device": "LG webOS TV OLED55B3PSA", "area": "home",
     "entities": ["media_player.lg_webos_tv_oled55b3psa"],
     "jobs": [
         ("nap_mode", "alone", "Muted while he sleeps, also when someone turns it on mid-nap, unmuted when he wakes"),
         ("read", "ask", "Power and volume above a low level wait for a yes"),
     ]},
    {"device": "Samsung 43\" Crystal UHD", "area": "Bedroom",
     "entities": ["media_player.43_crystal_uhd_un43u8000fgxpr", "remote.43_crystal_uhd_un43u8000fgxpr"],
     "jobs": [
         ("nap_mode", "alone", "Muted while he sleeps, also when someone turns it on mid-nap, unmuted when he wakes"),
         ("read", "ask", "Power and volume above a low level wait for a yes"),
     ]},
    {"device": "Tapo C200 Sofa (and its ONVIF stream)", "area": "home",
     "entities": ["camera.tapo_c200_sofa_hd_stream", "binary_sensor.tapo_c200_sofa_onvif_person_detection",
                  "binary_sensor.tapo_c200_sofa_onvif_cell_motion_detection", "light.tapo_c200_sofa_floodlight_timed"],
     "jobs": [
         ("floor_clean", "read", "Person detection: someone on the living room floor means the vacuum does not start there"),
         ("read", "read", "Microphone: house sounds (cry, doorbell, dog) through the existing house sounds skill"),
         ("read", "read", "Video: the existing changing table and bath skills see the room through it"),
         ("read", "ask", "Floodlight: harsh, only with a yes"),
     ]},
    {"device": "Tapo C200 Barbacue", "area": "home",
     "entities": ["camera.tapo_c200_barbacue_hd_stream", "binary_sensor.barbecue_tapo_c200_barbacue_person_detection_2"],
     "jobs": [
         ("door", "read", "Person detection outside: a person at the door becomes a silent push while he sleeps, a spoken line when he is awake"),
         ("read", "ask", "Floodlight: outdoor, only with a yes"),
     ]},
    {"device": "Tapo C100 Living", "area": "home",
     "entities": ["camera.tapo_c100_living_hd_stream_direct"],
     "jobs": [
         ("read", "read", "a second view of the kitchen for bottle prep at night"),
     ]},
    {"device": "WiZ study light", "area": "home",
     "entities": ["light.wiz_824512_192_0_2_10"],
     "jobs": [
         ("read", "alone", "Warm and dim for night feeds (the existing study_light tool). Unavailable on Oct 28 and 29"),
     ]},
    {"device": "Refrigerator", "area": "home",
     "entities": ["binary_sensor.refrigerator_door"],
     "jobs": [
         ("read", "read", "Door opened during a night wake-up: a bottle is being made, the night summary can say who was up"),
         ("read", "never", "Its settings (temperature, express mode) are never touched"),
     ]},
    {"device": "Shelly Plus Plug (bathroom)", "area": "home",
     "entities": ["sensor.shellyplusplugit_bathroom_power"],
     "jobs": [
         ("read", "read", "Power reading only: the bathroom heater drawing power before bath time is a sign the bath is being set up"),
         ("read", "never", "The switch is never touched, it has its own safety cut automation"),
     ]},
    {"device": "Cookidoo", "area": "home",
     "entities": ["calendar.cookidoo_meal_plan", "todo.cookidoo_shopping_list", "todo.cookidoo_additional_purchases"],
     "jobs": [
         ("morning_brief", "read", "Today's dinner from the meal plan in the morning brief"),
         ("parents_meals", "read", "After a hard night, quick Thermomix recipes (read only through home-agents) for the next quiet window"),
         ("read", "never", "Never written: the meal plan and its lists stay read only, the Thermomix is never started"),
     ]},
    {"device": "Shopping list", "area": "home",
     "entities": ["todo.shopping_list"],
     "jobs": [
         ("supplies", "alone", "Diapers, wipes and formula added before they run out, counted from the log"),
         ("supplies", "read", "Read first, so an item already on the list is not added twice"),
     ]},
    {"device": "Pantry, fridge and freezer lists", "area": "home",
     "entities": ["todo.freezer", "todo.fridge", "todo.pantry"],
     "jobs": [
         ("parents_meals", "read", "Freezer: meals already cooked are named next to the quick recipes after a hard night"),
     ]},
    {"device": "Weather (met.no)", "area": "home",
     "entities": ["weather.forecast_home"],
     "jobs": [
         ("morning_brief", "read", "Today's sky, high and low and rain in the morning brief"),
     ]},
    {"device": "Gonza's iPhone", "area": "home",
     "entities": ["notify.gonzas_iphone", "device_tracker.gonzas_iphone", "sensor.gonzas_iphone_battery_level"],
     "jobs": [
         ("door", "alone", "Silent push (passive, no sound) when someone is at the door while he sleeps"),
         ("floor_clean", "alone", "The yes or no question before a floor clean"),
         ("read", "read", "Presence: home or away, for 'nobody home'"),
     ]},
    {"device": "People", "area": "home",
     "entities": ["person.gonza", "person.ceci"],
     "jobs": [
         ("read", "read", "Who is home. Unknown never counts as away"),
     ]},
    {"device": "Sun", "area": "home",
     "entities": ["sun.sun"],
     "jobs": [
         ("read", "read", "Dark or light outside, for night mode and the study light"),
     ]},
]

# Present in the registry and deliberately without a job.
NO_JOB = [
    ("Tapo camera settings (switches, selects, buttons, numbers)", "camera privacy, recording, sirens and tamper are on the never list"),
    ("Sirens", "never"),
    ("Mi Body Composition Scale and its sensors", "never, private to Gonza"),
    ("Backups and updates", "never"),
    ("Existing automations", "read only, the agent adds none"),
    ("LLM Vision timeline calendar", "Gonza's existing camera notes, not used by the agent"),
]

MISSING = [
    {"device": "Smart plug for the bottle warmer", "price_usd": "10 to 15", "example": "TP-Link Tapo P100 or a Shelly Plug S",
     "unlocks": "Warm the bottle 5 min before the predicted night feed, off after 20 min, ask first the first week",
     "routine": "night feeds"},
    {"device": "Power-monitoring plug for the washer", "price_usd": "15 to 25", "example": "Shelly Plus Plug S or Tapo P110",
     "unlocks": "Tell when the washer is done and its spin is over, so baby clothes go to the dryer in the next awake window and the spin never lands in a nap",
     "routine": "nap_mode"},
    {"device": "Nursery temperature and humidity sensor", "price_usd": "10 to 20", "example": "Aqara T1 or a Xiaomi LYWSD03MMC",
     "unlocks": "The nursery reading in the morning brief and at bedtime, instead of the kitchen Echo",
     "routine": "morning_brief"},
    {"device": "Nursery night light", "price_usd": "10 to 15", "example": "a WiZ or Tapo dimmable bulb in a small lamp",
     "unlocks": "Warm 10 percent light for night feeds in the nursery, off when he is back asleep",
     "routine": "nap_mode"},
    {"device": "Nursery speaker", "price_usd": "25 to 50", "example": "an Echo Pop, or the DIY ESP32 white noise machine from #32",
     "unlocks": "White noise in the room where he sleeps, and the nap mode's white noise leaves dry run",
     "routine": "nap_mode"},
    {"device": "A family calendar in Home Assistant", "price_usd": "0", "example": "the Google Calendar integration",
     "unlocks": "Today's appointments in the morning brief",
     "routine": "morning_brief"},
]


def job_count():
    """(devices with a job, device to job pairs) for the useful devices."""
    return len(DEVICES), sum(len(d["jobs"]) for d in DEVICES)


def entities():
    return [e for d in DEVICES for e in d["entities"]]
