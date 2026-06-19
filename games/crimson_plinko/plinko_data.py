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
# The BONUS is a SEPARATE mode (bonus<tier>, deterministic auto-fire), NOT folded into the base, so the
# base modes are board-only again (+ the rare in-drop free spin). With a 14-row Galton distribution the
# per-ball board EV is ~0.957. NOTE for the ±0.5% cross-mode band: baseone is board-only (no free spin),
# the others get a small free-spin add — keep that add tiny/uniform (SPIN_METER_TIER) or trim the board
# a touch so all 8 modes cluster. Mirror in apps/plinko game-logic/boardMultipliers.ts.
BOARD_SLOT_MULTIPLIERS = [100, 40, 15, 8, 1.5, 0.4, 0.2, 0, 0.2, 0.4, 1.5, 8, 15, 40, 100]

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


# BONUS = a dedicated trigger mode per balls-per-drop tier (June 2026 — Option #1: deterministic +
# normal-bet cost). The client auto-fires `bonus<tier>` when the bonus meter fills (RGS honors `mode`),
# so it triggers exactly when the meter is full with betting locked until then. CRITICAL: the mode COST
# = the TIER COST (1/10/20/50), the SAME as the player's normal bet — so the trigger deducts exactly one
# normal bet, NOT 49×. To stay compliant at that cost (RGS requires cost ≥ 1 with an operator edge), the
# bonus payout is SIZED so the mode averages ~TARGET_RTP of its cost: avg free balls ≈ tier balls (a
# "free re-drop"), so payout ≈ balls × board_EV(0.957) ≈ cost × 0.957 → RTP ≈ TARGET_RTP. (The big 47×
# jackpot is gone — it can't cost only one normal bet without operator loss, which Stake blocks.)
BONUS_MODE_BY_BALLS: dict[int, str] = {
    1: "bonusone",
    10: "bonusten",
    20: "bonustwenty",
    50: "bonusfifty",
}


def bonus_mode_for_balls(balls_per_drop: int) -> str:
    return BONUS_MODE_BY_BALLS.get(int(balls_per_drop), "bonusten")


def all_trigger_mode_names() -> list[str]:
    return list(BONUS_MODE_BY_BALLS.values())


# Declared RTP for the Stake Engine math summary. Base modes ≈ board EV (+ the rare in-drop free spin);
# bonus modes are SIZED to ≈ this at their tier cost. Every mode should cluster within ±0.5%.
TARGET_RTP = 0.957


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

# Balls-per-drop tier scaling for the BONUS meter (SESSION meter; apps/plinko METER_TIER_CONFIG).
# `start_ratio` is the per-tier value the meter resets to when the bonus triggers (and the value a
# fresh tier starts at): 0 on 1/10-ball, 1/8 on 20-ball, 1/4 on 50-ball — higher tiers start partially
# filled so the bonus fires more often there. `max_ratio` stays 1.0 (max is 20 on every tier). This is
# purely a CLIENT seeding concern (the client owns the session meter and remaps book values as deltas),
# but is mirrored here so the two tables stay in sync. The spin meter uses SPIN_METER_TIER below.
METER_TIER_CONFIG: dict[int, dict[str, float]] = {
    1: {"start_ratio": 0.0, "max_ratio": 1.0},
    10: {"start_ratio": 0.0, "max_ratio": 1.0},
    20: {"start_ratio": 0.125, "max_ratio": 1.0},
    50: {"start_ratio": 0.25, "max_ratio": 1.0},
}

# Per-drop FREE-SPIN meter, per balls-per-drop tier. The meter resets every round to
# `start_ratio × max` (NO cross-bet carry) and fires the free spin IN-DROP when it reaches `max`
# within the round. `max` scales UP with ball count so the fire rate stays rare enough that the
# in-drop free spin (which pays bet × wheel, mean ~12.5× a ball's stake incl. the BONUS chain)
# keeps every tier's RTP add < ~0.9% (cross-mode spread < 1%). Higher tiers start partially filled
# (1/8, 1/4). The 1-ball tier is OMITTED — it has no free spin (a single-hit trigger on a 1-ball
# bet can't be made compliant with this wheel). Tune `max` via `run.py` report_mode_rtp.
SPIN_METER_TIER: dict[int, dict[str, float]] = {
    10: {"max": 6, "start_ratio": 0.0},
    20: {"max": 10, "start_ratio": 0.125},
    50: {"max": 21, "start_ratio": 0.25},
}

