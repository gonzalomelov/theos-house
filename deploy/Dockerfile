# The family's private agent core (issue #15). Standard library only: no packages are installed.
# Vision (OpenCV, SAM 3.1) stays on the Mac, so this image has none of it.
# python:3.12-slim-bookworm pinned by digest (2026-10-28). Bump deliberately.
FROM python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY parenting_agent ./parenting_agent
COPY config ./config
USER 1000:1000
CMD ["python", "-m", "parenting_agent", "--config", "config/agent.vostro.json"]
