"""ffmpeg conversions. Telegram voice notes are OGG Opus, Muse takes WAV or MP3, Telegram sendVoice wants OGG Opus."""
import shutil
import subprocess


class AudioError(Exception):
    pass


def ffmpeg(data, args, timeout=30):
    binary = shutil.which("ffmpeg")
    if binary is None:
        raise AudioError("ffmpeg is not installed")
    try:
        done = subprocess.run([binary, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1"],
                              input=data, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        raise AudioError("ffmpeg timed out") from None
    if done.returncode != 0 or not done.stdout:
        raise AudioError(f"ffmpeg failed: {done.stderr[-200:].decode(errors='replace').strip()}")
    return done.stdout


def to_wav(data, rate=16000):
    """Any audio ffmpeg reads, as 16 kHz mono 16-bit WAV, the format Muse hears."""
    return ffmpeg(data, ["-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", "-f", "wav"])


def to_ogg_opus(data):
    """Any audio ffmpeg reads, as OGG Opus mono, the format Telegram shows as a voice note."""
    return ffmpeg(data, ["-vn", "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "32k",
                         "-application", "voip", "-f", "ogg"])
