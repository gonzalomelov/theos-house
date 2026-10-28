"""3D-rendered car seat clips with exact labels, for testing the car seat coach (issue #30).

A small software renderer in NumPy and OpenCV (painter's algorithm, Lambert shading), no extra packages.
It draws a rear bench, an infant carrier installed rear facing with the car's 3-point belt, a doll, the
belt guides, the handle and the level line, and plants one mistake per wrong clip:
  outside_guide   the belt misses a guide: the near lap guide, both lap guides, or the rear guide
                  (a miss at the far lap guide alone is not rendered: from the door side it projects onto the
                  guide and cannot be told apart, so the coach asks for a far-side view in real use)
  twisted         a half twist in the lap belt across the carrier
  recline         the carrier pitched so the level line is not level
  handle          the handle in position 2 or 3 instead of position 1 (upright, the car position)
plus "unseen" clips where the carrier never comes into view or a blanket covers the belt path.

Each clip starts with the camera on the floor, pans to the carrier and holds with a hand-held drift.
labels.json records the error, the parameters and visible_s, the first moment the carrier is fully in view.

    python scripts/carseat_render.py --out ~/Engineering/gonza/meta-hackathon-2026-synthetic/carseat/clips --set test
"""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np

W, H, SS, FPS = 960, 720, 2, 15
ERRORS = ("outside_guide", "twisted", "recline", "handle")


# ---------- small linear algebra ----------

def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


class Camera:
    def __init__(self, eye, target, roll=0.0, fov=62.0):
        self.eye = np.asarray(eye, float)
        f = unit(np.asarray(target, float) - self.eye)
        r = unit(np.cross(f, [0, 1, 0]))
        u = np.cross(r, f)
        c, s = math.cos(roll), math.sin(roll)
        r, u = c * r + s * u, -s * r + c * u
        self.R = np.stack([r, u, f])
        self.focal = (W * SS / 2) / math.tan(math.radians(fov) / 2)

    def project(self, pts):
        cam = (pts - self.eye) @ self.R.T
        z = cam[:, 2]
        x = W * SS / 2 + self.focal * cam[:, 0] / np.maximum(z, 1e-6)
        y = H * SS / 2 - self.focal * cam[:, 1] / np.maximum(z, 1e-6)
        return np.stack([x, y], 1), z


# ---------- meshes: lists of (polygon Nx3, color BGR, material) ----------

def quad_strip(a, b, color, mat="plastic"):
    """Quads between two point rows a[i], b[i]."""
    return [(np.array([a[i], a[i + 1], b[i + 1], b[i]]), color, mat) for i in range(len(a) - 1)]


def box(center, size, color, R=np.eye(3), mat="plastic"):
    sx, sy, sz = np.asarray(size) / 2
    corners = np.array([[x, y, z] for x in (-sx, sx) for y in (-sy, sy) for z in (-sz, sz)]) @ R.T + center
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return [(corners[list(f)], color, mat) for f in faces]


def extrude(profile_zy, x0, x1, color, top_color, mat="plastic"):
    """Side profile in (z, y) extruded across x. Edges whose outward normal points up get top_color."""
    p = np.asarray(profile_zy, float)
    left = np.column_stack([np.full(len(p), x0), p[:, 1], p[:, 0]])
    right = np.column_stack([np.full(len(p), x1), p[:, 1], p[:, 0]])
    faces = [(left, color, mat), (right, color, mat)]
    area = 0.5 * np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])
    for i in range(len(p)):
        j = (i + 1) % len(p)
        dz, dy = p[j] - p[i]
        normal_y = -dz if area > 0 else dz
        faces.append((np.array([left[i], left[j], right[j], right[i]]), top_color if normal_y > 0.3 * math.hypot(dz, dy) else color, mat))
    return faces


