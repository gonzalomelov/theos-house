# shellcheck shell=sh disable=SC2016,SC2029  # remote commands are quoted on purpose, they expand on the Vostro
# One deploy at a time on the Vostro. Sourced by agent.sh, public.sh and voice.sh, which define HOST and remote().
#
# The lock is the directory ~/apps/.pa-deploy.lock.d on the Vostro. mkdir is atomic, so only one deploy gets it.
# A directory, not flock, because one deploy spans several ssh sessions (send the code, then build and run).
# A person or an agent can take it by hand with `ssh vostro 'mkdir ~/apps/.pa-deploy.lock.d'` and rmdir it after.
# A deploy waits up to PA_DEPLOY_LOCK_WAIT seconds (default 600) and then stops without touching anything.
LOCK_TOKEN=""

deploy_lock() { # deploy_lock <what is deployed>
  LOCK_TOKEN="$(hostname -s 2>/dev/null || echo mac)-$$-$(date +%s)"
  remote "LOCK_WAIT='${PA_DEPLOY_LOCK_WAIT:-600}' LOCK_TOKEN='$LOCK_TOKEN' LOCK_WHAT='$1' sh -s" <<'REMOTE' || { LOCK_TOKEN=""; exit 75; }
set -eu
L="$HOME/apps/.pa-deploy.lock.d"
holder() { cat "$L/owner" 2>/dev/null || echo "unknown (taken by hand, or just being taken)"; }
START="$(date +%s)"
SAID=0
until mkdir "$L" 2>/dev/null; do
  WAITED=$(( $(date +%s) - START ))
  if [ "$WAITED" -ge "$LOCK_WAIT" ]; then
    echo "deploy lock $L is still held after ${WAITED}s by: $(holder)" >&2
    echo "Nothing was changed. If no deploy is running, remove it with: ssh vostro 'rm -rf ~/apps/.pa-deploy.lock.d'" >&2
    exit 75
  fi
  if [ "$SAID" = 0 ]; then echo "== another deploy holds $L: $(holder). Waiting up to ${LOCK_WAIT}s" >&2; SAID=1; fi
  sleep 5
done
printf '%s %s since %s\n' "$LOCK_TOKEN" "$LOCK_WHAT" "$(date +%Y-%m-%dT%H:%M:%S%z)" > "$L/owner"
echo "== deploy lock taken for $LOCK_WHAT"
REMOTE
  trap deploy_unlock EXIT
  trap 'exit 130' INT TERM
}

# Removes the lock only if this deploy still owns it, so a lock someone took by hand after clearing ours stays.
deploy_unlock() {
  [ -n "$LOCK_TOKEN" ] || return 0
  T="$LOCK_TOKEN"
  LOCK_TOKEN=""
  remote "LOCK_TOKEN='$T' sh -s" <<'REMOTE' || echo "could not release the deploy lock: ssh vostro 'rm -rf ~/apps/.pa-deploy.lock.d'" >&2
set -eu
L="$HOME/apps/.pa-deploy.lock.d"
if [ "$(cut -d' ' -f1 "$L/owner" 2>/dev/null)" = "$LOCK_TOKEN" ]; then rm -f "$L/owner" && rmdir "$L"; fi
REMOTE
}
