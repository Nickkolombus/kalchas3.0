"""Catalogue of every admin-tunable strategy coefficient.

This is pure data: the coefficients each strategy exposes, their defaults, the
bounds the admin UI clamps sliders to, and the human copy that explains them.

Ported from Kalchas 2.2 `utils/strategy_weights.py`. The registry itself came
across intact -- the numbers are tuned domain knowledge. What did not come
across is that module's `resolve()`, which read the effective value straight
from Postgres. Because every formula called it, no formula could run without a
database. See `kalchas_core.weights.WeightSet` for the replacement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class WeightSpec:
    """One tunable coefficient: its default, its bounds, and how to describe it."""

    key: str
    label: str
    default: float
    min_val: float
    max_val: float
    step: float
    description: str = ""
    suggested: str = ""

    def clamp(self, value: float) -> float:
        """Constrain a proposed value to this coefficient's registered bounds."""
        return max(self.min_val, min(self.max_val, float(value)))


@dataclass(frozen=True, slots=True)
class StrategyInfo:
    """Display copy for a strategy's settings panel."""

    slot: str
    name: str
    short: str
    equation: str
    blurb: str


STRATEGY_INFO: Mapping[str, StrategyInfo] = MappingProxyType(
    {
        "rule_of_three": StrategyInfo(
            slot="1",
            name="Unrealised goals",
            short="UrG",
            equation=(
                "UG = (SOT·sot_weight·(quality_base + quality_slope·SOT/(SOT+SOFFT))"
                " + SOFFT·sofft_weight − Goals)\n"
                "     × (1 + possession_penalty·(50−Poss)/50  if Poss<50)\n"
                "     × OddsFactor × GameState × TimeMult"
            ),
            blurb=(
                "Finds teams creating more chances than the scoreboard reflects. "
                "Builds an 'unrealised goals' value from shots on/off target and "
                "possession, then adjusts for odds imbalance, current scoreline, "
                "and how late in the match we are. High values flag teams overdue "
                "to score."
            ),
        ),
        "pressure_index": StrategyInfo(
            slot="2",
            name="Pressure Index",
            short="Δ10′",
            equation=(
                "PI = sqrt(SOT_Δ)·sot_points + sqrt(SOFFT_Δ)·sofft_points"
                " + sqrt(Corner_Δ)·corner_points + sqrt(DA_Δ)·da_points\n"
                "     × GameState × TimeMult,  clamped to [0, 100]"
            ),
            blurb=(
                "Tracks attacking momentum over a rolling 10-minute window. Each "
                "shot, corner, and dangerous attack adds weighted points "
                "(sqrt-scaled so bursts don't dominate). Game-state and time-of-match "
                "modifiers adjust the final value — pressure while trailing late "
                "converts to goals more often than pressure while leading early."
            ),
        ),
        "delta_goal": StrategyInfo(
            slot="3",
            name="Form Bar",
            short="Bar",
            equation=(
                "xG = (median scored, last 10 · opponent median conceded, last 10) / 2\n"
                "Expected by now = xG · min(minute, 90) / 90\n"
                "Bar = expected by now − scored   # + behind pace, − ahead\n"
                "Delivered: scored ≥ xG (and ≥ 1 goal) — no alert"
            ),
            blurb=(
                "Form Bar: how many goals this team should have by now, from its own "
                "median goals scored and the opponent's median goals conceded over "
                "their last 10 played games, against what it has actually scored. "
                "Needs 5+ recent games (if only the opponent is short, its own median "
                "alone). No live match stats: attach Δ5′/Δ10′/UrG as extra "
                "conditions below to require pressure. The fire threshold is goals "
                "behind pace."
            ),
        ),
        "delta_5min": StrategyInfo(
            slot="4",
            name="5-minute pressure",
            short="Δ5′",
            equation=(
                "Δ5 = (SOT_Δ5 · sot_weight) + (DA_Δ5 · da_weight)\n"
                "Gate: DA_Δ5 ≥ min_da_delta and (SOT_Δ5 ≥ min_sot_delta"
                " or DA_Δ5 ≥ fallback_da_delta)"
            ),
            blurb=(
                "Short-horizon pressure detector. Takes deltas over the last "
                "5 minutes of shots on target and dangerous attacks, multiplies by "
                "weights, and fires when the corroboration gate (minimum DA + SOT "
                "activity) is met. Complements the Pressure Index by catching "
                "rapid surges the 10-minute window smooths out."
            ),
        ),
        "npei": StrategyInfo(
            slot="5",
            name="NPEI (Net Pressure Efficiency)",
            short="NPEI",
            equation=(
                "R1=ΔD/ΔA, R2=ΔT/ΔS, R3=ΔS/ΔA (5m window)\n"
                "NPEI = 100·(w1·R1 + w2·R2 + w3·R3); ratios below min activity "
                "contribute 0 (no weight redistribution)"
            ),
            blurb=(
                "Measures conversion efficiency, not volume. Three ratios over a "
                "5-minute window blended into a 0–100 score. Five admin-tunable "
                "zones label each team from Totally Inefficient to Highly Efficient "
                "(see zone ceiling weights below)."
            ),
        ),
        "kscore": StrategyInfo(
            slot="7",
            name="K-Score",
            short="K",
            equation=(
                "base = goal rate from kickoff 1X2 x share of goals in the next window "
                "(to half end) x score tilt x base level\n"
                "boost = [1H multiplier] x (1 + boost x unrealised)"
                " x (1 + shots last 10')^power\n"
                "K = round(100 x (1 - exp(-base x boost)))"
            ),
            blurb=(
                "The chance, in %, that this team scores within the window (20 minutes "
                "by default, ending at half time), the same bet a K alert is settled "
                "on. Kickoff prices, the clock and the score set the base; unrealised "
                "goals and recent shots nudge it. Fitted on match history: K 40-50 "
                "scored about 42% of the time."
            ),
        ),
    }
)


