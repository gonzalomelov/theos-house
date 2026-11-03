#!/usr/bin/env bash
# The Python environment for SAM 3.1 on a Mac, see docs/sam3-local.md: Meta's code at a pinned commit, patched where it assumes
# an NVIDIA GPU, then PyTorch and SAM's own dependencies. SAM3_SOURCE_ONLY=1 stops after the source, for checking the patches.
set -euo pipefail
SAM3_COMMIT=7f473cfd983d5eb43040ff608f66bff0d7bdcb53
home_dir="${SAM3_NATIVE_DIR:-$HOME/Engineering/gonza/sam3-native}"
base_python="${SAM3_BASE_PYTHON:-$HOME/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none/bin/python3.11}"

patch_for_mac() {
  python3 - "$1" <<'PY'
import pathlib, sys
model = pathlib.Path(sys.argv[1]) / "sam3" / "model"
init = 'os.environ.get("SAM3_INIT_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")'
EDITS = {
    # Where SAM builds its first tensors, chosen by us so the weights can load on the CPU before moving to the GPU.
    "position_encoding.py": [('device="cuda")\n', f"device={init})\n")],
    "decoder.py": [('feat_size, feat_size, device="cuda"\n', f"feat_size, feat_size, device={init}\n")],
    # NVIDIA only: mixed precision multiply, and pinned memory.
    "vitdet.py": [("x = addmm_act(type(self.act), self.fc1, x)\n", "x = self.act(self.fc1(x))\n")],
    "geometry_encoders.py": [("scale = scale.pin_memory().to(device=boxes_xyxy.device, non_blocking=True)", "scale = scale.to(device=boxes_xyxy.device)"),
        # grid_sample fails on MPS with no points at all, so that case gets its empty result directly.
        ("sampled = torch.nn.functional.grid_sample(\n                img_feats, grid, align_corners=False\n            )",
         "sampled = (torch.nn.functional.grid_sample(img_feats, grid, align_corners=False) if n_points\n                       else img_feats.new_zeros((bs, self.d_model, 0, 1)))")],
}
for name, edits in EDITS.items():
    path = model / name
    text = path.read_text()
    for old, new in edits:
        if old not in text:
            sys.exit(f"{name}: the code to patch isn't there: {old!r}")
        text = text.replace(old, new)
    if name in ("position_encoding.py", "decoder.py"):
        text = "import os\n" + text
    path.write_text(text)
PY
}

if [ ! -d "$home_dir/src/sam3" ]; then
  mkdir -p "$home_dir/src"
  curl -fsSL "https://github.com/facebookresearch/sam3/archive/$SAM3_COMMIT.tar.gz" | tar xz -C "$home_dir/src" --strip-components=1
  patch_for_mac "$home_dir/src"
fi
[ -z "${SAM3_SOURCE_ONLY:-}" ] || exit 0

[ -x "$home_dir/venv/bin/python" ] || "$base_python" -m venv "$home_dir/venv"
packages=(torch==2.8.0 torchvision==0.23.0 "numpy<2" "timm>=1.0.17" ftfy==6.1.1 regex "iopath>=0.1.10" huggingface_hub einops
  pycocotools==2.0.11 psutil==7.2.2 opencv-contrib-python==4.10.0.84)
"$home_dir/venv/bin/pip" install -q "${packages[@]}"
"$home_dir/venv/bin/pip" install -q --no-deps -e "$home_dir/src"
echo "SAM 3.1 is ready: $home_dir/venv/bin/python"