# Per-ball chance to award a bonus-meter coin-peg hit (independent of the landing pocket).
BONUS_PEG_HIT_PROB = 0.14

# Free-spin wheel segments (label list) — the original wheel's values with NO BONUS (the old BONUS
# slot repeats 2X). Rendered on the label-less `free-spin-roulette-wheel-empty.png` with a
# data-driven text overlay (FreeSpinRoulette.svelte). The free spin fires IN-DROP (per-drop meter)
# and the multiplier applies to the BET PER BALL (fixed base): `M` pays `stake_per_ball × M` on top
# of the drop. Mirror in apps/plinko game-logic/constants.ts FREE_SPIN_SEGMENTS.
FREE_SPIN_SEGMENTS: list[str] = ["2X", "0.5X", "1X", "5X", "10X", "2X", "20X", "15X"]

# Bonus wheel RELATIVE free-ball multipliers (8 segments, average ≈ 1.0). The per-tier free balls =
# `round(m × balls)` (>=1), so the wheel averages ≈ `balls` free balls per tier → bonus payout ≈
# `balls × board_EV(0.957)` ≈ `cost × 0.957` → bonus mode RTP ≈ TARGET_RTP at the tier cost. Max
# multiplier kept < 1.5 so the 1-ball tier rounds to avg ≈ 1 (not over). The CLIENT renders these
# per-tier values on the data-driven wheel (mirror in apps/plinko game-logic/constants.ts). Tune the
# spread/average to retune the bonus RTP.
BONUS_WHEEL_RELATIVE: list[float] = [0.6, 0.8, 1.0, 1.2, 1.4, 1.0, 0.8, 1.2]


def bonus_wheel_free_balls(balls_per_drop: int) -> list[int]:
    """Per-tier free-ball wheel awards (avg ≈ balls_per_drop). Sized so the bonus mode RTP ≈ TARGET_RTP
    at the tier cost."""
    balls = max(1, int(balls_per_drop))
    return [max(1, _js_round(m * balls)) for m in BONUS_WHEEL_RELATIVE]

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


def spin_in_drop_for_balls(balls_per_drop: int) -> bool:
    """True for tiers that fire the free spin in-drop (10/20/50); False for 1-ball (no free spin)."""
    return int(balls_per_drop) in SPIN_METER_TIER


def scaled_spin_meter_max(balls_per_drop: int) -> int:
    """Per-drop free-spin meter max for this tier (1 if the tier has no free spin)."""
    cfg = SPIN_METER_TIER.get(int(balls_per_drop))
    return max(1, int(cfg["max"])) if cfg else 1


def scaled_spin_meter_start(balls_per_drop: int) -> int:
    """Per-drop free-spin meter reset value for this tier (start_ratio × max)."""
    cfg = SPIN_METER_TIER.get(int(balls_per_drop))
    return _js_round(cfg["max"] * cfg["start_ratio"]) if cfg else 0


def scaled_bonus_meter_max(balls_per_drop: int) -> int:
    cfg = meter_tier_config(balls_per_drop)
    return max(1, _js_round(BONUS_METER_MAX * cfg["max_ratio"]))


def scaled_bonus_meter_start(balls_per_drop: int) -> int:
    """Per-tier bonus-meter reset / fresh-start value (start_ratio x max). Mirrors apps/plinko
    `bonusMeterTierFor`: 0 on 1/10-ball, 1/8 on 20-ball, 1/4 on 50-ball."""
    cfg = meter_tier_config(balls_per_drop)
    return _js_round(scaled_bonus_meter_max(balls_per_drop) * cfg["start_ratio"])


def bonus_meter_strata_starts(balls_per_drop: int) -> tuple[int, int, int]:
    """Mid / high / near-full bonus_meter_start values for distribution strata."""
    max_bonus = scaled_bonus_meter_max(balls_per_drop)
    mid = max(max_bonus // 2, 1)
    near_full = max(max_bonus - 1, 1)
    high = max((max_bonus * 3) // 4, mid)
    return mid, high, near_full
