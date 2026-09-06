"""Kalchas API — FastAPI app."""

from __future__ import annotations

from fastapi import FastAPI
from kalchas_core import __version__ as core_version
from kalchas_core.weights import WeightSet, strategy_names
from pydantic import BaseModel

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
    """Placeholder live feed — scanner persistence will populate this."""
    return LiveResponse(matches=[], source="empty")
