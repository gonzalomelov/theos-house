import json, sys, time, urllib.request
r = json.loads(sys.argv[1])
body = json.dumps({"text": r["text"], "lang": r["lang"]}).encode()
req = urllib.request.Request("http://127.0.0.1:8800/speak", data=body, headers={"Content-Type": "application/json"})
t = time.monotonic()
with urllib.request.urlopen(req, timeout=300) as resp:
    ogg = resp.read(); model = json.loads(resp.headers.get("X-Timings"))
s = time.monotonic() - t
print(json.dumps({"id": r["id"], "seconds": round(s, 2), "model": model, "rest": round(s - sum(model), 2), "bytes": len(ogg),
                  "load1": float(open("/proc/loadavg").read().split()[0])}))
