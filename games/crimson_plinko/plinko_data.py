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

# 1-BALL BOARD (onedrop only). That tier is FEATURE-FREE — no free spin, no bonus (see
# BONUS_IN_DROP_RATE) — so the centre pocket, which exists only to fill the free-spin meter, would be a
# dead 0× slot hit ~20.9% of the time, leaving onedrop at the bare board EV (~89.6%): BELOW the 90.00%
# compliance floor. The 1-ball board therefore pays the CENTRE 0.1× and lifts the two pockets either
# side 0.2× → 0.3×, funding the tier to ~95.40% (other modes ~95.70%, so cross-mode spread ≈0.30%).
# Nothing else moves and the per-tier wincap (200×) is unchanged.
# ⚠️ The centre is NOT flagged `hitSpinSlot` on this tier (there is no spin meter to feed), so its
# multiplier is paid normally. Mirror in apps/plinko game-logic/boardMultipliers.ts.
ONE_BALL_BOARD_SLOT_MULTIPLIERS = [100, 50, 20, 5, 1.5, 0.4, 0.3, 0.1, 0.3, 0.4, 1.5, 5, 20, 50, 100]

# Serialized on plinkoDrop.difficulty for RGS / published math compatibility.
DEFAULT_VARIANT_ID = 0

DEFAULT_SLOT_MULTIPLIERS = list(BOARD_SLOT_MULTIPLIERS)

COEFFICIENT_SETS: list[list[float]] = [list(DEFAULT_SLOT_MULTIPLIERS)] * 13

# Per-balls-per-drop board override. Only tiers listed here differ from COEFFICIENT_SETS; every other
# tier (and every buy-bonus mode) keeps the shared board.
COEFFICIENT_SETS_BY_BALLS: dict[int, list[list[float]]] = {
    1: [list(ONE_BALL_BOARD_SLOT_MULTIPLIERS)] * 13,
}

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
    # 1-ball is FEATURE-FREE, so its only payout is the pocket the single ball lands in: the advertised
    # max IS the board's top pocket, 100× (hit 2/16384 ≈ 1/8,192 — far above the 1/20,000,000 floor).
    # It was 200× while the folded bonus could still fire here; that is now unreachable, so it must not
    # be advertised. Keep this in sync with `ONE_BALL_BOARD_SLOT_MULTIPLIERS`' top value.
    1: 100.0,
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
# FINE-TUNE the higher tiers to exactly TARGET_RTP, since the meter fire rate is DISCRETE
# (`P(Binomial(balls, BONUS_PEG_HIT_PROB) ≥ hits_to_fill)`) and can't land precisely on its own. INITIAL
# values; tune via measure_tuning.py / run.py so each base mode lands at ~TARGET_RTP.
#
# ⚠️ THE QUOTA IS NOT A SECOND TRIGGER PATH. A quota book does not bypass the meter: `gamestate.py`
# calls `ensure_coin_pegs_fill_meter` on it, turning on enough of the drop's `hitBonusPeg` flags
# (spread across the drop) that the meter fills 0 → max from REAL coin-peg hits and fires down the
# ordinary in-drop meter path. Every tier with a non-zero rate here has `bonus_in_drop=True` and
# `start_ratio 0.0`, so NO book can ever carry a bonus event with a meter that isn't full — which is
# exactly what the player-facing rules promise ("the meter fills as balls strike the gold coin pegs").
# What the quota actually fixes is the NUMBER of coin-peg hits on ~0.25–1.35% of drops; `hitBonusPeg`
# is sampled independently of the ball's pocket, so this is EV-neutral on the drop itself.
#
# ⚠️ THE 1-BALL TIER IS FEATURE-FREE (rate 0.0, and `game_config.py` omits its bonus stratum entirely —
# `Distribution` asserts quota > 0, so a 0 rate MUST mean "no distribution", not "quota 0"). onedrop can
# neither meter-fire (one ball ⇒ at most one coin-peg hit) nor quota-fire, and `spin_in_drop` is off, so
# an `onedrop` book can NEVER carry bonusRoulette / bonusRound / freeSpinTrigger events. The client
# enforces the same rule independently (`isSingleBallMode` in apps/plinko gameOrchestrator.ts).
# CONSEQUENCE: onedrop RTP is exactly its board EV, with nothing else funding it. That is why the tier
# has its OWN board (`COEFFICIENT_SETS_BY_BALLS[1]`) paying 0.95396×/ball — clear of the 90.00% floor —
# instead of the shared 0.89635×/ball table, which would put it UNDER the floor. Do not point onedrop at
# the shared board. Re-check with measure_tuning_capped.py.
# Re-tuned for the ESCALATING per-level level-up (`bonus_levelup_pegs`, thresholds 5,8,14,25,42,71,121,
# 205) + the avg-60 entry wheel (BONUS_WHEEL_FREE_BALLS = 20..100), via the WINCAP-AWARE tuner
# (measure_tuning_capped.py). Escalating level-ups make leveling FREQUENT + graduated (avg bonus level
# ≈ 2.69, up from ≈1.27 on the old flat bar), which ≈doubled the bonus EV.
# ⚠️ The entry wheel was RAISED back 10..90 → 20..100 (avg 50 → 60) so the award always matches the
# number painted on the wheel art (QA 2026-07-27: landed on 80, won 70). That extra entry EV alone puts
# the 10-ball tier at 96.198% on its NATURAL meter fire rate — i.e. with a ZERO quota, so the quota lever
# bottoms out and CANNOT pull it back to target. The 10-ball `BONUS_METER_TIER` max was therefore raised
# 6 → 7 (rarer natural fire) to reopen headroom; with that, these quotas re-solve tiers 10/20/50 to
# exactly 95.700% (spread 0.000%) with wincap-hit ≈1.4–9.5% of bonuses (advertised max win easily
# achievable). Re-confirm with a full `make run` LUT before publishing.
BONUS_IN_DROP_RATE: dict[int, float] = {
    1: 0.0,  # FEATURE-FREE tier: no bonus stratum is published for onedrop at all.
    10: 0.00283,
    20: 0.00253,
    50: 0.01350,
}


