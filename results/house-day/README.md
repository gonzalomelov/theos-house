# A simulated day of the whole house, in dry run

Issues #9 and #29, built during the Meta hackathon on Oct 29 2026. `scripts/house_day_sim.py` runs the day engine
(`parenting_agent/day_engine.py`) minute by minute through Sat Oct 24 06:00 to Sun Oct 25 07:00 of the simulated
week, the morning after the hard night of Fri Oct 23 (4 wake-ups).

## What is real and what is simulated

| Part | Source |
|---|---|
| The baby log | the simulated week (`tests/fixtures/simweek.json`) plus scripted notes: diaper, wipes and formula stock on Thu, tummy times on Wed to Fri, "Feeding in the bedroom" at 13:56 |
| The starting house | the real house read on Oct 29 2026 through the tunnel, read only: vacuum docked, both TVs off, Echo do not disturb off, kitchen 18.2 C, shopping list empty (`house-start.json`) |
| The weather | the real met.no forecast read on Oct 29 2026 (sunny, 14.9 to 20.2 C), used as the simulated Saturday's weather |
| The vacuum run length | 31 min for the whole house (the house plan's figure). Its own run calendar logged 32 runs in two weeks, median 16 min, most of them single rooms |
| What people do | scripted: TVs turned on and off, the vacuum started by hand, Echo motion, two doorbells |
| Appointments | two invented calendar entries, Home Assistant has no family calendar yet |
| Recipes | one real read-only Cookidoo run saved Oct 28 (`tests/fixtures/fast_recipes.json`) |
| Gonza's yes | given 2 min after the question |
| Every house write | a dry run. The writer has no client, `house.live` is false. A simulated house follows the dry writes so the next minute sees the change |
| White noise | the simulated device from #32, nothing plays |

## Checks over the whole day

| Check | Result |
|---|---|
| Sleeps in the day | 11 |
| Minutes the vacuum cleaned while he slept | 0 |
| Minutes a TV was on and not muted while he slept | 0 |
| Minutes the Echo was not on do not disturb while he slept | 0 |
| Loudest white noise at the crib | 48.1 dB (cap 50.0 dB) |
| House writes | 31 dry runs, 0 live |

## Routines that fired

| Routine | Kind | Fired at |
|---|---|---|
| `nap_mode` | skill | Sat 06:28, Sat 08:11, Sat 09:03, Sat 11:11, Sat 11:57, Sat 12:40, Sat 13:54, Sat 14:51, Sat 16:28, Sat 17:40, Sat 18:47, Sat 19:55, Sat 20:30, Sat 21:20, Sat 22:10, Sun 00:04, Sun 06:43 |
| `door` | skill | Sat 10:20, Sat 16:35 |
| `floor_clean` | schedule | Sat 08:05, Sat 13:56, Sat 13:58 |
| `morning_brief` | schedule | Sat 07:30, Sat 08:20 |
| `supplies` | schedule | Sat 14:03, Sat 17:18 |
| `parents_meals` | schedule | Sat 07:30 |

## Timeline

Each house write is the exact request the engine would send, in dry run.

| Time | Routine | What | Detail |
|---|---|---|---|
| Sat 06:28 | nap_mode | on | sleep started, the house goes quiet |
| Sat 06:28 | nap_mode | dry run switch.turn_on switch.gonza_s_echo_dot_do_not_disturb | (sleep started at 06:28) |
| Sat 06:28 | nap_mode | white noise on (simulated device) | crib_db 48.1, reason sleep started at 06:28 |
| Sat 07:30 | morning_brief | telegram |  |
| Sat 07:30 | morning_brief | message to Gonza (telegram) | Good morning. Night summary for Fri 23: 4 feeds at 22:04, 00:51, 03:21, 05:47, longest sleep 2.1 h. Wake-ups: Parent A 2, Parent B 2. Next on duty: Parent A. Next feed expected around 08:15. Weather: sunny, 15 to 20 C, 0.8 mm of rain. Kitchen 18 C. Running low: Diapers (about 2.3 days left), Formula (about 2.6 days left). 2 appointments today: 11:30 Newborn photos at home, 16:00 Grandma visits. |
| Sat 07:30 | parents_meals | suggest | wakeups 4, recipes ['Cogumelos salteados', 'Langostinos salteados al oporto'], window {'start': '2026-10-24T09:08:00-03:00', 'end': '2026-10-24T10:45:00-03:00'} |
| Sat 07:30 | parents_meals | message to Gonza (telegram) | Hard night: 4 wake-ups, longest sleep 2.1 h. Next quiet window: his nap around 09:08 to 10:45. Quick Thermomix options from Cookidoo: Cogumelos salteados (20 min), Langostinos salteados al oporto (25 min). Already cooked in the freezer: Cooked Pascualina, Cooked Torta de Pollo. Nothing is written to Cookidoo, the Thermomix waits for your press of the dial. |
| Sat 08:05 | floor_clean | hold | floor_at 2026-10-24T08:40:00-03:00, why he is asleep |
| Sat 08:11 | nap_mode | off | sleep ended, the house goes back |
| Sat 08:11 | nap_mode | dry run switch.turn_off switch.gonza_s_echo_dot_do_not_disturb | (he woke up, sleep since 06:28) |
| Sat 08:11 | nap_mode | white noise off (simulated device) | crib_db 0.0, reason he woke up, sleep since 06:28 |
| Sat 08:15 | house | Someone turns on the living room TV |  |
| Sat 08:20 | house | Someone moves in the kitchen (Echo motion) |  |
| Sat 08:20 | morning_brief | echo |  |
| Sat 08:20 | morning_brief | dry run notify.send_message notify.gonza_s_echo_dot_announce | {"message": "Good morning. Last night he woke 4 times, longest sleep 2.1 hours. Today sunny, up to 20 degrees. 2 appointments today, the first at 11:30. Running low: Diapers, Formula."} (morning brief, someone is in the kitchen) |
| Sat 08:45 | house | Someone starts the vacuum by hand in the Xiaomi app |  |
| Sat 09:03 | nap_mode | on | nap started, the house goes quiet |
| Sat 09:03 | nap_mode | dry run vacuum.pause vacuum.xiaomi_ov71gl_0681_robot_cleaner | (nap started at 09:03) |
| Sat 09:03 | nap_mode | dry run vacuum.return_to_base vacuum.xiaomi_ov71gl_0681_robot_cleaner | (nap started at 09:03) |
| Sat 09:03 | nap_mode | dry run media_player.volume_mute media_player.lg_webos_tv_oled55b3psa | {"is_volume_muted": true} (nap started at 09:03) |
| Sat 09:03 | nap_mode | dry run switch.turn_on switch.gonza_s_echo_dot_do_not_disturb | (nap started at 09:03) |
| Sat 09:03 | nap_mode | white noise on (simulated device) | crib_db 48.1, reason nap started at 09:03 |
| Sat 10:20 | house | The doorbell rings and the outdoor camera sees a person |  |
| Sat 10:20 | door | silent push | source doorbell |
| Sat 10:20 | door | dry run notify.mobile_app_gonzas_iphone | {"title": "Door", "message": "The doorbell rang at 10:20. He is asleep, the Echo stays quiet."} (the doorbell rang during the nap) |
| Sat 10:20 | door | same visit | source person_detection |
| Sat 11:11 | nap_mode | off | nap ended, the house goes back |
| Sat 11:11 | nap_mode | dry run media_player.volume_mute media_player.lg_webos_tv_oled55b3psa | {"is_volume_muted": false} (he woke up, nap since 09:03) |
| Sat 11:11 | nap_mode | dry run switch.turn_off switch.gonza_s_echo_dot_do_not_disturb | (he woke up, nap since 09:03) |
| Sat 11:11 | nap_mode | white noise off (simulated device) | crib_db 0.0, reason he woke up, nap since 09:03 |
| Sat 11:11 | nap_mode | dry run vacuum.start vacuum.xiaomi_ov71gl_0681_robot_cleaner | (resume the run the nap paused, 13 min left, done before the next predicted sleep) |
| Sat 11:57 | nap_mode | on | nap started, the house goes quiet |
| Sat 11:57 | nap_mode | dry run media_player.volume_mute media_player.lg_webos_tv_oled55b3psa | {"is_volume_muted": true} (nap started at 11:57) |
| Sat 11:57 | nap_mode | dry run switch.turn_on switch.gonza_s_echo_dot_do_not_disturb | (nap started at 11:57) |
| Sat 11:57 | nap_mode | white noise on (simulated device) | crib_db 48.1, reason nap started at 11:57 |
| Sat 12:00 | house | Someone turns off the living room TV |  |
| Sat 12:40 | house | Someone turns on the bedroom TV mid-nap |  |
| Sat 12:40 | nap_mode | dry run media_player.volume_mute media_player.43_crystal_uhd_un43u8000fgxpr | {"is_volume_muted": true} (bedroom TV turned on while he sleeps) |
| Sat 13:54 | nap_mode | off | nap ended, the house goes back |
| Sat 13:54 | nap_mode | dry run media_player.volume_mute media_player.43_crystal_uhd_un43u8000fgxpr | {"is_volume_muted": false} (he woke up, nap since 11:57) |
| Sat 13:54 | nap_mode | dry run switch.turn_off switch.gonza_s_echo_dot_do_not_disturb | (he woke up, nap since 11:57) |
| Sat 13:54 | nap_mode | white noise off (simulated device) | crib_db 0.0, reason he woke up, nap since 11:57 |
| Sat 13:56 | floor_clean | ask | floor_at 2026-10-24T14:35:00-03:00 |
| Sat 13:56 | floor_clean | message to Gonza (telegram) | Tummy time is usually around 14:35. He is awake in the bedroom, I can run the vacuum now: 31 min, done by 14:27, before the next predicted nap. Reply yes to start it. |
| Sat 13:58 | floor_clean | Gonza replies yes |  |
| Sat 13:58 | floor_clean | start | by Gonza's yes, floor_at 2026-10-24T14:35:00-03:00 |
| Sat 13:58 | floor_clean | dry run vacuum.start vacuum.xiaomi_ov71gl_0681_robot_cleaner | (floor clean before tummy time around 14:35, Gonza's yes) |
| Sat 14:03 | supplies | low | item formula, left 170, per_day 135.2 |
| Sat 14:03 | supplies | dry run todo.add_item todo.shopping_list | {"item": "Formula", "description": "About 170 ml left, 135.2 ml a day, runs out around Sun 20:13"} (formula running low) |
| Sat 14:03 | supplies | message to Gonza (telegram) | Formula added to the shopping list. About 170 ml left, 135.2 ml a day, runs out around Sun 20:13. |
| Sat 14:30 | house | Someone turns off the bedroom TV |  |
| Sat 14:51 | nap_mode | on | nap started, the house goes quiet |
| Sat 14:51 | nap_mode | dry run switch.turn_on switch.gonza_s_echo_dot_do_not_disturb | (nap started at 14:51) |
| Sat 14:51 | nap_mode | white noise on (simulated device) | crib_db 48.1, reason nap started at 14:51 |
| Sat 16:28 | nap_mode | off | nap ended, the house goes back |
| Sat 16:28 | nap_mode | dry run switch.turn_off switch.gonza_s_echo_dot_do_not_disturb | (he woke up, nap since 14:51) |
| Sat 16:28 | nap_mode | white noise off (simulated device) | crib_db 0.0, reason he woke up, nap since 14:51 |
| Sat 16:35 | house | A courier rings the doorbell while he is awake |  |
| Sat 16:35 | door | announce | source doorbell |
| Sat 16:35 | door | dry run notify.send_message notify.gonza_s_echo_dot_announce | {"message": "Someone is at the door."} (the doorbell rang) |
| Sat 17:18 | supplies | low | item diapers, left 16, per_day 8.2 |
| Sat 17:18 | supplies | dry run todo.add_item todo.shopping_list | {"item": "Diapers", "description": "About 16 left, 8.2 a day, runs out around Mon 15:56"} (diapers running low) |
| Sat 17:18 | supplies | message to Gonza (telegram) | Diapers added to the shopping list. About 16 left, 8.2 a day, runs out around Mon 15:56. |
| Sat 17:40 | nap_mode | on | nap started, the house goes quiet |
| Sat 17:40 | nap_mode | dry run switch.turn_on switch.gonza_s_echo_dot_do_not_disturb | (nap started at 17:40) |
| Sat 17:40 | nap_mode | white noise on (simulated device) | crib_db 48.1, reason nap started at 17:40 |
| Sat 18:47 | nap_mode | off | nap ended, the house goes back |
| Sat 18:47 | nap_mode | dry run switch.turn_off switch.gonza_s_echo_dot_do_not_disturb | (he woke up, nap since 17:40) |
| Sat 18:47 | nap_mode | white noise off (simulated device) | crib_db 0.0, reason he woke up, nap since 17:40 |
| Sat 19:55 | nap_mode | on | sleep started, the house goes quiet |
| Sat 19:55 | nap_mode | dry run switch.turn_on switch.gonza_s_echo_dot_do_not_disturb | (sleep started at 19:55) |
| Sat 19:55 | nap_mode | white noise on (simulated device) | crib_db 48.1, reason sleep started at 19:55 |
| Sat 20:30 | house | Someone turns on the living room TV |  |
| Sat 20:30 | nap_mode | dry run media_player.volume_mute media_player.lg_webos_tv_oled55b3psa | {"is_volume_muted": true} (living room TV turned on while he sleeps) |
| Sat 21:20 | nap_mode | off | sleep ended, the house goes back |
| Sat 21:20 | nap_mode | dry run media_player.volume_mute media_player.lg_webos_tv_oled55b3psa | {"is_volume_muted": false} (he woke up, sleep since 19:55) |
| Sat 21:20 | nap_mode | dry run switch.turn_off switch.gonza_s_echo_dot_do_not_disturb | (he woke up, sleep since 19:55) |
| Sat 21:20 | nap_mode | white noise off (simulated device) | crib_db 0.0, reason he woke up, sleep since 19:55 |
| Sat 22:10 | nap_mode | on | sleep started, the house goes quiet |
| Sat 22:10 | nap_mode | dry run media_player.volume_mute media_player.lg_webos_tv_oled55b3psa | {"is_volume_muted": true} (sleep started at 22:10) |
| Sat 22:10 | nap_mode | dry run switch.turn_on switch.gonza_s_echo_dot_do_not_disturb | (sleep started at 22:10) |
| Sat 22:10 | nap_mode | white noise on (simulated device) | crib_db 48.1, reason sleep started at 22:10 |
| Sat 23:00 | house | Someone turns off the living room TV |  |
| Sun 00:04 | nap_mode | night wake stays quiet | detail a night wake-up, the house stays quiet until morning |
| Sun 06:43 | nap_mode | off | sleep ended, the house goes back |
| Sun 06:43 | nap_mode | dry run switch.turn_off switch.gonza_s_echo_dot_do_not_disturb | (he woke up, sleep since 22:10) |
| Sun 06:43 | nap_mode | white noise off (simulated device) | crib_db 0.0, reason he woke up, sleep since 22:10 |

## Run it

```bash
.venv/bin/python scripts/house_day_sim.py
```

The same day is a test: `tests/test_day_engine.py` (SimulatedDayTest).