def tube(path, radius, color, sides=8, mat="plastic"):
    path = np.asarray(path, float)
    rings = []
    for i, p in enumerate(path):
        t = unit(path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)])
        a = unit(np.cross(t, [0.3, 1, 0.2]))
        b = np.cross(t, a)
        rings.append([p + radius * (math.cos(k * 2 * math.pi / sides) * a + math.sin(k * 2 * math.pi / sides) * b)
                      for k in range(sides + 1)])
    rings = np.array(rings)
    faces = []
    for k in range(sides):
        faces += quad_strip(rings[:, k], rings[:, k + 1], color, mat)
    return faces


def ellipsoid(center, radii, color, R=np.eye(3), n=10, mat="skin"):
    faces = []
    for i in range(n):
        for j in range(2 * n):
            pts = []
            for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                th, ph = math.pi * (i + di) / n, math.pi * (j + dj) / n
                pts.append(np.array([math.sin(th) * math.cos(ph), math.cos(th), math.sin(th) * math.sin(ph)]) * radii)
            faces.append((np.array(pts) @ R.T + center, color, mat, np.asarray(center, float)))
    return faces


def smooth_path(points, per_segment=10):
    """Catmull-Rom through the control points."""
    p = np.asarray(points, float)
    p = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = []
    for i in range(1, len(p) - 2):
        for k in range(per_segment):
            t = k / per_segment
            a, b, c, d = p[i - 1], p[i], p[i + 1], p[i + 2]
            out.append(0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t * t + (-a + 3 * b - 3 * c + d) * t ** 3))
    out.append(p[-2])
    return np.array(out)


def ribbon(path, width, normal_hint, color, twist=None):
    """Belt webbing along path. twist=(start_frac, end_frac) adds a half turn there."""
    path = np.asarray(path, float)
    n = len(path)
    a_side, b_side = [], []
    for i, p in enumerate(path):
        t = unit(path[min(i + 1, n - 1)] - path[max(i - 1, 0)])
        hint = normal_hint(p) if callable(normal_hint) else np.asarray(normal_hint, float)
        w = unit(np.cross(t, hint))
        half = width / 2
        if twist:
            f = i / (n - 1)
            s = min(max((f - twist[0]) / (twist[1] - twist[0]), 0), 1)
            ang = math.pi * s
            nrm = np.cross(w, t)
            w = math.cos(ang) * w + math.sin(ang) * nrm
            half = width / 2 * (1 - 0.7 * math.sin(ang))  # webbing bunches up where it turns over
        a_side.append(p + w * half)
        b_side.append(p - w * half)
    faces = []
    a_side, b_side = np.array(a_side), np.array(b_side)
    lanes = [(0.0, 0.1, 1.25), (0.1, 0.9, 1.0), (0.9, 1.0, 1.25)]
    for i in range(n - 1):
        weave = 1.0 if i % 2 == 0 else 0.9
        for lo, hi, gain in lanes:
            p0, p1 = a_side[i] + (b_side[i] - a_side[i]) * lo, a_side[i] + (b_side[i] - a_side[i]) * hi
            q0, q1 = a_side[i + 1] + (b_side[i + 1] - a_side[i + 1]) * lo, a_side[i + 1] + (b_side[i + 1] - a_side[i + 1]) * hi
            faces.append((np.array([p0, q0, q1, p1]), tuple(min(255, int(c * weave * gain)) for c in color), "webbing"))
    return faces


# ---------- the scene ----------

SHELL = [(-0.32, 0.26), (-0.335, 0.12), (-0.29, 0.04), (-0.16, 0.0), (0.05, 0.0), (0.22, 0.02), (0.33, 0.08),
         (0.385, 0.26), (0.38, 0.46), (0.32, 0.52), (0.24, 0.45), (0.12, 0.33), (-0.04, 0.28), (-0.2, 0.27)]
SEAT = [(-0.32, 0.21), (-0.335, 0.12), (-0.29, 0.04), (-0.16, 0.0), (0.05, 0.0), (0.22, 0.02), (0.33, 0.08),
        (0.385, 0.26), (0.37, 0.44), (0.30, 0.40), (0.20, 0.27), (0.08, 0.17), (-0.06, 0.15), (-0.2, 0.18)]
