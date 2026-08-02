FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/pip pip install poetry==1.8.3

COPY apps/storage-sync/pyproject.toml apps/storage-sync/poetry.lock* /app/

RUN --mount=type=cache,target=/root/.cache/pypoetry/cache \
    --mount=type=cache,target=/root/.cache/pypoetry/artifacts \
    poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root

COPY apps/storage-sync/src/ /app/src/
COPY apps/storage-sync/alembic.ini /app/
COPY apps/storage-sync/alembic/ /app/alembic/

COPY packages/contracts/gen/python/proto /app/src/proto
COPY apps/schema-aligner/src/core/registry.json /schema-aligner/src/core/registry.json

ENV PYTHONPATH="/app/src"
ENV SCHEMA_REGISTRY_PATH="/schema-aligner/src/core/registry.json"

CMD ["python", "-m", "main"]
