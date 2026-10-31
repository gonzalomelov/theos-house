#!/usr/bin/env bash
# The Ear's Meta listener (Oct 31 2026): a venv with torch and transformers, and Meta's Perception Encoder Audio Frame
# small (facebook/pe-a-frame-small, Apache 2.0) pinned to a commit, every file checked by SHA-256.
# Venv in .venv-hearing, weights (1.76 GB) in .models/pe-a-frame-small, both git ignored.
# Point the agent at other places with HEARING_PYTHON and HEARING_MODEL_DIR.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
venv="${HEARING_VENV:-$root/.venv-hearing}"
dir="${HEARING_MODEL_DIR:-$root/.models/pe-a-frame-small}"
python="${PYTHON:-python3.12}"
rev=e5fc71c1f0be50279f52f292390b589780079e13
base="https://huggingface.co/facebook/pe-a-frame-small/resolve/$rev"

if [ ! -x "$venv/bin/python" ]; then
  "$python" -m venv "$venv"
fi
"$venv/bin/pip" install --quiet --upgrade pip
"$venv/bin/pip" install --quiet "torch>=2.8" "transformers==5.21.0" "numpy<3" safetensors
"$venv/bin/python" -c "from transformers import PeAudioFrameLevelModel, PeAudioFeatureExtractor; print('ok transformers')"

mkdir -p "$dir"
fetch() {
  local name=$1 sum=$2
  if [ ! -f "$dir/$name" ] || [ "$(shasum -a 256 "$dir/$name" | cut -d' ' -f1)" != "$sum" ]; then
    curl -fsSL --retry 5 -C - -o "$dir/$name" "$base/$name" || curl -fsSL --retry 5 -o "$dir/$name" "$base/$name"
  fi
  [ "$(shasum -a 256 "$dir/$name" | cut -d' ' -f1)" = "$sum" ] || { echo "bad checksum: $name"; exit 1; }
  echo "ok $name"
}
fetch config.json b71e59652d8d3bc2b4a6d5e882418c24b4ce08267df88145e5ac4ec508f4d14c
fetch preprocessor_config.json 0ee55f8b2de0849b9fdebdc96486fcbb12eafe8e63d688f3a307a24048d80efa
fetch processor_config.json 9bf1e54b150eca3ff5301a6b9896395043906766f5fdeb04c6fc7ceb1c4f5150
fetch special_tokens_map.json ea97ecdbcc73713039d8d64dbb05e3689495c96657fbd9a18f5bed381be81049
fetch tokenizer.json 43e9ea931bb0f359d16d0e435c26abbebd9a42a7298270b8ab7e5c9fa1be1dcb
fetch tokenizer_config.json c16e13355ed389742590152634aa4923a6bc6cd180958d73ed43283fa1f0e8a2
fetch model.safetensors 00ead719f02ef703ee1b55d6aee801074195d7d507a69622cda67ee4c484ed81
echo "ready: HEARING_PYTHON=$venv/bin/python HEARING_MODEL_DIR=$dir"
