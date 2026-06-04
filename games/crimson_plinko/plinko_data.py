"""Crimson Plinko coefficient tables (aligned with apps/plinko config)."""

# row tier index (row_count - 8) -> slot multipliers
# Row tiers 8..20 map to indices 0..12. Tables match 14-row crimson board (13 slots).

# Default board — calibrated for sim; raw drop win is normalized to
# payoutMultiplier with base mode cost 1.0 (see game_override.update_final_win).
_DEFAULT_14_BASE = [18, 3.2, 1.6, 1.1, 1, 0.5, 0.3, 0.5, 1, 1.1, 1.6, 3.2, 18]
_DEFAULT_MC_AVG_RAW_DROP_WIN = 6.987  # E[sum(stake*mult)] per drop, stake_per_ball=1
_TARGET_RTP = 0.97
_DEFAULT_BALLS_PER_DROP = 10.0
# Target E[payoutMultiplier] = RTP * cost = 0.97 after dividing raw win by balls*stake.
_DEFAULT_RTP_SCALE = (_TARGET_RTP * _DEFAULT_BALLS_PER_DROP) / _DEFAULT_MC_AVG_RAW_DROP_WIN

# Serialized on plinkoDrop.difficulty for RGS / published math compatibility.
DEFAULT_VARIANT_ID = 0


def _scale_coefficients(coefficients: list[float], scale: float) -> list[float]:
    return [round(c * scale, 2) for c in coefficients]


DEFAULT_SLOT_MULTIPLIERS = _scale_coefficients(_DEFAULT_14_BASE, _DEFAULT_RTP_SCALE)

COEFFICIENT_SETS: list[list[float]] = [list(DEFAULT_SLOT_MULTIPLIERS)] * 13

ROW_COUNT_OPTIONS = (10, 14, 20)
BALLS_PER_DROP_OPTIONS = (10, 20, 50)

# Meter / feature (aligned with apps/plinko game-logic/constants.ts)
SPIN_METER_MAX = 10
BONUS_METER_MAX = 20
# Per-ball chance to award a bonus-meter coin peg hit (independent of pocket).
BONUS_PEG_HIT_PROB = 0.14


def row_tier_index(row_count: int) -> int:
    return max(0, min(row_count - 8, 12))


def coefficients_for(row_count: int) -> list[float]:
    tier = row_tier_index(row_count)
    return list(COEFFICIENT_SETS[tier])


def spin_slot_index(num_slots: int) -> int:
    return (num_slots - 1) // 2
