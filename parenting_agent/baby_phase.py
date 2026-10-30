"""Before or after the birth: which routines the family agent runs (Oct 30, the test log behind the morning brief).

Until Theo is born the baby log the family agent reads is a test child, so everything computed from it is about a baby
that does not exist: "a feed was expected 1753 min ago" in the Oct 30 morning brief came from test entries that stopped
on Oct 29. Config block "baby": {"born": false} puts the agent in prep mode:

| Before the birth ("born": false) | After the birth ("born": true, the default) |
|---|---|
| The prep plug-in leads: lists, appointments, countdown, its lines in the morning message | Prep lines leave the morning message |
| Day engine routines read an empty log: no nap mode, floor clean, supplies, night summary or meals from test data. The morning message keeps the weather and appointments | Every routine reads the log |
| The night feed, the house brain (tonight's plan, the morning explanation) and the next feed reminders stay silent | All on |
| The brain is told the log holds test entries only | Nothing added |

At birth: create Theo in Baby Buddy, point "baby_log.child" and "rhythm.child" at him, set "baby": {"born": true}, deploy.
A config with no "baby" block keeps every routine running and the prep plug-in as it was, so the Mac, the demo and the
tests do not change: only an explicit "born" true or false switches.
"""

NOT_BORN_NOTE = ("Theo is not born yet. The baby log holds test entries only, not Theo's: never report a feed, a diaper, "
                 "a sleep or a time from it as his, and say the log starts when he is born.")


def born(config):
    return (config.get("baby") or {}).get("born", True) is not False


def phase(config):
    """"prep" (born false), "born" (born true) or None (no "baby" block)."""
    value = (config.get("baby") or {}).get("born")
    return {False: "prep", True: "born"}.get(value)


def born_note(name, people=None):
    """After the birth the brain is told the baby's name, and that a parent's name is never his: on Oct 30 the
    end-to-end day answered "Gonza comió por última vez a las 10:40" when Ceci asked for her mother."""
    parents = [people.name(p) for p in people.keys()] if people else []
    tail = f" {' and '.join(parents)} are the parents: never call the baby by their names." if parents else ""
    return f"The baby is {name}.{tail}"
