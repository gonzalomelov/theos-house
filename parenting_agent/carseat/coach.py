"""Car seat coach: one step at a time by voice, the camera checks what it can see, the parent answers the rest.

The steps come from the seat profile (the maker's manual) and the car profile, in the order of a real install: the
harness first, while the carrier still faces the parent. A camera step waits for the parent to finish: a spoken "listo"
or "ya" (ready()), or the check passing on its own, or a long fallback. Then it runs SAM 3.1 on the newest frames until a
check passes or fails, or the view times out and is listed as not seen. The belt guides are judged only up close: the
coach asks the parent to bring the phone to each guide. Ask steps (the seat position in the car and the hand checks a camera cannot see) are
spoken, wait for the parent's answer and are logged. They are never skipped: an unanswered one stays open in
the summary. The coach never calls the install safe. The summary lists which visible checks passed, which
failed or were not seen, which hand checks remain, and suggests one check by a certified technician.

Frames stay in memory on this machine. Only the spoken text and the summary reach the bus and the brain.
"""
import json
import re
import threading
import time
from pathlib import Path

from . import checks as checks_mod

# Every line the coach says, in English and in Spanish (es-UY, voseo). The parent hears, reads on Telegram and sees on
# the glasses card the language of the people block. Never "safe", never "seguro" or "segura".
# A camera step first waits for the parent to finish ("listo", or the check passing on its own, or a long fallback),
# then judges. The guide steps judge only close-ups, one per guide ("closeups"): from the door SAM 3.1 never found the
# guides on a real install video (Nov 1), only with the phone 30 to 50 cm from them.
CAMERA_STEPS = {
    "lap_guides": {
        "prompts": ("belt", "guide"), "manual_step": 0, "closeups": ("near", "far"),
        "en": {"say": "Slide the lap belt into both blue side guides of the carrier. Say done when you finish.",
               "pass": "I can see the lap belt in both side guides.",
               "fail": "The lap belt is not in the {missed}.",
               "unseen": "I could not see the lap belt and both side guides."},
        "es": {"say": "Pasá el cinturón de cadera por las dos guías azules de los costados de la silla. Decime listo "
                      "cuando termines.",
               "pass": "Veo el cinturón de cadera en las dos guías laterales.",
               "fail": "El cinturón de cadera no está en {missed}.",
               "unseen": "No pude ver el cinturón de cadera y las dos guías laterales."}},
    "shoulder_guide": {
        "prompts": ("belt", "guide"), "manual_step": 1, "closeups": ("rear",),
        "en": {"say": "Take the shoulder belt around the back of the carrier and slide it into the blue rear guide, "
                      "behind the head end. Say done when you finish.",
               "pass": "I can see the shoulder belt in the rear guide.",
               "fail": "The shoulder belt is not in the rear guide.",
               "unseen": "I could not see the rear guide."},
        "es": {"say": "Pasá el cinturón de hombro por detrás de la silla y metelo en la guía azul de atrás, detrás de "
                      "la cabecera. Decime listo cuando termines.",
               "pass": "Veo el cinturón de hombro en la guía de atrás.",
               "fail": "El cinturón de hombro no está en la guía de atrás.",
               "unseen": "No pude ver la guía de atrás."}},
    "no_twist": {
        "prompts": ("belt", "guide"), "manual_step": 2,
        "en": {"say": "Show me the lap belt from the door, across the carrier: it has to lie flat, with no twist. Say "
                      "done when you are there.",
               "pass": "The lap belt looks flat across the carrier.",
               "fail": "The lap belt looks twisted across the carrier.",
               "unseen": "I could not see the lap belt well enough to check for a twist."},
        "es": {"say": "Mostrame desde la puerta el cinturón de cadera sobre la silla: tiene que quedar plano, sin "
                      "giros. Decime listo cuando estés.",
               "pass": "El cinturón de cadera se ve plano sobre la silla.",
               "fail": "El cinturón de cadera se ve girado sobre la silla.",
               "unseen": "No pude ver bien el cinturón de cadera para revisar si está girado."}},
    "level_line": {
        "prompts": ("level",), "manual_step": 3,
        "en": {"say": "Show me the level line on the side of the carrier, with your head held level. Say done when you "
                      "are there.",
               "pass": "The level line looks level.",
               "fail": "The level line is tilted about {angle} degrees. The manual says it must be level to the ground.",
               "unseen": "I could not see the level line."},
        "es": {"say": "Mostrame la línea de nivel al costado de la silla, con la cabeza derecha. Decime listo cuando "
                      "estés.",
               "pass": "La línea de nivel se ve nivelada.",
               "fail": "La línea de nivel está inclinada unos {angle} grados. El manual dice que tiene que quedar "
                       "nivelada con el piso.",
               "unseen": "No pude ver la línea de nivel."}},
    "handle": {
        "prompts": ("handle", "belt", "seat"), "manual_step": None,
        "en": {"say": "Put the handle upright, in position {position}, the car position. Say done when you finish.",
               "pass": "The handle is upright.",
               "fail": "The handle is not upright. Move it to position {position}.",
               "unseen": "I could not see the handle."},
        "es": {"say": "Poné la manija hacia arriba, en la posición {position}, la posición para el auto. Decime listo "
                      "cuando termines.",
               "pass": "La manija está hacia arriba.",
               "fail": "La manija no está hacia arriba. Movela a la posición {position}.",
               "unseen": "No pude ver la manija."}},
}
# The order of a real belt install (Joie i-Gemm video, Nov 1, and the i-Snug 2 manual). The harness comes first: the
# camera sees it only while the baby or doll faces the parent, before the carrier goes in the car facing back.
ORDER = ("harness_pinch", "car_position", "lap_guides", "buckle", "shoulder_guide", "tension", "no_twist", "level_line",
         "handle", "belt_path_movement")
