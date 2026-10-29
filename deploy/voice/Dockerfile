# The voice service (issue #58): ffmpeg and Meta's MMS-TTS on the CPU, behind parenting_agent.voice.server.
# python:3.12-slim-bookworm pinned by digest (2026-10-28), the same base as the agent. Bump deliberately.
FROM python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HOME=/opt/hf PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
# The CPU build of torch only, from the PyTorch index. The same versions were run on the Mac on Oct 28 2026.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.15.0 \
 && pip install transformers==5.21.0 numpy==2.4.6 onnxruntime==1.31.1 onnx==1.23.2
# The weights are baked in at build time, pinned to a revision, so nothing is downloaded at run time and the
# container needs no internet. facebook/mms-tts-* are CC-BY-NC 4.0 (Meta, Massively Multilingual Speech).
RUN python -c "from huggingface_hub import snapshot_download as get; \
get('facebook/mms-tts-spa', revision='833b96c0278c85cf09776d565ba8f1cb2819f7ec'); \
get('facebook/mms-tts-eng', revision='c71de0fe7204c83f1c10820a7d696d0b450048ba')" \
 && chmod -R a+rX /opt/hf
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
WORKDIR /app
COPY parenting_agent/__init__.py parenting_agent/bus.py parenting_agent/
COPY parenting_agent/voice parenting_agent/voice
# The HiFi-GAN decoder, exported from the weights above to ONNX and quantized to int8 for the Vostro CPU (about
# 2 times faster there, see results/voice). Only the int8 files are kept. Offline, from the cached weights. Niced,
# so a build on the Vostro never starves the live agents.
RUN nice -n 19 python -m parenting_agent.voice.onnx_decoder /opt/mms-onnx && rm /opt/mms-onnx/mms-??-decoder.onnx \
 && chmod -R a+rX /opt/mms-onnx
ENV PA_VOICE_ONNX=/opt/mms-onnx
COPY parenting_agent/agent parenting_agent/agent
RUN useradd --uid 10003 --no-create-home --user-group pavoice
USER pavoice
EXPOSE 8800
CMD ["python", "-m", "parenting_agent.voice.server", "--host", "0.0.0.0", "--port", "8800", "--preload"]