def bonus_in_drop_rate(balls_per_drop: int) -> float:
    return float(BONUS_IN_DROP_RATE.get(int(balls_per_drop), 0.0))


def row_tier_index(row_count: int) -> int:
    return max(0, min(row_count - 8, 12))


def coefficients_for(row_count: int, balls_per_drop: int = 0) -> list[float]:
    """Slot multipliers for a row count, on the board that `balls_per_drop` tier plays. Tiers without an
    override (everything but 1-ball, plus the buy modes) get the shared COEFFICIENT_SETS board."""
    tier = row_tier_index(row_count)
    sets = COEFFICIENT_SETS_BY_BALLS.get(int(balls_per_drop), COEFFICIENT_SETS)
    return list(sets[tier])


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
# meter, so it can't meter-fire a rare bonus; its (cosmetic) meter never triggers, and it has NO quota
# either (BONUS_IN_DROP_RATE[1] = 0), so onedrop is fully feature-free. Tune `max` via measure_tuning.
# ⚠️ 10-ball `max` RAISED 6 → 7 when the entry wheel went back to 20..100 (avg 60): at max 6 the natural
# fire rate alone lands that tier on 96.198%, above TARGET_RTP with a zero quota and nothing left to tune.
# Mirror in apps/plinko game-logic/constants.ts BONUS_METER_TIER.
BONUS_METER_TIER: dict[int, dict[str, float]] = {
    10: {"max": 7, "start_ratio": 0.0},
    20: {"max": 9, "start_ratio": 0.0},
    50: {"max": 17, "start_ratio": 0.0},
}

