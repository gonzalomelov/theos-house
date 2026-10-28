#!/usr/bin/env bash
# PANNs CNN14 16 kHz for the house sounds (issue #14): model code pinned to a commit, weights from Zenodo, all checked by MD5.
# Same files and checksums as meta-hackathon-2026 muse/hearing.Dockerfile. Lands in .models/panns (git-ignored).
set -euo pipefail
dir="${PANNS_DIR:-$(cd "$(dirname "$0")/.." && pwd)/.models/panns}"
code=https://raw.githubusercontent.com/qiuqiangkong/audioset_tagging_cnn/542c8c8bbb4287de5b2b622bc502423b27474b33
mkdir -p "$dir"
fetch() {
  local name=$1 url=$2 sum=$3
  [ -f "$dir/$name" ] || curl -fsSL -o "$dir/$name" "$url"
  [ "$(md5 -q "$dir/$name" 2>/dev/null || md5sum "$dir/$name" | cut -d' ' -f1)" = "$sum" ] || { echo "bad checksum: $name"; exit 1; }
  echo "ok $name"
}
fetch models.py "$code/pytorch/models.py" cd84d1602a5ceb8a5fa5ba53c89260ea
fetch pytorch_utils.py "$code/pytorch/pytorch_utils.py" b64e1a93515e2593ce6d23cba1946046
fetch class_labels_indices.csv "$code/metadata/class_labels_indices.csv" 68c0b5c199d6cc789852b144cc3ab500
fetch Cnn14_16k.pth "https://zenodo.org/records/3987831/files/Cnn14_16k_mAP%3D0.438.pth?download=1" 362fc5ff18f1d6ad2f6d464b45893f2c
