# The families service. Standard library only: no pip install, no extra packages.
# Pin this base by digest at deploy time (docker buildx imagetools inspect python:3.11-slim-bookworm).
FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=America/Montevideo PA_FAMILIES_DATA_DIR=/data
WORKDIR /app
# Only the code the service runs: the agent core, the rhythm engine, the Telegram adapter and the families package.
# The demo package is copied for its settings checks and its session export. No config, no env file, no house code.
COPY parenting_agent/__init__.py parenting_agent/bus.py parenting_agent/
COPY parenting_agent/agent parenting_agent/agent
COPY parenting_agent/rhythm parenting_agent/rhythm
COPY parenting_agent/channels parenting_agent/channels
COPY parenting_agent/demo parenting_agent/demo
COPY parenting_agent/families parenting_agent/families
COPY simweek simweek
RUN useradd --uid 10002 --no-create-home families && mkdir /data && chown families /data && chmod 700 /data
USER families
CMD ["python", "-m", "parenting_agent.families", "run"]
