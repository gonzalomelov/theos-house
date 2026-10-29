#!/bin/sh
# Builds the mock glasses camera feed for the simulator from the synthetic changing-table clips
# (generated, no real child). One hand stays on for 6 s, then both hands leave. DAT's MockDeviceKit
# plays HEVC, so the clip is re-encoded to H.265 with the hvc1 tag. The output stays out of git.
set -eu
CLIPS="${1:-$HOME/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/ParentingGlasses/MockFeed/changing-table-feed.mp4"
mkdir -p "$(dirname "$OUT")"
ffmpeg -v error -y -i "$CLIPS/onehand/table-onehand-01.mp4" -i "$CLIPS/handsoff/table-handsoff-01.mp4" \
  -filter_complex "[0:v]scale=1280:704,setsar=1,fps=24[a];[1:v]scale=1280:704,setsar=1,fps=24[b];[a][b]concat=n=2:v=1:a=0[v]" \
  -map "[v]" -c:v libx265 -tag:v hvc1 -preset medium -crf 28 -pix_fmt yuv420p -an "$OUT"
ls -l "$OUT"
