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
apps/api          FastAPI service. Serves the dashboard and admin endpoints.
apps/scanner      Polls the football feed, evaluates strategies, writes alerts.
apps/bot          Telegram delivery.
apps/web          React + Vite dashboard.
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
```

## Relationship to Kalchas 2.2

2.2 lives in a separate folder and is frozen. It is not a dependency, not a
submodule, and receives no further commits. Code moves from it by deliberate
port only.
