# The families service. Standard library only: no pip install, no extra packages.
# python:3.12-slim-bookworm pinned by digest (2026-10-28), the same base as the family agent. Bump deliberately.
FROM python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=America/Montevideo PA_FAMILIES_DATA_DIR=/data
WORKDIR /app
# Only the code the service runs: the agent core, the rhythm engine, the cry reason, the Telegram adapter and the
# families package.
# The demo package is copied for its settings checks and its session export. No config, no env file, no house code.
COPY parenting_agent/__init__.py parenting_agent/bus.py parenting_agent/cry_reason.py parenting_agent/
COPY parenting_agent/agent parenting_agent/agent
COPY parenting_agent/rhythm parenting_agent/rhythm
COPY parenting_agent/channels parenting_agent/channels
COPY parenting_agent/demo parenting_agent/demo
COPY parenting_agent/families parenting_agent/families
COPY parenting_agent/voice parenting_agent/voice
COPY simweek simweek
RUN useradd --uid 10002 --no-create-home families && mkdir /data && chown families /data && chmod 700 /data
USER families
CMD ["python", "-m", "parenting_agent.families", "run"]
