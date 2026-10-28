#!/usr/bin/env bash
# Run after a deploy: from inside the families container, the house and the family agent must be unreachable,
# the proxy must refuse anything but the brain and Telegram, and the env must hold no house secret.
# Usage: deploy/families/check-wall.sh HA_HOST:PORT BABYBUDDY_HOST:PORT [MORE_HOST:PORT ...]
set -euo pipefail
probe() {
  docker exec pa-families python -c "import socket,sys; h,p=sys.argv[1].rsplit(':',1)
try:
    socket.create_connection((h,int(p)),timeout=3); print('REACHABLE',sys.argv[1]); sys.exit(1)
except OSError: print('blocked',sys.argv[1])" "$1"
}
via_proxy() {
  docker exec pa-families python -c "import socket,sys
s=socket.create_connection(('egress',8888),timeout=5); s.sendall(('CONNECT %s HTTP/1.1\r\nHost: %s\r\n\r\n'%(sys.argv[1],sys.argv[1])).encode())
line=s.recv(200).split(b'\r\n')[0].decode(); ok=' 200 ' in line+' '
print(('proxy allows ' if ok else 'proxy refuses ')+sys.argv[1]); sys.exit(0 if ok==(sys.argv[2]=='allow') else 1)" "$1" "$2"
}
fail=0
for target in "$@" parenting-agent-relay:8790 parenting-agent-relay:8123 1.1.1.1:443 host.docker.internal:22; do
  probe "$target" || fail=1
done
via_proxy api.telegram.org:443 allow || fail=1
via_proxy api.anthropic.com:443 allow || fail=1
via_proxy example.com:443 refuse || fail=1
via_proxy babybuddy:8000 refuse || fail=1
for target in "$@"; do via_proxy "$target" refuse || fail=1; done
docker exec pa-families python -c "import os,sys
# GPG_KEY is set by the python base image: the fingerprint that signs the Python release, public, not a secret.
keep={'ANTHROPIC_API_KEY','BASETEN_API_KEY','TELEGRAM_FAMILIES_BOT_TOKEN','GPG_KEY'}
bad=[k for k in os.environ if k not in keep and any(w in k for w in ('HA_','BABYBUDDY','TELEGRAM','TOKEN','_KEY','SECRET'))]
print('env ok' if not bad else 'FORBIDDEN '+','.join(bad)); sys.exit(1 if bad else 0)" || fail=1
if [ "$fail" = 0 ]; then echo "wall holds"; else echo "WALL BROKEN" >&2; fi
exit $fail
