# WhatsApp

The agent's messages go on WhatsApp through Meta's Cloud API when `WHATSAPP_TOKEN` and `WHATSAPP_PHONE_ID` are set, and on Telegram otherwise. Code: `parenting_agent/channels/whatsapp.py`, webhook in `parenting_agent/core/server.py`.

Free text works for 24 hours after the parent's last message. Outside that, WhatsApp takes only an approved template, so the agent sends the template, keeps the words for the reply, and carries them on Telegram right away. The action's record says which happened. For the demo and video, the parent sends the first message.

## Turning it on

In `~/apps/parenting-agent.env` on the Vostro, then `CUTOVER=1 ... sh deploy/core.sh deploy`:

```
WHATSAPP_TOKEN=          the app's access token
WHATSAPP_PHONE_ID=       the test number's Phone number ID
WHATSAPP_APP_SECRET=     App settings, Basic
WHATSAPP_VERIFY_TOKEN=   any long random string, also typed into the webhook form
WHATSAPP_GONZA=          the number in international format, one of the approved test recipients
WHATSAPP_CECI=           leave empty to keep her on Telegram
```

The way in, once: rebuild the egress proxy (`graph.facebook.com` is in its filter) and recreate the relay so `/whatsapp` exists. The deploy starts its own door, `parenting-whatsapp-door`, on `127.0.0.1:4831`. Add a tunnel hostname such as `whatsapp.home.example` to that port with no Access in front, and set `https://whatsapp.home.example/whatsapp` as the callback on Meta's webhook form, subscribed to `messages`.

## Twilio, while Meta's review is pending

`WHATSAPP_BACKEND=twilio` sends through Twilio (`parenting_agent/channels/twilio_whatsapp.py`), with `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `WHATSAPP_GONZA` in `~/apps/parenting-agent.env`. The sandbox's sender is shared, and each parent first sends its join code. Set the sandbox's "When a message comes in" to `https://whatsapp.home.example/twilio`, method POST. Both webhooks check `X-Twilio-Signature`. A message is on record as delivered only when Twilio's status callback says so, and a failed one goes on Telegram. Outside the 24 hour window nothing goes on WhatsApp and Telegram carries the words.
