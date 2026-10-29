import sys
sys.argv=["x","en1","ear","1","/dev/null"]
exec(open("probe.py").read().split("clips = sys.argv")[0])
def ia(wav): return {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}}
def au(wav): return {"type": "audio_url", "audio_url": {"url": wav_data_url(wav)}}
def txt(t): return {"type":"text","text":t}
en1 = open("en1.wav","rb").read(); es1 = open("es1.wav","rb").read()
SCH = {"type":"json_schema","json_schema":{"name":"answer","strict":True,"schema":{"type":"object","additionalProperties":False,"required":["words"],"properties":{"words":{"type":"string"}}}}}
T = "This is a voice note from a parent. Write down exactly what the parent said, with numbers as digits."
TJ = T + " Answer as JSON with the field words."
rows=[]
def call(name, content, **extra):
    body = {"model": E.MODEL, "max_tokens": 1500, "reasoning_effort": "low", "messages":[{"role":"user","content":content}], **extra}
    r = post_json(URL, H, body, 90); m = r["choices"][0]["message"]
    row={"variant":name,"prompt_tokens":r["usage"]["prompt_tokens"],"answer":m.get("content")}
    print(json.dumps(row,ensure_ascii=False),flush=True); rows.append(row)
for rep in range(2):
    call("ear_prompt+audio_url", [txt(E.PROMPT), au(en1)])
    call("affirm_text+input_audio", [txt(T), ia(es1)])
    call("affirm_json_schema+input_audio", [txt(TJ), ia(es1)], response_format=SCH)
json.dump(rows, open("shape3.json","w"), ensure_ascii=False, indent=1)
