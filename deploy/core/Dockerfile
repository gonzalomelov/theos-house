# The persistent agent (parenting_agent/core). The old agent's image stays on the standard library, this one needs LangGraph.
# python:3.12-slim-bookworm pinned by digest (2026-10-28), the same base as deploy/Dockerfile. Bump deliberately.
FROM python@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_ROOT_USER_ACTION=ignore PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements-core.txt .
RUN pip install --quiet --disable-pip-version-check -r requirements-core.txt && mkdir /data && chown 1000:1000 /data
COPY parenting_agent ./parenting_agent
COPY config ./config
USER 1000:1000
CMD ["python", "-m", "parenting_agent.core", "--port", "8780"]
