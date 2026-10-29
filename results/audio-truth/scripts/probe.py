import base64, json, os, sys, time
sys.path.insert(0, os.path.expanduser("~/Engineering/gonza/parenting-agent-worktrees/audio-truth"))
from parenting_agent.voice import ear as E
from parenting_agent.muse_senses import MuseSenses, wav_data_url
from parenting_agent.agent.brain import post_json, BrainError
for line in open(os.path.expanduser("~/.parenting-agent.env")):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
KEY = os.environ["BASETEN_API_KEY"]; URL = "https://inference.baseten.co/v1/chat/completions"
H = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
BEEP_Q = "How many beeps are in the attached audio clip? Reply with the number only."
def ear_body(wav, text):
    audio = {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}
    return {"model": E.MODEL, "max_tokens": 1500, "reasoning_effort": "low",
            "messages": [{"role": "user", "content": [{"type": "text", "text": text}, audio]}]}
SPEECH_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["heard_sound", "words"],
                 "properties": {"heard_sound": {"type": "boolean"}, "words": {"type": "string"}}}
BEEP_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["heard_sound", "beeps"],
               "properties": {"heard_sound": {"type": "boolean"}, "beeps": {"type": "integer"}}}
ms = MuseSenses()
def cry_body(wav, kind):
    if kind == "beep":
        return ms.body("You listen to the attached audio clip. If no audio reaches you, set heard_sound false.",
                       "How many beeps are in the attached audio clip?", BEEP_SCHEMA, audio_url=wav_data_url(wav))
    return ms.body("You listen to the attached audio clip. If no audio reaches you, set heard_sound false.",
                   "Write down exactly the words spoken in the attached audio clip.", SPEECH_SCHEMA, audio_url=wav_data_url(wav))
clips = sys.argv[1].split(","); shapes = sys.argv[2].split(","); reps = int(sys.argv[3])
rows = []
for clip in clips:
    wav = open(f"{clip}.wav", "rb").read(); kind = "beep" if clip.startswith("beep") else "speech"
    for shape in shapes:
        for rep in range(reps):
            if shape == "ear": body = ear_body(wav, BEEP_Q if kind == "beep" else E.PROMPT)
            elif shape == "cry": body = cry_body(wav, kind)
            elif shape == "cry_ia":
                body = cry_body(wav, kind)
                body["messages"][1]["content"][0] = {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}
            elif shape == "ear_noaudio":
                body = ear_body(wav, E.PROMPT); body["messages"][0]["content"] = body["messages"][0]["content"][:1]
            t = time.monotonic()
            try: r = post_json(URL, H, body, 90); err = None
            except BrainError as e: r, err = {}, str(e)[:200]
            u = r.get("usage") or {}
            ans = ((r.get("choices") or [{}])[0].get("message") or {}).get("content") if r else None
            row = {"clip": clip, "shape": shape, "rep": rep + 1, "seconds": round(time.monotonic() - t, 2),
                   "prompt_tokens": u.get("prompt_tokens"), "completion_tokens": u.get("completion_tokens"),
                   "prompt_tokens_details": u.get("prompt_tokens_details"), "answer": ans, "finish": ((r.get("choices") or [{}])[0].get("finish_reason")) if r else None, "reasoning_head": ((((r.get("choices") or [{}])[0].get("message") or {}).get("reasoning_content") or "")[:160]) if r else None, "error": err}
            rows.append(row); print(json.dumps(row, ensure_ascii=False), flush=True)
json.dump(rows, open(sys.argv[4], "w"), ensure_ascii=False, indent=1)
