# The public demo. Standard library only: no pip install, no extra packages.
# python:3.12-slim-bookworm pinned by digest (2026-10-28), the same base as the family agent. Bump deliberately.
FROM python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=America/Montevideo \
    PA_DEMO_HOST=0.0.0.0 PA_DEMO_PORT=8765 PA_DEMO_DATA_DIR=/data PA_DEMO_SECURE_COOKIE=1
WORKDIR /app
# Only the code the demo runs: the agent core, the rhythm engine and the simulated week generator.
COPY parenting_agent/__init__.py parenting_agent/bus.py parenting_agent/
COPY parenting_agent/agent parenting_agent/agent
COPY parenting_agent/rhythm parenting_agent/rhythm
COPY parenting_agent/demo parenting_agent/demo
COPY simweek simweek
RUN useradd --uid 10001 --no-create-home demo && mkdir /data && chown demo /data
USER demo
EXPOSE 8765
CMD ["python", "-m", "parenting_agent.demo"]
