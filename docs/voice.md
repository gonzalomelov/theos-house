# The agent hears and speaks (issue #58)

A parent sends a Telegram voice note, "le di 90 ml a las 3". Muse Spark Open hears the audio itself, the agent logs a 90 ml bottle at 03:00, and the answer comes back twice: as text that starts with the words heard, so a mishearing is easy to spot and correct, and as a voice note in a Meta open voice. Both senses are Meta open models: Muse Spark Open (`meta-models/muse-spark-open-1026` on Baseten) for hearing, MMS-TTS for speaking. There is no other speech-to-text model anywhere in the path.

Built on Oct 28 2026, during the hackathon.

## The path of a voice note

1. Telegram delivers an update with `voice.file_id`. The adapter (`parenting_agent/channels/telegram.py`) downloads it with `getFile`, through the same egress proxy as every other Telegram call. It is OGG Opus.
2. ffmpeg converts it to 16 kHz mono WAV (`parenting_agent/voice/audio.py`).
3. The ear (`parenting_agent/voice/ear.py`) sends the WAV to Muse as an `input_audio` part on the OpenAI-compatible chat endpoint, with a short instruction to write down exactly what the parent said, numbers as digits.
4. The words go into the agent as a normal message. Every guard that runs on a typed note runs on a voice note too: the emergency line, the health refusal, "never add a detail the parent did not say", the correction path, the double-send question.
5. The answer is sent as text, `«words heard»` then the reply, and the reply is spoken with MMS-TTS, converted to OGG Opus and sent with `sendVoice`.

A voice note is answered by voice. A typed message is answered in text only.

Why two Muse calls and not one: the guards in `parenting_agent/agent/rules.py` read the parent's words. `said_only` drops any amount, side or time the parent did not say, and it needs the words to know. One call that both hears and logs would skip all of them. So Muse hears first, then thinks.

### What Muse accepts

Tested with real calls on Oct 28 2026:

| Format | Result |
|---|---|
| WAV, 16 kHz mono | heard right |
| MP3 | heard right |
| OGG Opus (what Telegram sends) | refused, HTTP 400, the request body does not deserialize |

Sometimes, with the same request that works the other times, Muse answers as if no audio came with it ("No tengo acceso al audio", "I don't have access to audio files", "Enviá el audio y lo escribo"). It happened to 2 of 20 notes in the first full run on Oct 28, and to 1 of 4 identical MP3 calls in a probe. The ear never takes such an answer as the parent's words: it asks again, up to 3 times. If all fail, the parent is asked to send it again or type it. No local fallback model was needed, Muse audio input works.

Checked again on Oct 29 with clips Muse could not guess (a made-up word and random digits, in both languages): it wrote down speech in all 9 tries, the digits exact in the 6 tries of two clips, while the third clip's "sixty eight" came back as "868" every time, and its prompt tokens grow with the clip's length. Muse hears speech only. Beeps and house sounds get "I cannot hear audio". `usage.prompt_tokens_details.audio_tokens` reads 0 on every call, even when every word comes back, so that field is no sign either way. A system message, or a prompt that offers "if no audio reaches you" as a way out, makes Muse say it heard nothing. The ear has neither. Details in `results/audio-truth/README.md`.

## The voice: Meta open TTS options

| Option | License | Runs here | Verdict |
|---|---|---|---|
| MMS-TTS, `facebook/mms-tts-spa` and `facebook/mms-tts-eng` (VITS, about 36M parameters each) | CC-BY-NC 4.0 | Yes, CPU: 0.4 s a sentence on the Mac, about 10 s on the Vostro | **Picked** |
| SeamlessM4T v2 large, text to speech | CC-BY-NC 4.0 | 2.3B parameters, too heavy for the Vostro CPU, slow on the Mac | Not picked |
| Seamless Expressive | Seamless license, gated on Hugging Face | Needs a request form for the weights, GPU | Not picked, gated |
| Anything newer from Meta | | No Meta open-weights TTS release found on Oct 28 2026 | |

**License: MMS-TTS is CC-BY-NC 4.0, non-commercial only.** Fine for the hackathon and the family's own use. A paid product would need another voice.

Numbers: MMS-TTS reads letters only and drops digits, so `parenting_agent/voice/words.py` writes numbers, units and clock times as words first ("90 ml a las 15:30" becomes "noventa mililitros a las tres y media"), and strips markdown and arrows.

## Where it runs

- **On the Mac**: `python -m parenting_agent.voice say "Listo, anoté 90 ml"` speaks on the default output device, so AirPods work when they are the output. `parenting_agent/speaker.py` uses MMS-TTS for the reflex prompt with `PA_SPEAKER_VOICE=mms` (or `Speaker(voice="mms")`). It synthesizes "hand" at start, so the first prompt plays from the cache. `say` stays the default for the reflex. Needs torch and transformers in the venv.
- **On the Vostro**: the voice service, `deploy/voice/`. One image (python slim, ffmpeg, torch CPU, transformers, both MMS weights baked in at build and pinned to a revision, `HF_HUB_OFFLINE=1`), two containers:
  - `pa-voice-family` on `parenting-agent-internal`, used by the family agent (`"voice": {"service": "http://pa-voice-family:8800"}` in `config/agent.vostro.json`).
  - `pa-voice-families` on `pa-families-internal`, used by the families bot (`PA_FAMILIES_VOICE`).
  Two containers so the family's private agent and the families bot never share one. On the Vostro CPU a sentence takes about 10 s, so the text answer goes out at once and the voice note follows in the background. Only the first 3 sentences are spoken. Hearing itself is the Muse call from the agent or families container, through their egress proxies, as before.

### The wall

The voice service holds no secret and has no proxy settings, and its networks are internal with no gateway, so it has no internet, no host and no LAN. `deploy/voice/voice_check.py` proves it on every deploy: it speaks and converts in both languages, and fails if `1.1.1.1:443`, `huggingface.co:443` or the host answer. Like every container on those networks, it could open a TCP connection to the relay and the egress proxy next to it. It never does, and it has no token for anything behind them.

No audio leaves the house except the voice note to Muse on Baseten, the configured brain. The replies are spoken in the house.

```bash
sh deploy/voice.sh deploy     # build, run both containers, health, wall and speak checks
sh deploy/voice.sh check
sh deploy/voice.sh status
```

Deploy the voice service first, then `sh deploy/agent.sh deploy` and the families bot.

Families bot: only a parent of a family is heard, and only while the family is under its daily caps, because each voice note costs a Muse call. The hearing call is added to the family's spend. A stranger's voice note costs nothing.

## Results

`results/voice/README.md` has the numbers: 20 synthetic voice notes, 10 rioplatense Spanish and 10 English, through the families bot's real voice path with Muse as ear and brain.
