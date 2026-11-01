"""Spoken language ID worker for the OPOL helper (opol.py): one utterance of 16 kHz audio in, language scores out.

Runs in a Python that has torch and transformers (the hearing venv, scripts/hearing-setup.sh), started by
parenting_agent.opol.MmsLid. The model is facebook/mms-lid-126 (Meta's Massively Multilingual Speech, language ID over
126 languages, CC-BY-NC 4.0), loaded from a local folder with HF_HUB_OFFLINE: no network, nothing leaves the machine.

Protocol on stdin and stdout, the same as the hearing worker:
  start: one JSON line {"ready": true, ...} or {"blocked": "reason"}
  each request: 4-byte big-endian length, then that many bytes of 16-bit little-endian mono PCM at 16 kHz
  each reply: one JSON line {"probs": {"eng": p, "spa": p}, "top": iso code, "top_p": p, "seconds": float}
Audio stays in memory: the worker never opens a file for writing.
"""
import json
import os
import struct
import sys
import time

RATE = 16000
KEEP = ("eng", "spa")
MAX_S = 20  # the glasses cut utterances at 15 s, longer audio is trimmed


class Lid:
    def __init__(self, cfg):
        import numpy as np
        import torch
        from transformers import AutoFeatureExtractor, Wav2Vec2ForSequenceClassification
        self.np, self.torch = np, torch
        device = cfg.get("device") or "cpu"
        if device == "mps" and not torch.backends.mps.is_available():
            device = "cpu"
        self.device = device
        path = os.path.expanduser(cfg["model_dir"])
        self.features = AutoFeatureExtractor.from_pretrained(path, local_files_only=True)
        self.model = Wav2Vec2ForSequenceClassification.from_pretrained(path, local_files_only=True).to(device).eval()
        labels = self.model.config.id2label
        self.labels = [labels[i] for i in range(len(labels))]
        self.keep = {code: self.labels.index(code) for code in KEEP if code in self.labels}

    def score(self, pcm):
        np, torch = self.np, self.torch
        started = time.monotonic()
        samples = np.frombuffer(pcm, "<i2").astype(np.float32) / 32768.0
        samples = samples[:MAX_S * RATE]
        inputs = self.features(samples, sampling_rate=RATE, return_tensors="pt")
        with torch.no_grad():
            logits = self.model(inputs["input_values"].to(self.device)).logits[0]
        probs = torch.softmax(logits.float(), dim=-1).cpu().numpy()
        top = int(probs.argmax())
        return {"probs": {code: round(float(probs[i]), 4) for code, i in self.keep.items()}, "top": self.labels[top],
                "top_p": round(float(probs[top]), 4), "seconds": round(time.monotonic() - started, 3)}


def read_exact(stream, n):
    data = b""
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def main():
    try:
        lid = Lid(json.loads(os.environ["OPOL_LID_CONFIG"]))
    except Exception as error:  # noqa: BLE001 the agent is told why, and counts nothing from audio
        print(json.dumps({"blocked": f"{type(error).__name__}: {str(error)[:200]}"}), flush=True)
        return
    print(json.dumps({"ready": True, "model": "facebook/mms-lid-126", "device": lid.device, "keep": sorted(lid.keep)}),
          flush=True)
    stdin = sys.stdin.buffer
    while True:
        head = read_exact(stdin, 4)
        if head is None:
            return
        pcm = read_exact(stdin, struct.unpack(">I", head)[0])
        if pcm is None:
            return
        try:
            reply = lid.score(pcm)
        except Exception as error:  # noqa: BLE001 one bad clip is reported, the next one is scored
            reply = {"error": f"{type(error).__name__}: {str(error)[:200]}"}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
