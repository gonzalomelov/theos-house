"""Theo's nursery from the home twin: the study's real size and the two layouts of the nursery plan.

The numbers come from the my own home twin (docs/nursery-plan.html, Sep 2026, before the hackathon): the study
measured at 3.60 x 1.85 m after an iPhone LiDAR scan corrected by hand, the door 0.80 m wide on the garage hall wall,
the window on the exterior wall. Positions are room metres: x from the door wall, z from the desk wall. Each piece is
its centre and its size, width along x and depth along z.

The checks are geometry only: clearances, the door's swing, a shelf over the crib, and how far the white noise machine
can sit from the crib. They say where the furniture goes, never anything about the baby's health.
"""
import math

ROOM = {"w": 3.60, "d": 1.85, "door": {"wall": "x0", "z0": 0.15, "z1": 0.95, "swing_m": 0.80},
        "window": {"wall": "x1", "z0": 0.52, "z1": 1.62}}
SOURCE = "my own home twin, the home twin of the study (prior work, Sep 2026)"

COMMON = {
    "crib": {"label": "Crib", "w": 1.30, "d": 0.70, "x": 1.47, "z": 1.50},
    "dresser": {"label": "Dresser with changing mat", "w": 1.20, "d": 0.45, "x": 1.42, "z": 0.225},
    "rocker": {"label": "Alba rocker", "w": 0.69, "d": 0.80, "x": 0.41, "z": 1.45},
    "rug": {"label": "Star rug", "w": 1.45, "d": 0.92, "x": 1.47, "z": 0.80, "floor": True},
}
LAYOUTS = {
    "a": {"name": "desk on the inner wall", "pieces": {
        **COMMON,
        "desk": {"label": "Standing desk", "w": 1.40, "d": 0.70, "x": 2.90, "z": 0.35},
        "shelf": {"label": "Wall shelf 152 cm up", "w": 0.86, "d": 0.20, "x": 2.85, "z": 1.74, "wall": True}}},
    "b": {"name": "desk at the window", "pieces": {
        **COMMON,
        "desk": {"label": "Standing desk", "w": 0.70, "d": 1.40, "x": 3.25, "z": 0.70},
        "shelf": {"label": "Wall shelf 152 cm up", "w": 0.86, "d": 0.20, "x": 1.95, "z": 1.74, "wall": True}}},
}
WALKWAY_MIN_M = 0.60
NOISE_DISTANCE_M = 2.0
# Smart devices already in the study, from the home twin's house.json and Home Assistant.
DEVICES = {"light": "light.wiz_824512_192_0_2_10", "heater_plug": "switch.shellyplusplugit_bathroom"}


def box(piece):
    return (piece["x"] - piece["w"] / 2, piece["x"] + piece["w"] / 2, piece["z"] - piece["d"] / 2, piece["z"] + piece["d"] / 2)


def overlap(a, b):
    return min(a[1], b[1]) - max(a[0], b[0])


def gap_z(a, b):
    """Clear floor between two boxes that face each other along z."""
    lower, upper = sorted((a, b), key=lambda r: r[2])
    return round(upper[2] - lower[3], 2)


def distance_to_box(px, pz, b):
    dx = max(b[0] - px, 0, px - b[1])
    dz = max(b[2] - pz, 0, pz - b[3])
    return math.hypot(dx, dz)


def farthest_from(b, step=0.05):
    """The floor point of the room farthest from a box, on a 5 cm grid: (distance, x, z)."""
    best = (0.0, 0.0, 0.0)
    for i in range(int(ROOM["w"] / step) + 1):
        for j in range(int(ROOM["d"] / step) + 1):
            x, z = round(i * step, 2), round(j * step, 2)
            far = distance_to_box(x, z, b)
            if far > best[0]:
                best = (round(far, 2), x, z)
    return best


def checks(layout):
    """Pass or warn for each placement rule of one layout, with the numbers behind it."""
    pieces = LAYOUTS[layout]["pieces"]
    crib, dresser, shelf = box(pieces["crib"]), box(pieces["dresser"]), box(pieces["shelf"])
    out = []
    walkway = gap_z(crib, dresser)
    out.append({"check": "walkway between dresser and crib", "ok": walkway >= WALKWAY_MIN_M,
                "text": f"{round(walkway * 100)} cm of clear floor between the dresser and the crib"})
    swing_clear = round(dresser[0] - ROOM["door"]["swing_m"], 2)
    out.append({"check": "door swing", "ok": swing_clear >= 0,
                "text": f"the dresser starts {round(dresser[0] * 100)} cm from the door wall, the door swings {round(ROOM['door']['swing_m'] * 100)} cm"})
    over = round(overlap(crib, shelf), 2)
    out.append({"check": "nothing on the wall above the crib", "ok": over <= 0,
                "text": (f"the wall shelf hangs {round(over * 100)} cm over the crib's end, move it past "
                         f"{round(crib[1] * 100)} cm from the door wall") if over > 0 else "the wall shelf is clear of the crib"})
    far, x, z = farthest_from(crib)
    out.append({"check": "white noise machine 2 m from the crib", "ok": far >= NOISE_DISTANCE_M,
                "text": (f"the farthest floor spot from the crib is {round(far * 100)} cm away "
                         f"({round(x * 100)} cm from the door wall, {round(z * 100)} cm from the desk wall)"
                         + ("" if far >= NOISE_DISTANCE_M else ", so 2 m is not possible in this room: use that corner and"
                            " set the 50 dB cap by measuring at the crib"))})
    return out


def summary(layout=None):
    """Both layouts with their checks, or one."""
    names = [layout] if layout else sorted(LAYOUTS)
    return {"room": f"{ROOM['w']:.2f} x {ROOM['d']:.2f} m, {ROOM['w'] * ROOM['d']:.1f} m2", "source": SOURCE,
            "devices": DEVICES,
            "layouts": {name: {"name": LAYOUTS[name]["name"], "checks": checks(name)} for name in names}}
