"""python -m parenting_agent.demo.export_sessions [--db data/demo_sessions.sqlite]

Prints every row of the sessions table as one JSON object per line, oldest first, for the real-user scorer.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from .records import DB_NAME


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(Path(os.environ.get("PA_DEMO_DATA_DIR", "data")) / DB_NAME))
    args = parser.parse_args(argv)
    if not Path(args.db).exists():
        print(f"no sessions database at {args.db}", file=sys.stderr)
        return 1
    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        for ts, visitor, channel, kind, internal in db.execute(
                "select ts, visitor_id, channel, kind, internal from sessions order by rowid"):
            print(json.dumps({"ts": ts, "visitor_id": visitor, "channel": channel, "kind": kind, "internal": internal}))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
