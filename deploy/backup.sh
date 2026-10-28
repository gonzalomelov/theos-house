#!/bin/sh
# Run on the Vostro, daily (systemd/pa-backup.timer, installed by sh deploy/public.sh backup install).
# Copies every SQLite file of the public demo and the families service with SQLite's own online backup, from
# inside each container (the data folders belong to the container users), checks each copy, and keeps 7 days.
# A failed or empty backup is an error: nothing is reported as written and the older backups are kept.
set -eu
DIR="${BACKUP_DIR:-$HOME/backups/parenting-agent-public}"
mkdir -p "$DIR"
chmod 700 "$DIR"
umask 077
DAY="$(date +%Y-%m-%d)"
FAILED=0

# Runs inside the container: one tar.gz on stdout, each database copied consistently and integrity checked.
INSIDE='
import glob, os, sqlite3, sys, tarfile
names = sorted(glob.glob("/data/**/*.sqlite", recursive=True))
if not names:
    sys.exit("no SQLite file in /data")
tmp = "/data/.backup-copy.sqlite"
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as tar:
    for path in names:
        if os.path.exists(tmp):
            os.remove(tmp)
        src, dst = sqlite3.connect(path), sqlite3.connect(tmp)
        src.backup(dst)
        src.close()
        check = dst.execute("pragma integrity_check").fetchone()[0]
        dst.close()
        if check != "ok":
            os.remove(tmp)
            sys.exit("integrity check failed for " + os.path.relpath(path, "/data"))
        tar.add(tmp, arcname=os.path.relpath(path, "/data"))
        os.remove(tmp)
print(len(names), file=sys.stderr)
'

for APP in ${BACKUP_APPS:-pa-demo pa-families}; do
  OUT="$DIR/$APP-$DAY.tar.gz"
  TMP="$OUT.tmp"
  if ! docker exec "$APP" python -c "$INSIDE" > "$TMP" 2> "$TMP.err"; then
    echo "$APP: backup failed, $(tail -1 "$TMP.err")" >&2
    rm -f "$TMP" "$TMP.err"; FAILED=1; continue
  fi
  COUNT="$(tail -1 "$TMP.err")"; rm -f "$TMP.err"
  if ! gzip -t "$TMP" || [ "$(tar -tzf "$TMP" | wc -l)" -ne "$COUNT" ]; then
    echo "$APP: the archive is not complete, no backup written" >&2
    rm -f "$TMP"; FAILED=1; continue
  fi
  mv "$TMP" "$OUT"
  echo "$APP: wrote $OUT ($COUNT databases, $(wc -c < "$OUT" | tr -d ' ') bytes)"
  # Old backups go only after a good new one exists.
  find "$DIR" -name "$APP-*.tar.gz" -mtime +7 -delete
done
exit $FAILED
