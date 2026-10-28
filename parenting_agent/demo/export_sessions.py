"""python -m parenting_agent.demo.export_sessions [--db data/demo_sessions.sqlite]

Prints every row of the sessions table as one JSON object per line, oldest first, for the real-user scorer.
A sessions table with a family_id column (the families service) adds family_id to each row.
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from .records import DB_NAME

COLUMNS = ("ts", "visitor_id", "channel", "kind", "internal")


def print_rows(path, out=None):
    out = out or sys.stdout
    if not Path(path).exists():
        print(f"no sessions database at {path}", file=sys.stderr)
        return 1
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        present = {row[1] for row in db.execute("pragma table_info(sessions)")}
        columns = COLUMNS + (("family_id",) if "family_id" in present else ())
        for row in db.execute(f"select {', '.join(columns)} from sessions order by rowid"):
            print(json.dumps(dict(zip(columns, row))), file=out)
    finally:
        db.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(Path(os.environ.get("PA_DEMO_DATA_DIR", "data")) / DB_NAME))
    args = parser.parse_args(argv)
    return print_rows(args.db)


if __name__ == "__main__":
    sys.exit(main())
