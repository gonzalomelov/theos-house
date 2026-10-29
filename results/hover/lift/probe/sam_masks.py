import json, sys, time
from pathlib import Path
PA = Path.home() / "Engineering/gonza/parenting-agent/parenting_agent"
sys.path.insert(0, str(PA / "sam3_stubs")); sys.path.insert(0, str(PA))
import os; os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
import numpy as np, cv2
from PIL import Image
import sam3_worker as W
cfg = dict(W.DEFAULTS)
sam = W.Sam3(cfg)
FR = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(exist_ok=True)
for row in json.loads((FR / "index.json").read_text()):
    dst = OUT / (row["file"][:-4] + ".npz")
    if dst.exists(): continue
    f = cv2.imread(str(FR / row["file"]))
    t = time.monotonic()
    st = sam.processor.set_image(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
    out = {}
    for w in ("hand", "baby"):
        r = sam.processor.set_text_prompt(w, st)
        out[w] = r["masks"][:, 0].cpu().numpy().astype(bool)
        out[w + "_scores"] = r["scores"].float().cpu().numpy()
    np.savez_compressed(dst, **out, seconds=time.monotonic() - t)
    print(row["file"], out["hand"].shape[0], out["baby"].shape[0], round(time.monotonic() - t, 2), flush=True)
