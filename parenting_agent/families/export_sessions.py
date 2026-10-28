"""python -m parenting_agent.families.export_sessions [--db data/families/families.sqlite]

Prints every family session row as one JSON object per line, oldest first, in the demo export's format plus
family_id, for the real-user scorer (measure-kr222.sh reads both exports as one stream).
"""
import argparse
import os
import sys
from pathlib import Path

from ..demo.export_sessions import print_rows
from .store import DB_NAME


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=str(Path(os.environ.get("PA_FAMILIES_DATA_DIR", "data/families")) / DB_NAME))
    args = parser.parse_args(argv)
    return print_rows(args.db)


if __name__ == "__main__":
    sys.exit(main())
