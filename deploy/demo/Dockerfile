# The public demo. Standard library only: no pip install, no extra packages.
# Pin this base by digest at deploy time (docker buildx imagetools inspect python:3.11-slim-bookworm).
FROM python:3.11-slim-bookworm
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
