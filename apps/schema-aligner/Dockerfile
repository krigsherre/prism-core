FROM python:3.11-slim

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/pip pip install poetry==1.8.3

RUN poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock* ./

RUN --mount=type=cache,target=/root/.cache/pypoetry/cache \
    --mount=type=cache,target=/root/.cache/pypoetry/artifacts \
    poetry install --no-interaction --no-root --without dev

COPY . .
ENV PYTHONPATH="/app/src"

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
