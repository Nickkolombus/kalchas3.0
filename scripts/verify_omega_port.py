"""Differential check: does the 3.0 Omega match 2.2 exactly?

Omega is a second derivative of two pressure series, so it is the most
sensitive port so far: an error of one minute in either series, or a rounding
difference, moves the acceleration and can flip a trigger. This compares both
series-derived slopes, the angles, the level, the state label and the decision.

2.2's settings loader reads the live admin store, so it is pinned to the
defaults here to make the comparison deterministic.

    uv run python scripts/verify_omega_port.py [path-to-kalchas2.2]
"""

from __future__ import annotations

import asyncio
import itertools
import random
import sys
from pathlib import Path
from unittest.mock import MagicMock

from kalchas_core.match import MatchTimeline, Side
from kalchas_core.strategies.omega import OmegaSettings, evaluate

DEFAULT_LEGACY_ROOT = Path(r"c:\Users\Casual Use\Github Projects\kalchas2.2")
TOLERANCE = 1e-9

STATS = ("shots_on_target", "shots_off_target", "corners", "dangerous_attacks")


# The default acceleration threshold is strict, so a grid run only on defaults
# barely exercises the trigger path. The looser pair mirrors 2.2's "Earlier
# signals" preset, and the strict pair its "Confirmed surges only".
SETTINGS_VARIANTS: list[tuple[str, dict[str, float]]] = [
    ("defaults", {}),
    ("earlier", {"min_accel": 4.0, "min_baseline_slope": -0.5, "pi_level_min": 0.0}),
    ("loose", {"min_accel": 0.5, "min_baseline_slope": -5.0, "pi_level_min": 0.0}),
    ("strict", {"min_accel": 8.0, "min_baseline_slope": 1.0, "pi_level_min": 45.0}),
    (
        "wide-windows",
        {"fast_window": 8.0, "slow_window": 20.0, "deriv_window": 5.0, "k_scale": 25.0},
    ),
]


def load_legacy(root: Path):
    """Load 2.2's Omega formula with its settings loader pinned to defaults."""
    formula_path = root / "strategies" / "strategy_006_omega" / "formula.py"
    if not formula_path.exists():
        raise SystemExit(f"2.2 checkout not found under {root}")

    for name in ("psycopg2", "psycopg2.extras", "psycopg2.pool", "psycopg2.extensions"):
        sys.modules.setdefault(name, MagicMock())

    sys.path.insert(0, str(root))
    try:
        import strategies.strategy_006_omega.formula as legacy  # type: ignore
    except Exception as exc:
        raise SystemExit(f"could not import 2.2 Omega: {exc!r}") from exc

    # classify_omega_state resolves flat_band from the admin store when not
    # passed one; pin it so the state label is comparable.
    original_classify = legacy.classify_omega_state
    legacy.classify_omega_state = lambda theta, alpha, flat_band=None: original_classify(
        theta, alpha, legacy._FLAT_BAND_DEG if flat_band is None else flat_band
    )

    return legacy


