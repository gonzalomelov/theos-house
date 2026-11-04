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

## Voice notes through Twilio

A voice note on WhatsApp goes the way one does on Telegram: the note becomes WAV in the voice service, Muse's ear writes down the words, the screen checks them, and they reach the gate and Muse as the parent's message. The webhook answers Twilio at once and the hearing runs behind it, since Twilio waits 15 seconds at most.

- `MediaUrl0` is fetched only for a known parent, on a signed form, and only from this account's media on `api.twilio.com`, with basic auth. Twilio answers with a redirect to a short-lived address. The redirect is followed by hand, only to `mms.twiliocdn.com`, `media.twiliocdn.com` or `s3-external-1.amazonaws.com`, with no auth.
- Only those two twiliocdn hosts are in `deploy/egress/filter`, so the egress proxy has to be rebuilt once. S3 is a whole region's worth of buckets, so it stays out unless a real note shows Twilio needs it: then the note's `voice_note_not_heard` event names the failure in `why`, on `/events`.
- At most 2 MB, about 8 minutes, and audio types only.
- A note that couldn't be fetched or heard gets a plain line from the home, with no Muse in it: "No pude escuchar ese audio...". A photo with nothing written gets its own plain line.

## What happens when

| Who, and when on the real clock | `PA_REHEARSAL=1` | Otherwise |
|---|---|---|
| Gonza, 07:00 to 22:00 | WhatsApp, with "Ensayo: " in front. A quiet one goes on Telegram | WhatsApp. A quiet one goes on Telegram |
| Gonza, 22:00 to 07:00 | Telegram with no sound, always, with "Ensayo: " | WhatsApp. A quiet one goes on Telegram |
| Ceci with `WHATSAPP_CECI` set | The same by day. 22:00 to 07:00 nothing on any channel | The same as Gonza |
| Either, window closed or Twilio failing | Telegram carries the words, under the same rules | Telegram carries the words |

The sandbox sends one message every 3 seconds, so two messages in a row from it wait for that. WhatsApp can't send without a sound, so a quiet message is always Telegram's. An event sent with `at` on the API lives that moment for the rota and for who may be woken, but the rehearsal rule above reads the real clock: a 02:50 cry sent at 15:00 goes on WhatsApp.
