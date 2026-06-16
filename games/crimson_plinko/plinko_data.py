"""Crimson Plinko coefficient + feature tables (aligned with apps/plinko config).

This module is the single source of truth for the feature tunables that are also
exported to the front-end config (`run.py:write_plinko_fe_config`):
  - meter maxima + per-tier scaling
  - bonus-peg hit probability
  - free-spin wheel segments
  - bonus wheel entry-ball awards
  - bonus level-up ball table
"""

import math

# row tier index (row_count - 8) -> slot multipliers
# Row tiers 8..20 map to indices 0..12. Tables match 14-row board (15 slots).

# Canonical board — same literal values as apps/plinko `BOARD_SLOT_MULTIPLIERS`.
# Center index 7 is the spin pocket (0× payout; fills the free-spin meter only).
BOARD_SLOT_MULTIPLIERS = [100, 50, 20, 10, 2, 0.5, 0.2, 0, 0.2, 0.5, 2, 10, 20, 50, 100]

# Serialized on plinkoDrop.difficulty for RGS / published math compatibility.
DEFAULT_VARIANT_ID = 0

DEFAULT_SLOT_MULTIPLIERS = list(BOARD_SLOT_MULTIPLIERS)

COEFFICIENT_SETS: list[list[float]] = [list(DEFAULT_SLOT_MULTIPLIERS)] * 13

ROW_COUNT_OPTIONS = (10, 14, 20)
BALLS_PER_DROP_OPTIONS = (1, 10, 20, 50)

# RGS `/wallet/play` `mode` — one published LUT per tier (meta stratum matching is not reliable).
BET_MODE_BY_BALLS_PER_DROP: dict[int, str] = {
    1: "baseone",
    10: "baseten",
    20: "basetwenty",
    50: "basefifty",
}


def bet_mode_for_balls_per_drop(balls_per_drop: int) -> str:
    balls = int(balls_per_drop)
    return BET_MODE_BY_BALLS_PER_DROP.get(balls, "baseten")


def row_tier_index(row_count: int) -> int:
    return max(0, min(row_count - 8, 12))


def coefficients_for(row_count: int) -> list[float]:
    tier = row_tier_index(row_count)
    return list(COEFFICIENT_SETS[tier])


def spin_slot_index(num_slots: int) -> int:
    return (num_slots - 1) // 2


# ---------------------------------------------------------------------------
# Feature tunables (mirror apps/plinko game-logic/constants.ts).
# ---------------------------------------------------------------------------

# Base meter maxima at the 10-ball reference tier (apps/plinko METER_TIER_CONFIG).
SPIN_METER_MAX = 10
BONUS_METER_MAX = 20

# Balls-per-drop tier scaling for meter maxima (apps/plinko METER_TIER_CONFIG).
METER_TIER_CONFIG: dict[int, dict[str, float]] = {
    1: {"start_ratio": 0.0, "max_ratio": 1.0},
    10: {"start_ratio": 0.0, "max_ratio": 1.0},
    20: {"start_ratio": 0.0, "max_ratio": 1.0},
    50: {"start_ratio": 0.0, "max_ratio": 1.0},
}

# Per-ball chance to award a bonus-meter coin-peg hit (independent of the landing pocket).
BONUS_PEG_HIT_PROB = 0.14

# Free-spin wheel segments (label list; uniform weight placeholders — tune RTP later).
FREE_SPIN_SEGMENTS: list[str] = ["2X", "0.5X", "1X", "5X", "10X", "BONUS", "20X", "15X"]

# Bonus wheel entry free-ball awards (uniform weight placeholders — tune RTP later).
BONUS_WHEEL_FREE_BALLS: list[int] = [100, 20, 50, 50, 50, 80, 20, 20]

# Additional free balls granted on each bonus level-up (level reached -> extra balls).
# Level 1 entry balls come from the bonus wheel (BONUS_WHEEL_FREE_BALLS); levels 2..MAX
# add these when the bonus meter re-fills during the round. Edit here to retune the ladder
# (mirror the same table in apps/plinko game-logic/constants.ts `BONUS_LEVEL_BALLS`).
BONUS_LEVEL_BALLS: dict[int, int] = {
    2: 20,
    3: 30,
    4: 50,
    5: 75,
    6: 100,
    7: 150,
    8: 200,
    9: 300,
}

# Highest reachable bonus level (length of the ladder including the level-1 entry).
MAX_BONUS_LEVEL = 9


def bonus_level_balls(level: int) -> int:
    """Additional free balls granted when reaching `level` (0 outside the ladder)."""
    return int(BONUS_LEVEL_BALLS.get(int(level), 0))


def meter_tier_config(balls_per_drop: int) -> dict[str, float]:
    return METER_TIER_CONFIG.get(int(balls_per_drop), METER_TIER_CONFIG[10])


def _js_round(value: float) -> int:
    """Match apps/plinko `Math.round` (round half up, not Python banker's `round`)."""
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
    high = max(near_full - 1, 0)
    return mid, high, near_full


def bonus_meter_strata_starts(balls_per_drop: int) -> tuple[int, int, int]:
    """Mid / high / near-full bonus_meter_start values for distribution strata."""
    max_bonus = scaled_bonus_meter_max(balls_per_drop)
    mid = max(max_bonus // 2, 1)
    near_full = max(max_bonus - 1, 1)
    high = max((max_bonus * 3) // 4, mid)
    return mid, high, near_full