def build_history(
    current_minute: int,
    seed: int,
    *,
    shape: str,
    drop_rate: float,
) -> dict:
    """Cumulative history whose activity follows a chosen shape over time."""
    rng = random.Random(seed)  # noqa: S311 - fixture data, deliberately reproducible
    history: dict = {}
    totals = {(stat, side): 0 for stat in STATS for side in ("home", "away")}

    for minute in range(1, current_minute + 1):
        progress = minute / max(1, current_minute)

        if shape == "surging":
            # Quiet, then an accelerating burst: what Omega exists to catch.
            home_rate = 0.2 + 3.0 * progress**3
        elif shape == "fading":
            home_rate = 3.0 * (1.0 - progress) ** 2
        elif shape == "steady":
            home_rate = 1.2
        elif shape == "spiky":
            home_rate = 3.5 if (minute // 4) % 3 == 0 else 0.2
        else:
            home_rate = 0.0

        for stat in STATS:
            scale = 3.0 if stat == "dangerous_attacks" else 1.0
            totals[(stat, "home")] += int(rng.random() < home_rate / 2) * max(
                1, int(home_rate * scale)
            )
            totals[(stat, "away")] += int(rng.random() < 0.4) * max(1, int(scale))

        if minute < current_minute and rng.random() < drop_rate:
            continue

        history[str(minute)] = {
            stat: {side: totals[(stat, side)] for side in ("home", "away")} for stat in STATS
        }
    return history


def pin_settings(legacy, overrides: dict[str, float]) -> OmegaSettings:
    """Pin 2.2's loader to a fixed configuration and mirror it in 3.0.

    Both sides run the same bounding rules, so this also checks that
    `OmegaSettings.from_stored` reproduces 2.2's clamping order.
    """
    stored = {
        "min_accel": legacy.DEFAULT_MIN_ACCEL,
        "min_baseline_slope": legacy.DEFAULT_MIN_BASELINE_SLOPE,
        "pi_level_min": legacy.DEFAULT_PI_LEVEL_MIN,
        "k_scale": legacy.DEFAULT_K_SCALE,
        "fast_window": float(legacy.DEFAULT_FAST_WINDOW),
        "slow_window": float(legacy.DEFAULT_SLOW_WINDOW),
        "deriv_window": float(legacy.DEFAULT_DERIV_WINDOW),
        **overrides,
    }

    legacy_settings = legacy.OmegaSettings(
        min_accel=stored["min_accel"],
        min_baseline_slope=stored["min_baseline_slope"],
        pi_level_min=stored["pi_level_min"],
        k_scale=stored["k_scale"],
        fast_window=int(stored["fast_window"]),
        slow_window=int(stored["slow_window"]),
        deriv_window=int(stored["deriv_window"]),
    )
    legacy._load_omega_settings = lambda: legacy_settings

    return OmegaSettings.from_stored(
        min_acceleration=stored["min_accel"],
        min_baseline_slope=stored["min_baseline_slope"],
        min_level=stored["pi_level_min"],
        angle_scale=stored["k_scale"],
        fast_window=int(stored["fast_window"]),
        slow_window=int(stored["slow_window"]),
        derivative_window=int(stored["deriv_window"]),
    )


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LEGACY_ROOT
    legacy = load_legacy(root)

    minutes = [12, 13, 14, 20, 30, 44, 46, 50, 52, 55, 65, 75, 90, 96, 98, 112]
    shapes = ["surging", "fading", "steady", "spiky", "silent"]
    drop_rates = [0.0, 0.2]

    checked = 0
    readings = 0
    triggered = 0
    divergences: list[str] = []

    grid = itertools.product(minutes, shapes, drop_rates, SETTINGS_VARIANTS)

    for seed, (minute, shape, drop_rate, (variant, overrides)) in enumerate(grid):
        settings = pin_settings(legacy, overrides)
        for repeat in range(2):
            history = build_history(minute, seed * 50 + repeat, shape=shape, drop_rate=drop_rate)
            match_data = {
                "match_id": f"verify-{seed}-{repeat}",
                "current_minute": minute,
                "minute_by_minute": history,
                "home_team": "H",
                "away_team": "A",
                "home_score": 0,
                "away_score": 0,
            }

            legacy_snapshot = legacy.get_omega_snapshot(dict(match_data))
            legacy_alert = asyncio.run(legacy.calculate(dict(match_data)))
            result = evaluate(MatchTimeline.from_raw(history, minute), settings=settings)

            checked += 1
            context = (
                f"(minute={minute} {shape} drop={drop_rate} "
                f"settings={variant} seed={seed}-{repeat})"
            )

            if (legacy_snapshot is None) != (result is None):
                divergences.append(
                    f"reading: 2.2={legacy_snapshot is not None} 3.0={result is not None} {context}"
                )
                continue
            if result is None or legacy_snapshot is None:
                continue

            readings += 1

            if legacy_snapshot["minute"] != result.minute:
                divergences.append(
                    f"minute: 2.2={legacy_snapshot['minute']} 3.0={result.minute} {context}"
                )
                continue

            for side in (Side.HOME, Side.AWAY):
                legacy_block = legacy_snapshot.get(side.value) or {}
                reading = result.team(side)
                if not legacy_block:
                    if reading is not None:
                        divergences.append(f"{side.value}: 2.2 empty, 3.0 present {context}")
                    continue
                if reading is None:
                    divergences.append(f"{side.value}: 2.2 present, 3.0 None {context}")
                    continue

                for label, old, new in (
                    ("accel", legacy_block["accel"], reading.acceleration),
                    ("baseline", legacy_block["baseline_slope"], reading.baseline_slope),
                    ("level", legacy_block["level"], reading.level),
                    ("theta", legacy_block["theta"], reading.theta),
                    ("alpha", legacy_block["alpha"], reading.alpha),
                    ("d5_prime", legacy_block["d5_prime"], reading.fast_slope),
                    ("d5", legacy_block["d5"], reading.fast_level),
                    ("state", legacy_block["state"], reading.state.value),
                    ("triggered", legacy_block["triggered"], reading.meets(settings)),
                ):
                    differs = (
                        abs(float(old) - float(new)) > TOLERANCE
                        if isinstance(old, (int, float)) and not isinstance(old, bool)
                        else old != new
                    )
                    if differs:
                        divergences.append(
                            f"{side.value}.{label}: 2.2={old!r} 3.0={new!r} {context}"
                        )

            legacy_team = legacy_alert.get("team") if legacy_alert else None
            new_side = result.triggering_team
            new_team = new_side.value if new_side else None
            if legacy_team:
                triggered += 1
            if legacy_team != new_team:
                divergences.append(f"trigger: 2.2={legacy_team!r} 3.0={new_team!r} {context}")
            elif (
                legacy_alert
                and abs(float(legacy_alert["value"]) - result.trigger_value) > TOLERANCE
            ):
                divergences.append(
                    f"value: 2.2={legacy_alert['value']!r} 3.0={result.trigger_value!r} {context}"
                )

    print(f"compared {checked} timelines, {readings} yielding a reading, {triggered} triggering")
    if divergences:
        print(f"\n{len(divergences)} DIVERGENCES\n")
        for line in divergences[:25]:
            print(f"  {line}")
        return 1

    print("identical across the whole grid (both series, angles, state and decision)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
