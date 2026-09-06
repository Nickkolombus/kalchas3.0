# Kalchas 3.0

Strategy-based live football analytics. A scanner evaluates in-play matches
against a set of strategy formulas, an API serves the results to a web
dashboard, and a Telegram bot delivers alerts to subscribers.

This is a ground-up rebuild of Kalchas 2.2. The domain core — the strategy
formulas, outcome engine, K-Score and NPEI — was carried over. The
infrastructure around it was not.

## Layout

```
packages/core     Pure domain logic. No IO. This is the valuable part.
packages/football API-Football HTTP client.
packages/db       asyncpg pool + Alembic migrations.
apps/api          FastAPI service. Serves the dashboard and admin endpoints.
apps/scanner      Polls the football feed, evaluates strategies, persists
                  match minutes to Postgres, writes alerts to the outbox.
apps/bot          Telegram delivery.
apps/web          React + Vite dashboard (mock fixtures until OpenAPI live contract).
```

Three deployables (`api`, `scanner`, `bot`) share `packages/core`. They scale
and fail independently; only `bot` is pinned to a single replica, because
Telegram long-polling does not tolerate two.

## The rule that holds this together

Every boundary is checked:

| Boundary | Enforced by |
|---|---|
| HTTP request/response | Pydantic models, published as OpenAPI |
| Backend to frontend | TypeScript client generated from that OpenAPI schema |
| Database schema | A single Alembic migration history |
| Every commit | `ruff`, `mypy`, and `pytest` in CI |

Kalchas 2.2 had none of these, and the cost was not abstract: the only way to
learn whether a change worked was to deploy it and watch Telegram. Adding
these four contracts is the entire point of 3.0.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras --dev   # create the venv and install everything
uv run pytest                # run the test suite
uv run ruff check .          # lint
uv run mypy                  # type check

# Apps (each is a workspace member)
uv run kalchas-api           # FastAPI on :8000 — /health, /api/weights, /api/live (Postgres)
uv run kalchas-scanner       # poll live matches (needs API_FOOTBALL_KEY)
SCANNER_ONCE=1 uv run kalchas-scanner   # single cycle
uv run kalchas-bot           # Telegram (needs TELEGRAM_TOKEN; single replica only)
uv run kalchas-migrate       # alembic upgrade head (needs DATABASE_URL)

# Local Postgres + API
docker compose up postgres migrate api

# Web (mock fixtures)
cd apps/web && npm install && npm run dev
```

### Environment

| Variable | Used by |
|---|---|
| `DATABASE_URL` | migrate, api, scanner, bot |
| `API_FOOTBALL_KEY` | scanner (apiv3.apifootball.com) |
| `FOOTBALL_API_BASE` | scanner (default `https://apiv3.apifootball.com/`) |
| `FOOTBALL_REQUESTS_PER_HOUR` | scanner (default 180 — free-tier friendly) |
| `SCANNER_INTERVAL_SEC` | scanner (default 60) |
| `SCANNER_ONCE` | scanner (one cycle then exit) |
| `TELEGRAM_TOKEN` | bot |
| `TELEGRAM_CHAT_ID` | bot delivery worker |
| `API_HOST` / `API_PORT` | api (default 127.0.0.1:8000) |

## Relationship to Kalchas 2.2

2.2 lives in a separate folder and is frozen. It is not a dependency, not a
submodule, and receives no further commits. Code moves from it by deliberate
port only.
