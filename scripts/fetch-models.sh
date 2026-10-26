#!/usr/bin/env bash
# Official MediaPipe model files from Google's storage, checked by SHA-256 after download.
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)/.models"
mkdir -p "$dir"
fetch() {
  local name=$1 url=$2 sum=$3
  [ -f "$dir/$name" ] || curl -fsSL -o "$dir/$name" "$url"
  echo "$sum  $dir/$name" | shasum -a 256 -c -
}
fetch hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task \
  fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1
fetch efficientdet_lite0.tflite \
  https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/int8/1/efficientdet_lite0.tflite \
  0720bf247bd76e6594ea28fa9c6f7c5242be774818997dbbeffc4da460c723bb
