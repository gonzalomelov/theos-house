"""Alexa custom skill "baby agent" / "agente del bebé": the Echo asks the family's baby agent.

Echo -> Alexa cloud -> this Lambda -> Cloudflare Access (service token) -> the door on the Vostro -> the relay ->
the agent's voice bridge /ask. The agent answers with Muse Spark Open. This Lambda calls no model itself: no Claude,
no other vendor.

Alexa gives a skill 8 seconds. When the agent is slower, the skill says a holding line and keeps the question's id in
the session. "Again" (or "de nuevo", "sí") fetches the same answer from the bridge, which never runs a question twice.
"""

import json
import os
import socket
import traceback
import urllib.error
import urllib.request

ASK_URL = os.environ.get("PA_ASK_URL", "https://baby-voice.home.example/ask")
PERSON = os.environ.get("PA_PERSON", "")  # empty: the agent treats the speaker as a guest, read only
ASK_TIMEOUT_S = float(os.environ.get("PA_ASK_TIMEOUT_S", "6"))

AGAIN = {
    "again", "ask again", "try again", "yes", "yeah", "tell me", "and", "so",
    "de nuevo", "otra vez", "sí", "si", "dale", "decime", "y", "entonces",
}

STRINGS = {
    "en": {
        "welcome": "Baby agent here. What do you want to know?",
        "reprompt": "Anything else?",
        "goodbye": "Bye.",
        "help": "Ask me about the baby, like when Theo last ate. Say stop when you're done.",
        "retry": "I didn't catch that. Say it again?",
        "holding": "The baby agent is still thinking. Say again in a moment and I'll tell you.",
        "holding_reprompt": "Say again to hear the answer.",
        "error": "I couldn't reach the baby agent just now. Try again later.",
    },
    "es": {
        "welcome": "Acá el agente del bebé. ¿Qué querés saber?",
        "reprompt": "¿Algo más?",
        "goodbye": "Chau.",
        "help": "Preguntame por el bebé, por ejemplo cuándo comió Theo. Decí basta cuando termines.",
        "retry": "No te escuché bien. ¿Lo repetís?",
        "holding": "El agente del bebé todavía lo está pensando. Decí de nuevo en un momento y te cuento.",
        "holding_reprompt": "Decí de nuevo para escuchar la respuesta.",
        "error": "Ahora no pude hablar con el agente del bebé. Probá más tarde.",
    },
}


def strings_for(request):
    lang = (request.get("locale") or "en").split("-")[0]
    return STRINGS.get(lang, STRINGS["en"])


def ask_agent(text, request_id):
    """POST the words to the bridge. Returns the reply text. Raises TimeoutError when the agent is slower than us."""
    body = {"text": text, "source": "echo", "request_id": request_id}
    if PERSON:
        body["person"] = PERSON
    req = urllib.request.Request(
        ASK_URL,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            # Cloudflare refuses Python-urllib's own User-Agent.
            "User-Agent": "alexa-muse-baby/1.0",
            "Authorization": "Bearer " + os.environ["PA_BEARER_TOKEN"],
            "CF-Access-Client-Id": os.environ["CF_ACCESS_CLIENT_ID"],
            "CF-Access-Client-Secret": os.environ["CF_ACCESS_CLIENT_SECRET"],
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=ASK_TIMEOUT_S) as resp:
            return json.loads(resp.read())["reply"]
    except socket.timeout as err:  # the reply did not come in time (an alias of TimeoutError on 3.10 and later)
        raise TimeoutError(str(err)) from err
    except urllib.error.HTTPError as err:
        if err.code == 504:  # the bridge's own timeout: still answering
            raise TimeoutError("bridge 504") from err
        raise
    except urllib.error.URLError as err:
        if isinstance(err.reason, (TimeoutError, socket.timeout)) or "timed out" in str(err.reason):
            raise TimeoutError(str(err.reason)) from err
        raise


def speech_response(text, session_attributes=None, end_session=False, reprompt="Anything else?"):
    response = {
        "version": "1.0",
        "sessionAttributes": session_attributes or {},
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session,
        },
    }
    if not end_session:
        response["response"]["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    return response


def answer(text, request_id, s):
    """Speaks the agent's reply, or the holding line with the question kept for the next turn."""
    try:
        reply = ask_agent(text, request_id)
    except TimeoutError:
        print(json.dumps({"holding": request_id}))
        return speech_response(s["holding"], {"pending": {"id": request_id, "text": text}},
                               reprompt=s["holding_reprompt"])
    except urllib.error.HTTPError as err:
        print("bridge error:", err.code)
        return speech_response(s["error"], reprompt=s["reprompt"])
    except Exception:
        traceback.print_exc()
        return speech_response(s["error"], reprompt=s["reprompt"])
    print(json.dumps({"answer": reply}))
    return speech_response(reply, reprompt=s["reprompt"])


def lambda_handler(event, context):
    request = event.get("request", {})
    request_type = request.get("type")
    intent = request.get("intent", {}) or {}
    query = ((intent.get("slots", {}) or {}).get("query", {}) or {}).get("value")
    attributes = event.get("session", {}).get("attributes", {}) or {}
    print(json.dumps({
        "event": request_type,
        "intent": intent.get("name"),
        "query": query,
        "locale": request.get("locale"),
        "new_session": event.get("session", {}).get("new"),
    }))
    s = strings_for(request)

    if request_type == "LaunchRequest":
        return speech_response(s["welcome"], reprompt=s["reprompt"])

    if request_type == "SessionEndedRequest":
        return {"version": "1.0", "response": {}}

    if request_type == "IntentRequest":
        name = intent.get("name")
        if name in ("AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NavigateHomeIntent"):
            return speech_response(s["goodbye"], end_session=True)
        if name == "AMAZON.HelpIntent":
            return speech_response(s["help"], attributes, reprompt=s["reprompt"])
        if name in ("ChatIntent", "AMAZON.FallbackIntent"):
            pending = attributes.get("pending")
            said = (query or "").strip().lower().rstrip("?.!")
            if pending and (not said or said in AGAIN):
                return answer(pending["text"], pending["id"], s)
            if not query:
                return speech_response(s["retry"], attributes, reprompt=s["reprompt"])
            return answer(query, request.get("requestId") or "", s)

    return speech_response(s["retry"], reprompt=s["reprompt"])
