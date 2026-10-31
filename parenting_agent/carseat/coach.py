"""Car seat coach: one step at a time by voice, the camera checks what it can see, the parent answers the rest.

The steps come from the seat profile (the maker's manual) and the car profile. Camera steps run SAM 3.1 on the
newest frame taken after the step was spoken, until a check passes or fails, or the step times out and is
listed as not seen. Ask steps (the seat position in the car and the hand checks a camera cannot see) are
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
CAMERA_STEPS = {
    "lap_guides": {
        "prompts": ("belt", "guide"), "manual_step": 0,
        "en": {"say": "Slide the lap belt into both side guides of the carrier, then show me the belt path from the door.",
               "pass": "I can see the lap belt in both side guides.",
               "fail": "The lap belt is not in the {missed}.",
               "unseen": "I could not see the lap belt and both side guides."},
        "es": {"say": "Pasá el cinturón de cadera por las dos guías laterales de la silla y mostrame el recorrido del "
                      "cinturón desde la puerta.",
               "pass": "Veo el cinturón de cadera en las dos guías laterales.",
               "fail": "El cinturón de cadera no está en {missed}.",
               "unseen": "No pude ver el cinturón de cadera y las dos guías laterales."}},
    "shoulder_guide": {
        "prompts": ("belt", "guide"), "manual_step": 1,
        "en": {"say": "Slide the shoulder belt into the rear guide behind the carrier's head end.",
               "pass": "I can see the shoulder belt in the rear guide.",
               "fail": "The shoulder belt is not in the rear guide.",
               "unseen": "I could not see the rear guide."},
        "es": {"say": "Pasá el cinturón de hombro por la guía de atrás, detrás de la cabecera de la silla.",
               "pass": "Veo el cinturón de hombro en la guía de atrás.",
               "fail": "El cinturón de hombro no está en la guía de atrás.",
               "unseen": "No pude ver la guía de atrás."}},
    "no_twist": {
        "prompts": ("belt", "guide"), "manual_step": 2,
        "en": {"say": "Pull the shoulder belt tight and keep the belt flat, with no twist.",
               "pass": "The lap belt looks flat across the carrier.",
               "fail": "The lap belt looks twisted across the carrier.",
               "unseen": "I could not see the lap belt well enough to check for a twist."},
        "es": {"say": "Tirá del cinturón de hombro hasta que quede tenso y mantenelo plano, sin giros.",
               "pass": "El cinturón de cadera se ve plano sobre la silla.",
               "fail": "El cinturón de cadera se ve girado sobre la silla.",
               "unseen": "No pude ver bien el cinturón de cadera para revisar si está girado."}},
    "level_line": {
        "prompts": ("level",), "manual_step": 3,
        "en": {"say": "Show me the level line on the side of the carrier, with the phone held level.",
               "pass": "The level line looks level.",
               "fail": "The level line is tilted about {angle} degrees. The manual says it must be level to the ground.",
               "unseen": "I could not see the level line."},
        "es": {"say": "Mostrame la línea de nivel al costado de la silla, con el teléfono derecho.",
               "pass": "La línea de nivel se ve nivelada.",
               "fail": "La línea de nivel está inclinada unos {angle} grados. El manual dice que tiene que quedar "
                       "nivelada con el piso.",
               "unseen": "No pude ver la línea de nivel."}},
    "handle": {
        "prompts": ("handle", "belt", "guide"), "manual_step": None,
        "en": {"say": "Put the handle upright, in position {position}, the car position.",
               "pass": "The handle is upright.",
               "fail": "The handle is not upright. Move it to position {position}.",
               "unseen": "I could not see the handle."},
        "es": {"say": "Poné la manija hacia arriba, en la posición {position}, la posición para el auto.",
               "pass": "La manija está hacia arriba.",
               "fail": "La manija no está hacia arriba. Movela a la posición {position}.",
               "unseen": "No pude ver la manija."}},
}
LINES = {
    "en": {"unsure": "My two checks disagree here, so I am not counting it as passed. Show me another view, or check it "
                     "by hand against the manual.",
           "not_checked": " I am listing it as not checked.",
           "fix": "Noted. Please fix this before driving, and ask me to check again.",
           "open": "I will keep this check open in the summary.",
           "both_guides": "near and far side guides", "one_guide": "{side} side guide", "side": "side",
           "near": "near", "far": "far", "a_few": "a few",
           "start": "Coaching the {seat} in the {car}, installed with the seat belt and no base. Put the carrier on a "
                    "rear seat, facing the back of the car. {rule} Is the carrier on a rear seat, facing the back? Say "
                    "yes or no.",
           "not_a_verdict": "This is not a verdict on the install.",
           "missing": "Not done yet"},
    "es": {"unsure": "Mis dos chequeos no coinciden acá, así que no lo cuento como bien. Mostrame otra vista, o revisalo "
                     "a mano con el manual.",
           "not_checked": " Lo dejo como no revisado.",
           "fix": "Anotado. Corregilo antes de manejar y pedime que lo revise de nuevo.",
           "open": "Dejo este chequeo abierto en el resumen.",
           "both_guides": "las guías laterales de los dos lados", "one_guide": "la guía lateral del lado {side}",
           "side": "de la puerta", "near": "de la puerta", "far": "de adentro", "a_few": "unos pocos",
           "start": "Te guío con la {seat} en el {car}, instalada con el cinturón del auto y sin base. Poné la silla en "
                    "un asiento de atrás, mirando hacia la parte de atrás del auto. {rule} ¿La silla está en un asiento "
                    "de atrás, mirando hacia atrás? Decí sí o no.",
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
           "harness_pinch": "no slack in the harness pinch test"},
    "es": {"lap_guides": "cinturón de cadera en las dos guías laterales", "shoulder_guide": "cinturón de hombro en la guía de atrás",
           "no_twist": "sin giros en el cinturón de cadera", "level_line": "línea de nivel nivelada",
           "handle": "manija hacia arriba", "car_position": "silla en un asiento de atrás mirando hacia atrás",
           "belt_path_movement": "menos de 2,5 centímetros de movimiento en el cinturón",
           "harness_pinch": "sin correa de sobra en la prueba del pellizco"},
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


def plan(cfg, seat, car, lang="en"):
    """The ordered steps for this seat and car, each said in lang."""
    lang = lang_of(lang)
    rule = " ".join(localized(r, "text", lang) for r in car["rules"] if r["id"] == "no_front_airbag")
    steps = [{"id": "car_position", "kind": "ask",
              "say": " ".join(LINES[lang]["start"].format(seat=seat["seat"], car=car["car"], rule=rule).split()),
              "pass_answer": "yes"}]
    position = seat.get("handle_car_position") or 1
    for check_id, step in CAMERA_STEPS.items():
        manual = seat["steps"][step["manual_step"]] if step["manual_step"] is not None and step["manual_step"] < len(seat["steps"]) else None
        steps.append({"id": check_id, "kind": "camera", "say": step[lang]["say"].format(position=position), "manual": manual})
    for hand in cfg["hand_checks"]:
        steps.append({"id": hand["id"], "kind": "ask", "say": localized(hand, "ask", lang),
                      "pass_answer": hand.get("pass_answer", "yes"), "source": hand.get("source")})
    return steps


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
    def __init__(self, cfg, bus, vision, source, seat, car, recheck=False, answer_timeout_s=None, clock=time.monotonic,
                 muse=None, lang="en"):
        self.cfg, self.bus, self.vision, self.source = cfg, bus, vision, source
        self.lang = lang_of(lang)
        self.lines = LINES[self.lang]
        self.muse = muse  # a MuseSeatCheck: Muse Spark Open's second opinion on the same frame
        self.seat, self.car = seat, car
        self.recheck, self.answer_timeout_s, self.clock = recheck, answer_timeout_s, clock
        self.steps = plan(cfg, seat, car, self.lang)
        self.results = {}
        self.answers, self.answer_ready = {}, threading.Condition()
        self.stop_flag = False
        self.asking = None  # the ask step waiting for the parent's yes or no

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

    def run_camera(self, step):
        spec = {**CAMERA_STEPS[step["id"]], **CAMERA_STEPS[step["id"]][self.lang]}
        position = self.seat.get("handle_car_position") or 1
        started_at = self.stream_now()
        _, start_seq, _ = self._latest(0) or (None, 0, 0.0)
        self.say(step["say"], step=step["id"])
        prompts_cfg = self.cfg["prompts"]
        prompts = [prompts_cfg[k] for k in spec["prompts"]]
        deadline = self.clock() + self.cfg.get("step_timeout_s", 8.0)
        seq, first, last_frame = start_seq, None, None
        while self.clock() < deadline and not self.stop_flag:
            got = self._latest(seq)
            if got is None:
                if getattr(self.source, "stopped", False):
                    break
                time.sleep(0.005)
                continue
            frame, seq, frame_s = got
            last_frame = frame
            found, seconds = self.vision.masks(frame, prompts)
            verdict = checks_mod.analyze(found, prompts_cfg, frame.shape[:2], self.cfg.get("checks"))[step["id"]]
            self.bus.publish("carseat_frame", step=step["id"], frame_s=round(frame_s, 3), sam_s=seconds,
                             result=verdict["result"])
            if verdict["result"] == "unseen":
                continue
            if first is None:
                verdict = self.second_opinion(step["id"], frame, verdict)
                first = verdict
                missed = self.missed(verdict.get("missed") or [])
                text = (spec[verdict["result"]] if verdict["result"] in spec else self.lines["unsure"]).format(missed=missed,
                                                      angle=round(abs(verdict.get("angle_deg", 0))), position=position)
                spoken_at = self.stream_now()
                self.say(text, step=step["id"], result=verdict["result"])
                self._record(step, verdict, started_at, frame_s, spoken_at)
            if verdict["result"] == "pass" or not self.recheck:
                return
            if first["result"] == "fail" and verdict["result"] == "pass":
                return
        if first is None:
            verdict = self.second_opinion(step["id"], last_frame, {"result": "unseen"}) if last_frame is not None else {"result": "unseen"}
            if verdict["result"] == "unseen":
                self.say(spec["unseen"] + self.lines["not_checked"], step=step["id"], result="unseen")
            else:
                text = spec["fail"].format(missed=self.missed([]), angle=self.lines["a_few"], position=position) \
                    if verdict["result"] == "fail" else self.lines["unsure"]
                self.say(text, step=step["id"], result=verdict["result"])
            self._record(step, verdict, started_at, None, self.stream_now())

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
                                    "frame_s": None if frame_s is None else round(frame_s, 3), "spoken_s": spoken_at}
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
