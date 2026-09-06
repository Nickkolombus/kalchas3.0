# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock alembic.ini README.md ./
COPY packages ./packages
COPY apps ./apps

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

FROM base AS api
CMD ["kalchas-api"]

FROM base AS scanner
CMD ["kalchas-scanner"]

FROM base AS bot
CMD ["kalchas-bot"]

FROM base AS migrate
CMD ["kalchas-migrate", "upgrade", "head"]