SHELL_HALF_W = 0.215
WALL = 0.012
LAP_GUIDE = np.array([0.0, 0.285, -0.12])        # x set per side
REAR_GUIDE = np.array([0.05, 0.50, 0.355])
HUB = np.array([0.0, 0.30, 0.02])
COLORWAYS = [((150, 155, 160), (70, 72, 78)), ((120, 140, 150), (60, 66, 70)), ((165, 160, 150), (82, 78, 74))]
GUIDE_COLOR = (200, 120, 30)   # BGR blue
BELT_COLOR = (80, 80, 86)


class Carrier:
    """Carrier pose: rear facing, head end toward the car front (+z). Local +z is the head end."""

    def __init__(self, center, pitch_deg, yaw_deg=0.0):
        self.center = np.asarray(center, float)
        self.R = rot_y(math.radians(yaw_deg)) @ rot_x(math.radians(-pitch_deg))

    def world(self, p):
        return np.asarray(p, float) @ self.R.T + self.center


def handle_points(carrier, theta_deg, n=24):
    th = math.radians(theta_deg)
    up = np.array([0.0, math.cos(th), math.sin(th)])
    pts = []
    for k in range(n + 1):
        phi = math.pi * k / n
        x = -(SHELL_HALF_W + 0.025) * math.cos(phi)
        h = 0.27 * math.sin(phi) ** 0.35
        pts.append(HUB + np.array([x, 0, 0]) + h * up)
    return [carrier.world(p) for p in pts]


def scene(p):
    """All faces for one clip's parameters p."""
    faces = []
    cushion_y, back_z = 0.45, -0.36
    seat_dark, seat_mid = (46, 46, 50), (58, 58, 62)
    # floor, door sill and the far door panel
    faces += box([0.2, 0.0, 0.25], [2.6, 0.02, 1.6], (44, 46, 48), mat="fabric")
    faces += box([-0.95, 0.6, 0.0], [0.04, 1.2, 1.6], (52, 54, 58), mat="fabric")
    # rear bench: cushion slopes down toward the backrest, backrest leans back
    faces += box([0.0, cushion_y - 0.09, -0.06], [1.5, 0.18, 0.62], seat_mid, R=rot_x(math.radians(-8)), mat="fabric")
    faces += box([0.0, cushion_y + 0.33, back_z], [1.5, 0.72, 0.14], seat_dark, R=rot_x(math.radians(-14)), mat="fabric")
    faces += box([0.48, cushion_y + 0.78, back_z - 0.08], [0.24, 0.2, 0.14], seat_dark, mat="fabric")
    carrier = Carrier([p["x"], cushion_y + 0.01, -0.02], p["pitch"], p.get("yaw", 0.0))
    shell, pad = COLORWAYS[p["colorway"]]
    for f, color, mat in extrude(SEAT, -SHELL_HALF_W + WALL, SHELL_HALF_W - WALL, shell, pad, mat="fabric"):
        faces.append((carrier.world(f), color, mat))
    for side in (1, -1):
        x0 = side * (SHELL_HALF_W - WALL)
        for f, color, mat in extrude(SHELL, min(x0, side * SHELL_HALF_W), max(x0, side * SHELL_HALF_W), shell, shell):
            faces.append((carrier.world(f), color, mat))
    # level line: dark label with a green line on the near (door, +x) side
    label_c = np.array([SHELL_HALF_W + 0.003, 0.15, 0.10])
    faces.append((carrier.world(label_c + np.array([[0, -0.035, -0.07], [0, -0.035, 0.07], [0, 0.035, 0.07], [0, 0.035, -0.07]])), (55, 55, 55), "decal"))
    faces.append((carrier.world(label_c + np.array([[0.002, -0.006, -0.06], [0.002, -0.006, 0.06], [0.002, 0.006, 0.06], [0.002, 0.006, -0.06]])), (60, 200, 70), "decal"))
    # doll lying in the carrier, head toward the head end
    faces += [(carrier.world(f), c, m, carrier.world(o)) for f, c, m, o in ellipsoid(np.array([0, 0.30, 0.27]), [0.065, 0.07, 0.07], (150, 175, 215))]
    faces += [(carrier.world(f), c, m, carrier.world(o)) for f, c, m, o in ellipsoid(np.array([0, 0.21, 0.05]), [0.09, 0.06, 0.16], p["onesie"], R=rot_x(0.5), mat="fabric")]
    # guides: two lap guides at the rim, one rear guide on top of the back
    for side in (1, -1):
        g = LAP_GUIDE * np.array([0, 1, 1]) + np.array([side * (SHELL_HALF_W + 0.012), 0, 0])
        faces += [(carrier.world(f), c, m) for f, c, m in box(g, [0.022, 0.06, 0.07], GUIDE_COLOR, mat="guide")]
    faces += [(carrier.world(f), c, m) for f, c, m in box(REAR_GUIDE + np.array([0, 0.012, 0.02]), [0.08, 0.05, 0.022], GUIDE_COLOR, mat="guide")]
    # handle
    handle = handle_points(carrier, p["handle"])
    faces += tube(handle, 0.027, tuple(min(255, int(c * 1.1)) for c in shell), sides=12, mat="gloss")
    faces += tube(handle[9:16], 0.034, (60, 60, 64), sides=12, mat="fabric")
    faces += belts(p, carrier)
    if p.get("unseen") == "covered":  # a blanket over the whole belt path
        faces += [(carrier.world(f), c, "decal") for f, c, m in box(np.array([0, 0.43, 0.03]), [0.6, 0.36, 0.8], (170, 150, 200))]
    return faces


