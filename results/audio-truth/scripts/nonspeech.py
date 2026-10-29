import sys
sys.argv=["x","en1","ear","1","/dev/null"]
exec(open("probe.py").read().split("clips = sys.argv")[0])
from pathlib import Path
from parenting_agent import hearing
from parenting_agent.muse_senses import wav_bytes
MEDIA = Path.home() / "Engineering/gonza/meta-hackathon-2026-synthetic"
def ia(wav): return {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}
Q = ("This is 5 seconds of sound from the baby monitor in the nursery. Which one is the main sound: baby crying, "
     "dog barking, doorbell, coughing, water splashing, speech, or other? Reply with the label only.")
rows = []
for cid in ["cry-01", "cry-02", "dog-01", "doorbell-01", "cough-01", "splash-01"]:
    s = hearing.from_file(MEDIA / f"audio/{cid}.wav", seconds=5.0)
    wav = wav_bytes(s)
    for shape in ["ear_like", "ear_like_16k_raw"][:1]:
        body = {"model": E.MODEL, "max_tokens": 1500, "reasoning_effort": "low",
                "messages": [{"role": "user", "content": [{"type": "text", "text": Q}, ia(wav)]}]}
        r = post_json(URL, H, body, 90); m = r["choices"][0]["message"]
        row = {"clip": cid, "prompt_tokens": r["usage"]["prompt_tokens"], "answer": m.get("content"), "reasoning": (m.get("reasoning_content") or "")[:220]}
        print(json.dumps(row, ensure_ascii=False), flush=True); rows.append(row)
json.dump(rows, open("nonspeech.json","w"), ensure_ascii=False, indent=1)