# Cosmetic bonus-meter for the 1-ball tier (and any tier without a BONUS_METER_TIER entry): it fills
# visually but NEVER fires (the 1-ball tier has no bonus at all). Max only; start is 0.
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
# in-bonus level-up: coin-peg hits during bonus balls re-fill the meter → next level.
#
# THIS IS THE DEFAULT / BASE-MODE VALUE. It is now a PER-MODE tunable — see
# `BONUS_PEG_HIT_PROB_BY_MODE` below, which is the RTP lever that lets every mode share ONE in-bonus
# level-up ladder (`BONUS_LEVELUP_PEG_HITS_BY_LEVEL`). All four base modes keep 0.18.
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

# Bonus roulette ABSOLUTE entry free-ball awards (9 segments, clockwise from the top marker; avg = 60).
# THE ART IS THE SOURCE OF TRUTH: these are exactly the numbers painted on the wheel PNG, in wedge order
# (index 0 = the wedge parked under the pointer = 100, then clockwise 90,80,...,20). The player must be
# awarded the number they watched the wheel land on, so DO NOT change this list without repainting the
# art to match — a 2026-07-24 change to 10..90 left the art at 20..100 and every spin paid 10 less than
# it showed (QA 2026-07-27: "landed on 80, won 70").
# Tier-INDEPENDENT; level-ups add more (BONUS_LEVEL_BALLS). The avg-60 entry costs RTP headroom — see
# BONUS_IN_DROP_RATE / BONUS_METER_TIER above, where the 10-ball meter max is raised 6 → 7 to pay for it.
# Mirror in apps/plinko game-logic/constants.ts (BONUS_WHEEL_FREE_BALLS + BonusRoulette.svelte
# ART_SLOT_FREE_BALLS, which must stay in this same wedge order).
BONUS_WHEEL_FREE_BALLS: list[int] = [100, 90, 80, 70, 60, 50, 40, 30, 20]


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
# MULTIPLIER = 10 → award = bar value ×10 (L2→20, L3→40, L4→80, L5→160, L6→320, L7→640, L8→1280,
# L9→2560), matching inout's Plinko Aztec free-ball ladder (per user).
#
# ⚠️ The ladder is EXPONENTIAL, so the ×10 awards SELF-SUSTAIN the cascade: once a bonus reaches the level
# where one award (2^(L-1)×10 balls) alone funds the next level-up (≈ BONUS_LEVELUP_PEG_HITS/BONUS_PEG_HIT_PROB
# balls), it runs away to level 9 and dumps ~entry+5,100 balls — which both blows RTP up and OOM's `make
# run` (each ball is an outcome dict). So the level-up bar MUST be high enough that reaching that
# self-sustain level is RARE: with ×10, self-sustain begins at level L* = smallest L with 2^(L-1)×10 ≥
# bar/0.18 (bar 6→L*3, 15→L*5, 30→L*6, 60→L*7). BONUS_LEVELUP_PEG_HITS is raised accordingly (see below)
# so the deep dumps stay a rare jackpot (RAM-safe + RTP-tunable) while level 2/3 (20/40 balls) still land
# regularly. Re-tune quotas (BONUS_IN_DROP_RATE) + the buy tiers whenever MULTIPLIER changes.
BONUS_LEVEL_BALL_MULTIPLIER: int = 10

BONUS_LEVEL_BALLS: dict[int, int] = {
    lvl: BONUS_LEVEL_LABELS[lvl - 1] * BONUS_LEVEL_BALL_MULTIPLIER
    for lvl in range(2, len(BONUS_LEVEL_LABELS) + 1)
}

# Highest reachable bonus level (length of the ladder including the level-1 entry).
MAX_BONUS_LEVEL = 9

