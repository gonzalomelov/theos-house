"""Meta Perception Encoder Audio hearing worker: 2 s of 16 kHz audio in, label scores out, nothing written anywhere.

Runs in a Python that has torch and transformers 5.21 or later (scripts/hearing-setup.sh makes one), started by
parenting_agent.hearing.MetaListener. The model is facebook/pe-a-frame-small (Perception Encoder Audio Frame, Meta,
Apache 2.0), loaded from a local folder with no network: it scores every 40 ms of audio against text prompts, zero
shot. The prompts per label and the background prompts come from HEARING_CONFIG, their text embeddings are computed
once at start.

Per label two numbers, each the best 40 ms frame of the window:
  logit: the best prompt's frame logit (the model's own sigmoid scale)
  margin: the best prompt's logit minus the best background prompt's logit, in the same frame
"scores" holds the one the config names for that label ("mode"), on the logit scale, so the Ear's thresholds are the
raw thresholds chosen on the tune set. The model's probability is its sigmoid. "raw" holds both numbers.

Protocol on stdin and stdout, the same as the SAM 3.1 worker:
  start: one JSON line {"ready": true, ...} or {"blocked": "reason"}
  each request: 4-byte big-endian length, then that many bytes of float32 mono PCM at 16 kHz
  each reply: one JSON line {"scores": {label: logit scale}, "raw": {label: {"logit", "margin"}}, "seconds": float}
Audio stays in memory: the worker never opens a file for writing.
"""
import json
import os
import struct
import sys
import time

RATE = 16000
MODEL_RATE = 48000


def upsample(np, samples):
    """16 kHz to 48 kHz by zero padding the spectrum, so nothing is added above 8 kHz."""
    n = samples.size
    spectrum = np.fft.rfft(samples)
    out = np.zeros(3 * n // 2 + 1, np.complex128)
    out[:spectrum.size] = spectrum
    return (np.fft.irfft(out, 3 * n) * 3).astype(np.float32)


class Encoder:
    def __init__(self, cfg):
        import numpy as np
        import torch
        from transformers import AutoTokenizer, PeAudioFeatureExtractor, PeAudioFrameLevelModel
        self.np, self.torch = np, torch
        device = cfg.get("device") or "cpu"
        if device == "mps" and not torch.backends.mps.is_available():
            device = "cpu"
        self.device = device
        path = os.path.expanduser(cfg["model_dir"])
        self.model = PeAudioFrameLevelModel.from_pretrained(path, local_files_only=True).to(device).eval()
        self.features = PeAudioFeatureExtractor.from_pretrained(path, local_files_only=True)
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self.prompts = cfg["prompts"]
        self.background = cfg.get("background", [])
        self.modes = cfg.get("modes", {})
        texts = [p for label in self.prompts for p in self.prompts[label]] + list(self.background)
        tokens = tokenizer(texts, padding=True, return_tensors="pt").to(device)
        with torch.no_grad():
            hidden = self.model.text_model(input_ids=tokens["input_ids"], attention_mask=tokens["attention_mask"],
                                           output_hidden_states=True, return_dict=True).hidden_states[-1][:, 0]
            self.text = self.model.text_audio_head(hidden)
        self.slices, start = {}, 0
        for label, prompts in self.prompts.items():
            self.slices[label] = slice(start, start + len(prompts))
            start += len(prompts)
        self.bg = slice(start, start + len(self.background))
        self.scale = float(self.model.text_audio_logit_scale)
        self.bias = float(self.model.text_audio_logit_bias)

    def score(self, samples):
        np, torch = self.np, self.torch
        started = time.monotonic()
        wave = upsample(np, np.asarray(samples, np.float32))
        inputs = self.features(wave, sampling_rate=MODEL_RATE, return_tensors="pt")
        with torch.no_grad():
            audio = self.model.get_audio_embeds(inputs["input_values"].to(self.device),
                                                inputs["padding_mask"].to(self.device))
            logits = (audio[0] @ self.text.T) * self.scale + self.bias
        logits = logits.float().cpu().numpy()
        bg = logits[:, self.bg].max(axis=1) if self.background else np.zeros(logits.shape[0], np.float32)
        raw, scores = {}, {}
        for label, cols in self.slices.items():
            best = logits[:, cols].max(axis=1)
            raw[label] = {"logit": round(float(best.max()), 4), "margin": round(float((best - bg).max()), 4)}
            scores[label] = raw[label][self.modes.get(label, "logit")]
        return {"scores": scores, "raw": raw, "seconds": round(time.monotonic() - started, 3)}


def main():
    import numpy as np
    cfg = json.loads(os.environ.get("HEARING_CONFIG", "{}"))
    out = sys.stdout
    try:
        model = Encoder(cfg)
    except Exception as error:
        out.write(json.dumps({"blocked": f"{type(error).__name__}: {str(error)[:300]}"}) + "\n")
        out.flush()
        return 1
    out.write(json.dumps({"ready": True, "model": "facebook/pe-a-frame-small", "device": model.device,
                          "labels": sorted(model.prompts)}) + "\n")
    out.flush()
    read = sys.stdin.buffer.read
    while True:
        header = read(4)
        if len(header) < 4:
            return 0
        data = read(struct.unpack(">I", header)[0])
        try:
            reply = model.score(np.frombuffer(data, np.float32))
        except Exception as error:  # one bad window never kills the worker
            reply = {"scores": {}, "error": str(error)[:200]}
        out.write(json.dumps(reply) + "\n")
        out.flush()


if __name__ == "__main__":
    raise SystemExit(main())
