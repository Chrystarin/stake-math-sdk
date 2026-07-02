"""Crimson Plinko coefficient + feature tables (aligned with apps/plinko config).

This module is the single source of truth for the feature tunables that are also
exported to the front-end config (`run.py:write_plinko_fe_config`):
  - meter maxima + per-tier scaling
  - bonus-peg hit probability
  - free-spin wheel segments + weights
  - bonus wheel entry-ball awards
  - bonus level-up ball table
  - per-tier in-drop bonus rate
"""

import math

# row tier index (row_count - 8) -> slot multipliers
# Row tiers 8..20 map to indices 0..12. Tables match 14-row board (15 slots).

# Canonical board — Aztec values (same literal table as apps/plinko `BOARD_SLOT_MULTIPLIERS`).
# Center index 7 is the spin pocket (0× payout; fills the free-spin meter only).
# FOLDED-BONUS DESIGN (June 2026): the BONUS is no longer a separate paid mode — it fires IN-DROP on a
# rare per-tier quota inside the base book and is FREE (the player pays only the normal base cost). To
# fund that free bonus + the in-drop free spin while staying under the 96.70% cap, the board is LOWERED
# from the old ~0.957 to a fair 14-row Galton EV of ~0.896, so base RTP = board_EV(0.896) +
# bonus_add + free_spin_add ≈ TARGET_RTP. Mirror in apps/plinko game-logic/boardMultipliers.ts.
BOARD_SLOT_MULTIPLIERS = [100, 50, 20, 5, 1.5, 0.4, 0.2, 0, 0.2, 0.4, 1.5, 5, 20, 50, 100]

# Serialized on plinkoDrop.difficulty for RGS / published math compatibility.
DEFAULT_VARIANT_ID = 0

DEFAULT_SLOT_MULTIPLIERS = list(BOARD_SLOT_MULTIPLIERS)

COEFFICIENT_SETS: list[list[float]] = [list(DEFAULT_SLOT_MULTIPLIERS)] * 13

ROW_COUNT_OPTIONS = (10, 14, 20)
BALLS_PER_DROP_OPTIONS = (1, 10, 20, 50)

# RGS `/wallet/play` `mode` — one published LUT per tier (meta stratum matching is not reliable).
# FOLDED-BONUS DESIGN: only these 4 BASE modes are published (cost = ball count); there is NO separate
# bonus mode (a free big bonus can only exist funded by the base game — see game_config.py).
BET_MODE_BY_BALLS_PER_DROP: dict[int, str] = {
    1: "onedrop",
    10: "tendrop",
    20: "twentydrop",
    50: "fiftydrop",
}


def bet_mode_for_balls_per_drop(balls_per_drop: int) -> str:
    balls = int(balls_per_drop)
    return BET_MODE_BY_BALLS_PER_DROP.get(balls, "tendrop")


# Declared RTP for the Stake Engine math summary. Each base mode = board EV + the rare in-drop bonus +
# the rare in-drop free spin. Every mode should cluster within ±0.5% and stay inside 90.00%-96.70%.
TARGET_RTP = 0.957

# ---------------------------------------------------------------------------
# Per-tier max win (wincap) ladder.
# ---------------------------------------------------------------------------
# Stake requires the ADVERTISED max win to be ACHIEVABLE (hit-rate >= 1/20,000,000). The folded bonus is
# tier-independent in absolute ball mechanics, but higher tiers sample it more, so each tier's organic
# payout ceiling differs (measured maxima at the published sim counts: 1-ball ~214x, 10 ~287x, 20 ~323x,
# 50 ~430x). A single flat cap would either be unreachable on the low tiers (e.g. 300x on 1-ball) or
# throw away the high-tier tail. So the wincap is PER-TIER, set at/just below each tier's organic max:
# the cap binds only the thin tail above it (creating an achievable spike exactly AT the advertised max)
# while removing almost no EV (RTP stays put, no re-tune). This matches the UI story "more balls / higher
# risk => bigger potential payouts". The SDK applies it per mode automatically: BetMode.max_win below is
# wincap_for_balls(balls), and src/state/run_sims.py sets gamestate.config.wincap = bm.get_wincap() before
# each mode's sims, so game_override.update_final_win caps the per-ball payout multiplier at this value.
WINCAP_BY_BALLS: dict[int, float] = {
    1: 200.0,
    10: 250.0,
    20: 300.0,
    50: 400.0,
}

