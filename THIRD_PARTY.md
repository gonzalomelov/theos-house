# Third-party models, SDKs and data

Built with Muse Spark Open.

## Which license covers what

The `LICENSE` file (MIT) covers only the code and docs written in this repo. It does not cover any model, SDK, service or data listed below. Each of those keeps its own terms, and anyone who runs this project agrees to them separately.

This repo ships one small set of weights of its own, the cry reason head (`parenting_agent/assets/cry_reason_head.json`, 5 x 2048 numbers), trained here on the Donate-a-Cry corpus, listed under Data. The agent no longer runs it since Oct 31 2026, it is kept to reproduce the Oct 30 result. Otherwise it does not ship any model weights or SDK binaries. Weights are downloaded at setup time by the scripts named below or baked into the voice image at build time, the iOS SDK is fetched by Xcode, and Muse Spark Open is called through Baseten's API.

Why MIT: our own code has no reason to be more restrictive than the parts it calls, and a permissive license keeps it compatible with all of them. MIT does not grant any rights in the third-party parts. In particular, using the glasses app means accepting the Meta Wearables Developer Terms, running SAM 3.1 means accepting the SAM License, and the MMS-TTS voice is CC BY-NC 4.0, which limits commercial use of that part even though the code calling it is MIT.

Checked against origin/main on Oct 28 2026. Licenses were read from the linked pages that day. This is a summary, not legal advice. The linked terms are what counts.

## Models

| Model | Used for | Where it runs | License | Link |
|---|---|---|---|---|
| Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten) | The agent's brain | Baseten's API, weights not in this repo | Muse Model License, Muse Spark Open version (Oct 15 2026) with its Usage Policy. It asks for "Built with Muse Spark Open" to be shown in the product or its docs | https://huggingface.co/meta-models/Muse-Spark-Open-816B-A42B |
| SAM 3.1 (`facebook/sam3.1`, falls back to `facebook/sam3`) | Confirms or cancels the hand alarm, car seat visible checks | The Mac's GPU, weights downloaded from Hugging Face (gated) by `parenting_agent/sam3_worker.py` | SAM License (Meta, Nov 19 2025) | https://huggingface.co/facebook/sam3.1 and https://github.com/facebookresearch/sam3 |
| SAM 3 code at commit `7f473cf` | The code that runs SAM 3.1 | Fetched and patched for MPS by `scripts/sam3-setup.sh`, not in this repo | SAM License | https://github.com/facebookresearch/sam3 |
| Perception Encoder Audio Frame small (`facebook/pe-a-frame-small` at `e5fc71c`) | House sound labels: cry, doorbell, dog, splash, zero shot from text prompts | The Mac's CPU in `parenting_agent/hearing_worker.py`, weights fetched and SHA-256 checked by `scripts/hearing-setup.sh`, not in this repo | Apache 2.0 (Meta) | https://huggingface.co/facebook/pe-a-frame-small |
| PANNs CNN14 16 kHz | Not called by the agent since Oct 31 2026. Offline only, the before baseline in `scripts/panns_baseline.py` and the Oct 30 cry head training | The Mac, fetched by `scripts/fetch-panns.sh` | Code MIT, weights CC BY 4.0 (Kong et al.) | https://github.com/qiuqiangkong/audioset_tagging_cnn and https://zenodo.org/records/3987831 |
| MediaPipe hand landmarker | The hand reflex, in the prior work library `a private repo`. Optional: `"hands": "sam3_only"` (or a clone without that library) runs SAM 3.1 alone with no MediaPipe | The Mac, fetched by `scripts/fetch-models.sh` | Apache 2.0 | https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker |
| MediaPipe EfficientDet-Lite0 object detector | Object boxes for the reflex | The Mac, fetched by `scripts/fetch-models.sh` | Apache 2.0 | https://ai.google.dev/edge/mediapipe/solutions/vision/object_detector |
| Muse Spark Open, audio input | Hears Telegram voice notes (`parenting_agent/voice/ear.py`). Speech only: it does not hear beeps or house sounds well enough to use (`results/audio-truth/README.md`) | Baseten's API | Same as above | Same as above |
| MMS-TTS (`facebook/mms-tts-spa` at `833b96c`, `facebook/mms-tts-eng` at `c71de0f`) | The agent's spoken answers | The Mac, or the voice container on the Vostro where `deploy/voice/Dockerfile` bakes the weights in at build | **CC BY-NC 4.0, non-commercial only** (Meta, Massively Multilingual Speech) | https://huggingface.co/facebook/mms-tts-spa and https://huggingface.co/facebook/mms-tts-eng |

## SDKs and libraries

