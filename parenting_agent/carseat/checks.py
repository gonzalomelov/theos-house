"""Visible checks of a belt-installed infant carrier, from SAM 3.1 masks.

SAM 3.1 finds the parts by text (the seat profile names the prompts, for example "strap" for the belt and
"blue clip" for the belt guides). The geometry here decides each check from those masks and returns
"pass", "fail" or "unseen". Unseen means the camera cannot tell, and the coach then asks for a better view.
It never turns unseen into pass.

Checks:
  lap_guides      the lap belt runs through both side guides
  shoulder_guide  the shoulder belt runs through the rear guide
  no_twist        the lap belt keeps its width across the carrier
  level_line      the level line on the carrier is level (the recline is right)
  handle          the handle stands upright, the car position
"""
import math

import numpy as np

CHECKS = ("lap_guides", "shoulder_guide", "no_twist", "level_line", "handle")
DEFAULTS = {
    "belt_min_score": 0.1, "guide_min_score": 0.15, "guide_relative_score": 0.6, "handle_min_score": 0.15, "level_min_score": 0.5,
    "guide_min_px": 60, "border_px": 4, "ring_scale": 0.6, "guide_coverage_min": 0.12,
    "twist_samples": 15, "lap_between_min": 0.6, "twist_inner": (0.2, 0.8), "twist_ratio_min": 0.45, "twist_found_min": 0.6,
    "level_max_deg": 8.0, "level_plausible_deg": 30.0, "handle_max_deg_from_vertical": 40.0, "handle_strap_margin": 0.05,
}


def _dilate(mask, px):
    import cv2
    px = max(int(px), 1)
    return cv2.dilate(mask.astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)).astype(bool)


def _touches_border(mask, px):
    return mask[:px].any() or mask[-px:].any() or mask[:, :px].any() or mask[:, -px:].any()


def _centroid(mask):
    ys, xs = np.nonzero(mask)
    return np.array([xs.mean(), ys.mean()])


def _axis_angle(mask):
    """Angle of the mask's main axis from the image horizontal, in degrees, -90 to 90."""
    ys, xs = np.nonzero(mask)
    pts = np.column_stack([xs - xs.mean(), ys - ys.mean()])
    _, vecs = np.linalg.eigh(pts.T @ pts)
    vx, vy = vecs[:, -1]
    angle = math.degrees(math.atan2(-vy, vx))
    return (angle + 90) % 180 - 90


def guides(found, prompt, cfg):
    """Distinct guide masks well inside the frame, best score first."""
    kept = []
    items = found.get(prompt, [])
    floor = max(cfg["guide_min_score"], cfg["guide_relative_score"] * max((s for s, _ in items), default=0))
    for score, mask in items:
        if score < floor or mask.sum() < cfg["guide_min_px"] or _touches_border(mask, cfg["border_px"]):
            continue
        if any((mask & k).sum() > 0.3 * min(mask.sum(), k.sum()) for k in kept):
            continue
        kept.append(mask)
    return kept


def split_guides(masks):
    """(lap pair, rear guide) from the guide masks. The two lap guides sit on either side of the carrier at the
    same point along it, so they line up across the view; the rear guide sits at the head end, off that line."""
    if len(masks) < 2:
        return None, None
    centers = [_centroid(m) for m in masks]
    best = None
    for i in range(len(masks)):
        for j in range(i + 1, len(masks)):
            dx, dy = abs(centers[i][0] - centers[j][0]), abs(centers[i][1] - centers[j][1])
            spread = dx / (dy + 1.0)
            if best is None or spread < best[0]:
                best = (spread, i, j)
    spread, i, j = best
    if spread > 1.0:
        return None, None
    lap = [masks[i], masks[j]]
    lap.sort(key=lambda m: -_centroid(m)[1])  # near guide (lower in the view) first
    rest = [m for k, m in enumerate(masks) if k not in (i, j)]
    return lap, (rest[0] if rest else None)


def belt_union(found, prompt, cfg, shape):
    belt = np.zeros(shape, bool)
    for score, mask in found.get(prompt, []):
        if score >= cfg["belt_min_score"]:
            belt |= mask
    return belt


def coverage(guide, belt, cfg):
    """Share of the ring around a guide that is belt."""
    size = math.sqrt(guide.sum())
    ring = _dilate(guide, cfg["ring_scale"] * size) & ~guide
    return float((ring & belt).sum() / max(ring.sum(), 1))


