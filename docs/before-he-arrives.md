# Before he arrives (issue #56)

Theo is due around mid December 2026. Until then the family agent (@home_agent_example_bot) helps Gonza and Ceci get ready, so they use it every day from now and not only after the birth. Built during the Meta hackathon, Oct 28 2026. a usage goal scores it from the agent's own log.

Everything here is logistics: what to buy, build, place, pack, and when. The agent never gives medical advice. An appointment keeps only what, when, where and what to bring, and a title or note with medical words is refused with "I keep only the logistics".

## What the agent can do

| Ask | Tool | Writes |
|---|---|---|
| "What is next?", "how many days left?" | `prep_next` | nothing |
| "Show the hospital bag list" | `prep_list` | nothing |
| "We bought the MAX98357A amplifier", "the crib is up" | `prep_check` | the agent's memory file |
| "Add hair ties to the hospital bag" | `prep_add` | the agent's memory file |
| "Hospital tour Nov 3 at 10, main entrance, bring IDs" | `add_appointment`, `appointments`, `cancel_appointment` | the agent's memory file |
| "Theo is due Dec 12" | `set_due_date` | the agent's memory file |
| "Where should the shelf go?" | `nursery_plan` | nothing |
| "Put the car seat list on our to-do list" | `prep_to_home_assistant` | Home Assistant, only after a yes, and a dry run while `house.live` is false |

`prep_to_home_assistant` is never on the allowed list. The plug-in takes it off if a config adds it, so the agent always asks first. With `house.live` false every item becomes a `house_call` event with status `dry` and nothing changes in the house.

## The four lists

| List | Items | From |
|---|---|---|
| Car seat | 10: check the Litetrax box has the i-Snug 2 carrier, buy, read the belt install section, pick the rear seat, first install with the car seat coach after the Model 3 arrives on Nov 5, hand checks, a certified technician, practice, recall registration | `skills/carseat/joie-i-snug-2.json`, `skills/carseat/tesla-model-3.json`, `docs/car-seat-coach.md`, `docs/tesla.md` |
| Nursery | 12: layout, crib, dresser with changing mat, anchoring, walkway, shelf, rocker, rug, bins, the night feed light, the heater, the white noise spot | the home twin's nursery plan (`a private project/docs/nursery-plan.html`, prior work, Sep 2026) |
| White noise machine | 10: the ESP32-S3 board and the USB-C supply are in hand, buy the MAX98357A and a 3 W 4 ohm speaker, breadboard, pick the sound with Ceci, ESPHome, measure 50 dB at the crib, enclosure, the bedtime automation | `parenting_agent/white_noise.py` |
| Hospital bag | 11: ask the hospital first, IDs and the health provider card, papers, chargers, clothes for both, Theo's going home outfit, diapers if asked, snacks, payment for parking, the car seat in the car | logistics only |

Hospital bag items are due a set number of days before the due date, so they move when a parent sets the real date. The other items have fixed dates, the car seat ones around the Model 3 arriving on Nov 5.

## The nursery from the home twin

`parenting_agent/prep/nursery.py` holds the study's measured size (3.60 x 1.85 m) and the two layouts of the nursery plan, and checks them:

| Check | Layout A, desk on the inner wall | Layout B, desk at the window |
|---|---|---|
| Walkway between dresser and crib | 70 cm, pass | 70 cm, pass |
| Door swing | dresser starts 82 cm from the door wall, the door swings 80 cm, pass | same, pass |
| Nothing on the wall above the crib | the shelf is clear, pass | the shelf hangs 60 cm over the crib's end, fail |
| White noise machine 2 m from the crib | the farthest floor spot is 187 cm away, fail | same, fail |

The last line is a real finding: in a 3.60 x 1.85 m room no floor spot is 2 m from the crib. The machine goes in the far corner by the window, and the 50 dB cap is set by measuring at the crib, which is the rule that matters. These are geometry checks on the plan's numbers, not a check of the real room.

## The morning nudge

Once a day between 08:00 and 11:00 local time the agent sends Gonza a short message: the countdown, the next appointment in the coming 7 days, and the next three open items. It goes only to the first chat id in `TELEGRAM_CHAT_ID`. The day it was sent is in `data/prep-nudge.json`, so a restart never sends it twice. It is built from the lists, with no brain call.