# Default/global wincap = the top of the ladder (used before any per-mode override).
DEFAULT_WINCAP = max(WINCAP_BY_BALLS.values())


def wincap_for_balls(balls_per_drop: int) -> float:
    """Per-tier max-win multiplier (per stake_per_ball). Falls back to the ladder max."""
    return float(WINCAP_BY_BALLS.get(int(balls_per_drop), DEFAULT_WINCAP))

# OPTION A (per-drop meter trigger): the bonus fires IN-DROP when the PER-DROP bonus meter
# (BONUS_METER_TIER) fills from this drop's own coin-peg hits — NOT a cross-bet meter (statelessness:
# each bet is independent). This `BONUS_IN_DROP_RATE` is now only a small `force_bonus` QUOTA used to
# (a) give the 1-ball tier its bonus — 1-ball can't meter-fire (one ball ⇒ at most one coin-peg hit),
# so it MUST come from a quota or onedrop sits ~6% below the others and fails the cross-mode band; and
# (b) FINE-TUNE the higher tiers to exactly TARGET_RTP, since the meter fire rate is DISCRETE
# (`P(Binomial(balls, BONUS_PEG_HIT_PROB) ≥ hits_to_fill)`) and can't land precisely on its own. A quota
# book snaps the meter to full + plays the bonus, so it still reads as a meter completion. INITIAL
# values; tune via measure_tuning.py / run.py so each base mode lands at ~TARGET_RTP.
# Re-tuned for the inout-style ×1 BONUS_LEVEL_BALLS ladder (BONUS_LEVELUP_PEG_HITS=6) via the
# WINCAP-AWARE tuner (measure_tuning_capped.py): deep-level dumps are CAPPED at WINCAP_BY_BALLS and stay
# a rare tail (avg bonus level ≈ 2.1, wincap hit ≈0.8–1.1% of bonuses), so each mode solves to ~95.700%
# (spread ≈ 0) while the advertised max win stays easily achievable. Re-confirm with a full `make run`
# LUT before publishing.
BONUS_IN_DROP_RATE: dict[int, float] = {
    1: 0.00168,
    10: 0.00511,
    20: 0.01463,
    50: 0.04461,
}


def bonus_in_drop_rate(balls_per_drop: int) -> float:
    return float(BONUS_IN_DROP_RATE.get(int(balls_per_drop), 0.0))


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

# PER-DROP BONUS meter (Option A), per balls-per-drop tier — mirror of SPIN_METER_TIER. The meter ALWAYS
# starts EMPTY (start_ratio 0 on every tier — no per-tier head start) and fires the bonus IN-DROP when
# this drop's own coin-peg hits fill it to `max`. So `max` IS the hits-to-fill: it must be reachable
# within one drop (a drop yields ~`balls × BONUS_PEG_HIT_PROB` hits) AND rare enough (~0.4–0.5% so a big
# ~58× FREE bonus stays under the 96.70% cap). `max` scales per tier (more balls ⇒ more hits ⇒ a higher
# bar), like the spin meter's 6/10/21. The 1-ball tier is OMITTED — one ball can add at most 1 to the
# meter, so it can't meter-fire a rare bonus; its (cosmetic) meter never triggers and its bonus comes
# from the BONUS_IN_DROP_RATE quota instead. Tune `max` (+ quotas) via measure_tuning.
BONUS_METER_TIER: dict[int, dict[str, float]] = {
    10: {"max": 6, "start_ratio": 0.0},
    20: {"max": 9, "start_ratio": 0.0},
    50: {"max": 17, "start_ratio": 0.0},
}

# Cosmetic bonus-meter for the 1-ball tier (and any tier without a BONUS_METER_TIER entry): it fills
# visually but NEVER fires (the 1-ball bonus is quota-driven). Max only; start is 0.
BONUS_METER_COSMETIC_MAX = 20

