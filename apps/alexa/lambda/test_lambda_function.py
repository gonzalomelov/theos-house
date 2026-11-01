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
                if body.get("confirm"):
                    answer = {"reply": f"Listo, anoté ({body['confirm']}).", "written": [{"kind": "feeding", "id": 7}]}
                elif body.get("cancel"):
                    answer = {"reply": "Listo, no anoté nada."}
                elif "ml" in body["text"]:
                    answer = {"reply": "¿Anoto 90 ml de mamadera a las 7:50? Decí sí.", "confirm": {"id": "c-1"}}
                else:
                    answer = {"reply": f"answer to {body['text']}", "role": "guest"}
                data = json.dumps(answer).encode()
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


def chat(query, locale="en-US", attributes=None, request_id="amzn1.echo-api.request.1", intent="ChatIntent"):
    slots = {"query": {"value": query}} if intent == "ChatIntent" else {}
    return {"session": {"new": False, "attributes": attributes or {}},
            "request": {"type": "IntentRequest", "requestId": request_id, "locale": locale,
                        "intent": {"name": intent, "slots": slots}}}


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


    def test_a_write_asks_first_and_si_confirms_it(self):
        self.bridge = FakeBridge()
        asked = fn.lambda_handler(chat("le di 90 ml de mamadera", "es-US", request_id="r-1"), None)
        self.assertEqual(said(asked), "¿Anoto 90 ml de mamadera a las 7:50? Decí sí.")
        self.assertEqual(asked["sessionAttributes"], {"pending_write": {"id": "c-1"}})
        self.assertEqual(asked["response"]["reprompt"]["outputSpeech"]["text"], "Decí sí para anotarlo, o no.")
        self.assertEqual(self.bridge.seen[0]["body"]["lang"], "es")
        done = fn.lambda_handler(chat("sí", "es-US", asked["sessionAttributes"], request_id="r-2"), None)
        self.assertEqual(said(done), "Listo, anoté (c-1).")
        self.assertEqual(self.bridge.seen[1]["body"], {"text": "", "source": "echo", "request_id": "r-2", "lang": "es",
                                                       "confirm": "c-1"})
        self.assertEqual(done["sessionAttributes"], {})

    def test_the_yes_intent_confirms_too(self):
        self.bridge = FakeBridge()
        pending = {"pending_write": {"id": "c-1"}}
        done = fn.lambda_handler(chat(None, "en-US", pending, intent="AMAZON.YesIntent"), None)
        self.assertEqual(self.bridge.seen[0]["body"]["confirm"], "c-1")
        self.assertIn("anoté", said(done))

    def test_no_cancels_and_nothing_is_confirmed(self):
        self.bridge = FakeBridge()
        out = fn.lambda_handler(chat("no", "es-US", {"pending_write": {"id": "c-1"}}), None)
        self.assertEqual(said(out), "Listo, no anoté nada.")
        self.assertEqual(self.bridge.seen[0]["body"]["cancel"], "c-1")
        self.assertNotIn("confirm", self.bridge.seen[0]["body"])

    def test_something_else_while_a_write_waits_is_a_new_utterance(self):
        self.bridge = FakeBridge()
        out = fn.lambda_handler(chat("cuánto durmió", "es-US", {"pending_write": {"id": "c-1"}}), None)
        self.assertEqual(said(out), "answer to cuánto durmió")
        self.assertNotIn("confirm", self.bridge.seen[0]["body"])
        self.assertEqual(out["sessionAttributes"], {})

    def test_a_slow_confirm_is_fetched_again_with_the_same_id(self):
        self.bridge = FakeBridge(delay=1.0)
        out = fn.lambda_handler(chat("sí", "es-US", {"pending_write": {"id": "c-1"}}, request_id="r-5"), None)
        self.assertIn("todavía lo está pensando", said(out))
        self.assertEqual(out["sessionAttributes"]["pending"], {"id": "r-5", "confirm": "c-1"})
        again = fn.lambda_handler(chat("de nuevo", "es-US", out["sessionAttributes"], request_id="r-6"), None)
        self.assertEqual(said(again), "Listo, anoté (c-1).")
        self.assertEqual([s["body"]["request_id"] for s in self.bridge.seen], ["r-5", "r-5"])

    def test_stop_with_a_write_waiting_cancels_it(self):
        self.bridge = FakeBridge()
        out = fn.lambda_handler(chat(None, "es-US", {"pending_write": {"id": "c-1"}}, intent="AMAZON.StopIntent"), None)
        self.assertTrue(out["response"]["shouldEndSession"])
        self.assertEqual(self.bridge.seen[0]["body"]["cancel"], "c-1")


if __name__ == "__main__":
    unittest.main()
