FROM python:3.10-slim AS builder

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/pip pip install poetry==1.8.3

COPY packages/contracts/gen/python packages/contracts/gen/python

WORKDIR /app/apps/gpu-extractor
COPY apps/gpu-extractor/pyproject.toml apps/gpu-extractor/poetry.lock* ./

RUN --mount=type=cache,target=/root/.cache/pypoetry/cache \
    --mount=type=cache,target=/root/.cache/pypoetry/artifacts \
    poetry config virtualenvs.create false && \
    poetry install --no-root --no-interaction --no-ansi

COPY apps/gpu-extractor/ .

FROM python:3.10-slim

COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --from=builder /app/packages/contracts /contracts

WORKDIR /app
COPY --from=builder /app/apps/gpu-extractor /app

ENV PYTHONPATH="/contracts/gen/python:/app/src"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
