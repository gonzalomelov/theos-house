"""The agent's ears and voice, both Meta open models.

- Hearing: a Telegram voice note (OGG Opus) is converted to WAV with ffmpeg and heard by Muse Spark Open as
  audio input (ear.py). The words it heard go through the same path as a typed note, so every guard applies.
- Speaking: Meta's MMS-TTS (VITS, facebook/mms-tts-spa and facebook/mms-tts-eng, CC-BY-NC 4.0) turns a reply into
  speech (tts.py), sent as a Telegram voice note or played on this machine's default output.

ffmpeg and torch are heavy, so the family agent and the families bot reach them through the voice service
(server.py), a separate walled container with no internet. On the Mac they can also run in process (client.py).
"""
