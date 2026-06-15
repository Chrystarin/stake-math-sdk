"""Crimson Plinko coefficient tables (aligned with apps/plinko config)."""

import math

# row tier index (row_count - 8) -> slot multipliers
# Row tiers 8..20 map to indices 0..12. Tables match 14-row board (15 slots).

# Canonical board — same literal values as apps/plinko `BOARD_SLOT_MULTIPLIERS`.
# Center index 7 is the spin pocket (0× payout; meter fill only).
BOARD_SLOT_MULTIPLIERS = [100, 50, 20, 10, 2, 0.5, 0.2, 0, 0.2, 0.5, 2, 10, 20, 50, 100]

# Serialized on plinkoDrop.difficulty for RGS / published math compatibility.
DEFAULT_VARIANT_ID = 0

DEFAULT_SLOT_MULTIPLIERS = list(BOARD_SLOT_MULTIPLIERS)

COEFFICIENT_SETS: list[list[float]] = [list(DEFAULT_SLOT_MULTIPLIERS)] * 13

ROW_COUNT_OPTIONS = (10, 14, 20)
BALLS_PER_DROP_OPTIONS = (1, 10, 20, 50)

# Meter / feature (aligned with apps/plinko game-logic/constants.ts)
SPIN_METER_MAX = 10
BONUS_METER_MAX = 20

# Balls-per-drop tier scaling (apps/plinko METER_TIER_CONFIG).
METER_TIER_CONFIG: dict[int, dict[str, float]] = {
    1: {"start_ratio": 0.0, "max_ratio": 0.1},
    10: {"start_ratio": 0.0, "max_ratio": 1.0},
    20: {"start_ratio": 0.125, "max_ratio": 1.125},
    50: {"start_ratio": 0.25, "max_ratio": 1.25},
}


def meter_tier_config(balls_per_drop: int) -> dict[str, float]:
    return METER_TIER_CONFIG.get(int(balls_per_drop), METER_TIER_CONFIG[10])


def _js_round(value: float) -> int:
    """Match apps/plinko `Math.round` (not Python banker's `round`)."""
    return int(math.floor(value + 0.5))


def scaled_spin_meter_max(balls_per_drop: int) -> int:
    cfg = meter_tier_config(balls_per_drop)
    return max(1, _js_round(SPIN_METER_MAX * cfg["max_ratio"]))


def scaled_bonus_meter_max(balls_per_drop: int) -> int:
    cfg = meter_tier_config(balls_per_drop)
    return max(1, _js_round(BONUS_METER_MAX * cfg["max_ratio"]))


def spin_meter_strata_starts(balls_per_drop: int) -> tuple[int, int, int]:
    """Mid / high / near-full spin_meter_start values for distribution strata."""
    max_spin = scaled_spin_meter_max(balls_per_drop)
    mid = max(max_spin // 2, 1)
    near_full = max(max_spin - 1, 1)
    return mid, max(near_full - 1, 0), near_full


# Per-ball chance to award a bonus-meter coin peg hit (independent of pocket).
BONUS_PEG_HIT_PROB = 0.14


def row_tier_index(row_count: int) -> int:
    return max(0, min(row_count - 8, 12))


def coefficients_for(row_count: int) -> list[float]:
    tier = row_tier_index(row_count)
    return list(COEFFICIENT_SETS[tier])


def spin_slot_index(num_slots: int) -> int:
    return (num_slots - 1) // 2
