"""Offline: a fake bridge on 127.0.0.1 stands in for Cloudflare, the door and the agent.

    python3 -m unittest discover -s lambda
"""
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.update({"PA_BEARER_TOKEN": "b" * 24, "CF_ACCESS_CLIENT_ID": "id", "CF_ACCESS_CLIENT_SECRET": "secret",
                   "PA_ASK_TIMEOUT_S": "0.5"})
import lambda_function as fn  # noqa: E402


class FakeBridge:
    def __init__(self, delay=0.0):
        self.seen, self.delay = [], delay
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.seen.append({"body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
                time.sleep(fake.delay if len(fake.seen) == 1 else 0)
                data = json.dumps({"reply": f"answer to {body['text']}", "role": "guest"}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        fn.ASK_URL = f"http://127.0.0.1:{self.server.server_address[1]}/ask"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def chat(query, locale="en-US", attributes=None, request_id="amzn1.echo-api.request.1"):
    return {"session": {"new": False, "attributes": attributes or {}},
            "request": {"type": "IntentRequest", "requestId": request_id, "locale": locale,
                        "intent": {"name": "ChatIntent", "slots": {"query": {"value": query}}}}}


def said(response):
    return response["response"]["outputSpeech"]["text"]


class LambdaTest(unittest.TestCase):
    def tearDown(self):
        self.bridge.close()

    def test_the_words_go_to_the_bridge_as_echo_with_both_tokens(self):
        self.bridge = FakeBridge()
        out = fn.lambda_handler(chat("cuándo comió theo", "es-US"), None)
        self.assertEqual(said(out), "answer to cuándo comió theo")
        seen = self.bridge.seen[0]
        self.assertEqual(seen["body"]["source"], "echo")
        self.assertNotIn("person", seen["body"])
        self.assertEqual(seen["headers"]["authorization"], "Bearer " + "b" * 24)
        self.assertEqual(seen["headers"]["cf-access-client-id"], "id")
        self.assertEqual(seen["headers"]["user-agent"], "alexa-muse-baby/1.0")
        self.assertFalse(out["response"]["shouldEndSession"])

    def test_a_slow_agent_gets_a_holding_line_and_again_fetches_the_same_question(self):
        self.bridge = FakeBridge(delay=1.0)
        out = fn.lambda_handler(chat("when did theo last eat", request_id="r-1"), None)
        self.assertIn("still thinking", said(out))
        self.assertEqual(out["sessionAttributes"]["pending"], {"id": "r-1", "text": "when did theo last eat"})
        again = fn.lambda_handler(chat("again", attributes=out["sessionAttributes"], request_id="r-2"), None)
        self.assertEqual(said(again), "answer to when did theo last eat")
        self.assertEqual([s["body"]["request_id"] for s in self.bridge.seen], ["r-1", "r-1"])
        self.assertEqual(again["sessionAttributes"], {})

    def test_holding_line_in_spanish(self):
        self.bridge = FakeBridge(delay=1.0)
        out = fn.lambda_handler(chat("cuándo comió", "es-US"), None)
        self.assertIn("todavía lo está pensando", said(out))

    def test_a_new_question_while_pending_is_asked_as_new(self):
        self.bridge = FakeBridge()
        pending = {"pending": {"id": "r-1", "text": "old"}}
        out = fn.lambda_handler(chat("how long did he sleep", attributes=pending, request_id="r-3"), None)
        self.assertEqual(said(out), "answer to how long did he sleep")
        self.assertEqual(self.bridge.seen[0]["body"]["request_id"], "r-3")

    def test_stop_ends_the_session(self):
        self.bridge = FakeBridge()
        event = chat("x")
        event["request"]["intent"] = {"name": "AMAZON.StopIntent"}
        self.assertTrue(fn.lambda_handler(event, None)["response"]["shouldEndSession"])
        self.assertEqual(self.bridge.seen, [])


if __name__ == "__main__":
    unittest.main()
