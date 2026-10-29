"""Lift check: tells a hand resting on the baby from one held a few cm above it, which the reflex reads as on.

A head camera looks down at the baby from camera_cm away. A hand lifted h cm toward it grows in the image by
camera_cm / (camera_cm - h), while the baby and the table keep their size. So while the reflex reads on, the check
keeps a baseline frame of the resting hands and measures each new frame against it: the scale of each hand's
SIFT features over the baseline, divided by the scale of the rest of the scene (that part absorbs the parent's
head moving closer or further). The ratio becomes a lift in cm, the lowest hand counts, and the reading is the
median of the last smooth_frames measures. The hands are lifted once that reading reaches min_lift_cm and rest
again once it falls under rest_cm. The baseline follows the hands while they rest (reading under rest_cm, refreshed
every refresh_s) and is frozen while they rise, so a slow drift is absorbed and a lift is not.
The skill keeps the baseline through a short reflex flicker to off and drops it after reset_after_off_s.

With regions "sam3" the hand regions come from SAM 3.1 instead of MediaPipe: the skill sends a resting frame to
SAM 3.1, and its hand masks (the ones that touch the baby mask) become the baseline once the answer lands, about
2 s later. The check then asks for a new anchor where it would otherwise refresh the baseline. No anchor, no reading.

Limits: a hand that arrives already hovering and never rests has no resting baseline, so it reads as resting.
A lift slower than about rest_cm per refresh_s is absorbed by the baseline. When a hand cannot be measured against
the baseline for refresh_s while resting, the baseline starts over. Everything runs on this machine.
"""
from collections import deque

import cv2
import numpy as np

DEFAULTS = {"camera_cm": 45.0, "min_lift_cm": 1.0, "rest_cm": 0.5, "refresh_s": 1.0, "smooth_frames": 5, "reset_after_off_s": 1.0,
            "min_matches": 8, "hull_grow": 1.18, "scene_margin_px": 30, "search_px": 60, "ratio": 0.8, "ransac_px": 2.0,
            "min_hands": 1, "regions": "mediapipe", "max_scene_shift_px": None, "max_scene_zoom": None, "max_hand_shift_px": None}


def hand_masks(hands_px, shape, grow):
    """Each hand as the convex hull of its 21 landmarks in pixels, grown a little about its centre."""
    masks = []
    for points in hands_px:
        points = np.asarray(points, np.float32)
        centre = points.mean(axis=0)
        hull = (cv2.convexHull(points) - centre) * grow + centre
        mask = np.zeros(shape, np.uint8)
        cv2.fillConvexPoly(mask, hull.astype(np.int32), 1)
        masks.append(mask.astype(bool))
    return masks


def similarity(p0, p1, ransac_px, min_matches):
    """Scale and shift in pixels of the similarity that maps p0 onto p1, or None when too few points agree."""
    if len(p0) < min_matches:
        return None
    matrix, inliers = cv2.estimateAffinePartial2D(np.float32(p0), np.float32(p1), method=cv2.RANSAC,
                                                  ransacReprojThreshold=ransac_px)
    if matrix is None or inliers.sum() < min_matches:
        return None
    return float(np.hypot(matrix[0, 0], matrix[1, 0])), matrix


def similarity_scale(p0, p1, ransac_px, min_matches):
    found = similarity(p0, p1, ransac_px, min_matches)
    return None if found is None else found[0]


def shift_px(matrix, point):
    """How far the similarity moves a point, in pixels."""
    x, y = point
    return float(np.hypot(matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2] - x,
                          matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2] - y))


