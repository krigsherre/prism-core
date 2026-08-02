FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip pip install poetry==1.8.3

COPY apps/agentic-brain/pyproject.toml apps/agentic-brain/poetry.lock* /app/

RUN --mount=type=cache,target=/root/.cache/pypoetry/cache \
    --mount=type=cache,target=/root/.cache/pypoetry/artifacts \
    poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

COPY apps/agentic-brain/src/ /app/src/
COPY packages/contracts/gen/python/proto /app/src/grpc_proto
COPY apps/schema-aligner/src/core/registry.json /schema-aligner/src/core/registry.json

ENV PYTHONPATH="/app/src"
ENV SCHEMA_REGISTRY_PATH="/schema-aligner/src/core/registry.json"

EXPOSE 8001

HEALTHCHECK CMD curl --fail http://localhost:8001/health || exit 1

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8001"]