def _specs(*specs: WeightSpec) -> tuple[WeightSpec, ...]:
    return specs


REGISTRY: Mapping[str, tuple[WeightSpec, ...]] = MappingProxyType(
    {
        "rule_of_three": _specs(
            WeightSpec(
                "sot_weight",
                "Shot on target weight",
                0.25,
                0.05,
                1.0,
                0.01,
                "Goals per shot-on-target in the unrealised calculation.",
            ),
            WeightSpec(
                "sofft_weight",
                "Shot off target weight",
                0.05,
                0.0,
                0.5,
                0.01,
                "Goals per shot-off-target — smaller contribution than SOT.",
            ),
            WeightSpec(
                "quality_base",
                "Shot quality base",
                0.8,
                0.3,
                1.5,
                0.05,
                "Base multiplier for SOT conversion before accuracy bonus.",
            ),
            WeightSpec(
                "quality_slope",
                "Shot quality slope",
                0.4,
                0.0,
                1.0,
                0.05,
                "Extra multiplier as SOT accuracy rises above league average.",
            ),
            WeightSpec(
                "possession_penalty",
                "Low-possession penalty",
                -0.15,
                -0.5,
                0.0,
                0.01,
                "Applied linearly when possession < 50% — dampens UG for passive teams.",
            ),
        ),
        "pressure_index": _specs(
            WeightSpec(
                "sot_points",
                "Shot on target points",
                26.0,
                1.0,
                40.0,
                1.0,
                "Points per sqrt(shot-on-target Δ) — largest contributor.",
            ),
            WeightSpec(
                "sofft_points",
                "Shot off target points",
                16.0,
                0.0,
                30.0,
                1.0,
                "Points per sqrt(shot-off-target Δ).",
            ),
            WeightSpec(
                "corner_points", "Corner points", 10.0, 0.0, 20.0, 1.0, "Points per sqrt(corner Δ)."
            ),
            WeightSpec(
                "da_points",
                "Dangerous attack points",
                4.0,
                0.0,
                12.0,
                0.5,
                "Points per sqrt(dangerous-attack Δ) — the noisy input, so low weight.",
            ),
        ),
        # Form Bar is goals-vs-form arithmetic with no tunable coefficients; its
        # fire threshold lives in strategy_thresholds like every slot's. Kept as
        # an empty entry because admin endpoints (presets, conditions) key on it.
        "delta_goal": _specs(),
        "delta_5min": _specs(
            WeightSpec(
                "sot_weight",
                "SOT Δ weight",
                2.0,
                0.5,
                5.0,
                0.5,
                "Multiplier on 5-minute shot-on-target delta.",
            ),
            # 2.2 registered this default as 1.0, but `utils/delta_calculator.py`
            # hardcoded 0.5 and never read the registry at all -- so the admin
            # slider moved nothing, and the alert text quoted subscribers a DA
            # term twice its real size. Defaulted to the value actually in use,
            # so wiring the coefficient up leaves computed values unchanged.
            WeightSpec(
                "da_weight",
                "DA Δ weight",
                0.5,
                0.0,
                3.0,
                0.5,
                "Multiplier on 5-minute dangerous-attack delta "
                "(falls back to shots off target if DA is unavailable).",
            ),
            WeightSpec(
                "min_da_delta",
                "Min DA Δ gate",
                4.0,
                0.0,
                15.0,
                1.0,
                "Minimum dangerous-attack delta required before the alert fires.",
            ),
            WeightSpec(
                "min_sot_delta",
                "Min SOT Δ gate",
                1.0,
                0.0,
                5.0,
                1.0,
                "Minimum shot-on-target delta required alongside DA gate.",
            ),
            WeightSpec(
                "fallback_da_delta",
                "Fallback DA Δ gate",
                3.0,
                0.0,
                10.0,
                1.0,
                "Relaxed DA gate when SOT Δ alone is weak.",
            ),
        ),
        "npei": _specs(
            WeightSpec(
                "w1_attack_conv",
                "R1 weight: attack conversion",
                0.35,
                0.0,
                1.0,
                0.05,
                "Share of the score from ΔD/ΔA (dangerous attacks ÷ total attacks).",
            ),
            WeightSpec(
                "w2_shot_accuracy",
                "R2 weight: shot accuracy",
                0.40,
                0.0,
                1.0,
                0.05,
                "Share of the score from ΔT/ΔS (shots on target ÷ total shots).",
            ),
            WeightSpec(
                "w3_shot_creation",
                "R3 weight: shot creation",
                0.25,
                0.0,
                1.0,
                0.05,
                "Share of the score from ΔS/ΔA (total shots ÷ total attacks).",
            ),
            WeightSpec(
                "min_attacks",
                "Min attacks to score R1/R3",
                3.0,
                1.0,
                10.0,
                1.0,
                "Below this many attacks in the window, R1 and R3 are skipped.",
            ),
            WeightSpec(
                "min_shots",
                "Min shots to score R2",
                2.0,
                1.0,
                10.0,
                1.0,
                "Below this many shots, R2 is skipped.",
            ),
            WeightSpec(
                "zone_max_totally",
                "Zone ceiling: Totally Inefficient",
                5.0,
                0.0,
                50.0,
                1.0,
                "ΦI 0 through this score → Totally Inefficient.",
            ),
            WeightSpec(
                "zone_max_inefficient",
                "Zone ceiling: Inefficient",
                20.0,
                1.0,
                70.0,
                1.0,
                "Scores above the previous ceiling through this value → Inefficient.",
            ),
            WeightSpec(
                "zone_max_moderate",
                "Zone ceiling: Moderately Efficient",
                40.0,
                2.0,
                85.0,
                1.0,
                "Scores above the previous ceiling through this value → Moderately Efficient.",
            ),
            WeightSpec(
                "zone_max_efficient",
                "Zone ceiling: Efficient",
                55.0,
                3.0,
                99.0,
                1.0,
                "Scores above the previous ceiling through this value → Efficient; "
                "above → Highly Efficient.",
            ),
        ),
        "kscore": _specs(
            WeightSpec(
                "horizon_minutes",
                "Window (minutes)",
                20.0,
                5.0,
                45.0,
                1.0,
                "K is the chance the team scores within this many minutes, stopping "
                "at the end of the half. Keep it equal to the K-Index outcome window.",
            ),
            WeightSpec(
                "base_multiplier",
                "Base level",
                0.92,
                0.5,
                1.5,
                0.01,
                "Scales the scoring rate the kickoff prices, clock and score give. "
                "1.0 takes the prices as they are; fitted 0.92 on match history.",
            ),
            WeightSpec(
                "first_half_multiplier",
                "First-half multiplier",
                1.28,
                1.0,
                2.0,
                0.01,
                "Goals inside a first-half window come more often than the "
                "quarter-hour shares say. Applied in the first half only.",
            ),
            WeightSpec(
                "unrealised_boost",
                "Boost per unrealised goal",
                0.07,
                0.0,
                0.5,
                0.01,
                "Each Rule of 3 unrealised goal (0 to 4) raises the rate by this "
                "share: 0.07 means +7% per unrealised goal.",
            ),
            WeightSpec(
                "recent_shots_power",
                "Recent shots power",
                0.08,
                0.0,
                0.5,
                0.01,
                "Rate x (1 + shots in the last 10 minutes) ^ this. At 0.08, two "
                "shots add 9% and five add 15%.",
            ),
            WeightSpec(
                "max_live_boost",
                "Most the live stats can add",
                2.0,
                1.0,
                3.0,
                0.05,
                "Cap on the combined first-half, unrealised and recent-shots multiplier.",
            ),
        ),
    }
)


