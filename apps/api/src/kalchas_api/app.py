"""Kalchas API — FastAPI app."""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from kalchas_core import __version__ as core_version
from kalchas_core.alert_outcomes import DEFAULT_RULES
from kalchas_core.weights import WeightSet, strategy_names
from pydantic import BaseModel, Field

app = FastAPI(
    title="Kalchas API",
    version="3.0.0",
    description="Strategy analytics API. OpenAPI is the contract for the web client.",
)


class HealthResponse(BaseModel):
    status: str
    core_version: str
    strategies: list[str]


class WeightsSummary(BaseModel):
    strategies: dict[str, dict[str, float]]


class StrategyRuleOut(BaseModel):
    strategy_slot: int
    strategy_name: str
    success_window_minutes: int
    expiration_buffer_minutes: int
    infinite_ttl: bool
    team_specific: bool
    enabled: bool
    source: str = "defaults"


class StrategyRulesResponse(BaseModel):
    rules: list[StrategyRuleOut]


class TeamSpecificPatch(BaseModel):
    team_specific: bool = Field(..., description="True = only trigger team goals count")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        core_version=core_version,
        strategies=list(strategy_names()),
    )


@app.get("/api/weights/defaults", response_model=WeightsSummary)
def default_weights() -> WeightsSummary:
    w = WeightSet.defaults()
    payload: dict[str, dict[str, float]] = {}
    for name in strategy_names():
        payload[name] = {row["key"]: float(row["current"]) for row in w.describe(name)}
    return WeightsSummary(strategies=payload)


class LiveMatchRow(BaseModel):
    match_id: str
    home_team: str
    away_team: str
    minute: int
    score: str
    league: str | None = None


class LiveResponse(BaseModel):
    matches: list[LiveMatchRow]
    source: str


@app.get("/api/live", response_model=LiveResponse)
def live() -> LiveResponse:
    """Live matches from scanner persistence (Postgres), or empty without DATABASE_URL."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        return LiveResponse(matches=[], source="empty")
    from kalchas_db.matches import list_live_matches_sync

    try:
        rows = list_live_matches_sync(dsn)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"live feed unavailable: {exc}") from exc
    return LiveResponse(
        matches=[
            LiveMatchRow(
                match_id=str(r["match_id"]),
                home_team=str(r["home_team"]),
                away_team=str(r["away_team"]),
                minute=int(r["minute"]),
                score=f"{int(r['home_score'])}-{int(r['away_score'])}",
                league=str(r["league_name"]) if r.get("league_name") else None,
            )
            for r in rows
        ],
        source="postgres",
    )


def _default_rule_outs() -> list[StrategyRuleOut]:
    return [
        StrategyRuleOut(
            strategy_slot=r.strategy_slot,
            strategy_name=r.strategy_name,
            success_window_minutes=r.success_window_minutes,
            expiration_buffer_minutes=r.expiration_buffer_minutes,
            infinite_ttl=r.infinite_ttl,
            team_specific=r.team_specific,
            enabled=r.enabled,
            source="defaults",
        )
        for r in DEFAULT_RULES
    ]


@app.get("/api/strategy-rules", response_model=StrategyRulesResponse)
def strategy_rules() -> StrategyRulesResponse:
    """Confirmation rules. Uses Postgres when DATABASE_URL is set, else defaults."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        return StrategyRulesResponse(rules=_default_rule_outs())
    from kalchas_db.rules import list_strategy_rules

    rows = list_strategy_rules(dsn)
    return StrategyRulesResponse(
        rules=[
            StrategyRuleOut(
                strategy_slot=int(r["strategy_slot"]),
                strategy_name=str(r["strategy_name"]),
                success_window_minutes=int(r["success_window_minutes"]),
                expiration_buffer_minutes=int(r["expiration_buffer_minutes"]),
                infinite_ttl=bool(r["infinite_ttl"]),
                team_specific=bool(r["team_specific"]),
                enabled=bool(r["enabled"]),
                source="database",
            )
            for r in rows
        ]
    )


@app.patch("/api/strategy-rules/{slot}", response_model=StrategyRuleOut)
def patch_team_specific(slot: int, body: TeamSpecificPatch) -> StrategyRuleOut:
    """Toggle team_specific for a slot (settings). Requires DATABASE_URL."""
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="DATABASE_URL required to change settings")
    from kalchas_db.rules import set_team_specific

    row = set_team_specific(dsn, slot, body.team_specific)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No strategy_rules row for slot {slot}")
    return StrategyRuleOut(
        strategy_slot=int(row["strategy_slot"]),
        strategy_name=str(row["strategy_name"]),
        success_window_minutes=int(row["success_window_minutes"]),
        expiration_buffer_minutes=int(row["expiration_buffer_minutes"]),
        infinite_ttl=bool(row["infinite_ttl"]),
        team_specific=bool(row["team_specific"]),
        enabled=bool(row["enabled"]),
        source="database",
    )
