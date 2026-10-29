"""Meta's MMS-TTS, a VITS model per language, run on the CPU in process.

facebook/mms-tts-spa and facebook/mms-tts-eng on Hugging Face, from Meta's Massively Multilingual Speech project.
License CC-BY-NC 4.0: fine for this hackathon and the family's own use, not for a commercial product.
Weights are read from the local Hugging Face cache only when HF_HUB_OFFLINE=1, which the voice image sets, so
nothing is downloaded at run time.

On a slow CPU the decoder can run on ONNX Runtime in int8 (onnx_decoder.py): set PA_VOICE_ONNX to the folder the
image build exported it to. Without it, everything runs in torch, as on the Mac.
"""
import io
import os
import threading
import time
import wave

from . import words

# Pinned revisions, the same ones deploy/voice/Dockerfile bakes into the image (a test checks they match).
MODELS = {"es": ("facebook/mms-tts-spa", "833b96c0278c85cf09776d565ba8f1cb2819f7ec"),
          "en": ("facebook/mms-tts-eng", "c71de0fe7204c83f1c10820a7d696d0b450048ba")}


class MmsVoice:
    name = "mms-tts"

    def __init__(self, models=None, threads=2, onnx_dir=None):
        self.models, self.threads = dict(models or MODELS), threads
        self.onnx_dir = onnx_dir if onnx_dir is not None else os.environ.get("PA_VOICE_ONNX", "")
        self.decoders = {}
        self.loaded = {}
        self.lock = threading.Lock()
        self.busy = threading.Lock()  # one synthesis at a time, the CPU is the limit
        self.cache = {}
        self.last_timings = []

    def load(self, lang):
        lang = lang if lang in self.models else "en"
        with self.lock:
            if lang not in self.loaded:
                import torch
                from transformers import AutoTokenizer, VitsModel
                torch.set_num_threads(self.threads)
                torch.set_flush_denormal(True)
                repo, revision = self.models[lang]
                model = VitsModel.from_pretrained(repo, revision=revision)
                model.eval()
                self.use_onnx_decoder(lang, model)
                self.loaded[lang] = (model, AutoTokenizer.from_pretrained(repo, revision=revision))
        return lang, self.loaded[lang]

    def use_onnx_decoder(self, lang, model):
        """Swaps the torch decoder for the int8 ONNX one when the image has it. Fails loudly when PA_VOICE_ONNX
        names a folder without it, so a broken image never falls back to the slow path in silence."""
        if not self.onnx_dir:
            self.decoders[lang] = "torch"
            return
        from . import onnx_decoder
        file = onnx_decoder.path(self.onnx_dir, lang)
        if not file.exists():
            raise FileNotFoundError(f"PA_VOICE_ONNX is set but {file} is missing")
        del model.decoder
        model.decoder = onnx_decoder.OrtDecoder(file, self.threads)
        self.decoders[lang] = file.name

    def synth(self, text, lang="en", seed=0):
        """WAV bytes (16-bit mono at the model's rate) for text, sentence by sentence. Returns (wav, timings) where
        timings lists the seconds each sentence took. The same text twice comes from the cache."""
        key = (text, lang)
        if key in self.cache:
            self.last_timings = []
            return self.cache[key], []
        lang, (model, tokenizer) = self.load(lang)
        with self.busy:
            return self._synth(key, text, lang, model, tokenizer, seed)

    def _synth(self, key, text, lang, model, tokenizer, seed):
        import numpy
        import torch
        rate = model.config.sampling_rate
        parts, timings = [], []
        for sentence in words.sentences(text) or [text]:
            said = words.spoken(sentence, lang)
            inputs = tokenizer(said, return_tensors="pt")
            if inputs["input_ids"].shape[-1] == 0:
                continue
            started = time.monotonic()
            torch.manual_seed(seed)
            with torch.no_grad():
                wave_out = model(**inputs).waveform[0].numpy()
            timings.append({"sentence": sentence, "seconds": round(time.monotonic() - started, 3),
                            "audio_s": round(len(wave_out) / rate, 2)})
            parts += [wave_out, numpy.zeros(int(rate * 0.25), dtype=wave_out.dtype)]
        if not parts:
            raise ValueError("nothing to say")
        pcm = (numpy.clip(numpy.concatenate(parts), -1, 1) * 32767).astype("<i2").tobytes()
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(pcm)
        data = buffer.getvalue()
        self.last_timings = timings
        if len(self.cache) < 64:
            self.cache[key] = data
        return data, timings
