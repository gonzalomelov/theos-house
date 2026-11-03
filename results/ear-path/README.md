# The Mac's ear

**Recordings, in memory, with the post counted (`recordings.json`):** 339 of 348 cries sent, 1 false of 51. This repeats the Oct 31 held-out set, so it checks the path and is not a new test.

**Real Tapo microphone, recordings played on the Mac's speakers (`microphone.json`):** 0 of 10 cries caught, 0 false of 10 others, 416 s of camera audio with no stall. This doesn't measure the model: the Mac played at 24% volume, away from the camera, and most clips barely rose above the room (baseline -71 dBFS, cries mostly around -65). It needs a loud source next to the camera. Nothing reached the core.

**The earlier hang:** ffmpeg logged the Tapo's timestamp errors many times a second into a stderr pipe nobody read, which filled and froze it for 3.5 hours. It now logs fatal errors only, and timed runs end themselves.
