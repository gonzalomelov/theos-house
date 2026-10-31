"""Home Assistant's half of the Echo path: one question to the family agent's voice bridge, the answer on stdout as JSON.

Runs inside the Home Assistant container as shell_command.parenting_agent_ask (python3, standard library only):

    python3 /config/shell/parenting_agent_ask.py <source> <person> <text>     each argument base64 encoded

The arguments come base64 encoded from the shell_command template, so nothing a speaker says is ever read as shell
words. The bridge address and token are read from /config/secrets.yaml (parenting_agent_voice_url,
parenting_agent_voice_token) and never printed. The answer is {"reply": ..., "role": ..., "status": ...}.
"""
import base64
import json
import sys
import urllib.error
import urllib.request

SECRETS = "/config/secrets.yaml"
NO_ANSWER = "El agente del bebé no respondió."
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def secret(name, path=None):
    with open(path or SECRETS, encoding="utf-8") as lines:
        for line in lines:
            key, _, value = line.partition(":")
            if key.strip() == name:
                return value.strip().strip("\"'")
    raise KeyError(name)


def ask(source, person, text, url, token, timeout=50):
    body = json.dumps({"text": text, "source": source, "person": person}).encode()
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with DIRECT.open(request, timeout=timeout) as response:
            answer, status = json.loads(response.read() or b"{}"), response.status
    except urllib.error.HTTPError as error:
        try:
            answer = json.loads(error.read() or b"{}")
        except ValueError:
            answer = {}
        status = error.code
    except (OSError, ValueError) as error:
        return {"reply": NO_ANSWER, "role": None, "status": None, "error": type(error).__name__}
    reply = answer.get("reply") if status in (200, 504) else None
    return {"reply": reply or NO_ANSWER, "role": answer.get("role"), "status": status}


def main(argv):
    source, person, text = (base64.b64decode(arg).decode("utf-8") for arg in argv[1:4])
    result = ask(source, person, text, secret("parenting_agent_voice_url"), secret("parenting_agent_voice_token"))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