# Per-drop FREE-SPIN meter, per balls-per-drop tier. The meter resets every round to
# `start_ratio × max` (NO cross-bet carry) and fires the free spin IN-DROP when it reaches `max`
# within the round. `max` scales UP with ball count so the fire rate stays rare enough that the
# in-drop free spin (which pays bet × weighted wheel, mean ≈ 5.4 incl. the rare BONUS chain) keeps
# every tier's RTP add small (cross-mode spread < 1%). Per spec the starts are 10 → 0, 20 → 1/8,
# 50 → 1/4. The 1-ball tier is OMITTED — it has no free spin (a single-hit trigger on a 1-ball bet
# can't be made compliant with this wheel). Tune `max` via `run.py` report_mode_rtp.
SPIN_METER_TIER: dict[int, dict[str, float]] = {
    10: {"max": 6, "start_ratio": 0.0},
    20: {"max": 10, "start_ratio": 0.125},
    50: {"max": 21, "start_ratio": 0.25},
}

# Per-ball chance to award a bonus-meter coin-peg hit (independent of the landing pocket). Raised from
# 0.14 → 0.18 for a LIVELIER per-drop meter (it visibly ticks up more each drop). Also drives the
# in-bonus level-up: coin-peg hits during bonus balls re-fill the meter → next level (BONUS_LEVELUP_PEG_HITS
# was bumped in step with this so level-ups stay a rare jackpot, not more common).
BONUS_PEG_HIT_PROB = 0.18

# Free-spin wheel segments (label list) — ORIGINAL values, baked into the labeled `free-spin-roulette-
# wheel.png` (clockwise from the top marker). EQUAL weight (the labeled wheel has 8 equal slices). The
# free spin fires IN-DROP (per-drop meter); a numeric `M` pays `stake_per_ball × M` on top of the drop;
# `BONUS` (1-in-8) chains a bonus round. Order MUST match the PNG (index 0 = top). Mirror in apps/plinko
# game-logic/constants.ts FREE_SPIN_SEGMENTS.
FREE_SPIN_SEGMENTS: list[str] = ["2X", "0.5X", "1X", "5X", "10X", "BONUS", "20X", "15X"]

# Free-spin wheel WEIGHTS (index-aligned). EQUAL (all 1) — the labeled wheel is 8 equal slices, so the
# landing is uniform. Mirror in apps/plinko game-logic/constants.ts FREE_SPIN_WEIGHTS.
FREE_SPIN_WEIGHTS: list[float] = [1, 1, 1, 1, 1, 1, 1, 1]

# Bonus roulette ABSOLUTE free-ball awards — ORIGINAL values, baked into the labeled `bonus-roulette-
# wheel.png` (8 segments, clockwise from the top marker; avg ≈ 48.75 entry balls). Tier-INDEPENDENT;
# level-ups add more (BONUS_LEVEL_BALLS). Order MUST match the PNG (index 0 = top = 100). Mirror in
# apps/plinko game-logic/constants.ts.
BONUS_WHEEL_FREE_BALLS: list[int] = [100, 20, 50, 50, 50, 80, 20, 20]


def bonus_wheel_free_balls(balls_per_drop: int = 0) -> list[int]:
    """Bonus-roulette entry free-ball awards. ABSOLUTE (Aztec values), independent of the tier — the
    bonus is a free feature that dumps the same big ball counts regardless of the base ball count."""
    _ = balls_per_drop  # kept for signature stability (callers pass the tier)
    return list(BONUS_WHEEL_FREE_BALLS)


# On-screen bonus level-bar values (mirror apps/plinko game-logic/constants.ts BONUS_LEVEL_LABELS).
BONUS_LEVEL_LABELS: list[int] = [1, 2, 4, 8, 16, 32, 64, 128, 256]

# Level-up free-ball award = the reached level's bar value × BONUS_LEVEL_BALL_MULTIPLIER.
#
# LEVEL 1 (the entry level) gets NO ladder award — its balls come ONLY from the bonus roulette
# (BONUS_WHEEL_FREE_BALLS) or the bought free balls (`entry_balls_override`). The multiplier applies
# ONLY from level 2 onwards (BONUS_LEVEL_BALLS starts at key 2; `bonus_level_balls(1)` returns 0).
#
# MULTIPLIER = 1 → the award EQUALS the bar value (L2→2, L3→4, … L9→256). This MATCHES the SOURCE game,
# inout's Plinko Aztec, whose bonus levels ARE 1,2,4,…,256 free balls: you climb by hitting the central
# energy bumpers and the top level "drops up to 250–256 balls per spin", the run ending when you reach
# the top or run out of energy. (An earlier ×10 was wrong on two counts: it doesn't match inout, and the
# EXPONENTIAL bar means a snowball to level 9 dumps `entry + M×Σlabels` balls — ×10 → ~5,200-ball bonus
# books that OOM'd `make run`.) At ×1 the deepest bonus is ~610 balls (under the old 20..300 ramp's ~925
# and inout's ~250/level cap), so `make run` stays within RAM, while level 9 stays reachable (~0.9% of
# bonuses at BONUS_LEVELUP_PEG_HITS=6). Peak book ≈ entry + M×510 balls — keep M small (re-tune via
# measure_tuning_capped.py) so `make run` doesn't OOM.
BONUS_LEVEL_BALL_MULTIPLIER: int = 1