# In-bonus level-up: PER-LEVEL (escalating) coin-peg threshold — the number of coin-peg hits
# (accumulated across the falling bonus balls, reset on each level-up) needed to advance FROM level L to
# L+1 = round(BONUS_LEVELUP_BASE * BONUS_LEVELUP_GROWTH**(L-1)), clamped >= 2.
#
# WHY ESCALATING (not the old flat 15): the ×10 award ladder is EXPONENTIAL, so a FLAT bar is bimodal —
# either the bonus stays shallow (~L1-2) or, once an award is big enough to self-sustain, it runs away to
# L9 (~5,100 balls: RTP blow-up + OOM). A flat bar low enough for FREQUENT level-ups therefore always
# ran away. An escalating bar whose growth ≈ the award growth (~1.7 vs ×2) makes each level ~equally
# hard RELATIVE to its award, so leveling up is FREQUENT and graduated at low levels but progressively
# HARDER at higher ones, and the runaway never ignites. Measured (sweep_escalation.py, BASE=5 GROWTH=1.7
# → thresholds 5,8,14,25,42,71,121,205): L2≈86% L3≈59% L4≈22% L5≈1.7% L6≈0.06% … L9≈0.007%; 99.9% of
# bonuses ≤400 balls (RAM-safe like the old flat bar) yet the FULL ×10 ladder stays reachable as a rare
# escalating jackpot. The awarded free balls per level (BONUS_LEVEL_BALLS) are UNCHANGED. Bonus EV about
# doubles (avg pay ~66→~123), so BONUS_IN_DROP_RATE is re-solved DOWN to hold each base mode at ~95.7%.
# Tune the frequency via BASE (lower = more frequent early levels) and the deep-tail via GROWTH (lower =
# deeper jackpots reachable, but heavier RAM/variance). Mirror in apps/plinko game-logic/constants.ts.
BONUS_LEVELUP_BASE = 5
BONUS_LEVELUP_GROWTH = 1.7

# Threshold to LEAVE each level L (1 .. MAX_BONUS_LEVEL-1). Precomputed dict (single source of truth).
BONUS_LEVELUP_PEG_HITS_BY_LEVEL: dict[int, int] = {
    lvl: max(2, round(BONUS_LEVELUP_BASE * (BONUS_LEVELUP_GROWTH ** (lvl - 1))))
    for lvl in range(1, MAX_BONUS_LEVEL)
}


def bonus_levelup_pegs(level: int) -> int:
    """Coin-peg hits needed to advance FROM `level` to `level+1` (escalating per-level threshold).
    Clamped to the level-1 value below the ladder and to the top step at/above MAX_BONUS_LEVEL."""
    lvl = max(1, min(int(level), MAX_BONUS_LEVEL - 1))
    return int(BONUS_LEVELUP_PEG_HITS_BY_LEVEL[lvl])


