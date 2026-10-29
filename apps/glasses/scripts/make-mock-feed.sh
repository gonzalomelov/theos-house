#!/bin/sh
# Builds the mock glasses camera feeds for the simulator from the synthetic clips (generated, no real child).
# changing-table-feed: one hand stays on for 6 s, then both hands leave.
# hero-feed: the same two clips, then the 2.5 cm hover from the fresh hover render (one hand rests, then hovers
# 2.5 cm above the baby from 2.5 s on), with its resting first 2.5 s played twice, so the hand rests 5 s in the
# new view before it hovers. The SAM 3.1 lift anchor needs a resting frame and about 2 s to answer, and with only
# 2.5 s of rest after the cut the hover was missed (results/hero/README.md). 21.5 s in all.
# table-a-hover-2.5cm: the hover clip alone, for the first-hover-after-arming runs.
# DAT's MockDeviceKit plays HEVC, so every feed is re-encoded to H.265 with the hvc1 tag. The output stays out of git.
set -eu
CLIPS="${1:-$HOME/Engineering/gonza/meta-hackathon-2026-synthetic/kt/clips}"
HOVER="${2:-$HOME/Engineering/gonza/meta-hackathon-2026-synthetic/hover/fresh}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/ParentingGlasses/MockFeed"
mkdir -p "$DIR"
HEVC="-c:v libx265 -tag:v hvc1 -preset medium -crf 28 -x265-params log-level=error -pix_fmt yuv420p -an"
SCALE="scale=1280:704,setsar=1,fps=24"
ffmpeg -v error -y -i "$CLIPS/onehand/table-onehand-01.mp4" -i "$CLIPS/handsoff/table-handsoff-01.mp4" \
  -filter_complex "[0:v]$SCALE[a];[1:v]$SCALE[b];[a][b]concat=n=2:v=1:a=0[v]" \
  -map "[v]" $HEVC "$DIR/changing-table-feed.mp4"
ffmpeg -v error -y -i "$CLIPS/onehand/table-onehand-01.mp4" -i "$CLIPS/handsoff/table-handsoff-01.mp4" -i "$HOVER/table-a-hover-2.5cm.mp4" \
  -filter_complex "[0:v]$SCALE[a];[1:v]$SCALE[b];[2:v]$SCALE,split[c][d];[c]trim=0:2.5,setpts=PTS-STARTPTS[r];[a][b][r][d]concat=n=4:v=1:a=0[v]" \
  -map "[v]" $HEVC "$DIR/hero-feed.mp4"
ffmpeg -v error -y -i "$HOVER/table-a-hover-2.5cm.mp4" -vf "$SCALE" $HEVC "$DIR/table-a-hover-2.5cm.mp4"
ls -l "$DIR"