# What a parent says when a step is done ("listo", "ya"), on the glasses microphone or in the chat.
READY = ("listo", "lista", "ya", "terminé", "termine", "done", "ready", "finished")
LINES = {
    "en": {"unsure": "My two checks disagree here, so I am not counting it as passed. Show me another view, or check it "
                     "by hand against the manual.",
           "not_checked": " I am listing it as not checked.",
           "fix": "Noted. Please fix this before driving, and ask me to check again.",
           "open": "I will keep this check open in the summary.",
           "both_guides": "near and far side guides", "one_guide": "{side} side guide", "side": "side",
           "near": "near", "far": "far", "a_few": "a few",
           "start": "Coaching the {seat} in the {car}, installed with the seat belt and no base. We start with the "
                    "harness, while the carrier still faces you.",
           "car_position": "Put the carrier on a rear seat, facing the back of the car. {rule} Is the carrier on a rear "
                           "seat, facing the back? Say yes or no.",
           "closeup": "Bring the phone close to the {guide}.",
           "closeup_pass": "I can see the belt in the {guide}.", "closeup_fail": "The belt is not in the {guide}.",
           "closeup_unseen": "I could not see the {guide} up close.",
           "guides": {"near": "blue guide on the door side", "far": "blue guide on the far side",
                      "rear": "blue guide at the back"},
           "ready": "OK, looking.",
           "not_a_verdict": "This is not a verdict on the install.",
           "missing": "Not done yet"},
    "es": {"unsure": "Mis dos chequeos no coinciden acá, así que no lo cuento como bien. Mostrame otra vista, o revisalo "
                     "a mano con el manual.",
           "not_checked": " Lo dejo como no revisado.",
           "fix": "Anotado. Corregilo antes de manejar y pedime que lo revise de nuevo.",
           "open": "Dejo este chequeo abierto en el resumen.",
           "both_guides": "las guías laterales de los dos lados", "one_guide": "la guía lateral del lado {side}",
           "side": "de la puerta", "near": "de la puerta", "far": "de adentro", "a_few": "unos pocos",
           "start": "Te guío con la {seat} en el {car}, instalada con el cinturón del auto y sin base. Empezamos por el "
                    "arnés, con la silla todavía mirando hacia vos.",
           "car_position": "Poné la silla en un asiento de atrás, mirando hacia la parte de atrás del auto. {rule} ¿La "
                           "silla está en un asiento de atrás, mirando hacia atrás? Decí sí o no.",
           "closeup": "Acercá el teléfono a la {guide}.",
           "closeup_pass": "Veo el cinturón en la {guide}.", "closeup_fail": "El cinturón no está en la {guide}.",
           "closeup_unseen": "No pude ver de cerca la {guide}.",
           "guides": {"near": "guía azul del lado de la puerta", "far": "guía azul del otro lado",
                      "rear": "guía azul de atrás"},
           "ready": "Dale, miro.",
           "not_a_verdict": "Esto no es un veredicto sobre la instalación.",
           "missing": "Falta hacer"},
}
SUMMARY = {
    "en": (("camera", "pass", "Visible checks that passed"), ("camera", "fail", "Visible checks that failed"),
           ("camera", "unseen", "Visible checks I could not see"),
           ("camera", "unsure", "Visible checks my two checks disagree on, check them by hand"),
           ("hand", "pass", "Hand checks you confirmed"), ("hand", "fail", "Hand checks that need fixing"),
           ("hand", "open", "Hand checks still open")),
    "es": (("camera", "pass", "Chequeos con cámara que pasaron"), ("camera", "fail", "Chequeos con cámara que fallaron"),
           ("camera", "unseen", "Chequeos con cámara que no pude ver"),
           ("camera", "unsure", "Chequeos con cámara en los que mis dos chequeos no coinciden, revisalos a mano"),
           ("hand", "pass", "Chequeos a mano que confirmaste"), ("hand", "fail", "Chequeos a mano para corregir"),
           ("hand", "open", "Chequeos a mano todavía abiertos")),
}
NAMES = {
    "en": {"lap_guides": "lap belt in both side guides", "shoulder_guide": "shoulder belt in the rear guide",
           "no_twist": "no twist in the lap belt", "level_line": "level line level", "handle": "handle upright",
           "car_position": "carrier on a rear seat facing back",
           "belt_path_movement": "less than 2.5 centimeters of movement at the belt path",
           "harness_pinch": "no slack in the harness pinch test", "buckle": "seat belt buckled with a click",
           "tension": "lap belt tightened, then the shoulder belt"},
    "es": {"lap_guides": "cinturón de cadera en las dos guías laterales", "shoulder_guide": "cinturón de hombro en la guía de atrás",
           "no_twist": "sin giros en el cinturón de cadera", "level_line": "línea de nivel nivelada",
           "handle": "manija hacia arriba", "car_position": "silla en un asiento de atrás mirando hacia atrás",
           "belt_path_movement": "menos de 2,5 centímetros de movimiento en el cinturón",
           "harness_pinch": "sin correa de sobra en la prueba del pellizco", "buckle": "cinturón abrochado con clic",
           "tension": "cinturón de cadera tenso, después el de hombro"},
}
# Words the coach never says about an install, in either language. "Cinturón de seguridad" is the seat belt and
# "seguridad" alone is allowed, "seguro" and "segura" (safe) are not.
FORBIDDEN = ("safe", "safely", "seguro", "segura", "seguros", "seguras")


