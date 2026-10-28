# The daily house plan: vacuum, shopping list, dinner and white noise (issues #29 and #32)

Built during the Meta hackathon, Oct 28 2026. The agent runs the robot vacuum, the shopping list and the parents' dinner around the baby, from the baby log. Gonza presses as few buttons as possible. The Thermomix itself is never controlled: Vorwerk allows no remote start, a person presses the dial.

## What it does

| Part | What the agent does |
|---|---|
| Nap starts | The vacuum is paused and sent to its base, alone. Also when a predicted nap is 5 min away |
| Vacuum start | Never when the run (31 min, the last real run took 1860 s) plus 10 min would reach a predicted nap window, not even after a parent's yes. Alone only when nobody is home or the baby is out. Otherwise it asks: "I can run the vacuum now. It takes 31 min, done before the nap around 10:32. Reply yes to start it." |
| Daily run | One a day in the longest awake stretch between 08:00 and 19:00, the quietest awake time. Ties go to the stretch nearest 10:30. The slot moves when the rhythm moves |
| "Clean under the high chair" | A room clean of the dining room (`vacuum.clean_area` with the Home Assistant area). A mess in the log ("Food mess under the high chair", "Crumbs on the sofa") does the same within 2 hours |
| Running low | Diapers, wipes and formula from a "Stock: diapers 40" note in the log and the use since then, rate over the last 3 days. At 2 days left the item goes on `todo.shopping_list` with how many are left and when they run out |
| Bad night | 4 or more night wake-ups, or a longest night sleep under 1.5 h: in the morning a draft of two fast Thermomix dinners (30 min or less) from Cookidoo and a Telegram-ready message. Nothing is written to Cookidoo |
| Dinner timing | Between 17:30 and 21:00, when he is awake and the next predicted sleep leaves room for the recipe: "He is awake, until the sleep around 19:44. A good moment to start Cogumelos salteados (20 min). The Thermomix waits for your press of the dial." |
| White noise | On 5 min before each predicted nap and at bedtime (20:30), timer down once he sleeps, through the `WhiteNoisePlan` from #32. The 50 dB cap at the crib stays in code. When house sounds is loaded it drives the device and the house plan only lists the schedule |

Predicted nap windows chain forward from the last wake-up with his usual awake time and usual sleep length over the last two days, day and night apart. A sleep that is still going on counts as a window until its usual length.

## Action policy in code

`HouseWriter` in `parenting_agent/house_plan.py` is the only door to Home Assistant writes. It knows six writes and raises on anything else before a request is built:

| Write | Entity |
|---|---|
| `vacuum.pause`, `vacuum.return_to_base`, `vacuum.start`, `vacuum.clean_area` | `vacuum.xiaomi_ov71gl_0681_robot_cleaner` |
| `todo.add_item`, `todo.remove_item` | `todo.shopping_list` |

Anything with "thermomix" or "cookidoo" in the service or entity is refused. Without `live: true` and a Home Assistant token every write is a dry run, a `house_dry` event with the exact request.

Brain tools: `vacuum_dock` (pause and home), `vacuum_start` (with an optional place, for "clean under the high chair") and `house_plan_today`. `vacuum_start` is not on the allowed list, so the brain asks the parent first, and its handler still refuses a run that would reach a nap.

Unknown presence never counts as away. A person with no phone in Home Assistant is `unknown`, and the agent asks before any start unless the log says the baby is out ("Out with the baby", then "Back home").

## Cookidoo, read only

Fast recipes come from Cookidoo through home-agents (a private repo, fridge-plan), not a new client. `scripts/fast_recipes.py` runs in the home-agents virtual environment and reuses its `Cookidoo` client with the hard-coded read allowlist, its recipe parser and its dinner filter. It calls only `search_recipes` and `get_recipe_details`. Writing the draft into the Cookidoo meal plan needs a write tool that home-agents keeps locked on purpose. This item does not widen that allowlist.

```bash
~/Engineering/gonza/home-agents/.venv/bin/python scripts/fast_recipes.py --max-min 30   # run from the home-agents folder
```

`results/house-plan/fast-recipes.json` and `tests/fixtures/fast_recipes.json` are one real read-only run of Oct 28.

## Run it in the agent

Add `"parenting_agent.house_plan:HousePlanPlugin"` to `plugins`, with settings under `"house_plan"`, for example `{"live": false, "supplies": {"diapers": 40}, "recipes": "home-agents"}`. The log comes from the `"rhythm"` block, like the daily rhythm.

## Checks

Simulated week (`tests/test_house_plan.py`, 5 min ticks, a parent who says yes to every question, and one run a day started by hand in the Xiaomi app 15 min before a nap):

| Check | Result |
|---|---|
| Vacuum starts inside a predicted nap window | 0 of 8 starts |
| Runs started by hand before a nap, paused and docked within one tick of falling asleep | 6 of 6 |
| Started alone | 2, both while nobody was home or the baby was out |
| Daily run | one a day, the slot moved 5 times when the rhythm shifted |
| "Food mess under the high chair" | `vacuum.clean_area` with `dining_room` |
| Diapers, 40 in stock | on the list Fri 04:30 with 16 left, the 40th is used Sun 03:46 |
| Bad nights | Fri 23 and Sat 24 (4 wake-ups each), each with two fast recipes in the draft |
| White noise | 36 times on in the week, never above 48.1 dB at the crib |

Live check on the real house (`scripts/house_plan_check.py`, evidence in `results/house-plan/live-check.json`): reads the vacuum and presence, dry runs pause, return to base and the room clean, adds one test item to `todo.shopping_list` and removes it. It never starts the vacuum.

## Open

- The S40 Pro in Home Assistant has no `clean_area` support (supported features 12732, the area feature is 16384). A room clean asks to run the whole house instead until its rooms are mapped to Home Assistant areas.
- Starting the vacuum alone when nobody is home or the baby is out is a policy change that needs Gonza's OK. Until then keep `vacuum_start` off the allowed list and `live` off.
- Writing the meal plan to Cookidoo needs Gonza to decide on a write tool in home-agents.
