# syntax=docker/dockerfile:1

FROM public.ecr.aws/docker/library/node:22-bookworm-slim AS web
WORKDIR /web
COPY apps/web/package.json ./
RUN npm install
COPY apps/web/ ./
RUN npm run build

FROM public.ecr.aws/docker/library/python:3.13-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    WEB_DIST=/app/apps/web/dist

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock alembic.ini README.md ./
COPY packages ./packages
COPY apps ./apps
COPY --from=web /web/dist ./apps/web/dist

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

FROM base AS migrate
CMD ["kalchas-migrate", "upgrade", "head"]

FROM base AS scanner
CMD ["kalchas-scanner"]

FROM base AS bot
CMD ["kalchas-bot"]

# Last stage = default image when no --target (Railway deploys).
# Role is selected per service via KALCHAS_ROLE (api | scanner | bot | migrate).
FROM base AS api
ENV API_HOST=0.0.0.0
ENV KALCHAS_ROLE=kalchas-api
CMD ["sh", "-c", "if [ \"$KALCHAS_ROLE\" = \"kalchas-api\" ]; then kalchas-migrate upgrade head; fi; exec \"$KALCHAS_ROLE\""]
