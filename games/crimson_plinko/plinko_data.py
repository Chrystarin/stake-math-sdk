"""Crimson Plinko coefficient tables (aligned with apps/plinko config)."""

# row tier index (row_count - 8) -> slot multipliers
# Row tiers 8..20 map to indices 0..12. Tables match 14-row board (15 slots).

# Canonical board — same literal values as apps/plinko `BOARD_SLOT_MULTIPLIERS`.
# Center index 7 is the spin pocket (0× payout).
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