BONUS_LEVEL_BALLS: dict[int, int] = {
    lvl: BONUS_LEVEL_LABELS[lvl - 1] * BONUS_LEVEL_BALL_MULTIPLIER
    for lvl in range(2, len(BONUS_LEVEL_LABELS) + 1)
}

# Highest reachable bonus level (length of the ladder including the level-1 entry).
MAX_BONUS_LEVEL = 9

# In-bonus level-up: number of coin-peg hits (accumulated across the falling bonus balls) needed to
# advance one level and unlock the next batch of free balls (BONUS_LEVEL_BALLS). With BONUS_PEG_HIT_PROB
# ≈ 0.14, ~`T/0.14` balls fund one level, so a typical ~60-ball entry usually stays low and the deep
# levels (the up-to-250-ball dumps) are a rare jackpot — the inout "accumulate energy → unlock levels"
# feel. RAISE to make level-ups rarer (lower bonus EV); LOWER to make them common (higher EV).
# Set to 6 for the inout-style ×1 ladder: the small early awards (L2→2, L3→4 …) can't "snowball" to the
# deep levels unless the level-up bar is easy, so 6 (≈33 balls funds one level at BONUS_PEG_HIT_PROB=0.18)
# keeps level 9 REACHABLE (~0.9% of bonuses, avg level ≈2.1) while the small ball counts keep the deepest
# bonus ~610 balls (RAM-safe for `make run`). (Was 15 for the old steep ladder, which self-sustained on
# its own big counts; the ×1 ladder needs the lower bar to stay achievable.)
BONUS_LEVELUP_PEG_HITS = 6


def bonus_level_balls(level: int) -> int:
    """Additional free balls granted when reaching `level` (0 outside the ladder)."""
    return int(BONUS_LEVEL_BALLS.get(int(level), 0))


# ---------------------------------------------------------------------------
# BUY BONUS — 4 purchasable tiers that instantly trigger the bonus (is_buybonus modes).
# ---------------------------------------------------------------------------
# A buy is BONUS-ONLY: it plays NO paid base drop. The round opens with the bonus meter pre-filled to
# FULL, which fires the bonus immediately; the bonus is seeded with the tier's FIXED `entry_balls`
# (overriding the random bonus wheel), then the usual in-bonus level-up / chain hits add MORE balls on
# top — so the "roulette-won" balls combine with the bought balls (total = entry + level-up balls).
# cost is ×bet-per-ball (a Stake mode's cost is ALWAYS ×amount, never ×total-bet), taken straight from
# the Crimson Plinko rule-set PDF (80/100/150/250). Because the cost is FIXED to the PDF, the
# `entry_balls` are TUNED (measure_tuning.py) so RTP = mean(min(bonus_payout, wincap)) / cost ≈
# TARGET_RTP. The per-tier `wincap` is the advertised max win (must be achievable ≥ 1/20M and not over-
# clip EV below target). One published mode per tier, `buy{key}` (e.g. buystandard). Mirror in apps/plinko
# game/config.ts + game/plinkoBetMode.ts. INITIAL entry estimates — pin via measure_tuning.py + run.py.
# `head_start` = the PDF "Fury Meter Head-Start": the in-bonus level-up meter STARTS this fraction of the
# way filled (of BONUS_LEVELUP_PEG_HITS), so higher tiers reach the first level-up (chain → extra free
# balls) sooner. This raises EV, so `entry_balls` are re-tuned DOWN to hold RTP ≈ 95.7% at the fixed PDF
# cost. entry_balls tuned via measure_buybonus.py; wincap set at/just below each tier's organic payout max
# (achievable + binds the thin tail). Re-pinned by the full run.py sims + compliance_report.py.
BUY_BONUS_TIER_DEFS: list[dict] = [
    {"key": "standard", "entry_balls": 71, "cost": 80.0, "wincap": 300.0, "head_start": 0.0},
    {"key": "enhanced", "entry_balls": 81, "cost": 100.0, "wincap": 340.0, "head_start": 0.20},
    {"key": "premium", "entry_balls": 113, "cost": 150.0, "wincap": 450.0, "head_start": 0.40},
    {"key": "superfury", "entry_balls": 141, "cost": 250.0, "wincap": 600.0, "head_start": 0.70},
]