def twist_profile(belt, a, b, cfg):
    """Belt widths across the line from guide a to guide b, sampled in the inner stretch."""
    direction = b - a
    length = np.linalg.norm(direction)
    if length < 10:
        return []
    u = direction / length
    perp = np.array([-u[1], u[0]])
    h, w = belt.shape
    reach = int(0.25 * length)
    widths = []
    lo, hi = cfg["twist_inner"]
    for f in np.linspace(lo, hi, cfg["twist_samples"]):
        center = a + f * direction
        line = []
        for k in range(-reach, reach + 1):
            x, y = (center + k * perp).round().astype(int)
            line.append(bool(0 <= x < w and 0 <= y < h and belt[y, x]))
        hits = [k for k, on in enumerate(line) if on]
        if not hits:
            widths.append(None)
            continue
        mid = min(hits, key=lambda k: abs(k - reach))  # the run nearest the line between the guides
        left = right = mid
        while left > 0 and line[left - 1]:
            left -= 1
        while right < len(line) - 1 and line[right + 1]:
            right += 1
        widths.append(right - left + 1)
    return widths


def _strap_wins(mask, score, straps, cfg):
    """True when SAM reads the same pixels as a strap more surely than as a handle: then it is a belt."""
    for strap_score, strap in straps:
        union = (mask | strap).sum()
        if union and (mask & strap).sum() / union >= 0.5 and strap_score >= score + cfg["handle_strap_margin"]:
            return True
    return False


def analyze(found, prompts, shape, config=None):
    """{check: {"result": pass|fail|unseen, ...numbers}} for one frame's masks."""
    cfg = {**DEFAULTS, **(config or {})}
    out = {}
    guide_masks = guides(found, prompts["guide"], cfg)
    lap, rear = split_guides(guide_masks)
    belt = belt_union(found, prompts["belt"], cfg, shape)
    belt_seen = belt.sum() > 0
    if lap is None or not belt_seen:
        out["lap_guides"] = {"result": "unseen", "guides": len(guide_masks), "belt_px": int(belt.sum())}
    else:
        cover = [round(coverage(g, belt, cfg), 3) for g in lap]
        widths = twist_profile(belt, _centroid(lap[0]), _centroid(lap[1]), cfg)
        between = round(sum(1 for v in widths if v) / max(len(widths), 1), 3)
        ok = min(cover) >= cfg["guide_coverage_min"] and between >= cfg["lap_between_min"]
        out["lap_guides"] = {"result": "pass" if ok else "fail", "coverage": cover, "between": between,
                             "missed": [("near", "far")[k] for k, c in enumerate(cover) if c < cfg["guide_coverage_min"]]}
    if rear is None or not belt_seen:
        out["shoulder_guide"] = {"result": "unseen", "guides": len(guide_masks)}
    else:
        c = round(coverage(rear, belt, cfg), 3)
        out["shoulder_guide"] = {"result": "pass" if c >= cfg["guide_coverage_min"] else "fail", "coverage": c}
    if out["lap_guides"]["result"] != "pass":
        out["no_twist"] = {"result": "unseen", "why": "the lap belt is not seen between both guides"}
    else:
        widths = twist_profile(belt, _centroid(lap[0]), _centroid(lap[1]), cfg)
        seen = [v for v in widths if v]
        if len(seen) < cfg["twist_found_min"] * max(len(widths), 1):
            out["no_twist"] = {"result": "unseen", "widths": widths}
        else:
            ratio = round(min(seen) / float(np.median(seen)), 3)
            out["no_twist"] = {"result": "pass" if ratio >= cfg["twist_ratio_min"] else "fail", "ratio": ratio, "widths": widths}
    levels = [(s, m) for s, m in found.get(prompts["level"], []) if s >= cfg["level_min_score"] and m.sum() >= 20
              and not _touches_border(m, cfg["border_px"])]
    if not levels:
        out["level_line"] = {"result": "unseen"}
    else:
        angle = round(_axis_angle(levels[0][1]), 1)
        if abs(angle) > cfg["level_plausible_deg"]:
            # a carrier is never installed that steep: SAM read some other line (a label, a belt edge) as the level line
            out["level_line"] = {"result": "unseen", "angle_deg": angle, "why": "implausible angle"}
        else:
            out["level_line"] = {"result": "pass" if abs(angle) <= cfg["level_max_deg"] else "fail", "angle_deg": angle}
    handles = [(s, m) for s, m in found.get(prompts["handle"], []) if s >= cfg["handle_min_score"] and m.sum() >= 40
               and not _strap_wins(m, s, found.get(prompts["belt"], []), cfg)]
    if not handles or not guide_masks:
        out["handle"] = {"result": "unseen"}
    else:
        angle = _axis_angle(handles[0][1])
        from_vertical = round(90 - abs(angle), 1)
        out["handle"] = {"result": "pass" if from_vertical <= cfg["handle_max_deg_from_vertical"] else "fail",
                         "deg_from_vertical": from_vertical, "score": handles[0][0]}
    return out