def lang_of(lang):
    return "es" if lang == "es" else "en"


def localized(item, key, lang):
    """item[key + "_es"] in Spanish when the profile has it, else item[key]."""
    return (item.get(f"{key}_es") if lang == "es" else None) or item[key]


def load_profiles(cfg, root="."):
    root = Path(root)
    seat = json.loads((root / cfg["seat_profile"]).read_text())
    car = json.loads((root / cfg["car_profile"]).read_text())
    return seat, car


def step_ids(cfg):
    """The coach's step ids in the order it runs them: the skill's "order" exactly, else ORDER then any other hand
    check of the skill."""
    hands = [h["id"] for h in cfg.get("hand_checks", [])]
    known = {"car_position", *CAMERA_STEPS, *hands}
    ids = [i for i in cfg.get("order", ORDER) if i in known]
    return ids if "order" in cfg else ids + [h for h in hands if h not in ids]


def plan(cfg, seat, car, lang="en"):
    """The ordered steps for this seat and car, each said in lang. The first step opens with who the coach is."""
    lang = lang_of(lang)
    lines = LINES[lang]
    rule = " ".join(localized(r, "text", lang) for r in car["rules"] if r["id"] == "no_front_airbag")
    position = seat.get("handle_car_position") or 1
    hands = {h["id"]: h for h in cfg.get("hand_checks", [])}
    steps = []
    for step_id in step_ids(cfg):
        if step_id == "car_position":
            steps.append({"id": step_id, "kind": "ask", "say": lines["car_position"].format(rule=rule),
                          "pass_answer": "yes"})
        elif step_id in CAMERA_STEPS:
            step = CAMERA_STEPS[step_id]
            n = step["manual_step"]
            manual = seat["steps"][n] if n is not None and n < len(seat["steps"]) else None
            steps.append({"id": step_id, "kind": "camera", "say": step[lang]["say"].format(position=position),
                          "manual": manual})
        else:
            hand = hands[step_id]
            steps.append({"id": step_id, "kind": "ask", "say": localized(hand, "ask", lang),
                          "pass_answer": hand.get("pass_answer", "yes"), "source": hand.get("source")})
    intro = lines["start"].format(seat=seat["seat"], car=car["car"])
    steps[0]["say"] = " ".join(f"{intro} {steps[0]['say']}".split())
    return steps


