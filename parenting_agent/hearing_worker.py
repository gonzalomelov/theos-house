"""PANNs CNN14 hearing worker: 2 s of 16 kHz audio in, label scores out, nothing written anywhere.

Runs in a Python that has torch (the SAM 3.1 venv, see docs/house-sounds.md), started by parenting_agent.hearing.
Model code is qiuqiangkong/audioset_tagging_cnn pytorch/models.py at commit 542c8c8, weights Cnn14_16k_mAP=0.438.pth
from Zenodo record 3987831, both fetched by scripts/fetch-panns.sh with checksums. The checkpoint already holds the
STFT kernels and the mel filter bank, so torchlibrosa is replaced by a stub that only declares those tensors and
librosa is not needed. load_state_dict is strict, so a stub that does not match the checkpoint fails at start.

Protocol on stdin and stdout, like the SAM 3.1 worker:
  start: one JSON line {"ready": true, ...} or {"blocked": "reason"}
  each request: 4-byte big-endian length, then that many bytes of float32 mono PCM at 16 kHz
  each reply: one JSON line {"scores": {group: max over windows}, "speech": float, "seconds": float}
Audio stays in memory: the worker never opens a file for writing.
"""
import csv
import json
import os
import struct
import sys
import time
import types
from pathlib import Path

RATE = 16000
WINDOW = 2 * RATE
HOP = 7680
SPEECH_CLASSES = ("Speech", "Conversation", "Narration, monologue", "Child speech, kid speaking",
                  "Hubbub, speech noise, speech babble", "Speech synthesizer")


def torchlibrosa_stub():
    """Same module shapes as torchlibrosa 0.1.0 Spectrogram and LogmelFilterBank, values come from the checkpoint."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class STFT(nn.Module):
        def __init__(self, n_fft, hop_length, center=True, pad_mode="reflect"):
            super().__init__()
            self.n_fft, self.hop, self.center, self.pad_mode = n_fft, hop_length, center, pad_mode
            bins = n_fft // 2 + 1
            self.conv_real = nn.Conv1d(1, bins, n_fft, stride=hop_length, bias=False)
            self.conv_imag = nn.Conv1d(1, bins, n_fft, stride=hop_length, bias=False)

        def forward(self, x):
            x = x[:, None, :]
            if self.center:
                x = F.pad(x, (self.n_fft // 2, self.n_fft // 2), mode=self.pad_mode)
            return self.conv_real(x)[:, None].transpose(2, 3), self.conv_imag(x)[:, None].transpose(2, 3)

    class Spectrogram(nn.Module):
        def __init__(self, n_fft=2048, hop_length=None, win_length=None, window="hann", center=True,
                     pad_mode="reflect", power=2.0, freeze_parameters=True):
            super().__init__()
            assert window == "hann" and power == 2.0 and (win_length or n_fft) == n_fft
            self.stft = STFT(n_fft, hop_length, center, pad_mode)

        def forward(self, x):
            real, imag = self.stft(x)
            return real ** 2 + imag ** 2

    class LogmelFilterBank(nn.Module):
        def __init__(self, sr=22050, n_fft=2048, n_mels=64, fmin=0.0, fmax=None, is_log=True, ref=1.0, amin=1e-10,
                     top_db=80.0, freeze_parameters=True):
            super().__init__()
            assert is_log and ref == 1.0 and top_db is None
            self.amin = amin
            self.melW = nn.Parameter(torch.zeros(n_fft // 2 + 1, n_mels), requires_grad=False)

        def forward(self, x):
            return 10.0 * torch.log10(torch.clamp(torch.matmul(x, self.melW), min=self.amin))

    class SpecAugmentation(nn.Module):
        """Training only. The worker runs the model in eval mode, so this never runs."""

        def __init__(self, *args, **kwargs):
            super().__init__()

        def forward(self, x):
            raise RuntimeError("SpecAugmentation is training only")

    package = types.ModuleType("torchlibrosa")
    stft = types.ModuleType("torchlibrosa.stft")
    augmentation = types.ModuleType("torchlibrosa.augmentation")
    stft.Spectrogram, stft.LogmelFilterBank = Spectrogram, LogmelFilterBank
    augmentation.SpecAugmentation = SpecAugmentation
    package.stft, package.augmentation = stft, augmentation
    sys.modules.update({"torchlibrosa": package, "torchlibrosa.stft": stft, "torchlibrosa.augmentation": augmentation})


class Panns:
    def __init__(self, model_dir, groups):
        import numpy as np
        import torch
        torchlibrosa_stub()
        sys.path.insert(0, str(model_dir))
        from models import Cnn14_16k
        self.np, self.torch = np, torch
        self.model = Cnn14_16k(sample_rate=RATE, window_size=512, hop_size=160, mel_bins=64, fmin=50, fmax=8000,
                               classes_num=527)
        # The checkpoint also stores a few numpy scalars, so only those numpy types are allowlisted.
        allowed = [np.core.multiarray._reconstruct, np.ndarray, np.dtype, type(np.dtype("float64")),
                   type(np.dtype("int64")), np.core.multiarray.scalar]
        with torch.serialization.safe_globals(allowed):
            state = torch.load(Path(model_dir) / "Cnn14_16k.pth", map_location="cpu", weights_only=True)
        self.model.load_state_dict(state["model"], strict=True)
        self.model.eval()
        names = [row[2] for row in list(csv.reader(open(Path(model_dir) / "class_labels_indices.csv")))[1:]]
        index = {name: i for i, name in enumerate(names)}
        self.groups = {label: [index[c] for c in classes] for label, classes in groups.items()}
        self.speech = [index[c] for c in SPEECH_CLASSES]

    def score(self, samples):
        np, torch = self.np, self.torch
        started = time.monotonic()
        if samples.size < WINDOW:
            samples = np.pad(samples, (0, WINDOW - samples.size))
        starts = range(0, samples.size - WINDOW + 1, HOP)
        batch = torch.from_numpy(np.stack([samples[s:s + WINDOW] for s in starts]).astype(np.float32))
        with torch.no_grad():
            frames = self.model(batch)["clipwise_output"].numpy()
        # Wide groups summed per window, then the loudest window: the "wide-sum" listener chosen in meta-hackathon-2026.
        scores = {label: round(float(np.clip(frames[:, cols].sum(axis=1), 0, 1).max()), 4)
                  for label, cols in self.groups.items()}
        return {"scores": scores, "speech": round(float(frames[:, self.speech].max()), 4),
                "seconds": round(time.monotonic() - started, 3)}


def main():
    import numpy as np
    cfg = json.loads(os.environ.get("HEARING_CONFIG", "{}"))
    out = sys.stdout
    try:
        model = Panns(Path(cfg["model_dir"]), cfg["groups"])
    except Exception as error:
        out.write(json.dumps({"blocked": f"{type(error).__name__}: {str(error)[:300]}"}) + "\n")
        out.flush()
        return 1
    out.write(json.dumps({"ready": True, "model": "PANNs Cnn14_16k mAP 0.438", "groups": sorted(model.groups)}) + "\n")
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
