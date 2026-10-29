import sys
sys.argv=["x","en1","ear","1","/dev/null"]
exec(open("probe.py").read().split("clips = sys.argv")[0])
def ia(wav): return {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}
def txt(t): return {"type":"text","text":t}
def call(name, content, system=None, **extra):
    msgs = ([{"role":"system","content":system}] if system else []) + [{"role":"user","content":content}]
    body = {"model": E.MODEL, "max_tokens": 1500, "reasoning_effort": "low", "messages": msgs, **extra}
    r = post_json(URL, H, body, 90); u = r["usage"]; m = r["choices"][0]["message"]
    row = {"variant": name, "prompt_tokens": u["prompt_tokens"], "answer": m.get("content"), "reasoning": (m.get("reasoning_content") or "")[:300]}
    print(json.dumps(row, ensure_ascii=False), flush=True); return row
en1 = open("en1.wav","rb").read(); b5 = open("beep5.wav","rb").read()
G = "Write down exactly the words spoken in the attached audio clip."
rows = [call("generic_text_only", [txt(G)]),
        call("ear_audio_first_again", [ia(en1), txt(E.PROMPT)]),
        call("ear+system_again", [txt(E.PROMPT), ia(en1)], system="You listen to the attached audio clip. If no audio reaches you, set heard_sound false."),
        call("plain_transcribe", [txt("Transcribe this audio."), ia(en1)]),
        call("beep_affirm", [txt("This is a short sound recording of a test tone that beeps several times. Listen and count the beeps. Reply with the number only."), ia(b5)]),
        call("beep_describe", [txt("This is a short sound recording. Describe what you hear in one sentence."), ia(b5)])]
json.dump(rows, open("ablate2.json","w"), ensure_ascii=False, indent=1)
