#!/bin/sh
# Runs the HUD logic tests on the Mac: HUDState.swift and Tests/HUDStateTests.swift compiled together with swiftc,
# then the speech cutter tests the same way.
# HUDState is Foundation only, so this needs neither the simulator nor the DAT SDK.
set -eu
APP="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp "$APP/Tests/HUDStateTests.swift" "$WORK/main.swift"
xcrun swiftc -O -o "$WORK/hud-tests" "$APP/ParentingGlasses/HUD/HUDState.swift" "$WORK/main.swift"
"$WORK/hud-tests" "$APP/ParentingGlasses/HUD/hud-replay.json"
# The speech cutter (Speech/Utterances.swift), Foundation only too
cp "$APP/Tests/UtteranceCutterTests.swift" "$WORK/main.swift"
xcrun swiftc -O -o "$WORK/cutter-tests" "$APP/ParentingGlasses/Speech/Utterances.swift" "$WORK/main.swift"
"$WORK/cutter-tests"