```
Good morning. About 48 days to the due date, Dec 15 (an estimate).
Next up:
- Check the Litetrax box carries the i-Snug 2 carrier (EU and NZ) and not the Gemm (US): the coach's profile is the i-Snug 2
- Buy the Litetrax travel system (Gonza buys, the agent never pays)
- Read the 'Installation without base' part of the manual
Tell me when one is done, or ask what is next.
```

The nudge is in Spanish when most of the family's recent messages are, or when the config sets `"prep": {"lang": "es"}` (`"en"` forces English). The items read in Uruguayan Spanish, with cédula, mutualista and sanatorio, and an item a parent added or reworded keeps its own words. The brain is told to use the same words in Spanish answers (issue #77):

```
Buen día. Unos 47 días para la fecha de parto, el 15 de diciembre (estimada).
Lo que sigue:
- Revisar que la caja de la Litetrax traiga el huevito i-Snug 2 (Europa y Nueva Zelanda) y no el Gemm (EE.UU.)
- Comprar el sistema de viaje Litetrax (lo compra Gonza, el agente nunca paga)
- Leer la parte 'instalación sin base' del manual
Avisame cuando hagas uno, o preguntame qué sigue.
```

## Who used it, for the scorer

- Each family chat is tied to a person in the config (`people`): Gonza is `TELEGRAM_CHAT_ID`, Ceci is `TELEGRAM_CECI_CHAT_ID`. A chat id given to both belongs to neither.
- Every message gets a `turn` event in `data/events.jsonl`: channel, person, whether the agent answered, and `test` when the text starts with "Test:". The agent answers the words after "Test:", the marker never reaches the brain.
- Every prep change is a `prep` event with the person.
- At start the Telegram channel logs `family_channels`, for example `{"ceci": true, "gonza": true}`. A person whose chat id is not set shows as not connected.
- Replies go back to the chat that asked, so two parents on one bot each get their own answer.

## Check it

```bash
python -m parenting_agent.prep show --config config/agent.vostro.json                      # what the nudge would say, no brain key or Baby Buddy needed
python -m parenting_agent.prep ask "Test: what is next?" --config config/agent.vostro.json # one turn through the brain, nothing sent
python -m parenting_agent.prep nudge --send --config config/agent.vostro.json              # one nudge to Gonza now
.venv/bin/python -m unittest tests.test_prep -v
```

On the Vostro, prefix with `docker exec parenting-agent`.

## Ceci's channel

Ceci is connected to the family bot. Her chat id is set on the Vostro as `TELEGRAM_CECI_CHAT_ID`, and the agent's `family_channels` event on Oct 29 shows `{"ceci": true, "gonza": true}`. Her messages are `turn` events with person `ceci`, and her replies go back to her own chat.

Since Oct 30 the pushes the agent starts on its own reach the person they are for, in their own chat, with names instead of "Parent A" and "Parent B" (`parenting_agent/channels/push.py`):

| Push | Who gets it |
|---|---|
| The morning message (from Oct 31): the brief, the night explanation and the prep nudge merged into one short message per parent with only what is theirs (`parenting_agent/channels/morning.py`) | both, each their own text |
| Supplies, tonight's plan at bedtime, a re-plan | both |
| The night feed push, and anything else between 22:00 and 06:00 | the parent on duty from the night rota |
| A parent's own line in tonight's plan | that parent |
| A question that waits for a yes ("Reply yes to start it") | one parent: the one on duty at night, Gonza by day. Only that parent's yes answers it |
| A reminder ("recordame en 20 minutos ...", the `remind_me` tool) | whoever asked |

A question the agent asked in one parent's chat is answered only from that chat: the other parent's "sí" runs nothing. "¿Quién está de turno esta noche?" is answered from the night rota by name, with how the rota decides (fewer night wake-ups takes the next one, a tie goes to whoever did not take the last one), with no brain call. The router's partner route sends to the other parent's chat when the config has a people block with that chat. The router is not loaded on the Vostro, and the Mac config (`config/agent.json`) has no people block yet, so there it still only records `partner_stub`.

Every push is a `pushed` event (who got it and why) and a `reply` event with `proactive` true and the person. The house plans before each nap stay in the event log only, as before, so a day does not bring six of them. Open reminders live in `data/reminders.json`, so a restart keeps them.

To change her chat id: put it in the meta-hackathon `.env` as `TELEGRAM_CECI_CHAT_ID`, then `sh deploy/agent.sh push-env` and `sh deploy/agent.sh update`.