| Name | Used for | License | Link |
|---|---|---|---|
| Meta Wearables Device Access Toolkit for iOS 1.0.1 (DAT, with MockDeviceKit) | The glasses app in `apps/glasses` | Meta Wearables Developer Terms and Acceptable Use Policy | https://github.com/facebook/meta-wearables-dat-ios and https://wearables.developer.meta.com/terms |
| MediaPipe 0.10.14 (Python) | Runs the hand and object models | Apache 2.0 | https://github.com/google-ai-edge/mediapipe |
| OpenCV (`opencv-contrib-python` 4.10.0.84) | Video and image handling | Apache 2.0 | https://github.com/opencv/opencv-python |
| NumPy below 2 | Arrays | BSD 3-Clause | https://github.com/numpy/numpy |
| PyTorch 2.15.0 (CPU), Hugging Face Transformers 5.21.0 | Runs MMS-TTS in the voice image | BSD-style, Apache 2.0 | https://github.com/pytorch/pytorch and https://github.com/huggingface/transformers |
| FFmpeg (Debian bookworm package, with libopus) | Converts voice notes to WAV and answers to OGG Opus | LGPL 2.1 or later, GPL parts in the Debian build | https://ffmpeg.org/legal.html |
| PyTorch 2.8.0, torchvision 0.23.0 and the other packages in `scripts/sam3-setup.sh` | The separate SAM 3.1 environment | Each package's own license (PyTorch is BSD-style) | https://github.com/pytorch/pytorch |
| PyTorch, Hugging Face Transformers 5.21.0, safetensors in `scripts/hearing-setup.sh` | The separate hearing environment that runs Perception Encoder Audio | BSD-style, Apache 2.0, Apache 2.0 | https://github.com/huggingface/transformers |

## Services and self-hosted apps

| Name | Used for | License or terms | Link |
|---|---|---|---|
| Baseten | Hosts Muse Spark Open, on the hackathon's free credits. Meta said content sent on those credits may be used to train future Meta models, so messages, tool results and voice notes sent there are not promised to stay private | Baseten terms, and the hackathon credit terms | https://www.baseten.co |
| Baby Buddy | The baby log, self-hosted on the family server | BSD 2-Clause | https://github.com/babybuddy/babybuddy |
| Home Assistant | The house: lights, speakers, vacuum | Apache 2.0 | https://github.com/home-assistant/core |
| Telegram Bot API | The phone channel and the families bot | Telegram terms | https://core.telegram.org/bots/api |

## Data and documents

| Item | Used for | License or status | Link |
|---|---|---|---|
| Newborn crying sound, Wikimedia Commons | House sound test (`results/sounds/run.json`), audio not in this repo | CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Newborn_baby_crying_sounds_20190831_061900.wav |
| Doorbell sound, Wikimedia Commons | House sound test, audio not in this repo | Public domain | https://commons.wikimedia.org/wiki/File:Doorbell-cheap-dingdong.ogg |
| The 48-clip licensed hearing set (meta-hackathon-2026 `muse/data/hearing_sources.json`, Wikimedia Commons, each clip's license listed there) | Tune and held-out sets of the Meta listener swap (`results/sounds/meta-hearing/split.json`, file names and labels only), audio not in this repo | Public domain, CC0, CC BY 2.0 to 4.0, CC BY-SA 3.0 and 4.0, per clip | https://commons.wikimedia.org |
| Donate-a-Cry corpus (cleaned set, commit 6baf5ac) | Training and held-out test of the cry reason head, and the cries of the Meta listener test (`results/sounds/meta-hearing/split.json`, file names only). The head in `parenting_agent/assets/cry_reason_head.json` is a Produced Work of this database: it contains information from the Donate-a-Cry corpus, which is made available under the Open Database License (ODbL) 1.0. Audio not in this repo, the file names and tags are listed in `results/cry-reason/split.json` | ODbL 1.0, contents DbCL 1.0 | https://github.com/gveres/donateacry-corpus |
| Baby crying recordings cry-01 (public domain) and cry-04 (CC BY-SA 4.0), Wikimedia Commons | The live cry run (`results/cry-reason/live.json`), audio not in this repo | Public domain, CC BY-SA 4.0 | https://commons.wikimedia.org/wiki/File:Baby_long_wanting_cry.ogg |
| Joie i-Snug 2 instruction manual | Car seat steps and limits in `skills/carseat/joie-i-snug-2.json`, written in our words with the manual's URL and hash. The PDF is not in this repo | Joie's document, all rights with Joie | https://dl.joiebaby.com/Instruction_Manual/GL/i-Snug-2/Joie-carseat-i-snug-2-instruction-manual.pdf |
| Tesla child seat pages | Car rules in the simulated Tesla | Tesla's published pages, linked not copied | https://www.tesla.com |

## Media committed in this repo

All of it is synthetic or rendered, no family audio, photo or video. Checked on Oct 30 2026, the largest file is 2.5 MB.

| Files | Made with | Terms that apply |
|---|---|---|
| `results/voice/notes/*.ogg` | macOS `say` (Apple system voices Samantha, Daniel, Paulina, Mónica) reading scripted lines | Apple's macOS license allows system voice output for personal, non-commercial projects |
| `results/voice/reply-*.ogg`, the car seat lines in `results/hero2/carseat.mp4` | MMS-TTS | CC BY-NC 4.0, non-commercial only |
| `results/hero/speech/*.wav`, the glasses voice in `results/hero*/` videos | iOS AVSpeechSynthesizer in the simulator | Apple's SDK and simulator terms |
| `results/hero*/`, `results/glasses/` videos and screenshots | Screen recordings of the iOS simulator with DAT's mock device playing generated clips | Meta Wearables Developer Terms for the mock device, our own clips |
| `results/glasses-live/*.png` | Screenshots of the iOS simulator with DAT's mock device and MockDisplayKit playing generated clips and, in, a Wikimedia Commons photo by Wang Yu Ching, Office of the President (Taiwan), credited on screen | Meta Wearables Developer Terms for the mock device, our own clips, CC BY 2.0 for the photo |
