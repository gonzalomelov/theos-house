# SAM 3.1 on this Mac

The changing-table skill asks Meta's SAM 3.1 whether a hand really touches the baby or only hovers above it. SAM 3.1 runs here from Meta's open weights, on the Mac's GPU, so frames never leave the house.

## Setup, once

`scripts/sam3-setup.sh` builds a separate Python environment with PyTorch and the SAM 3 code, pinned to one commit, plus the small changes it needs to run without an NVIDIA GPU. It needs a Hugging Face read token at `~/.cache/huggingface/token` with access to `facebook/sam3.1` (the weights are cached in `~/.cache/huggingface`).

```bash
scripts/sam3-setup.sh          # default location ~/Engineering/gonza/sam3-native
```

## How the skill uses it

`parenting_agent/sam3_local.py` starts `parenting_agent/sam3_worker.py` in that environment once, when the skill arms. The worker loads SAM 3.1 (about 7 s), then answers one frame at a time through a local pipe: about 1.5 s per frame on an M3 Max. It finds the hands and the baby by text, and a hand counts as on the baby when enough of the ring of pixels around it is baby. If the environment or the token is missing, the skill fails at start with a clear reason, never in the middle of a change.

The local reflex still raises the alert first, in well under a second. SAM 3.1 then confirms or cancels it.
