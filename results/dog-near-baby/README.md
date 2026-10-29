# Dog near the baby, Oct 29 2026

Issue #109, built and scored on Oct 29 2026 during the Meta hackathon. Gonza has dogs. The watch warns the parents when a dog is close to the baby, and never on a dog alone.

## How it works

`parenting_agent/dog_watch.py`, plug-in `parenting_agent.dog_watch:DogWatch`.

1. Cheap gate: the C200 sofa camera's ONVIF motion and person sensors in Home Assistant, plus a snapshot every 30 s so a dog that trips no sensor is still seen.
2. SAM 3.1 on the Mac with the prompts "dog", "baby", "bassinet" and "play mat". The baby's area is the baby mask plus any bassinet or play mat that overlaps it. The gap is the shortest pixel distance from a dog mask to that area, divided by the baby's size (square root of the baby mask's area), so the threshold means the same near or far from the camera.
3. Rule: a dog and a baby (score at least 0.6) both in view, and the dog touches the baby's area or is within 0.5 baby sizes of it. No baby, no alert.
4. Alert: Telegram to `TELEGRAM_CHAT_ID` only, "Dog close to Theo in the living room", and the kitchen Echo announce, a dry run while `house.live` is false. One alert per room per 5 minutes.

Frames come from Home Assistant's camera proxy into memory and are never written to disk. The last 4 sit in a deque and are dropped as new ones arrive. A unit test fails if a look opens a file.

## Home Assistant, read only (Oct 29)

One `GET /api/states`, answered 200. No pet sensor exists for any camera.

| Camera | What Home Assistant has |
|---|---|
| C200 sofa, living room | `binary_sensor.tapo_c200_sofa_onvif_cell_motion_detection` and `..._onvif_person_detection` work (off at the time). The Tapo integration's own motion and person sensors are unavailable. `switch.tapo_c200_sofa_smart_track_pet` is pan and tilt tracking, not a sensor. Baby cry detection is off |
| C100 kitchen | Unavailable, all entities |
| C200 barbecue, outdoor | Person detection on, motion detection off, no pet sensor |

So the gate is ONVIF motion and person plus the low-rate snapshot. Pet detection would need the Tapo app's pet setting surfaced by the integration, which it is not.

## The set

Wikimedia Commons photos with free licenses (public domain, CC0, CC BY, CC BY-SA), labeled by hand, plus composites. Kept in `~/Engineering/gonza/pa-local-data/dog-near-baby`, never committed. `sources.json` lists every photo used with its license, author and page. `labels.json` and `set.sha256` are the frozen labels and hashes.

- Photos: 16 near, 1 far, 39 with a dog and no baby (including a dog in a stroller, a dog in a diaper, a dog with a kitten, sea otter pups, empty nursery scenes), 15 with a baby and no dog. Near means the dog touches the baby or is within about half a baby size. Most near photos show toddlers or babies in old black-and-white photos, not a newborn seen by a living room camera. That is the set Commons has.
- Composites: 64 images, a dog cut out of a dog photo and a baby cut out of a baby photo, pasted on a room photo at 1280 x 720, gap set by construction: near is 0 to 0.3 baby sizes, far is 1.5 to 3.5 baby sizes, plus 8 dog only and 8 baby only. The cutouts come from SAM 3.1 masks, so composites favour SAM. Photos are the harder test.

The split (seed 1029, half and half per label and kind) was frozen and committed (fe10894) before any dev run. The dev run picked the design (39511a5). The blind split was then run once.

## Result

Only "near" should alert. Everything else alerting is a false alert. Real time on the M3 Max, SAM 3.1 sharing the GPU with another agent's SAM 3.1 run, so latency is pessimistic.

| Split | Caught | Missed | False alerts | Latency per look, median and p90 | File |
|---|---|---|---|---|---|
| Dev, first design (baby score 0.5) | 19 of 20 | 1 | 1 of 46 | 5.18 s, 6.71 s | `dev.json` |
| Dev, final design (baby score 0.6) | 19 of 20 | 1 | 0 of 46 | 2.37 s, 4.91 s | `dev-final.json` |
| **Blind, final design, one run** | **15 of 20** | **5** | **0 of 49** | **3.01 s, 4.73 s**, max 6.65 s | `blind.json` |
| Blind photos only | 3 of 8 | 5 | 0 of 29 | | |
| Blind composites only | 12 of 12 | 0 | 0 of 20 | | |

- No false alert on blind: 0 of 24 dog-without-baby images, 0 of 13 far, 0 of 12 baby-without-dog.
- All 5 blind misses are the same failure: SAM 3.1 did not call the child "baby" at 0.6 (scores 0.425 to 0.586, one none). They are toddlers in old photos. 3 of the 5 scored between 0.5 and 0.6, so the dev change from 0.5 to 0.6, made to drop a dog-with-kitten false alert, cost 3 blind catches. The design stays as frozen. The real check is a newborn on a play mat on Gonza's camera, which this set cannot give before Theo arrives.
- The dev miss is a baby in a pram with two shepherds beside it: the pram was not counted as the baby's area.
- Threshold sweep on dev: any near ratio from 0.3 to 0.75 gives the same result, so 0.5 is not on a knife edge.

## Live camera path (Oct 29, 12:26)

`scripts/dog_watch_live.py --test-alert`, read only in Home Assistant, frame never saved.

| Step | Result |
|---|---|
| Gate | Both ONVIF sensors off, gate said "snapshot" |
| Frame | 1920 x 1080 from `camera.tapo_c200_sofa_hd_stream` through the camera proxy, 4.24 s |
| SAM 3.1 | 3.03 s, no dog and no baby in view, verdict no_baby, no alert |
| Test alert | Telegram to Gonza's chat in 0.82 s, text marked as a test. Echo announce: `house_dry`, nothing played |

End to end a look is about 7 s today: the camera proxy fetch is the slow half. Reading the RTSP stream directly (as house sounds does) would cut it.

## What runs 24/7, honestly

Nothing here runs 24/7 yet. The watch runs when the Mac runs it.

- SAM 3.1 needs the Mac's GPU. The Mac sleeps and travels, so it is not a full-time watcher.
- The Vostro is always on but has a 2-core i5-6200U, 7.5 GB of RAM and no GPU. SAM 3.1 was not tried there tonight, so there is no number. Expect it to be much slower than on the Mac, and memory is tight next to the family agent.
- The gate (Home Assistant sensors) is cheap and could run on the Vostro full time today.
- For SAM 3.1 full time, the house needs a machine with a GPU that stays on: an always-on Apple silicon Mac (a Mac mini would do what the M3 Max does here, latency not measured) or a small NVIDIA box. The gate would wake it only on motion, so it idles most of the day.
- Until then: run the watch on the Mac while it is home and awake, and say so in the app.

## Reproduce

```bash
D=~/Engineering/gonza/pa-local-data/dog-near-baby
mkdir /tmp/pa-gpu.lock
python scripts/dog_watch_set.py --data $D                      # builds the set, needs the photos in $D/commons
(cd $D && shasum -a 256 -c path/to/results/dog-near-baby/set.sha256)
python scripts/dog_watch_eval.py --set $D --split dev --out dev-final.json --sweep
python scripts/dog_watch_eval.py --set $D --split blind --out blind.json
python scripts/dog_watch_live.py --env PATH/.env                # one live look, add --test-alert for one Telegram test
rmdir /tmp/pa-gpu.lock
```