def belts(p, carrier):
    """Lap belt from the door-side anchor through both lap guides to the buckle, shoulder belt behind the head end
    through the rear guide up to the retractor. Mistakes move the belt off a guide or twist it."""
    x = p["x"]
    anchor_out = np.array([x + 0.34, 0.43, -0.30])
    buckle = np.array([x - 0.32, 0.47, -0.24])
    retractor = np.array([x + 0.45, 1.12, -0.48])
    rim = 0.305
    near = carrier.world(LAP_GUIDE * [0, 1, 1] + [SHELL_HALF_W + 0.004, 0.0, 0.0])
    far = carrier.world(LAP_GUIDE * [0, 1, 1] + [-SHELL_HALF_W - 0.004, 0.0, 0.0])
    miss = p.get("miss")
    if miss in ("near", "both"):  # the belt rides over the rim toward the head end instead of into the guide
        near = carrier.world([SHELL_HALF_W + 0.02, rim + 0.03, 0.10])
    if miss == "both":
        far = carrier.world([-SHELL_HALF_W - 0.02, rim + 0.03, 0.10])
    shift = {"near": lambda xx: 0.22 * max(xx, 0) / SHELL_HALF_W, "both": lambda xx: 0.22}.get(miss, lambda xx: 0.0)
    across = [carrier.world([xx, rim + 0.03, LAP_GUIDE[2] + shift(xx)]) for xx in (0.12, 0.0, -0.12)]
    lap = smooth_path([anchor_out, (anchor_out + near) / 2 + [0.03, 0.02, 0], near] + across + [far, (far + buckle) / 2 + [-0.02, 0, 0], buckle], 8)
    twist = p.get("twist")
    if twist:  # given as fractions of the stretch between the two lap guides (path points 16 to 48 of 64)
        twist = tuple((16 + 32 * v) / 64 for v in twist)
    up = lambda q: carrier.R @ np.array([0, 1, 0])
    faces = ribbon(lap, 0.048, up, BELT_COLOR, twist=twist)
    rear = carrier.world(REAR_GUIDE + [0, -0.004, 0.012])
    if miss == "rear":
        rear = carrier.world([0.05, 0.58, 0.12])
    around = carrier.world([-0.20, 0.36, 0.36]), carrier.world([-0.08, 0.47, 0.37])
    if miss == "rear":
        around = carrier.world([-0.20, 0.40, 0.10]), carrier.world([-0.08, 0.50, 0.11])
    over_head = [] if miss == "rear" else [carrier.world([0.18, 0.62, 0.30])]
    shoulder = smooth_path([buckle, buckle + [0.05, 0.08, 0.15], around[0], around[1], rear] + over_head + [retractor], 8)
    faces += ribbon(shoulder, 0.048, lambda q: unit(np.cross(unit(retractor - buckle), [1, 0, 0]) + [0, 0.3, 0]), BELT_COLOR)
    faces += box(buckle + [0, 0.02, 0.02], [0.05, 0.03, 0.08], (40, 40, 160))
    return faces


