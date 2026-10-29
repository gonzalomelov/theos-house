"""Live check: a new family's first bottle note, in English and Spanish, with the real brain at 15:00 Montevideo.

    .venv/bin/python scripts/families_first_entry_live.py ~/.parenting-agent.env
"""
import datetime, json, re, sys, tempfile, zoneinfo
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from parenting_agent.agent import memory as memory_mod
from parenting_agent.families import settings as settings_mod
from parenting_agent.families.service import Families
from parenting_agent.families.store import visitor_id
settings_mod.read_keys(sys.argv[1])
TZ = zoneinfo.ZoneInfo("America/Montevideo")
for app_lang, msg in [("es-UY", "Gave her a 60 ml bottle at 2:15"), ("en-US", "Gave her a 60 ml bottle at 2:15"), ("es-UY", "le di una mamadera de 60 a las 2 y cuarto")]:
    clock = {"now": datetime.datetime(2026, 10, 29, 15, 0, tzinfo=TZ)}
    memory_mod.now = lambda: clock["now"].isoformat(timespec="seconds")
    s = settings_mod.load({"PA_FAMILIES_BRAIN": "baseten", "PA_FAMILIES_DATA_DIR": tempfile.mkdtemp(), "PA_FAMILIES_FAMILY_USD": "1", "PA_FAMILIES_DAILY_USD": "1"})
    app = Families(s, clock=lambda: clock["now"])
    code = app.store.create_invite(internal=True)
    for t in (f"/start {code}", "Lola", "2/9/2026", "si"):
        app.handle(1, 1, t, "private", app_lang)
    fam = app.family(app.store.parent(visitor_id(1))["family_id"])
    calls = []
    run = fam.agent.tools.run
    fam.agent.tools.run = lambda n, a: (calls.append(f"{n}({json.dumps(a, ensure_ascii=False)})"), run(n, a))[1]
    reply = " ".join(t for _, t in app.handle(1, 1, msg, "private", app_lang))
    print(app_lang, "|", msg, "|", reply, "|", calls, "|", [(e["ts"][11:16], e["details"]) for e in fam.log.entries("feeding")])
