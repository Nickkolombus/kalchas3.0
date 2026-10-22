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
                "alone). No live match stats: attach Δ5′/Δ10′/UrG/Omega as extra "
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
        "omega": StrategyInfo(
            slot="6",
            name="Omega (Ω Surge)",
            short="Ω",
            equation=(
                "ω = recent rate − rate in the period just before it (not overlapping)\n"
                "Trigger (per team): ω > min_accel AND baseline > min_baseline_slope"
                " AND PI₁₀ ≥ pi_level_min AND shots_fast ≥ min_shots"
            ),
            blurb=(
                "Per-team pressure acceleration: how much busier the last few minutes "
                "are than the period right before them, gated by a rising trend, a "
                "pressure floor, and at least one shot. Tune the gates below on this "
                "tab — the Fire threshold field on the Thresholds tab doesn't apply "
                "to Omega. θ/α (shown on the board and in alerts) are the same gates "
                "expressed as degrees; default scale keeps 35°+ rare and fire at 30°."
            ),
        ),
        "kscore": StrategyInfo(
            slot="7",
            name="K-Score",
            short="K",
            equation=(
                "votes: momentum=σ(Δ5/ms), pressure=PI/100, rule3=(RO3+0.3)/1.3,\n"
                "       omega=σ(accel/0.8)·(0.45+0.55·σ(base/0.4))·clamp(level/55,0.2,1)\n"
                "logit = bias + Σ trust_i · (2·vote_i − 1) + context\n"
                "K = round(100 · σ(logit) · ΦI)   ΦI = floor+(1−floor)·NPEI/100"
            ),
            blurb=(
                "Meta-strategy: four consultant strategies vote in [0,1], a weighted "
                "logit blend produces a probability, and NPEI scales it as a focus "
                "multiplier (ΦI). Optional context terms adjust for red cards, late "
                "trailing and kickoff odds. Outputs a 0–100 score per team and a "
                "match-level OR of both."
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
            WeightSpec(
                "time_mult_0_30",
                "Time multiplier (≤30')",
                0.90,
                0.5,
                1.5,
                0.05,
                "UG multiplier in the opening 30 minutes.",
            ),
            WeightSpec(
                "time_mult_31_60",
                "Time multiplier (31-60')",
                1.00,
                0.5,
                1.5,
                0.05,
                "UG multiplier in the 31-60' window.",
            ),
            WeightSpec(
                "time_mult_61_75",
                "Time multiplier (61-75')",
                1.10,
                0.5,
                1.5,
                0.05,
                "UG multiplier in the 61-75' window.",
            ),
            WeightSpec(
                "time_mult_75_plus",
                "Time multiplier (>75')",
                1.20,
                0.5,
                2.0,
                0.05,
                "UG multiplier in the final 15 minutes — late game goals matter most.",
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
            WeightSpec(
                "time_mult_0_30",
                "Time multiplier (≤30')",
                0.90,
                0.5,
                1.5,
                0.05,
                "Pressure multiplier in the opening 30 minutes.",
            ),
            WeightSpec(
                "time_mult_31_60",
                "Time multiplier (31-60')",
                1.00,
                0.5,
                1.5,
                0.05,
                "Pressure multiplier in the 31-60' window.",
            ),
            WeightSpec(
                "time_mult_61_75",
                "Time multiplier (61-75')",
                1.10,
                0.5,
                1.5,
                0.05,
                "Pressure multiplier in the 61-75' window.",
            ),
            WeightSpec(
                "time_mult_75_plus",
                "Time multiplier (>75')",
                1.20,
                0.5,
                2.0,
                0.05,
                "Pressure multiplier in the final 15 minutes.",
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
        "omega": _specs(
            WeightSpec(
                "min_accel",
                "Min acceleration ω",
                0.866,
                0.0,
                5.0,
                0.01,
                "How much faster pressure has to be building right now than it was "
                "in the period just before, before Omega fires. Default 0.866 is "
                "about 30° on the board. Raise to ignore weak tilts; lower to catch "
                "earlier surges.",
                "0.866 (~30°)",
            ),
            WeightSpec(
                "min_baseline_slope",
                "Min baseline slope",
                0.08,
                -1.0,
                2.0,
                0.01,
                "Requires the period just before the surge to already be trending "
                "upward, so a burst with nothing behind it reads as a spike, not a "
                "confirmed surge. Default 0.08 needs a real climb; negative allows "
                "earlier, noisier calls.",
                "0.08 (confirmed climb)",
            ),
            WeightSpec(
                "pi_level_min",
                "Min PI₁₀ level",
                40.0,
                0.0,
                80.0,
                1.0,
                "Floor on how much real pressure (0–100, same scale as Δ10′) already "
                "exists before Omega can fire. Default 40. 0 removes the floor — "
                "a surge from nothing would still qualify.",
                "40",
            ),
            WeightSpec(
                "min_shots",
                "Min shots in fast window",
                1.0,
                0.0,
                5.0,
                1.0,
                "Shots on or off target required in the recent window. Default 1 "
                "stops Omega firing on dangerous attacks alone, the noisiest stat "
                "the feed carries. 0 turns this gate off.",
                "1",
            ),
            WeightSpec(
                "k_scale",
                "Display k (arctan scale)",
                1.5,
                0.1,
                50.0,
                0.1,
                "Only changes how the board and alerts display the angle (θ/α) — "
                "not whether Omega fires (that's min_accel above). Larger values "
                "flatten the scale so 35°+ stays rare. Default 1.5.",
                "1.5",
            ),
            WeightSpec(
                "fast_window",
                "Fast PI window (min)",
                5.0,
                2.0,
                15.0,
                1.0,
                "Minutes of Pressure Index used for the recent reading. Shorter is "
                "twitchier; longer smooths noise. Must stay below the slow window.",
                "5",
            ),
            WeightSpec(
                "slow_window",
                "Slow PI window (min)",
                10.0,
                5.0,
                25.0,
                1.0,
                "Minutes of Pressure Index used for the baseline — read for the "
                "period immediately before the fast window, not overlapping it. "
                "The match is too young to evaluate until fast_window + slow_window "
                "+ deriv_window minutes have elapsed.",
                "10",
            ),
            WeightSpec(
                "deriv_window",
                "Derivative window (min)",
                3.0,
                1.0,
                8.0,
                1.0,
                "Finite-difference width when computing slopes. Wider = less noise, "
                "slower to react.",
                "3",
            ),
            WeightSpec(
                "flat_band",
                "Flat-state band (degrees)",
                5.0,
                0.0,
                20.0,
                1.0,
                "Display/classify only — not a fire gate. |θ| and |α| below this "
                "are labelled 'flat' on diagnostics.",
                "5°",
            ),
        ),
        "kscore": _specs(
            WeightSpec(
                "trust_momentum",
                "Trust: Δ5min (momentum)",
                1.2,
                0.0,
                3.0,
                0.1,
                "Logit weight on the Delta 5min consultant vote.",
            ),
            WeightSpec(
                "trust_pressure",
                "Trust: Pressure Index",
                0.7,
                0.0,
                3.0,
                0.1,
                "Logit weight on the Pressure Index consultant vote.",
            ),
            WeightSpec(
                "trust_rule3",
                "Trust: Unrealised goals",
                0.8,
                0.0,
                3.0,
                0.1,
                "Logit weight on the Unrealised goals consultant vote.",
            ),
            WeightSpec(
                "trust_omega",
                "Trust: Omega",
                0.4,
                0.0,
                3.0,
                0.1,
                "Logit weight on the Omega consultant vote.",
            ),
            WeightSpec(
                "phi_floor",
                "ΦI focus floor",
                0.2,
                0.0,
                1.0,
                0.05,
                "Minimum focus multiplier when NPEI is zero.",
            ),
            WeightSpec(
                "bias",
                "Logit bias",
                -1.0,
                -5.0,
                5.0,
                0.1,
                "Constant shift applied before the sigmoid.",
            ),
            WeightSpec(
                "momentum_scale",
                "Δ5 → vote scale",
                8.0,
                1.0,
                30.0,
                0.5,
                "Divisor in σ(Δ5 / scale) for the momentum vote.",
            ),
            WeightSpec(
                "ctx_red_card",
                "Context: red-card penalty",
                0.4,
                0.0,
                1.0,
                0.05,
                "Logit subtracted per red card (capped at 2).",
            ),
            WeightSpec(
                "ctx_ko_prior",
                "Context: kickoff-odds prior",
                0.25,
                0.0,
                1.0,
                0.05,
                "Logit shift from normalised kickoff implied probabilities.",
            ),
            WeightSpec(
                "ctx_trailing",
                "Context: late-trailing boost",
                0.15,
                0.0,
                0.5,
                0.05,
                "Logit added when trailing after ctx_late_minute.",
            ),
            WeightSpec(
                "ctx_late_minute",
                "Context: late-game start",
                70.0,
                60.0,
                90.0,
                1.0,
                "Minute from which the trailing boost begins to ramp.",
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
            "Late-game bias": {
                "time_mult_0_30": 0.85,
                "time_mult_31_60": 1.00,
                "time_mult_61_75": 1.15,
                "time_mult_75_plus": 1.35,
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
        "omega": {
            "Default (~30°)": {},
            "Sensitive": {
                "min_accel": 0.546,
                "min_baseline_slope": 0.0,
                "pi_level_min": 0.0,
                "min_shots": 0.0,
            },
            "Confirmed surges only": {
                "min_accel": 0.866,
                "min_baseline_slope": 0.05,
                "pi_level_min": 45.0,
                "min_shots": 1.0,
            },
            "Quiet / picky": {
                "min_accel": 1.05,
                "min_baseline_slope": 0.10,
                "pi_level_min": 55.0,
                "min_shots": 2.0,
            },
        },
        "kscore": {
            "Balanced (default)": {},
            "Momentum-led": {
                "trust_momentum": 1.8,
                "trust_pressure": 0.5,
                "trust_omega": 0.3,
            },
            "Context-aware": {
                "ctx_red_card": 0.6,
                "ctx_trailing": 0.25,
                "ctx_ko_prior": 0.4,
            },
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
