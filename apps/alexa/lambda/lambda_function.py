"""Alexa custom skill "baby agent" / "agente del bebé": the Echo asks the family's baby agent.

Echo -> Alexa cloud -> this Lambda -> Cloudflare Access (service token) -> the door on the Vostro -> the relay ->
the agent's voice bridge /ask. The agent answers with Muse Spark Open. This Lambda calls no model itself: no Claude,
no other vendor.

Alexa gives a skill 8 seconds. When the agent is slower, the skill says a holding line and keeps the question's id in
the session. "Again" (or "de nuevo", "sí") fetches the same answer from the bridge, which never runs a question twice.

Write mode (the bridge's "echo_log" role): the Echo cannot tell who speaks, so a write is never made on the turn it is
said. The bridge answers with one question ("¿Anoto 90 ml de mamadera a las 7:50? Decí sí") and a confirm id, which
the skill keeps in the session. Only the next "sí" or "yes" sends {"confirm": id} and the bridge writes it. "No"
cancels it, anything else is a new utterance and the old write is dropped.
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

YES = {"yes", "yeah", "yep", "sure", "ok", "okay", "yes please", "do it", "go ahead",
       "sí", "si", "dale", "ok dale", "sí dale", "si dale", "claro", "sí por favor", "si por favor", "anotalo", "anótalo"}
NO = {"no", "nope", "no thanks", "cancel", "don't", "no gracias", "cancelá", "cancela", "no lo anotes", "dejá", "deja"}

STRINGS = {
    "en": {
        "welcome": "Baby agent here. What do you want to know or log?",
        "reprompt": "Anything else?",
        "goodbye": "Bye.",
        "help": "Ask me about the baby, like when Theo last ate, or tell me a feed, a diaper or a sleep to log. I always ask before I log. Say stop when you're done.",
        "retry": "I didn't catch that. Say it again?",
        "holding": "The baby agent is still thinking. Say again in a moment and I'll tell you.",
        "holding_reprompt": "Say again to hear the answer.",
        "error": "I couldn't reach the baby agent just now. Try again later.",
        "confirm_reprompt": "Say yes to log it, or no.",
    },
    "es": {
        "welcome": "Acá el agente del bebé. ¿Qué querés saber o anotar?",
        "reprompt": "¿Algo más?",
        "goodbye": "Chau.",
        "help": "Preguntame por el bebé, por ejemplo cuándo comió Theo, o contame una toma, un pañal o un sueño para anotar. Siempre te pregunto antes de anotar. Decí basta cuando termines.",
        "retry": "No te escuché bien. ¿Lo repetís?",
        "holding": "El agente del bebé todavía lo está pensando. Decí de nuevo en un momento y te cuento.",
        "holding_reprompt": "Decí de nuevo para escuchar la respuesta.",
        "error": "Ahora no pude hablar con el agente del bebé. Probá más tarde.",
        "confirm_reprompt": "Decí sí para anotarlo, o no.",
    },
}


def lang_of(request):
    lang = (request.get("locale") or "en").split("-")[0]
    return lang if lang in STRINGS else "en"


def strings_for(request):
    return STRINGS[lang_of(request)]


def ask_agent(text, request_id, lang="en", confirm=None, cancel=None):
    """POST the words, or a confirm or cancel of a write, to the bridge. Returns the bridge's JSON answer. Raises
    TimeoutError when the agent is slower than us."""
    body = {"text": text, "source": "echo", "request_id": request_id, "lang": lang}
    if confirm:
        body["confirm"] = confirm
    if cancel:
        body["cancel"] = cancel
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
            return json.loads(resp.read())
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


def answer(ask, s, lang):
    """Speaks the agent's reply, or the holding line with the request kept for the next turn. ask is
    {"id", "text"} and, for a write, "confirm" or "cancel"."""
    try:
        result = ask_agent(ask.get("text", ""), ask["id"], lang, ask.get("confirm"), ask.get("cancel"))
    except TimeoutError:
        print(json.dumps({"holding": ask["id"]}))
        return speech_response(s["holding"], {"pending": ask}, reprompt=s["holding_reprompt"])
    except urllib.error.HTTPError as err:
        print("bridge error:", err.code)
        return speech_response(s["error"], reprompt=s["reprompt"])
    except Exception:
        traceback.print_exc()
        return speech_response(s["error"], reprompt=s["reprompt"])
    reply = result["reply"]
    confirm = (result.get("confirm") or {}).get("id")
    print(json.dumps({"answer": reply, "asks_yes": bool(confirm), "written": result.get("written")}))
    if confirm:
        return speech_response(reply, {"pending_write": {"id": confirm}}, reprompt=s["confirm_reprompt"])
    return speech_response(reply, reprompt=s["reprompt"])


def words(said):
    return (said or "").strip().lower().strip("¿?¡!.,")


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
            if attributes.get("pending_write"):
                try:  # the write waiting for a yes is dropped on the bridge too, best effort
                    ask_agent("", request.get("requestId") or "", lang_of(request), cancel=attributes["pending_write"]["id"])
                except Exception:
                    traceback.print_exc()
            return speech_response(s["goodbye"], end_session=True)
        if name == "AMAZON.HelpIntent":
            return speech_response(s["help"], attributes, reprompt=s["reprompt"])
        request_id = request.get("requestId") or ""
        lang = lang_of(request)
        pending_write = attributes.get("pending_write")
        said = words(query)
        if pending_write and (name == "AMAZON.YesIntent" or said in YES):
            return answer({"id": request_id, "confirm": pending_write["id"]}, s, lang)
        if pending_write and (name == "AMAZON.NoIntent" or said in NO):
            return answer({"id": request_id, "cancel": pending_write["id"]}, s, lang)
        if name in ("ChatIntent", "AMAZON.FallbackIntent", "AMAZON.YesIntent", "AMAZON.NoIntent"):
            pending = attributes.get("pending")
            if pending and (not said or said in AGAIN or name == "AMAZON.YesIntent"):
                return answer(pending, s, lang)
            if not query:
                return speech_response(s["retry"], attributes, reprompt=s["reprompt"])
            return answer({"id": request_id, "text": query}, s, lang)

    return speech_response(s["retry"], reprompt=s["reprompt"])
