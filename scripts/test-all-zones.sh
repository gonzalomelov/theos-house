#!/usr/bin/env bash
# The full test suite under four server time zones, so the product never depends on the zone it runs in.
# Usage: scripts/test-all-zones.sh [python]. The default interpreter is .venv/bin/python.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
python="${1:-$root/.venv/bin/python}"
zones=(UTC America/Montevideo Asia/Tokyo America/Los_Angeles)
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
failed=()
cd "$root" || exit 1
for zone in "${zones[@]}"; do
  echo "== TZ=$zone"
  if TZ="$zone" "$python" -m unittest discover -s tests >"$log" 2>&1; then
    grep -E "^(Ran|OK|FAILED)" "$log"
  else
    grep -E "^(FAIL|ERROR):" "$log"
    grep -E "^(Ran|OK|FAILED)" "$log"
    failed+=("$zone")
  fi
done
if [ ${#failed[@]} -gt 0 ]; then
  echo "FAILED under: ${failed[*]}"
  exit 1
fi
echo "all ${#zones[@]} zones passed"
