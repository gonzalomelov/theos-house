import sys, copy
sys.argv=["x","en1","ear","1","/dev/null"]
exec(open("probe.py").read().split("clips = sys.argv")[0])
def ia(wav): return {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}
def call(name, body):
    r = post_json(URL, H, body, 90); u = r["usage"]; m = r["choices"][0]["message"]
    row = {"variant": name, "prompt_tokens": u["prompt_tokens"], "audio_tokens": u["prompt_tokens_details"].get("audio_tokens"), "answer": m.get("content"), "finish": r["choices"][0]["finish_reason"]}
    print(json.dumps(row, ensure_ascii=False), flush=True); return row
rows = []
en1 = open("en1.wav","rb").read()
def txt(t): return {"type":"text","text":t}
# token controls: same text, varying audio
for clip in ["beep5","silence3","en1","en1pad","long"]:
    w = open(clip+".wav","rb").read()
    rows.append(call(f"ear_prompt+{clip}", ear_body(w, E.PROMPT)))
rows.append(call("ear_prompt_noaudio", {**ear_body(en1,E.PROMPT), "messages":[{"role":"user","content":[txt(E.PROMPT)]}]}))
# ablation on en1: what breaks the cry shape
b = ear_body(en1, E.PROMPT); b["messages"][0]["content"] = [ia(en1), txt(E.PROMPT)]
rows.append(call("ear_audio_first", b))
b = ear_body(en1, E.PROMPT); b["messages"].insert(0, {"role":"system","content":"You listen to the attached audio clip. If no audio reaches you, set heard_sound false."})
rows.append(call("ear+system", b))
b = ear_body(en1, "Write down exactly the words spoken in the attached audio clip."); b["response_format"] = {"type":"json_schema","json_schema":{"name":"answer","strict":True,"schema":SPEECH_SCHEMA}}
rows.append(call("ear+json_schema", b))
b = ear_body(en1, "Write down exactly the words spoken in the attached audio clip.")
rows.append(call("ear_cry_text_no_schema", b))
b = cry_body(en1, "speech"); b["messages"] = b["messages"][1:]
rows.append(call("cry_no_system", b))
b = cry_body(en1, "speech"); b.pop("response_format")
rows.append(call("cry_no_schema", b))
json.dump(rows, open("ablate.json","w"), ensure_ascii=False, indent=1)
