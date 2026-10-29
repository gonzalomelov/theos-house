"""Depth map per frame with a Meta depth model. usage: depth_dump.py <model> <frames> <out>"""
import json, sys, time
from pathlib import Path
import numpy as np, cv2, torch
from PIL import Image
model_id, FR, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]); OUT.mkdir(parents=True, exist_ok=True)
dev = "mps"
if "sapiens" in model_id:
    from huggingface_hub import snapshot_download
    p = next(Path(snapshot_download(model_id)).glob("*.pt2"))
    net = torch.jit.load(str(p)).eval().to(dev)
    mean = torch.tensor([123.675, 116.28, 103.53], device=dev).view(1,3,1,1); std = torch.tensor([58.395, 57.12, 57.375], device=dev).view(1,3,1,1)
    def run(img):
        x = torch.from_numpy(cv2.resize(img[..., ::-1].copy(), (768, 1024))).permute(2,0,1)[None].float().to(dev)
        with torch.no_grad(): y = net((x - mean) / std)
        return y[0, 0].float().cpu().numpy()
else:
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    proc = AutoImageProcessor.from_pretrained(model_id); net = AutoModelForDepthEstimation.from_pretrained(model_id).to(dev).eval()
    def run(img):
        inp = proc(images=Image.fromarray(img[..., ::-1].copy()), return_tensors="pt").to(dev)
        with torch.no_grad(): y = net(**inp).predicted_depth
        return y[0].float().cpu().numpy()
times = []
for row in json.loads((FR / "index.json").read_text()):
    img = cv2.imread(str(FR / row["file"]))
    if dev == "mps": torch.mps.synchronize()
    t = time.monotonic(); d = run(img)
    if dev == "mps": torch.mps.synchronize()
    times.append(time.monotonic() - t)
    d = cv2.resize(d, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
    np.save(OUT / (row["file"][:-4] + ".npy"), d.astype(np.float32))
t = sorted(times[3:]); print(json.dumps({"model": model_id, "frames": len(times), "median_s": t[len(t)//2], "p90_s": t[int(len(t)*.9)]}))
