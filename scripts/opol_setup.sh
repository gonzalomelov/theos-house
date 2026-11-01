#!/usr/bin/env bash
# The OPOL helper's language ID (issue #144): Meta's MMS language ID, facebook/mms-lid-126 (CC-BY-NC 4.0, 1B parameters),
# pinned to a commit, every file checked by SHA-256. Weights (3.9 GB) in .models/mms-lid-126, git ignored.
# It runs in the hearing venv (scripts/hearing-setup.sh makes it). Point the agent elsewhere with OPOL_LID_PYTHON and
# OPOL_LID_MODEL_DIR, or "opol": {"lid": {"python": ..., "model_dir": ...}}.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
dir="${OPOL_LID_MODEL_DIR:-$root/.models/mms-lid-126}"
rev=53da6e311f3ce48f324fe335924216187e3109a4
base="https://huggingface.co/facebook/mms-lid-126/resolve/$rev"

mkdir -p "$dir"
fetch() {
  local name=$1 sum=$2
  if [ ! -f "$dir/$name" ] || [ "$(shasum -a 256 "$dir/$name" | cut -d' ' -f1)" != "$sum" ]; then
    curl -fsSL --retry 5 -C - -o "$dir/$name" "$base/$name" || curl -fsSL --retry 5 -o "$dir/$name" "$base/$name"
  fi
  [ "$(shasum -a 256 "$dir/$name" | cut -d' ' -f1)" = "$sum" ] || { echo "bad checksum: $name"; exit 1; }
  echo "ok $name"
}
fetch config.json f5f50a99828c0334299ca9180c026518ca69b6b2a41dd3bbede74eea762e4ba3
fetch preprocessor_config.json a2254a5b58f72cd4de3632f8eee64f3f098b7c1402128d2f419e7d00ae13e335
fetch model.safetensors 69fa8def8f0242660b47d8b47c2a1b645d9fc70098cc217fbd52087b68de0ecd
echo "ready: OPOL_LID_MODEL_DIR=$dir"
