"""MMS-TTS's HiFi-GAN decoder on ONNX Runtime, int8, for a slow CPU like the Vostro's.

The decoder turns the spectrogram into the waveform and takes about 96 percent of the time on the CPU. The text
encoder, the duration predictor and the flow stay in torch, so the voice is the same model with the same weights:
the decoder is exported from the official facebook/mms-tts-* weights and quantized to int8 (per channel weights,
calibrated on reply-like sentences). Nothing else is downloaded.

Run once at image build, after the weights are in the Hugging Face cache:

    python -m parenting_agent.voice.onnx_decoder /opt/mms-onnx

writes mms-<lang>-decoder.onnx (float32) and mms-<lang>-decoder-int8.onnx for each language in tts.MODELS.
MmsVoice uses the int8 file when PA_VOICE_ONNX points at that folder.
"""
import sys
from pathlib import Path

# Calibration only: typical replies, not the test set in results/voice.
CALIBRATION = {
    "es": ["Listo, anoté la mamadera de 150 ml a las 9:20.", "Anotado, pañal mojado de Sofi a las 11:05.",
           "Hoy Sofi durmió tres siestas, la última de 40 minutos.", "Corregí la última toma: 80 ml en vez de 60 ml.",
           "Buenas noches, que descansen.", "Anotado, teta derecha 15 minutos a las 2:10.",
           "Ayer tomó 640 ml en total, en 6 tomas.", "¿Querés que lo anote a las 10 o a las 11?"],
    "en": ["Done, I logged a 150 ml bottle at 9:20.", "Noted, wet diaper for Leo at 11:05.",
           "Leo napped three times today, the last one for 40 minutes.", "I fixed the last feed: 80 ml instead of 60 ml.",
           "Good night, rest well.", "Logged a left side breastfeed, 15 minutes at 2:10.",
           "Yesterday he drank 640 ml in total, across 6 feeds.", "Should I log it at 10 or at 11?"]}


def path(folder, lang, int8=True):
    return Path(folder) / f"mms-{lang}-decoder{'-int8' if int8 else ''}.onnx"


class OrtDecoder:
    """Stands in for VitsModel.decoder: spectrogram in, waveform out, as torch tensors."""

    def __init__(self, file, threads=2):
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.set_denormal_as_zero", "1")
        self.session = onnxruntime.InferenceSession(str(file), options, providers=["CPUExecutionProvider"])

    def __call__(self, spectrogram, global_conditioning=None):
        import torch
        if global_conditioning is not None:
            raise ValueError("the ONNX decoder has no speaker conditioning")
        wave_out = self.session.run(None, {"spec": spectrogram.detach().numpy()})[0]
        return torch.from_numpy(wave_out)


def export(folder, langs=None):
    import torch
    from onnxruntime.quantization import CalibrationDataReader, QuantFormat, QuantType, quantize_static

    from . import words
    from .tts import MmsVoice

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    voice = MmsVoice(onnx_dir="")
    for lang in langs or voice.models:
        _, (model, tokenizer) = voice.load(lang)
        specs = []
        hook = model.decoder.register_forward_pre_hook(lambda module, args: specs.append(args[0].numpy().copy()))
        with torch.no_grad():
            for sentence in CALIBRATION[lang]:
                torch.manual_seed(0)
                model(**tokenizer(words.spoken(sentence, lang), return_tensors="pt"))
        hook.remove()

        class Decoder(torch.nn.Module):
            def __init__(self, decoder):
                super().__init__()
                self.decoder = decoder

            def forward(self, spec):
                return self.decoder(spec)

        fp32 = path(folder, lang, int8=False)
        torch.onnx.export(Decoder(model.decoder).eval(), (torch.from_numpy(specs[0]),), str(fp32), dynamo=False,
                          opset_version=17, input_names=["spec"], output_names=["wave"],
                          dynamic_axes={"spec": {2: "frames"}, "wave": {2: "samples"}})

        class Reader(CalibrationDataReader):
            def __init__(self):
                self.items = iter([{"spec": spec} for spec in specs])

            def get_next(self):
                return next(self.items, None)

        quantize_static(str(fp32), str(path(folder, lang)), Reader(), quant_format=QuantFormat.QDQ, per_channel=True,
                        activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8,
                        op_types_to_quantize=["Conv", "ConvTranspose"])
        print(f"{lang}: {fp32.name} and {path(folder, lang).name}", flush=True)


if __name__ == "__main__":
    export(sys.argv[1] if len(sys.argv) > 1 else "/opt/mms-onnx")
