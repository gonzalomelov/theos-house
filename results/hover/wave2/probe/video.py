import os, sys, time, contextlib
import torch
os.environ.setdefault("SAM3_INIT_DEVICE", "mps")
torch.cuda.get_device_properties = lambda *a, **k: type("P", (), {"major": 0})()
torch.cuda.is_available = lambda: False
_to = torch.Tensor.to
torch.Tensor.cuda = lambda self, *a, **k: _to(self, "mps")
_ac = torch.autocast
class AC(_ac):
    def __init__(self, device_type, *a, **k):
        super().__init__("mps" if device_type == "cuda" else device_type, *a, **k)
torch.autocast = AC
_dev = torch.device
class Dev:
    def __new__(cls, *a, **k):
        if a and isinstance(a[0], str) and a[0].startswith("cuda"): a = ("mps",) + a[1:]
        return _dev(*a, **k)
torch.device = Dev
sys.path.insert(0, os.path.expanduser("~/Engineering/gonza/parenting-agent-worktrees/sam-essential/parenting_agent/sam3_stubs"))
from huggingface_hub import hf_hub_download
from sam3.model_builder import build_sam3_multiplex_video_predictor
ck = hf_hub_download("facebook/sam3.1", "sam3.1_multiplex.pt")
t = time.monotonic()
pred = build_sam3_multiplex_video_predictor(checkpoint_path=ck, use_fa3=False, async_loading_frames=False)
print("built", round(time.monotonic() - t, 1), flush=True)
sid = pred.handle_request(dict(type="start_session", resource_path=sys.argv[1]))["session_id"]
t = time.monotonic()
out = pred.handle_request(dict(type="add_prompt", session_id=sid, frame_index=0, text="hand"))["outputs"]
print("prompt", round(time.monotonic() - t, 2), {k: getattr(v, "shape", v) for k, v in out.items()} if isinstance(out, dict) else type(out), flush=True)
t = time.monotonic(); n = 0; areas = []
for r in pred.handle_stream_request(dict(type="propagate_in_video", session_id=sid)):
    n += 1
    o = r["outputs"]; m = o.get("out_binary_masks") if isinstance(o, dict) else None
    areas.append(None if m is None else [int(x.sum()) for x in m])
print("propagate frames", n, "s/frame", round((time.monotonic() - t) / max(n, 1), 2))
print(areas)
