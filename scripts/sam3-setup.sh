#!/usr/bin/env bash
# Build the Python environment that runs SAM 3.1 for the changing-table skill (see docs/sam3-local.md).
# Pinned SAM 3 commit, official PyTorch wheels, and the patches SAM 3 needs without an NVIDIA GPU.
set -euo pipefail
dir="${SAM3_NATIVE_DIR:-$HOME/Engineering/gonza/sam3-native}"
python="${SAM3_BASE_PYTHON:-$HOME/.local/share/uv/python/cpython-3.11.13-macos-aarch64-none/bin/python3.11}"
rev=7f473cfd983d5eb43040ff608f66bff0d7bdcb53

mkdir -p "$dir"
if [ ! -d "$dir/src/sam3" ]; then
  mkdir -p "$dir/src"
  curl -fsSL "https://github.com/facebookresearch/sam3/archive/$rev.tar.gz" | tar xz -C "$dir/src" --strip-components=1
  m="$dir/src/sam3/model"
  init='os.environ.get("SAM3_INIT_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")'
  sed -i '' "s/device=\"cuda\")\$/device=$init)/" "$m/position_encoding.py"
  sed -i '' "s/feat_size, feat_size, device=\"cuda\"\$/feat_size, feat_size, device=$init/" "$m/decoder.py"
  perl -0pi -e 's/\A/import os\n/' "$m/position_encoding.py" "$m/decoder.py"
  sed -i '' 's/        x = addmm_act(type(self.act), self.fc1, x)$/        x = self.act(self.fc1(x))/' "$m/vitdet.py"
  sed -i '' 's/scale = scale.pin_memory().to(device=boxes_xyxy.device, non_blocking=True)/scale = scale.to(device=boxes_xyxy.device)/' "$m/geometry_encoders.py"
  perl -0pi -e 's/            sampled = torch\.nn\.functional\.grid_sample\(\n                img_feats, grid, align_corners=False\n            \)/            sampled = (torch.nn.functional.grid_sample(img_feats, grid, align_corners=False) if n_points\n                       else img_feats.new_zeros((bs, self.d_model, 0, 1)))/' "$m/geometry_encoders.py"
  grep -q 'SAM3_INIT_DEVICE' "$m/position_encoding.py"
  grep -q 'img_feats.new_zeros((bs, self.d_model, 0, 1))' "$m/geometry_encoders.py"
fi
[ -x "$dir/venv/bin/python" ] || "$python" -m venv "$dir/venv"
"$dir/venv/bin/pip" install -q torch==2.8.0 torchvision==0.23.0 mediapipe==0.10.14 "numpy<2" \
  "timm>=1.0.17" ftfy==6.1.1 regex "iopath>=0.1.10" huggingface_hub einops pycocotools==2.0.11 psutil==7.2.2
"$dir/venv/bin/pip" install -q --no-deps -e "$dir/src"
echo "SAM 3.1 environment ready: $dir/venv/bin/python"
