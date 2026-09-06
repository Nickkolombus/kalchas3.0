#!/usr/bin/env bash
set -euo pipefail
export DATABASE_URL="${DATABASE_URL:-postgresql://kalchas:kalchas@postgres:5432/kalchas}"
# Keep Linux deps out of the Windows workspace .venv when bind-mounting.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/tmp/kalchas-smoke-venv}"
uv sync --frozen --no-dev
uv run kalchas-migrate
uv run python - <<'PY'
import os

os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"]
from kalchas_db.matches import (
    list_live_matches_sync,
    load_match_history_sync,
    upsert_match_minute_sync,
)

dsn = os.environ["DATABASE_URL"]
upsert_match_minute_sync(
    dsn,
    match_id="smoke-1",
    home_team="Smoke Home",
    away_team="Smoke Away",
    home_team_id=1,
    away_team_id=2,
    league_name="Smoke League",
    status_short="1H",
    home_score=1,
    away_score=0,
    minute=33,
    minute_block={
        "shots_on_target": {"home": 2, "away": 1},
        "dangerous_attacks": {"home": 15, "away": 7},
        "goals": {"home": 1, "away": 0},
    },
)
rows = list_live_matches_sync(dsn)
hist = load_match_history_sync(dsn, "smoke-1")
print("db_rows", len(rows))
print(
    "match",
    rows[0]["home_team"],
    rows[0]["away_team"],
    "min",
    rows[0]["minute"],
    f"{rows[0]['home_score']}-{rows[0]['away_score']}",
)
print("history_minutes", sorted(hist.keys()))

from fastapi.testclient import TestClient
from kalchas_api.app import app

res = TestClient(app).get("/api/live")
body = res.json()
print("http", res.status_code)
print("source", body.get("source"))
print("live_matches", body.get("matches"))
assert res.status_code == 200
assert body["source"] == "postgres"
assert any(m["match_id"] == "smoke-1" for m in body["matches"])
print("SMOKE_OK")
PY