class LiftCheck:
    def __init__(self, config=None):
        self.cfg = {**DEFAULTS, **(config or {})}
        self.sift = cv2.SIFT_create(nfeatures=3000, contrastThreshold=0.01)
        self.matcher = cv2.BFMatcher(cv2.NORM_L2)
        self.reset()

    def reset(self):
        self.base, self.base_s, self.lifted, self.lift_cm, self.failed_s = None, None, False, None, None
        self.recent = deque(maxlen=self.cfg["smooth_frames"])
        self.wants_anchor = self.cfg["regions"] == "sam3"

    def anchor(self, gray, hand_masks, baby, stream_s):
        """A SAM 3.1 answer for a resting frame: its hands on the baby become the baseline (regions sam3)."""
        self.wants_anchor = False
        if baby is not None and baby.any():
            near = cv2.dilate(baby.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
            hand_masks = [m for m in hand_masks if (m & near).any()]
        points, descriptors = self._features(gray)
        if len(hand_masks) < self.cfg["min_hands"] or descriptors is None:
            self.base = None
            return
        self._baseline(points, descriptors, hand_masks, stream_s)
        self.lifted, self.lift_cm = False, None

    def _rebase(self, points, descriptors, masks, stream_s):
        if self.cfg["regions"] == "sam3":
            self.wants_anchor = True
        else:
            self._baseline(points, descriptors, masks, stream_s)

    def _features(self, gray):
        keypoints, descriptors = self.sift.detectAndCompute(gray, None)
        points = np.float32([k.pt for k in keypoints]).reshape(-1, 2)
        return points, descriptors

    def _baseline(self, points, descriptors, masks, stream_s):
        h, w = masks[0].shape
        xy = np.clip(points.round().astype(int), 0, [w - 1, h - 1])
        union = np.zeros((h, w), np.uint8)
        for mask in masks:
            union |= mask.astype(np.uint8)
        margin = self.cfg["scene_margin_px"]
        near = cv2.dilate(union, np.ones((2 * margin + 1,) * 2, np.uint8)).astype(bool)
        search = self.cfg["search_px"]
        hands = []
        for mask in masks:
            inside = mask[xy[:, 1], xy[:, 0]]
            region = cv2.dilate(mask.astype(np.uint8), np.ones((2 * search + 1,) * 2, np.uint8)).astype(bool)
            hands.append({"points": points[inside], "descriptors": descriptors[inside], "region": region,
                          "centre": np.argwhere(mask).mean(axis=0)[::-1]})
        scene = ~near[xy[:, 1], xy[:, 0]]
        self.base = {"hands": hands, "scene_points": points[scene], "scene_descriptors": descriptors[scene]}
        self.base_s, self.failed_s = stream_s, None
        self.recent.clear()

    def _match(self, base_points, base_descriptors, points, descriptors, keep=None):
        if base_descriptors is None or len(base_descriptors) < 2 or descriptors is None or len(descriptors) < 2:
            return [], []
        if keep is not None:
            points, descriptors = points[keep], descriptors[keep]
            if len(descriptors) < 2:
                return [], []
        pairs = self.matcher.knnMatch(base_descriptors, descriptors, k=2)
        good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < self.cfg["ratio"] * p[1].distance]
        return [base_points[m.queryIdx] for m in good], [points[m.trainIdx] for m in good]

    def _camera_moved(self, scene, matrix, centre):
        """The head moved too much since the baseline for a scale reading to mean height: measure again from rest."""
        zoom, shift = self.cfg["max_scene_zoom"], self.cfg["max_scene_shift_px"]
        return (zoom is not None and abs(scene - 1) > zoom) or (shift is not None and shift_px(matrix, centre) > shift)

    def _hand_slid(self, hand_matrix, scene_matrix, centre):
        """The hand moved across the baby, beyond what a lift toward the camera explains: not a height reading."""
        limit = self.cfg["max_hand_shift_px"]
        if limit is None:
            return False
        moved = hand_matrix[:, :2] @ centre + hand_matrix[:, 2] - (scene_matrix[:, :2] @ centre + scene_matrix[:, 2])
        return float(np.hypot(*moved)) > limit

    def update(self, gray, hands_px, stream_s):
        """gray frame, the parent's hands over the baby as landmark arrays in pixels. Returns lifted or not."""
        sam = self.cfg["regions"] == "sam3"
        if not len(hands_px) or (not sam and len(hands_px) < self.cfg["min_hands"]):  # the bath asks for both hands
            self.reset()
            return False
        if sam and self.base is None:
            self.wants_anchor = True
            return False
        masks = None if sam else hand_masks(hands_px, gray.shape[:2], self.cfg["hull_grow"])
        points, descriptors = self._features(gray)
        if descriptors is None:
            return self.lifted
        if not sam and (self.base is None or len(self.base["hands"]) != len(masks)):
            self._baseline(points, descriptors, masks, stream_s)
            self.lifted, self.lift_cm = False, None
            return False
        cfg = self.cfg
        h, w = gray.shape[:2]
        xy = np.clip(points.round().astype(int), 0, [w - 1, h - 1])
        found = similarity(*self._match(self.base["scene_points"], self.base["scene_descriptors"], points, descriptors),
                           cfg["ransac_px"], cfg["min_matches"])
        scene, scene_matrix = found if found else (None, None)
        if scene is not None and self._camera_moved(scene, scene_matrix, (w / 2, h / 2)):
            scene = None
        lifts = []
        for hand in self.base["hands"]:
            keep = hand["region"][xy[:, 1], xy[:, 0]]
            found = similarity(*self._match(hand["points"], hand["descriptors"], points, descriptors, keep),
                               cfg["ransac_px"], cfg["min_matches"])
            if found is None or scene is None or self._hand_slid(found[1], scene_matrix, hand["centre"]):
                lifts.append(None)
                continue
            lifts.append(cfg["camera_cm"] * (1 - scene / found[0]))
        if any(v is None for v in lifts):  # cannot measure a hand: hold the last reading, start over if it lasts
            self.failed_s = stream_s if self.failed_s is None else self.failed_s
            if stream_s - self.failed_s >= cfg["refresh_s"] and not self.lifted:
                self._rebase(points, descriptors, masks, stream_s)
            return self.lifted
        self.failed_s = None
        self.recent.append(min(lifts))
        if len(self.recent) < self.recent.maxlen:
            return self.lifted
        self.lift_cm = float(np.median(self.recent))
        if self.lift_cm >= cfg["min_lift_cm"]:
            self.lifted = True
        elif self.lift_cm < cfg["rest_cm"]:
            self.lifted = False
            if stream_s - self.base_s >= cfg["refresh_s"]:
                self._rebase(points, descriptors, masks, stream_s)
        return self.lifted
