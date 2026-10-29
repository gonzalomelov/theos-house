import sys, time, os
from pathlib import Path
PA = Path.home()/"Engineering/gonza/parenting-agent-worktrees/sam-essential/parenting_agent"
sys.path.insert(0, str(PA/"sam3_stubs")); sys.path.insert(0, str(PA))
import numpy as np, cv2, torch
from PIL import Image
import sam3_worker as W
sam = W.Sam3(dict(W.DEFAULTS))
f = cv2.imread(sys.argv[1]); img = Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
P = sam.processor
DT = {"fp16": torch.float16, "bf16": torch.bfloat16}[sys.argv[2]]
ctx = torch.autocast("mps", dtype=DT)
ctx.__enter__()
for rep in range(4):
    t=time.monotonic(); st=P.set_image(img); torch.mps.synchronize(); a=time.monotonic()-t
    t=time.monotonic(); r=P.set_text_prompt("hand", st); m=r["masks"].cpu(); b=time.monotonic()-t
    t=time.monotonic(); r2=P.set_text_prompt("baby", st); m=r2["masks"].cpu(); c=time.monotonic()-t
    print(f"set_image {a:.2f} hand {b:.2f} baby {c:.2f}", flush=True)
print("resolution", getattr(P, "resolution", None))