# ---------- drawing ----------

DECAL_BIAS = {"decal": 0.06, "guide": 0.03}
LIGHT = unit(np.array([0.5, 1.0, 0.35]))


def draw(faces, cam, light_gain=1.0, rng=None):
    img = np.zeros((H * SS, W * SS, 3), np.float32)
    img[:] = (24, 26, 28)
    items = []
    for face in faces:
        poly, color, mat = face[:3]
        pts, z = cam.project(poly)
        if np.any(z < 0.05):
            continue
        n = unit(np.cross(poly[1] - poly[0], poly[2] - poly[0]))
        centroid = poly.mean(0)
        if len(face) > 3 and face[3] is not None and float((centroid - face[3]) @ (centroid - cam.eye)) > 0:
            continue  # back face of a closed body
        bias = DECAL_BIAS.get(mat, 0.0)
        lam = 0.5 + 0.6 * abs(float(n @ LIGHT))
        gloss = {"plastic": 1.0, "webbing": 0.95, "fabric": 0.9, "skin": 1.0, "decal": 1.0, "guide": 1.0, "gloss": 1.0}[mat]
        shade = np.array(color) * lam * gloss * light_gain
        if mat == "gloss":
            view = unit(cam.eye - centroid)
            n_view = n if float(n @ view) > 0 else -n
            shade = shade + 150 * light_gain * max(float(n_view @ unit(LIGHT + view)), 0.0) ** 24
        items.append((float(z.mean()) - bias, pts, np.clip(shade, 0, 255)))
    items.sort(key=lambda it: -it[0])
    for _, pts, color in items:
        cv2.fillPoly(img, [np.round(pts * 4).astype(np.int32)], color.tolist(), lineType=cv2.LINE_AA, shift=2)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    if rng is not None:
        img += rng.normal(0, 3.0, img.shape).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    vignette = 1 - 0.25 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    return np.clip(img * vignette[..., None], 0, 255).astype(np.uint8)


def carrier_box_points(p):
    carrier = Carrier([p["x"], 0.46, -0.02], p["pitch"], p.get("yaw", 0.0))
    pts = [[x, y, z] for x in (-0.24, 0.24) for y in (0.0, 0.52) for z in (-0.34, 0.39)]
    return np.array([carrier.world(q) for q in pts])


def camera_at(p, t, pan_start, pan_s=0.5):
    """Camera on the floor until pan_start, a quick pan to the carrier, then a slow hand-held drift."""
    target = np.array([p["x"], 0.62, 0.02])
    eye = target + p["dist"] * np.array([math.cos(math.radians(p["elev"])) * math.cos(math.radians(p["cam_yaw"])),
                                         math.sin(math.radians(p["elev"])),
                                         math.cos(math.radians(p["elev"])) * math.sin(math.radians(p["cam_yaw"]))])
    floor = np.array([p["x"] + 0.7, 0.0, 0.6])
    if p.get("unseen") == "floor":
        floor = np.array([p["x"] + 1.1, 0.0, 1.0])
        k = 0.0
    else:
        k = min(max((t - pan_start) / pan_s, 0.0), 1.0)
        k = k * k * (3 - 2 * k)
    drift = np.array([0.012 * math.sin(1.3 * t + p["seed"]), 0.008 * math.sin(1.7 * t), 0.01 * math.cos(1.1 * t)])
    look = floor * (1 - k) + target * k + drift
    return Camera(eye + drift * 0.5, look, roll=math.radians(p["roll"] + 0.6 * math.sin(0.9 * t)))


