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

    def clamp(self, value: float) -> float:
        """Constrain a proposed value to this coefficient's registered bounds."""
        return max(self.min_val, min(self.max_val, float(value)))


@dataclass(frozen=True, slots=True)
class StrategyInfo:
    """Display copy for a strategy's settings panel."""

    slot: str
    name: str
    equation: str
    blurb: str


STRATEGY_INFO: Mapping[str, StrategyInfo] = MappingProxyType(
    {
        "rule_of_three": StrategyInfo(
            slot="1",
            name="Rule of Three",
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
            name="Delta Goal (5m Pressure→Goal)",
            equation=(
                "Energy = weight_sot·ΔSOT + weight_sofft·ΔSOFFT + weight_corners·ΔCorners"
                " + weight_da·ΔDA + weight_possession·PossBonus\n"
                "Threat(0..20) ≈ 20·(threat_w_p·P_goal(5m) + threat_w_ps·PressureScore"
                " + threat_w_l·Lift + PatternBonuses)"
            ),
            blurb=(
                "Estimates goal probability in the next 5 minutes from normalised "
                "shot/corner/dangerous-attack rates versus league baselines. "
                "Combines a Poisson likelihood, a pressure-driven probability, and "
                "pattern bonuses (sustained attacks, corner sequences, shot bursts) "
                "into a 0-20 threat score. Alerts when the score crosses the "
                "dynamic threshold."
            ),
        ),
        "delta_5min": StrategyInfo(
            slot="4",
            name="Delta 5min Pressure",
            equation=(
                "Δ5 = (SOT_Δ5 · sot_weight) + (DA_Δ5 · da_weight)\n"
                "Gate: DA_Δ5 ≥ min_da_delta and (SOT_Δ5 ≥ min_sot_delta"
                " or DA_Δ5 ≥ fallback_da_delta)"
            ),
            blurb=(
                "Short-horizon pressure spike detector. Takes deltas over the last "
                "5 minutes of shots on target and dangerous attacks, multiplies by "
                "weights, and fires when the corroboration gate (minimum DA + SOT "
                "activity) is met. Complements the Pressure Index by catching "
                "rapid surges the 10-minute window smooths out."
            ),
        ),
        "npei": StrategyInfo(
            slot="5",
            name="NPEI (Net Pressure Efficiency)",
            equation=(
                "R1=ΔD/ΔA, R2=ΔT/ΔS, R3=ΔS/ΔA (5m window)\n"
                "NPEI = 100·(w1·R1 + w2·R2 + w3·R3) with mins: ΔA≥min_attacks, ΔS≥min_shots"
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
            equation=(
                "ω = D5' − D10'  (PI/min),  baseline = D10',  level = PI₁₀\n"
                "Trigger (per team): ω > min_accel AND baseline > min_baseline_slope"
                " AND PI₁₀ ≥ pi_level_min\n"
                "θ, α = display angles via atan(·/k_scale)"
            ),
            blurb=(
                "Per-team pressure acceleration: fast-window momentum minus slow-window "
                "momentum, gated by a rising baseline and minimum PI level. θ/α are "
                "display-only; the engine fires on linear PI/min thresholds."
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
                13.0,
                1.0,
                30.0,
                1.0,
                "Points per sqrt(shot-on-target Δ) — largest contributor.",
            ),
            WeightSpec(
                "sofft_points",
                "Shot off target points",
                8.0,
                0.0,
                20.0,
                1.0,
                "Points per sqrt(shot-off-target Δ).",
            ),
            WeightSpec(
                "corner_points", "Corner points", 5.0, 0.0, 15.0, 1.0, "Points per sqrt(corner Δ)."
            ),
            WeightSpec(
                "da_points",
                "Dangerous attack points",
                2.0,
                0.0,
                10.0,
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
        "delta_goal": _specs(
            WeightSpec(
                "weight_sot",
                "Shot on target weight",
                1.0,
                0.1,
                3.0,
                0.1,
                "Adaptive weight for SOT in the energy score (learning layer tunes around this).",
            ),
            WeightSpec(
                "weight_sofft",
                "Shot off target weight",
                0.6,
                0.0,
                2.0,
                0.1,
                "Adaptive weight for shots off target.",
            ),
            WeightSpec(
                "weight_corners",
                "Corner weight",
                0.7,
                0.0,
                2.0,
                0.1,
                "Adaptive weight for corners.",
            ),
            WeightSpec(
                "weight_da",
                "Dangerous attack weight",
                0.25,
                0.0,
                1.5,
                0.05,
                "Adaptive weight for dangerous attacks.",
            ),
            WeightSpec(
                "weight_possession",
                "Possession bonus weight",
                0.1,
                0.0,
                0.5,
                0.01,
                "Extra lift when possession favours the attacking team.",
            ),
            WeightSpec(
                "threat_w_p",
                "Threat weight: P (probability)",
                0.4,
                0.1,
                0.8,
                0.05,
                "Share of the composite score from the 5-min goal probability.",
            ),
            WeightSpec(
                "threat_w_ps",
                "Threat weight: PS (pressure score)",
                0.25,
                0.05,
                0.6,
                0.05,
                "Share of the composite score from sustained pressure.",
            ),
            WeightSpec(
                "threat_w_l",
                "Threat weight: L (lift)",
                0.15,
                0.0,
                0.5,
                0.05,
                "Share of the composite score from lift over baseline.",
            ),
            WeightSpec(
                "pattern_sustained",
                "Pattern bonus: sustained attack",
                0.05,
                0.0,
                0.2,
                0.01,
                "Added when three consecutive windows show consistent activity.",
            ),
            WeightSpec(
                "pattern_corner_seq",
                "Pattern bonus: corner sequence",
                0.03,
                0.0,
                0.2,
                0.01,
                "Added when multiple corners fire inside 10 minutes.",
            ),
            WeightSpec(
                "pattern_shot_burst",
                "Pattern bonus: shot burst",
                0.04,
                0.0,
                0.2,
                0.01,
                "Added when shots cluster inside the most recent window.",
            ),
            WeightSpec(
                "time_urgency_mult",
                "Late-game urgency multiplier",
                0.3,
                0.0,
                1.0,
                0.05,
                "Extra probability boost proportional to minute × scoreline-closeness.",
            ),
            WeightSpec(
                "alert_threshold",
                "Alert threshold (0-20)",
                18.5,
                5.0,
                20.0,
                0.5,
                "Fire alert when threat score reaches this level.",
            ),
        ),
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
            WeightSpec(
                "da_weight",
                "DA Δ weight",
                1.0,
                0.0,
                3.0,
                0.5,
                "Multiplier on 5-minute dangerous-attack delta "
                "(falls back to SOFFT if DA missing).",
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
                "Min accel ω (PI/min)",
                5.46,
                0.5,
                25.0,
                0.1,
                "Fast-minus-slow PI slope required to fire (per team).",
            ),
            WeightSpec(
                "min_baseline_slope",
                "Min baseline slope (PI/min)",
                0.0,
                -5.0,
                10.0,
                0.1,
                "Slow-window PI slope floor — baseline must be rising.",
            ),
            WeightSpec(
                "pi_level_min",
                "Min PI₁₀ level",
                0.0,
                0.0,
                80.0,
                1.0,
                "Slow-window pressure level floor (0–100) per team.",
            ),
            WeightSpec(
                "k_scale",
                "Display k (arctan scale)",
                15.0,
                1.0,
                50.0,
                0.5,
                "Maps PI/min to θ/α degrees for display only.",
            ),
            WeightSpec(
                "fast_window",
                "Fast PI window (min)",
                5.0,
                2.0,
                15.0,
                1.0,
                "Window used for the fast Pressure Index line.",
            ),
            WeightSpec(
                "slow_window",
                "Slow PI window (min)",
                10.0,
                5.0,
                25.0,
                1.0,
                "Window used for the slow Pressure Index baseline.",
            ),
            WeightSpec(
                "deriv_window",
                "Derivative window (min)",
                3.0,
                1.0,
                8.0,
                1.0,
                "Finite-difference width for computing slopes — wider = less noise.",
            ),
            WeightSpec(
                "flat_band",
                "Flat-state band (degrees)",
                5.0,
                0.0,
                20.0,
                1.0,
                "|θ| and |α| below this both classify as 'flat' (display).",
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
                "sot_points": 16.0,
                "sofft_points": 10.0,
                "corner_points": 4.0,
                "da_points": 1.5,
            },
            "DA/corners emphasized": {
                "sot_points": 11.0,
                "sofft_points": 7.0,
                "corner_points": 7.0,
                "da_points": 3.5,
            },
        },
        "delta_goal": {
            "Balanced (default)": {},
            "SOT-driven": {
                "weight_sot": 1.4,
                "weight_sofft": 0.4,
                "weight_corners": 0.5,
                "weight_da": 0.2,
            },
            "Pattern-sensitive": {
                "pattern_sustained": 0.10,
                "pattern_corner_seq": 0.07,
                "pattern_shot_burst": 0.08,
            },
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
            "Balanced (default)": {},
            "Earlier signals": {
                "min_accel": 4.0,
                "min_baseline_slope": -0.5,
                "pi_level_min": 0.0,
            },
            "Confirmed surges only": {
                "min_accel": 8.0,
                "min_baseline_slope": 1.0,
                "pi_level_min": 45.0,
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
