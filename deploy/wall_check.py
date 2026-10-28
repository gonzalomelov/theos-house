"""Proves the wall from inside the running agent container. Piped in by agent.sh, never part of the image:

    docker exec -i parenting-agent python - <host addresses...> < deploy/wall_check.py

It must reach Baby Buddy and Home Assistant through the relay, and the brain and Telegram through the egress
proxy. It must reach nothing else: not the brain directly, not other websites, not the host, not the LAN,
not other containers. "Reachable" means an HTTP answer of any status, or an open TCP connection.
Exit 0 when every check matches, 1 otherwise. Prints no secret: requests carry no token.
"""
import socket
import sys
import urllib.error
import urllib.request

PROXY = urllib.request.ProxyHandler()  # reads HTTPS_PROXY, HTTP_PROXY and NO_PROXY from the environment
DIRECT = urllib.request.ProxyHandler({})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer from the target itself. Following it would test another host."""

    def redirect_request(self, *args, **kwargs):
        return None


def http(url, handler):
    opener = urllib.request.build_opener(handler, NoRedirect)
    try:
        with opener.open(url, timeout=8) as response:
            return True, f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        if (error.headers.get("Server") or "").startswith("tinyproxy"):
            return False, f"refused by the egress proxy, HTTP {error.code}"
        return True, f"HTTP {error.code}"
    except Exception as error:  # every failure to connect is the expected answer for a blocked target
        return False, type(error).__name__ + ": " + str(getattr(error, "reason", error))[:60]


def tcp(host, port):
    try:
        with socket.create_connection((host, int(port)), timeout=4):
            return True, "connected"
    except Exception as error:
        return False, type(error).__name__ + ": " + str(error)[:60]


def main(hosts):
    must_work = [
        ("Baby Buddy through the relay", lambda: http("http://relay:8790/api/", DIRECT)),
        ("Home Assistant through the relay", lambda: http("http://relay:8123/api/", DIRECT)),
        ("Anthropic through the egress proxy", lambda: http("https://api.anthropic.com/v1/models", PROXY)),
        ("Baseten through the egress proxy", lambda: http("https://inference.baseten.co/v1/models", PROXY)),
        ("Telegram through the egress proxy", lambda: http("https://api.telegram.org/bot0/getMe", PROXY)),
    ]
    must_fail = [
        ("Anthropic, direct", lambda: http("https://api.anthropic.com/v1/models", DIRECT)),
        ("public website, direct", lambda: http("https://example.com/", DIRECT)),
        ("public website, through the egress proxy", lambda: http("https://example.com/", PROXY)),
        ("plain HTTP website, through the egress proxy", lambda: http("http://example.com/", PROXY)),
        ("Baby Buddy by name, direct", lambda: tcp("babybuddy", 8000)),
        ("Home Assistant by name, direct", lambda: tcp("homeassistant", 8123)),
        ("Home Assistant MCP server by name, direct", lambda: tcp("home-assistant-mcp-server", 8086)),
        ("Baby Buddy by name, through the egress proxy", lambda: http("http://babybuddy:8000/", PROXY)),
        ("relay on another port", lambda: tcp("relay", 80)),
        ("public DNS server, direct", lambda: tcp("1.1.1.1", 53)),
    ]
    for host in hosts:
        for port in (22, 80, 443, 8086, 8123, 8790):
            must_fail.append((f"{host}:{port}, direct", lambda h=host, p=port: tcp(h, p)))
        must_fail.append((f"{host}:8123, through the egress proxy", lambda h=host: http(f"http://{h}:8123/", PROXY)))
        must_fail.append((f"{host}:443, through the egress proxy", lambda h=host: http(f"https://{h}/", PROXY)))
    failed = 0
    for want, checks in ((True, must_work), (False, must_fail)):
        print("-- must work" if want else "-- must fail")
        for label, check in checks:
            got, detail = check()
            mark = "PASS" if got == want else "WRONG"
            failed += mark == "WRONG"
            print(f"{mark:5} {label:52} {'reached' if got else 'blocked'} ({detail})")
    print("wall holds" if not failed else f"WALL BROKEN: {failed} wrong")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