def visible_s(p, pan_start, duration):
    corners = carrier_box_points(p)
    for i in range(int(duration * FPS)):
        t = i / FPS
        xy, z = camera_at(p, t, pan_start).project(corners)
        xy = xy / SS
        if np.all(z > 0) and np.all((xy[:, 0] > 0) & (xy[:, 0] < W) & (xy[:, 1] > 0) & (xy[:, 1] < H)):
            return round(t, 3)
    return None


def clip_params(rng, error, seed):
    p = {"seed": seed, "error": error, "x": float(rng.uniform(0.32, 0.42)), "pitch": float(rng.uniform(-2.5, 2.5)),
         "yaw": float(rng.uniform(-4, 4)), "handle": float(rng.uniform(-6, 6)), "colorway": int(rng.integers(0, 3)),
         "onesie": tuple(int(v) for v in rng.choice([(200, 190, 230), (220, 210, 170), (190, 220, 200)])),
         "dist": float(rng.uniform(1.35, 1.6)), "elev": float(rng.uniform(30, 40)), "cam_yaw": float(rng.uniform(-5, 5)),
         "roll": float(rng.uniform(-2, 2)), "light": float(rng.uniform(0.85, 1.15))}
    if error == "outside_guide":
        p["miss"] = str(rng.choice(["near", "both", "rear"]))
    elif error == "twisted":
        start = float(rng.uniform(0.25, 0.45))
        p["twist"] = (start, start + 0.35)
    elif error == "recline":
        p["pitch"] = float(rng.choice([-1, 1]) * rng.uniform(12, 20))
    elif error == "handle":
        p["handle"] = float(rng.choice([95.0, 125.0]) + rng.uniform(-5, 5))
    elif error == "unseen":
        p["unseen"] = str(rng.choice(["floor", "covered"]))
    return p


SETS = {
    # dev: the only set used to choose prompts and thresholds
    "dev": {"seed": 101, "counts": {"correct": 8, "outside_guide": 3, "twisted": 3, "recline": 3, "handle": 3, "unseen": 2}},
    # test: rendered once, never used for tuning
    "test": {"seed": 202, "counts": {"correct": 12, "outside_guide": 3, "twisted": 3, "recline": 3, "handle": 3, "unseen": 4}},
}


def render_clip(p, path, duration=16.0, pan_start=0.8):
    rng = np.random.default_rng(p["seed"])
    faces = scene(p)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    for i in range(int(duration * FPS)):
        writer.write(draw(faces, camera_at(p, i / FPS, pan_start), p["light"], rng))
    writer.release()
    return None if p.get("unseen") else visible_s(p, pan_start, duration)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--set", choices=sorted(SETS), default="test")
    parser.add_argument("--still", action="store_true", help="also write one still per clip for a quick look")
    args = parser.parse_args()
    out = Path(args.out).expanduser() / args.set
    out.mkdir(parents=True, exist_ok=True)
    spec = SETS[args.set]
    rng = np.random.default_rng(spec["seed"])
    labels, n = [], 0
    for error, count in spec["counts"].items():
        for k in range(count):
            n += 1
            p = clip_params(rng, error, spec["seed"] * 1000 + n)
            name = f"{args.set}-{n:02d}-{error}.mp4"
            vis = render_clip(p, out / name)
            if args.still:
                cv2.imwrite(str(out / name.replace(".mp4", ".jpg")), draw(scene(p), camera_at(p, 3.0, 0.8), p["light"]))
            labels.append({"clip": name, "error": None if error == "correct" else error, "visible_s": vis,
                           "params": {k2: v for k2, v in p.items() if k2 != "onesie"}})
            print(name, "visible_s", vis)
    (out / "labels.json").write_text(json.dumps(labels, indent=1))


if __name__ == "__main__":
    main()