def is_ready(text):
    """True for "listo", "ya", "done" and the like: the parent finished the step they were doing."""
    words = (text or "").strip().lower().replace(",", " ").replace(".", " ").replace("!", " ").replace("¡", " ").split()
    return bool(words) and len(words) <= 3 and words[0] in READY


def _yes_no(text):
    words = (text or "").strip().lower().replace(",", " ").replace(".", " ").split()
    if not words:
        return None
    if words[0] in ("yes", "yeah", "yep", "si", "sí", "correct"):
        return "yes"
    if words[0] in ("no", "nope", "not"):
        return "no"
    return None


class Coach:
    def __init__(self, cfg, bus, vision, source, seat, car, answer_timeout_s=None, clock=time.monotonic, muse=None,
                 lang="en"):
        self.cfg, self.bus, self.vision, self.source = cfg, bus, vision, source
        self.lang = lang_of(lang)
        self.lines = LINES[self.lang]
        self.muse = muse  # a MuseSeatCheck: Muse Spark Open's second opinion on the same frame
        self.seat, self.car = seat, car
        self.answer_timeout_s, self.clock = answer_timeout_s, clock
        self.steps = plan(cfg, seat, car, self.lang)
        self.results = {}
        self.answers, self.answer_ready = {}, threading.Condition()
        self.readies = set()  # camera steps the parent said "listo" for
        self.stop_flag = False
        self.asking = None  # the ask step waiting for the parent's yes or no
        self.waiting = None  # the camera step waiting for the parent's "listo"
        self._last_frame = None

    # ---------- speech and logging ----------

    def say(self, text, **fields):
        words = set(re.findall(r"[^\W\d_]+", text.lower()))
        for word in FORBIDDEN:
            if word in words:
                raise ValueError(f"the coach must never say '{word}': {text}")
        self.bus.publish("voice", text=text, skill="car-seat", lang=self.lang, stream_s=self.stream_now(), **fields)

    def stream_now(self):
        started = getattr(self.source, "started", None)
        return round(self.clock() - started, 3) if started else 0.0

    # ---------- answers from the parent ----------

    def answer(self, check_id, text):
        """The parent's reply to an ask step, from voice, chat or a tool call."""
        with self.answer_ready:
            self.answers[check_id] = text
            self.answer_ready.notify_all()
        return f"noted for {check_id}"

    def ready(self, check_id=None):
        """The parent said "listo": the camera step they were doing (or check_id) is done, judge it now."""
        with self.answer_ready:
            check_id = check_id or self.waiting
            if check_id is None:
                return "the car seat coach is not waiting for a step"
            self.readies.add(check_id)
            self.answer_ready.notify_all()
        return f"ready for {check_id}"

    def _wait_answer(self, check_id):
        deadline = None if self.answer_timeout_s is None else self.clock() + self.answer_timeout_s
        with self.answer_ready:
            while check_id not in self.answers and not self.stop_flag:
                remaining = None if deadline is None else deadline - self.clock()
                if remaining is not None and remaining <= 0:
                    return None
                self.answer_ready.wait(timeout=0.2 if remaining is None else min(remaining, 0.2))
            return self.answers.get(check_id)

    # ---------- steps ----------

    def run_ask(self, step):
        self.asking = step["id"]
        self.say(step["say"], step=step["id"])
        reply = self._wait_answer(step["id"])
        self.asking = None
        said = _yes_no(reply)
        if said is None:
            result = "open"
        else:
            result = "pass" if said == step["pass_answer"] else "fail"
        self.results[step["id"]] = {"kind": "hand", "result": result, "answer": reply}
        self.bus.publish("carseat_check", check=step["id"], check_kind="hand", result=result, answer=reply)
        if result == "fail":
            self.say(self.lines["fix"], step=step["id"], result="fail")
        elif result == "open":
            self.say(self.lines["open"], step=step["id"], result="open")

    def views(self, check_id):
        """What a camera step judges: one door-distance view (None), or one close-up per guide ("near", "far", "rear").
        With "closeup": false in the skill (the rendered clips, filmed from the door) the guides are judged from the door."""
        if self.cfg.get("closeup", True):
            return list(CAMERA_STEPS[check_id].get("closeups") or [None])
        return [None]

    def run_camera(self, step):
        """Say the step, wait for the parent to finish it, then judge each view of it on the newest frames.

        The parent finishes with "listo" (ready()), or the first view's check passes on its own, or ready_timeout_s
        runs out (a long fallback, the parent may need minutes). Before that a fail is never said: the parent is still
        working. Then each close-up is asked for and judged on close frames only, for closeup_timeout_s, and a door
        view for step_timeout_s. A view that never shows is listed as not seen."""
        check_id = step["id"]
        spec = {**CAMERA_STEPS[check_id], **CAMERA_STEPS[check_id][self.lang]}
        views = self.views(check_id)
        started_at = self.stream_now()
        _, seq, _ = self._latest(0) or (None, 0, 0.0)
        self.say(step["say"], step=check_id)
        verdicts = {}
        self.waiting = check_id
        seq, early = self._watch(check_id, views[0], seq, self.cfg.get("ready_timeout_s", 180.0), "act")
        self.waiting = None
        if early is not None and views[0] is not None:
            seq, early = self._closeup(check_id, views[0], seq, [early])  # a close pass while working needs a second frame
        if early is not None:
            verdicts[views[0]] = self._speak(check_id, views[0], spec, *early)
        for view in views:
            if view in verdicts:
                continue
            if view is not None:
                self.say(self.lines["closeup"].format(guide=self.lines["guides"][view]), step=check_id, view=view)
            if view is None:
                seq, got = self._watch(check_id, view, seq, self.cfg.get("step_timeout_s", 20.0), "judge")
            else:
                seq, got = self._closeup(check_id, view, seq)
            verdicts[view] = self._speak(check_id, view, spec, *(got or (None, None, self._last_frame)))
        if views == [None]:
            verdict, frame_s, spoken_at = verdicts[None]
            self._record(step, verdict, started_at, frame_s, spoken_at)
            return
        results = [v[0]["result"] for v in verdicts.values()]
        result = next((r for r in ("fail", "unsure", "unseen") if r in results), "pass")
        detail = {"result": result, "views": {view: {**{k: v for k, v in verdict.items() if k != "widths"},
                                                     "frame_s": frame_s} for view, (verdict, frame_s, _) in verdicts.items()}}
        if result == "fail" and check_id == "lap_guides":
            detail["missed"] = [view for view, (verdict, _, _) in verdicts.items() if verdict["result"] == "fail"]
        self._record(step, detail, started_at, None, self.stream_now())

    def _watch(self, check_id, view, seq, timeout_s, phase):
        """Newest frames until a verdict: in the "act" phase only a pass (or "listo", or the timeout) ends the watch, in
        the "judge" phase any pass or fail does. Returns (seq, (verdict, frame_s, frame) or None)."""
        deadline = self.clock() + timeout_s
        self._last_frame = None
        while not self.stop_flag:
            if phase == "act" and check_id in self.readies:
                return seq, None
            if self.clock() >= deadline:
                return seq, None
            got = self._latest(seq)
            if got is None:
                if getattr(self.source, "stopped", False):
                    return seq, None
                with self.answer_ready:
                    self.answer_ready.wait(timeout=0.005)
                continue
            frame, seq, frame_s = got
            self._last_frame = frame
            verdict, seconds = self.check(check_id, view, frame)
            self.bus.publish("carseat_frame", step=check_id, view=view, phase=phase, frame_s=round(frame_s, 3),
                             sam_s=seconds, result=verdict["result"])
            if verdict["result"] == "pass" or (phase == "judge" and verdict["result"] != "unseen"):
                return seq, (verdict, frame_s, frame)
        return seq, None

    def _closeup(self, check_id, view, seq, seen=None):
        """A guide's verdict from close frames: two that agree, within closeup_timeout_s. One close frame alone counts
        when no other comes, a pass and a fail with no third frame are "unsure". On a real video one close frame of a
        belt in its guide read 0.07 of the ring as belt and the next ones 0.12 and 0.19."""
        deadline = self.clock() + self.cfg.get("closeup_timeout_s", 30.0)
        seen = list(seen or [])
        while True:
            seq, got = self._watch(check_id, view, seq, max(deadline - self.clock(), 0.0), "judge")
            if got is None:
                break
            seen.append(got)
            results = [v["result"] for v, _, _ in seen]
            if results.count(got[0]["result"]) >= 2:
                return seq, got
        if not seen:
            return seq, None
        if len({v["result"] for v, _, _ in seen}) == 1:
            return seq, seen[-1]
        verdict, frame_s, frame = seen[-1]
        return seq, ({**verdict, "result": "unsure", "frames": [v["result"] for v, _, _ in seen]}, frame_s, frame)

    def check(self, check_id, view, frame):
        """One frame's verdict for a step: the door-view checks, or the close-up check of one guide."""
        prompts_cfg = self.cfg["prompts"]
        prompts = [prompts_cfg[k] for k in CAMERA_STEPS[check_id]["prompts"] if k in prompts_cfg]
        found, seconds = self.vision.masks(frame, prompts)
        if view is None:
            verdict = checks_mod.analyze(found, prompts_cfg, frame.shape[:2], self.cfg.get("checks"))[check_id]
        else:
            verdict = checks_mod.closeup(found, prompts_cfg, frame.shape[:2], self.cfg.get("checks"))
        return verdict, seconds

    def _speak(self, check_id, view, spec, verdict, frame_s, frame):
        """Say what one view showed, with Muse's second opinion where it votes. Returns (verdict, frame_s, spoken_at)."""
        position = self.seat.get("handle_car_position") or 1
        if verdict is None:  # nothing seen in time: Muse may still see the last frame (door views only)
            verdict = {"result": "unseen"}
            if view is None and frame is not None:
                verdict = self.second_opinion(check_id, frame, verdict)
            if verdict["result"] == "unseen":
                line = spec["unseen"] if view is None else \
                    self.lines["closeup_unseen"].format(guide=self.lines["guides"][view])
                text = line + self.lines["not_checked"]
            elif verdict["result"] == "fail":
                text = spec["fail"].format(missed=self.missed([]), angle=self.lines["a_few"], position=position)
            else:
                text = self.lines["unsure"]
        else:
            verdict = self.second_opinion(check_id, frame, verdict)
            if view is not None:
                key = {"pass": "closeup_pass", "fail": "closeup_fail"}.get(verdict["result"])
                text = self.lines[key].format(guide=self.lines["guides"][view]) if key else self.lines["unsure"]
            else:
                text = (spec[verdict["result"]] if verdict["result"] in spec else self.lines["unsure"]).format(
                    missed=self.missed(verdict.get("missed") or []), angle=round(abs(verdict.get("angle_deg", 0))),
                    position=position)
        spoken_at = self.stream_now()
        self.say(text, step=check_id, result=verdict["result"], **({"view": view} if view else {}))
        return verdict, (None if frame_s is None else round(frame_s, 3)), spoken_at

    def missed(self, sides):
        """The side guides a fail names: both, or the one ("near" or "far") the belt is not in."""
        if len(sides) == 2:
            return self.lines["both_guides"]
        side = self.lines.get(sides[0], sides[0]) if sides else self.lines["side"]
        return self.lines["one_guide"].format(side=side)

    def second_opinion(self, check_id, frame, verdict):
        """SAM's verdict combined with Muse's on the same frame, for the checks Muse votes on (muse_check.py)."""
        from . import muse_check
        if self.muse is None or check_id not in muse_check.MUSE_VOTES:
            return verdict
        muse = self.muse.look(frame, check_id)
        both = muse_check.combine(verdict["result"], muse.get("result"))
        self.bus.publish("carseat_muse", step=check_id, sam=verdict["result"], muse=muse.get("result"),
                         result=both["result"], second_opinion=both["second_opinion"], muse_s=muse.get("seconds"),
                         usd=muse.get("usd"), host=muse.get("host"), error=muse.get("error"))
        return {**verdict, "result": both["result"], "sam_result": verdict["result"], "muse_result": muse.get("result"),
                "second_opinion": both["second_opinion"]}

    def _record(self, step, verdict, started_at, frame_s, spoken_at):
        detail = {k: v for k, v in verdict.items() if k not in ("widths",)}
        self.results[step["id"]] = {"kind": "camera", **detail, "step_started_s": started_at,
                                    "frame_s": frame_s, "spoken_s": spoken_at}
        self.bus.publish("carseat_check", check=step["id"], **{("check_kind" if k == "kind" else k): v for k, v in self.results[step["id"]].items()})

    def _latest(self, seq):
        return self.source.latest(seq)

    # ---------- whole run ----------

    def run(self):
        self.bus.publish("skill_armed", skill="car-seat")
        for step in self.steps:
            if self.stop_flag:
                break
            self.bus.publish("carseat_step", step=step["id"], step_kind=step["kind"])
            (self.run_camera if step["kind"] == "camera" else self.run_ask)(step)
        text = self.summary()
        self.say(text, step="summary")
        self.bus.publish("carseat_summary", text=text, results=self.results)
        return self.results

    def summary(self):
        names = NAMES[self.lang]
        parts = []
        for kind, result, label in SUMMARY[self.lang]:
            items = [names.get(k, k) for k, v in self.results.items() if v["kind"] == kind and v["result"] == result]
            if items:
                parts.append(f"{label}: {', '.join(items)}.")
        missing = [s["id"] for s in self.steps if s["id"] not in self.results]
        if missing:
            parts.append(f"{self.lines['missing']}: {', '.join(names.get(m, m) for m in missing)}.")
        parts.append(self.lines["not_a_verdict"] + " " + localized(self.cfg, "technician", self.lang))
        return " ".join(parts)

    def stop(self):
        self.stop_flag = True
        with self.answer_ready:
            self.answer_ready.notify_all()
