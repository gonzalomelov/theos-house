#!/usr/bin/env bash
# Run after a deploy: from inside the demo container, the house must be unreachable and only the brain allowed.
# Usage: deploy/demo/check-wall.sh HA_HOST:PORT BABYBUDDY_HOST:PORT
set -euo pipefail
probe() {
  docker exec pa-demo python -c "import socket,sys; h,p=sys.argv[1].rsplit(':',1)
try:
    socket.create_connection((h,int(p)),timeout=3); print('REACHABLE',sys.argv[1]); sys.exit(1)
except OSError: print('blocked',sys.argv[1])" "$1"
}
fail=0
for target in "$@" 1.1.1.1:443 host.docker.internal:22; do probe "$target" || fail=1; done
docker exec pa-demo python -c "import os,sys; bad=[k for k in os.environ if any(w in k for w in ('HA_','BABYBUDDY','TELEGRAM','TOKEN'))]; print('env ok' if not bad else 'FORBIDDEN '+','.join(bad)); sys.exit(1 if bad else 0)" || fail=1
exit $fail
