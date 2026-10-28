# Bath skill

Issue #10. The second camera skill, on the same core as the changing table. The bath itself is config: `skills/bath.json` and one entry in `camera_skills` in `config/agent.json`. The head camera is the only camera, there is never a fixed camera in the bathroom.

## What it does

| Moment | What happens |
|---|---|
| The parent says "bath time" | The phrase arms the skill at once, without waiting for the brain. The routine reminder goes to the ear: water ready, towel within reach, nothing left on in the kitchen, keep a hand on the baby the whole bath. Notifications are held |
| Both hands leave the baby | The local reflex chimes within a second. SAM 3.1 on the Mac GPU confirms or cancels. It does not tell a 2 to 5 cm hover from a touch yet (`results/hover/README.md`, Oct 28). "hand" is spoken within 2.5 s. Calling the partner waits for the parent's yes |
| One hand stays on | Silent |
| The door, the phone, a timer, a forgotten towel | While the bath is on, a fact in the agent's prompt says never to suggest stepping away and never to offer to watch the baby. The agent offers "one moment" on the house speaker, holding notifications or calling the partner. If the parent must go, the baby comes out of the water with them |
| The parent says "bath done" | The bath is logged in Baby Buddy as a note that starts with "Bath", read back by id, and notifications are restored |

The skill only listens for the parent's hands. It never watches the baby in the parent's place. Every text in the skill file is checked when the agent starts (`implies_left_alone` in `parenting_agent/camera_skill.py`), so a file that says or implies the baby can be left alone fails at start. The live run checks every reply of the brain the same way.

## How a new camera skill is added

`parenting_agent/camera_skill.py` turns any skill file with an `agent` block into two tools, the arm and finish phrases, the reminders and the prompt facts. A new head-camera routine is a new skill file and one more entry in `camera_skills`.

## Run it on the clips

```bash
python scripts/bath_run.py --baths 10        # Claude brain, Baby Buddy, SAM 3.1, the bath clips streamed live
python scripts/bath_run.py --wipe-only       # remove the entries earlier runs wrote (tag bath-sim)
```

Each bath gets a fresh agent memory, then: "bath time", the clips in real time, one interruption (doorbell, towel, phone, oven timer, "can I leave her a second"), "bath done". It writes `results/bath/bath.json`.

Clips live in `~/Engineering/gonza/meta-hackathon-2026-synthetic/bath/clips`, generated or rendered only, never a real child:

| Clip | Kind | Origin |
|---|---|---|
| bath-handoff-01 | both hands off at 4.0 s | the generated bath clip, its last frame held 2.5 s so the scene goes on after the hands leave |
| bath-onehand-01 | one hand on throughout | rendered from the same clip: the hands-on seconds cropped so only one hand shows, forward then backward |

No generated clip yet shows one hand staying while the other leaves the baby in the water.
