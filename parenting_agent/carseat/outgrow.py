"""Outgrow watch: the baby's weight and height from Baby Buddy against the seat's limits from the manual.

The pace is a straight line through the recent measurements. Early weeks grow fastest, so the line reaches a
limit sooner than real growth will: the heads up comes early, never late. It reports numbers only, no advice.
"""
import datetime

HEADS_UP_WEEKS = 4


def pace(points):
    """Least-squares slope per day through (date, value) points, None with fewer than two dates."""
    if len({d for d, _ in points}) < 2:
        return None
    xs = [(d - points[0][0]).days for d, _ in points]
    ys = [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def project(points, limit, today):
    """{latest, limit, per_day, days_left, date} for one measure, days_left 0 when the limit is reached."""
    points = sorted(points)
    latest_date, latest = points[-1]
    rate = pace(points)
    if latest >= limit:
        days = 0
    elif rate is None or rate <= 0:
        days = None
    else:
        days = max(int((limit - latest) / rate) - (today - latest_date).days, 0)
    return {"latest": latest, "measured": latest_date.isoformat(), "limit": limit,
            "per_day": None if rate is None else round(rate, 4), "days_left": days,
            "date": None if days is None else (today + datetime.timedelta(days=days)).isoformat()}


def watch(weights, heights, limits, today, seat="the seat", name="The baby", heads_up_weeks=HEADS_UP_WEEKS):
    """weights and heights are lists of (date, value). Returns the numbers and one plain sentence."""
    out = {"seat": seat, "today": today.isoformat(), "heads_up_weeks": heads_up_weeks}
    if weights and limits.get("max_weight_kg"):
        out["weight"] = project(weights, limits["max_weight_kg"], today)
    if heights and limits.get("height_cm"):
        out["height"] = project(heights, limits["height_cm"][1], today)
    known = [(k, v) for k, v in out.items() if k in ("weight", "height") and v["days_left"] is not None]
    if not known:
        out.update(status="no_data", text=f"I need at least two weight or height entries to watch the limits of {seat}.")
        return out
    first, info = min(known, key=lambda kv: kv[1]["days_left"])
    unit = "kg" if first == "weight" else "cm"
    weeks = info["days_left"] / 7
    now = ", ".join(f"{out[k]['latest']} {'kg' if k == 'weight' else 'cm'}" for k in ("weight", "height") if k in out)
    if info["days_left"] == 0:
        status = "reached"
        text = f"{name} is at {now}. That reaches the {first} limit of {seat}, {info['limit']} {unit}. Time to plan the next seat."
    elif weeks <= heads_up_weeks:
        status = "heads_up"
        text = (f"Heads up: {name} is at {now}. At the recent pace the {first} limit of {seat}, {info['limit']} {unit}, "
                f"comes in about {max(round(weeks), 1)} weeks, around {info['date']}. Time to plan the next seat.")
    else:
        status = "ok"
        text = (f"{name} is at {now}. At the recent pace the {first} limit of {seat}, {info['limit']} {unit}, "
                f"comes first, in about {round(weeks)} weeks.")
    out.update(status=status, first_limit=first, text=text)
    return out


def from_babybuddy(request, child):
    """(weights, heights) as (date, value) lists, read with a Baby Buddy request(method, path) function."""
    def rows(endpoint, field):
        data = request("GET", f"/api/{endpoint}/?child={child}&limit=100&ordering=-date")["results"]
        return [(datetime.date.fromisoformat(r["date"][:10]), float(r[field])) for r in data]
    return rows("weight", "weight"), rows("height", "height")
