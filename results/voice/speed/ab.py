import json, subprocess, sys
replies = json.load(open(sys.argv[1])); one = open(sys.argv[2]).read()
rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 1
for k in range(rounds):
    for r in replies:
        r = dict(r, text=r["text"] + " " * k)  # a new text each round, so the cache never answers
        for name, container in (("before", "vbench-old"), ("after", "pa-voice-families")):
            out = subprocess.run(["docker", "exec", "-i", container, "python", "-", json.dumps(r)], input=one,
                                 capture_output=True, text=True, check=True).stdout.strip()
            print(json.dumps({"image": name, "round": k, **json.loads(out)}), flush=True)