BUILTIN_PRESETS: Mapping[str, Mapping[str, Mapping[str, float]]] = MappingProxyType(
    {
        "rule_of_three": {
            "Balanced (default)": {},
            "Shot-heavy": {
                "sot_weight": 0.32,
                "sofft_weight": 0.07,
                "quality_base": 0.85,
                "quality_slope": 0.55,
            },
        },
        "pressure_index": {
            "Balanced (default)": {},
            "Shots emphasized": {
                "sot_points": 32.0,
                "sofft_points": 20.0,
                "corner_points": 8.0,
                "da_points": 3.0,
            },
            "DA/corners emphasized": {
                "sot_points": 22.0,
                "sofft_points": 14.0,
                "corner_points": 14.0,
                "da_points": 7.0,
            },
        },
        "delta_goal": {
            "Balanced (default)": {},
        },
        "delta_5min": {
            "Balanced (default)": {},
            "Strict gate": {
                "min_da_delta": 6.0,
                "min_sot_delta": 2.0,
                "fallback_da_delta": 5.0,
            },
            "Permissive gate": {
                "min_da_delta": 3.0,
                "min_sot_delta": 1.0,
                "fallback_da_delta": 2.0,
            },
        },
        "npei": {
            "Balanced (default)": {},
            "Accuracy-biased": {
                "w1_attack_conv": 0.25,
                "w2_shot_accuracy": 0.55,
                "w3_shot_creation": 0.20,
            },
            "Chance-creation biased": {
                "w1_attack_conv": 0.45,
                "w2_shot_accuracy": 0.30,
                "w3_shot_creation": 0.25,
            },
        },
        "kscore": {
            "Fitted (default)": {},
        },
    }
)


def spec_for(strategy: str, key: str) -> WeightSpec | None:
    """Look up one coefficient's spec, or None if it is not registered."""
    for spec in REGISTRY.get(strategy, ()):
        if spec.key == key:
            return spec
    return None


def strategy_names() -> tuple[str, ...]:
    return tuple(REGISTRY.keys())


def display_name_for(strategy_key: str) -> str:
    """Public name (Unrealised goals, K-Score, …). Falls back to the code key."""
    info = STRATEGY_INFO.get(strategy_key)
    return info.name if info else strategy_key.replace("_", " ")


def short_label_for(strategy_key: str) -> str:
    """Board-style short label (UrG, Δ10′, K, …)."""
    info = STRATEGY_INFO.get(strategy_key)
    return info.short if info else strategy_key
