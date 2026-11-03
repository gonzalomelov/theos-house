# The judge simulator. Only the code it runs: the agent core and what the core imports, on a mock home.
# python:3.12-slim-bookworm pinned by digest (2026-10-28), the same base as the family agent. Bump deliberately.
FROM python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=America/Montevideo PA_WORLD=mock PA_BIND=0.0.0.0 PA_SIM_MEDIA=/media
WORKDIR /app
COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt
COPY parenting_agent parenting_agent
RUN useradd --uid 10002 --no-create-home sim
USER sim
EXPOSE 8781
CMD ["python", "-m", "parenting_agent.simulator"]