# Backward-compat flat reference (= the level-1 threshold). Kept because a few dev tools still read it;
# the live math uses the per-level `bonus_levelup_pegs()` above.
#
# ⚠️ THE LADDER IS SHARED BY EVERY MODE. The buy modes used to override it with a FLAT per-tier bar
# (16/22/29/37) because a large fixed entry batch self-sustains the ×10 award cascade at the easy
# escalating bar. That override is GONE: a bonus round now costs the same coin-peg hits to climb no
# matter how it was entered, and each buy tier is instead held at TARGET_RTP by its own
# `BONUS_PEG_HIT_PROB_BY_MODE` entry (a bought bonus's balls hit coin pegs less often).
BONUS_LEVELUP_PEG_HITS = BONUS_LEVELUP_PEG_HITS_BY_LEVEL[1]


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
# `entry_balls` are TUNED so RTP = mean(min(bonus_payout, wincap)) / cost ≈ TARGET_RTP.
#
# GATE-THE-CLIMB (`peg_hit_prob`, buy-only): with the ×10 exponential ladder a large FIXED entry batch
# self-sustains the cascade — on the shared escalating bar it runs away to level 9 (~5,100 balls, e.g.
# superfury reaches L9 ~100%) → non-compliant (RTP 145–252%) + OOM. The climb therefore has to be gated,
# but the GATE IS NO LONGER THE LADDER: every mode now shares `BONUS_LEVELUP_PEG_HITS_BY_LEVEL`, and each
# buy tier instead lowers the per-ball COIN-PEG PROBABILITY of its own bonus balls (`peg_hit_prob`), so it
# takes the same 5/8/14/... hits to climb but those hits arrive far more slowly. Same gate, same level
# distribution (mean level 1.14–1.84, level 9 ≪0.01% of buys), one consistent rule on screen.
# The payout is dominated by the entry balls' own board EV (~0.896 each), so `entry_balls` sets the coarse
# RTP and `peg_hit_prob` trims it to TARGET_RTP (≈3–4 RTP points per 0.01 of probability). `head_start` is
# 0. `wincap` sits at each tier's ORGANIC (corner-luck + shallow-level) payout tail so the advertised max
# win is reachably produced (~1/1.3k–1/6.5k in the 200k buy sims) while barely clipping EV. One published
# mode per tier, `buy{key}`. Mirror in apps/plinko game/config.ts + game/plinkoBetMode.ts.
# Tuned via verify_buybonus.py; pin via run.py + compliance_report.py.
BUY_BONUS_TIER_DEFS: list[dict] = [
    {"key": "standard", "entry_balls": 72, "cost": 80.0, "wincap": 260.0, "head_start": 0.0, "peg_hit_prob": 0.0447},
    {"key": "enhanced", "entry_balls": 95, "cost": 100.0, "wincap": 290.0, "head_start": 0.0, "peg_hit_prob": 0.0292},
    {"key": "premium", "entry_balls": 145, "cost": 150.0, "wincap": 330.0, "head_start": 0.0, "peg_hit_prob": 0.0252},
    {"key": "superfury", "entry_balls": 239, "cost": 250.0, "wincap": 480.0, "head_start": 0.0, "peg_hit_prob": 0.0283},
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


def buy_bonus_peg_hit_prob(tier_key: str) -> float:
    """Per-ball coin-peg probability inside a BOUGHT bonus (0 = fall back to BONUS_PEG_HIT_PROB).
    Lowered below the base value so a big fixed entry batch climbs the SHARED level-up ladder slowly
    enough to stay at TARGET_RTP and RAM-safe (see BUY_BONUS_TIER_DEFS)."""
    tier = BUY_BONUS_TIER_BY_KEY.get(tier_key)
    return float(tier.get("peg_hit_prob", 0.0)) if tier else 0.0


# ---------------------------------------------------------------------------
# PER-MODE coin-peg probability — the RTP lever that lets all 7 feature modes share ONE in-bonus
# level-up ladder (`BONUS_LEVELUP_PEG_HITS_BY_LEVEL`).
# ---------------------------------------------------------------------------
# Keyed by the published RGS mode name. `game_config.py` puts the value on each distribution's
# conditions (`peg_hit_prob`); `gamestate.py` passes it into `build_drop_outcomes` /
# `build_feature_meter_events`, so it applies to BOTH the paid drop's bonus-trigger meter and the
# bonus round's energy meter for that mode.
#
# BASE MODES keep 0.18: their RTP is already tuned by the bonus quota (`BONUS_IN_DROP_RATE`) and the
# per-drop trigger bar (`BONUS_METER_TIER`), and their bonus depth (mean level ≈2.70) is the tuned
# reference the ladder was designed around. ⚠️ The ×10 award ladder self-sustains just above this
# value — at p = 0.25 the earned bonus explodes (mean payout 125 → 1,519, P(level 9) 0.001% → 29.7%),
# so never interpolate a base-mode increase; re-measure it (measure_tuning_capped.py).
#
# BUY MODES take a much lower value (see BUY_BONUS_TIER_DEFS) because their entry batch is 72–239
# FIXED balls; at 0.18 they would run away to level 9. Verified against the REAL simulate_bonus_round
# (verify_buybonus.py, n=150k/tier): buystandard 95.64%, buyenhanced 95.76%, buypremium 95.74%,
# buysuperfury 95.68% — spread 0.121%, max-win hit 1/1,136–1/6,803, largest book 299 balls.
# The lever is ~3-4 RTP points per 0.01 of probability; re-run verify_buybonus.py after any nudge.
BONUS_PEG_HIT_PROB_BY_MODE: dict[str, float] = {
    **{bet_mode_for_balls_per_drop(balls): BONUS_PEG_HIT_PROB for balls in BALLS_PER_DROP_OPTIONS},
    **{
        buy_bonus_mode_name(tier["key"]): float(tier["peg_hit_prob"])
        for tier in BUY_BONUS_TIER_DEFS
    },
}


def bonus_peg_hit_prob(mode_name: str) -> float:
    """Per-ball coin-peg probability for a published bet mode (falls back to the global default)."""
    return float(BONUS_PEG_HIT_PROB_BY_MODE.get(str(mode_name), BONUS_PEG_HIT_PROB))


def _js_round(value: float) -> int:
    """Match apps/plinko `Math.round` (round half up, not Python banker's `round`)."""
    return int(math.floor(value + 0.5))


def spin_in_drop_for_balls(balls_per_drop: int) -> bool:
    """True for tiers that fire the free spin in-drop (10/20/50); False for 1-ball (no free spin)."""
    return int(balls_per_drop) in SPIN_METER_TIER


def spin_pocket_active_for_balls(balls_per_drop: int) -> bool:
    """True where the centre pocket is the SPIN pocket (fills the free-spin meter, pays the board's 0×).
    False on the 1-ball tier, which has no free-spin meter — there the centre is an ordinary paying
    pocket (ONE_BALL_BOARD_SLOT_MULTIPLIERS) and balls landing in it are NOT flagged `hitSpinSlot`."""
    return spin_in_drop_for_balls(balls_per_drop)


def bonus_in_drop_for_balls(balls_per_drop: int) -> bool:
    """True for tiers whose PER-DROP bonus meter can fire the bonus in-drop (10/20/50). False for 1-ball
    (one ball can't fill the meter, and it has no quota either — see `bonus_possible_for_balls`)."""
    return int(balls_per_drop) in BONUS_METER_TIER


def bonus_possible_for_balls(balls_per_drop: int) -> bool:
    """True when a BASE book for this tier can contain a bonus at all — either the per-drop meter can
    fire it (`bonus_in_drop_for_balls`) or the `force_bonus` quota can (`bonus_in_drop_rate` > 0).

    False ONLY for the feature-free 1-ball tier, whose books must never carry bonusRoulette /
    bonusRound events. `game_config.py` uses this to omit the bonus stratum for that tier entirely."""
    return bonus_in_drop_for_balls(balls_per_drop) or bonus_in_drop_rate(balls_per_drop) > 0.0


def board_ev_per_ball(balls_per_drop: int, row_count: int = 14) -> float:
    """Analytic EV per ball of the board this tier plays (fair binomial peg walk, no features).

    Assumes the canonical `num_slots == row_count + 1` board (15 slots / 14 rows), where
    `sample_rate_index` maps the peg walk 1:1 onto the pockets."""
    coeffs = coefficients_for(row_count, balls_per_drop)
    if len(coeffs) != row_count + 1:
        return 0.0
    return sum(math.comb(row_count, k) * m for k, m in enumerate(coeffs)) / (2 ** row_count)


def declared_rtp_for_balls(balls_per_drop: int) -> float:
    """Declared RTP for a tier's bet mode. Feature-bearing tiers are tuned to TARGET_RTP by the bonus
    quota; a FEATURE-FREE tier (1-ball: no bonus, no free spin) returns EXACTLY its board EV, since the
    board is all it pays — publishing TARGET_RTP there would overstate it."""
    balls = int(balls_per_drop)
    if bonus_possible_for_balls(balls) or spin_in_drop_for_balls(balls):
        return TARGET_RTP
    return round(board_ev_per_ball(balls), 5)


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