# Fixed balls-per-drop reference for a buy's bonus sim — only affects in-bonus free-spin gating + meter-
# max scaling (entry + level-up balls are bpd-independent), so the buy EV is identical regardless of the
# player's balls-per-drop selector → exactly 4 modes (cost independent of bpd). 10 keeps the in-bonus
# free spin enabled (it is off only on the 1-ball tier).
BUY_BONUS_BALLS_PER_DROP_REF = 10

BUY_BONUS_TIER_BY_KEY: dict[str, dict] = {t["key"]: t for t in BUY_BONUS_TIER_DEFS}


def buy_bonus_mode_name(tier_key: str) -> str:
    """RGS `/wallet/play` mode for a buy tier (mirror web `buyBonusModeName`), e.g. buystandard."""
    return f"buy{tier_key}"


def buy_bonus_entry_balls(tier_key: str) -> int:
    tier = BUY_BONUS_TIER_BY_KEY.get(tier_key)
    return int(tier["entry_balls"]) if tier else 0


def buy_bonus_cost(tier_key: str) -> float:
    tier = BUY_BONUS_TIER_BY_KEY.get(tier_key)
    return float(tier["cost"]) if tier else 0.0


def buy_bonus_wincap(tier_key: str) -> float:
    tier = BUY_BONUS_TIER_BY_KEY.get(tier_key)
    return float(tier["wincap"]) if tier else DEFAULT_WINCAP


def buy_bonus_head_start(tier_key: str) -> float:
    """Fury-meter head-start fraction (0..1) for a buy tier (in-bonus level-up meter starting fill)."""
    tier = BUY_BONUS_TIER_BY_KEY.get(tier_key)
    return float(tier.get("head_start", 0.0)) if tier else 0.0


def _js_round(value: float) -> int:
    """Match apps/plinko `Math.round` (round half up, not Python banker's `round`)."""
    return int(math.floor(value + 0.5))


def spin_in_drop_for_balls(balls_per_drop: int) -> bool:
    """True for tiers that fire the free spin in-drop (10/20/50); False for 1-ball (no free spin)."""
    return int(balls_per_drop) in SPIN_METER_TIER


def bonus_in_drop_for_balls(balls_per_drop: int) -> bool:
    """True for tiers whose PER-DROP bonus meter can fire the bonus in-drop (10/20/50). False for 1-ball
    (one ball can't fill the meter — its bonus comes from the BONUS_IN_DROP_RATE quota)."""
    return int(balls_per_drop) in BONUS_METER_TIER


def scaled_spin_meter_max(balls_per_drop: int) -> int:
    """Per-drop free-spin meter max for this tier (1 if the tier has no free spin)."""
    cfg = SPIN_METER_TIER.get(int(balls_per_drop))
    return max(1, int(cfg["max"])) if cfg else 1


def scaled_spin_meter_start(balls_per_drop: int) -> int:
    """Per-drop free-spin meter reset value for this tier (start_ratio × max)."""
    cfg = SPIN_METER_TIER.get(int(balls_per_drop))
    return _js_round(cfg["max"] * cfg["start_ratio"]) if cfg else 0


def scaled_bonus_meter_max(balls_per_drop: int) -> int:
    """Per-drop bonus meter max for this tier. Tiers without an entry (1-ball) use the cosmetic max."""
    cfg = BONUS_METER_TIER.get(int(balls_per_drop))
    return max(1, int(cfg["max"])) if cfg else BONUS_METER_COSMETIC_MAX


def scaled_bonus_meter_start(balls_per_drop: int) -> int:
    """Per-drop bonus meter reset value for this tier (start_ratio × max). The meter resets to this each
    round and fills in-drop. 1-ball (no entry) is cosmetic → start 0 (never fires)."""
    cfg = BONUS_METER_TIER.get(int(balls_per_drop))
    return _js_round(cfg["max"] * cfg["start_ratio"]) if cfg else 0
