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
# BONUS_IN_DROP_RATE) — so nothing but the board funds it, and the shared table's 0.89635×/ball sits
# BELOW the 90.00% compliance floor. The 1-ball board therefore pays its two 1.5× pockets 2.0× instead.
# They are hit 12.219% of the time (2*C(14,4)/2^14), so that one 0.5 step is worth +6.110 points and
# lands the tier at 95.745%. Nothing else moves: the centre still pays 0× and the advertised max win is
# still the board's top pocket (100×, hit 2/16384).
#
# ⚠️ THIS BOARD *IS* THE TIER'S RTP. onedrop has no feature to fund it and no quota to tune (see
# `BONUS_IN_DROP_RATE`), so `board_ev_per_ball(1)` is EXACTLY what the mode returns — the one mode whose
# RTP is set by pocket values instead of by a lever. It was CENTRE 0.1× / sides 0.3× (EV 95.396%), which
# left onedrop 0.30% under the 95.70% every other mode is tuned to; combined with the ±0.2-0.3% sampling
# noise on the published low-tier LUTs, that systematic gap is what pushed the cross-mode RTP spread over
# Stake's 0.50% limit (measured 0.66%). Re-check with `rtp_audit.py` (it reports this tier in closed
# form) after ANY change to these values.
#
# ⚠️ WHY THE 1.5× POCKETS AND NOT THE MIDDLE. The three centre pockets look like the natural dial, but
# they are hit 20.947% (centre) and 36.658% (the pair either side), so ONE DECIMAL PLACE there is worth
# 2.09% and 3.67% of RTP — a 2-4 point instrument for a 0.30% correction. No one-decimal pair lands
# within 1.2% of target (the old 0.1/0.3 board was itself the best of them), and the closest clean pair
# at all, 0.25×/0.2×, needs a two-decimal pocket label. The 1.5× pockets are hit 3x less often, so they
# resolve 3x finer. This is also the SMALLEST possible departure from the shared board — two pockets,
# one decimal, and the whole middle of the board keeps the meaning it has on every other tier.
# ⚠️ The centre is NOT flagged `hitSpinSlot` on this tier (there is no spin meter to feed). It pays the
# board's 0× either way, so the flag's absence is invisible in the payout — keep it that way regardless:
# a tier with no meter must not report meter hits. Mirror in apps/plinko game-logic/boardMultipliers.ts.
ONE_BALL_BOARD_SLOT_MULTIPLIERS = [100, 50, 20, 5, 2.0, 0.4, 0.2, 0, 0.2, 0.4, 2.0, 5, 20, 50, 100]

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
# 6 → 7 (rarer natural fire) to reopen headroom.
#
# ⚠️ RE-SOLVED WITH `rtp_audit.py` (was 0.00283 / 0.00253 / 0.01350). Those values came from
# `measure_tuning_capped.py`, which AVERAGES SAMPLED PAYOUTS: at its sample counts the board's 100×
# corners leave ~0.2% of noise on the normal stratum's mean, and this lever is ~11 RTP points per 0.001
# of quota, so that noise mis-solved the low tiers badly — the published LUTs came out tendrop 95.01% and
# twentydrop 95.38%, and that miss is most of the 0.66% cross-mode RTP spread Stake rejected (limit
# 0.50%). `rtp_audit.py` takes the fire rates from the binomial in CLOSED FORM and folds the board in as
# its exact analytic EV × the ball count, so it reads each tier to ±0.01%; it puts the OLD quotas at
# 95.233% / 95.439% / 95.739%, confirmed against a 400k/200k brute-force mixture sim. These quotas are
# its solution for 95.700%. Re-solve with `rtp_audit.py`, NOT `measure_tuning_capped.py`, after any
# change to the bonus, the ladder, the entry wheel or `BONUS_METER_TIER`.
#
# ⚠️ FLAT-RATE DESIGN (Aug 2026). The quota is no longer a per-tier fine-tune around whatever the meter
# happened to fire at — every tier is now pinned to the SAME total bonus incidence, 2.000% per bet:
#
#     P(book contains >= 1 bonus) = 1 - (1 - p_trigger)(1 - p_chain) = 0.02000
#
# where `p_chain = P(free spin fires) x P(BONUS segment)` is the free-spin wheel chaining a bonus, and
# `p_trigger = quota + (1 - quota) x P(Binomial(balls, BONUS_PEG_HIT_PROB) >= BONUS_METER_TIER max)` is
# the meter path. The chain differs per tier (0.101% / 0.169% / 0.565%), so the meter path is solved
# DOWN to compensate — that is why the trigger column below is not itself flat:
#
#     tier   p_chain    p_trigger   meter max -> natural   quota      TOTAL
#      10    0.1011%     1.9008%      6 -> 0.3669%        0.01540    2.000%
#      20    0.1693%     1.8338%      8 -> 1.7707%        0.00064    2.000%
#      50    0.5653%     1.4428%     16 -> 1.2024%        0.00243    2.000%
#
# ⚠️ 2% IS NEAR THE CEILING, NOT AN ARBITRARY DIAL. The whole feature budget is
# `TARGET_RTP - board_ev_per_ball` = 6.07 RTP points on every tier, which pins
# `trigger_rate x E[bonus payout / bet] ~= 0.0607`. The bonus's cheapest possible outcome is one
# 20-ball wedge = 17.93x, so the 10-ball tier can afford at most 0.0607 x 10 / 17.93 = 2.98% of them
# even with the wheel pinned to all-20s. A "flat 5%" reads 99.32% RTP there and is unreachable under
# any weighting — it needs new wedge VALUES or a lower board. Do not raise this rate without
# re-deriving that ceiling.
BONUS_IN_DROP_RATE: dict[int, float] = {
    1: 0.0,  # FEATURE-FREE tier: no bonus stratum is published for onedrop at all.
    10: 0.01540,
    20: 0.00064,
    50: 0.00243,
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
#
# ⚠️ FLAT-RATE DESIGN (Aug 2026): `max` is now chosen as the SMALLEST bar whose natural fire rate sits
# at or below that tier's required `p_trigger` (see BONUS_IN_DROP_RATE), so the quota only ever tops the
# meter UP and never has to be negative. 10 -> 6 (0.3669%), 20 -> 8 (1.7707%), 50 -> 16 (1.2024%).
# Note the 20-ball bar lands almost exactly on target (quota 0.00064) while the 10-ball bar overshoots
# downward — 6 gives 0.3669% against a 1.9008% requirement, so ~81% of 10-ball bonuses arrive via the
# quota stratum rather than organically. That is unchanged in KIND from before (the old 10-ball split
# was 0.044% organic against a 0.323% quota) and still not a meter bypass: `ensure_coin_pegs_fill_meter`
# fills those drops' coin pegs so the meter completes 0 -> max from real hits either way.
BONUS_METER_TIER: dict[int, dict[str, float]] = {
    10: {"max": 6, "start_ratio": 0.0},
    20: {"max": 8, "start_ratio": 0.0},
    50: {"max": 16, "start_ratio": 0.0},
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


# Bonus-roulette LANDING WEIGHTS, per balls-per-drop tier (index-aligned with BONUS_WHEEL_FREE_BALLS).
#
# ⚠️ THE PAINTED VALUES NEVER CHANGE — only how often each wedge is landed on. This is the same device
# the free-spin wheel already uses (`FREE_SPIN_WEIGHTS`: 8 equal visual slices, weighted landing), and
# it is what makes a FLAT per-tier bonus trigger rate affordable at all.
#
# ⚠️ WHY THE WEIGHTS MUST BE PER-TIER. A bet costs `balls_per_drop`, but a bonus awards the SAME
# absolute ball count no matter which tier fired it — so one bonus costs 5x more RTP on a 10-ball bet
# than on a 50-ball bet. The whole feature budget is only `TARGET_RTP - board_ev_per_ball` = 6.07 RTP
# points on EVERY tier, which pins the product
#
#     trigger_rate x E[bonus payout, as a multiple of the bet]  ~=  0.0607
#
# A flat trigger rate therefore forces E[bonus payout / bet] to be flat too, and the only in-bounds
# lever for that (wedge values, pocket multipliers and level-up rewards all fixed) is the landing
# weight. Low tiers get a profile skewed to the small wedges; high tiers stay near uniform.
#
# ⚠️ THE WHEEL'S SMALLEST WEDGE IS A HARD FLOOR. Mean entry can never go below 20 balls, so the flat
# rate itself is capped: at 20 balls a bonus is worth 17.93x, and the 10-ball tier can only afford
# 0.0607 x 10 / 17.93 = 2.98% of them. A "flat 5%" is arithmetically impossible on 10-ball under any
# weighting — it reads 99.32% RTP even with the wheel pinned to all-20s. Re-derive with rtp_audit.py
# before raising the rate; do not interpolate.
#
# Tiers absent here (1-ball, and every buy mode — which overrides the entry with `entry_balls`) fall
# back to UNIFORM, i.e. exactly the pre-weighting behaviour. Mirror in apps/plinko
# game-logic/constants.ts BONUS_WHEEL_WEIGHTS.
#
# Weights are per-10,000, so `weight / 100` reads directly as the landing percentage. EVERY wedge keeps
# a non-zero weight — the 10-ball tier's 100 lands 1 spin in 10,000, not never.
#
#   10-ball  mean 24.70 balls   100:0.01% 90:0.02% 80:0.07% 70:0.23% 60:0.71% 50:2.23% 40:6.96%
#                               30:21.76% 20:68.01%
#   20-ball  mean 46.00 balls   100:3.86% 90:4.83% 80:6.04% 70:7.55% 60:9.45% 50:11.82% 40:14.79%
#                               30:18.51% 20:23.15%
#   50-ball  mean 77.80 balls   100:27.66% 90:20.53% 80:15.24% 70:11.32% 60:8.40% 50:6.24% 40:4.63%
#                               30:3.44% 20:2.55%
#
# ⚠️ THE TIERS SKEW IN OPPOSITE DIRECTIONS, and that is the design, not a bug: a 50-ball bet costs 5x a
# 10-ball bet, so it can afford 5x the bonus at the same trigger rate. Big-ball players land the big
# wedges; small-ball players land the small ones. This matches the per-tier wincap ladder's existing
# story ("more balls / higher risk => bigger potential payouts") and the per-tier boards already in
# COEFFICIENT_SETS_BY_BALLS. The rules copy should say the award scales with the ball count.
BONUS_WHEEL_WEIGHTS_BY_BALLS: dict[int, list[float]] = {
    10: [1, 2, 7, 23, 71, 223, 696, 2176, 6801],
    20: [386, 483, 604, 755, 945, 1182, 1479, 1851, 2315],
    50: [2766, 2053, 1524, 1132, 840, 624, 463, 344, 255],
}


def bonus_wheel_weights(balls_per_drop: int = 0) -> list[float]:
    """Landing weights for this tier's bonus roulette (uniform when the tier has no profile)."""
    weights = BONUS_WHEEL_WEIGHTS_BY_BALLS.get(int(balls_per_drop))
    if not weights or len(weights) != len(BONUS_WHEEL_FREE_BALLS):
        return [1.0] * len(BONUS_WHEEL_FREE_BALLS)
    return [float(w) for w in weights]


def bonus_wheel_mean_entry(balls_per_drop: int = 0) -> float:
    """Mean entry free balls for this tier's weighted wheel (the RTP-relevant summary)."""
    values = bonus_wheel_free_balls(balls_per_drop)
    weights = bonus_wheel_weights(balls_per_drop)
    total = math.fsum(weights)
    return math.fsum(v * w for v, w in zip(values, weights)) / total if total > 0 else 0.0


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
# the Crimson Plinko rule-set PDF (80/100/150/250). Because the cost is FIXED to the PDF, `entry_balls`
# (coarse) and `peg_hit_prob` (fine) are TUNED so RTP = mean(min(bonus_payout, wincap)) / cost ≈
# TARGET_RTP. `entry_balls` is a COARSE lever only: one ball is worth ~1.1% RTP on the standard tier
# (0.896 / 80), so it cannot land a tier on target by itself — that is `peg_hit_prob`'s job.
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
# 0. `wincap` sits inside each tier's ORGANIC (corner-luck + shallow-level) payout tail so the advertised
# max win is reachably produced while barely clipping EV. One published mode per tier, `buy{key}`. Mirror
# in apps/plinko game/config.ts + game/plinkoBetMode.ts.
# Solve with rtp_audit.py; pin via run.py + compliance_report.py.
# ⚠️ THE WINCAPS ARE ADVERTISED FIGURES, RAISED/LOWERED ON REQUEST (was 260/290/330/480). Each new cap
# still sits inside the tier's ORGANIC payout tail, so the advertised max win stays achievable — measured
# hit rates at n=70,000/tier: 250× 1/3,043, 300× 1/10,000, 350× 1/2,692, 500× 1/3,043, all far above the
# 1/20,000,000 floor, with raw maxima of 294/336/436/598 seen above each cap. Moving a cap by ±10-20×
# barely moves RTP (it only re-prices the ~0.01-0.04% of bonuses that reach it), so the `peg_hit_prob`
# column below is what actually holds each tier at TARGET_RTP.
#
# ⚠️ `peg_hit_prob` RE-SOLVED WITH `rtp_audit.py` (was 0.0447/0.0292/0.0252/0.0283, which measured
# 95.645/95.668/95.718/95.645% at these caps). The lever is ~3.2 RTP points per 0.001 and the response is
# CONVEX in probability (the ×10 award cascade accelerates), so solve it from the LOCAL derivative at the
# current value — a straight-line fit across a ±8% sweep reads ~0.07% off on the superfury tier. These
# values measure 95.689 / 95.659 / 95.706 / 95.762% (rtp_audit.py, n=150,000/tier).
#
# ⚠️ DON'T CHASE THE LAST ~0.05% HERE. `rtp_audit.py`'s printed SE only covers the ball-count variance,
# and a bought bonus's ball count is HEAVY-TAILED (a rare level 5-6 adds 160-320 balls at once), so the
# sample variance understates the true one and the real uncertainty per buy tier is ~±0.05%. Two
# independent reads of superfury 0.00016 apart in probability disagreed by 0.12% for that reason. The
# tier-to-tier residual above is inside that band; re-solving on it just moves noise around.
# Re-run `rtp_audit.py` after any nudge; do not interpolate.
BUY_BONUS_TIER_DEFS: list[dict] = [
    {"key": "standard", "entry_balls": 72, "cost": 80.0, "wincap": 250.0, "head_start": 0.0, "peg_hit_prob": 0.04487},
    {"key": "enhanced", "entry_balls": 95, "cost": 100.0, "wincap": 300.0, "head_start": 0.0, "peg_hit_prob": 0.02931},
    {"key": "premium", "entry_balls": 145, "cost": 150.0, "wincap": 350.0, "head_start": 0.0, "peg_hit_prob": 0.02515},
    {"key": "superfury", "entry_balls": 239, "cost": 250.0, "wincap": 500.0, "head_start": 0.0, "peg_hit_prob": 0.02846},
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
# so never interpolate a base-mode increase; re-measure it (rtp_audit.py).
#
# BUY MODES take a much lower value (see BUY_BONUS_TIER_DEFS) because their entry batch is 72–239
# FIXED balls; at 0.18 they would run away to level 9. Measured through the REAL simulate_bonus_round
# (rtp_audit.py, n=150k/tier): buystandard 95.689%, buyenhanced 95.659%, buypremium 95.706%,
# buysuperfury 95.762% — mean level 1.15–1.85, largest book 299 balls, and every advertised max win
# reachable (1/2,273–1/11,494 of buys). ALL EIGHT published modes now span 95.659%–95.762%, a 0.103%
# cross-mode spread against Stake's 0.50% limit (it was 0.66%).
# The lever is ~3-4 RTP points per 0.01 of probability; re-run rtp_audit.py after any nudge.
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


# IN-BONUS coin-peg probability, keyed by published mode — DECOUPLED from the drop-meter value above.
#
# ⚠️ WHY THE SPLIT. `BONUS_PEG_HIT_PROB_BY_MODE` drives TWO unrelated things that used to share one
# number: (a) how fast the PAID DROP's bonus-trigger meter fills, and (b) how fast a BONUS ROUND's balls
# climb the level-up ladder. Once the trigger rate is pinned flat (see BONUS_IN_DROP_RATE), those two
# pull in opposite directions — the trigger wants a lively 0.18 meter, while the flat rate's tiny EV
# budget wants the ladder climbed slowly. So (a) stays on `bonus_peg_hit_prob` and (b) moves here.
#
# This changes nothing for the BUY modes: their paid drop is empty, so only (b) ever applied to them,
# and any mode absent from this map falls back to its `BONUS_PEG_HIT_PROB_BY_MODE` value.
#
# ⚠️ The level-up REWARDS (`BONUS_LEVEL_BALLS`) and the ladder (`BONUS_LEVELUP_PEG_HITS_BY_LEVEL`) are
# UNTOUCHED by this — only how often a falling bonus ball delivers a hit. The ×10 award ladder
# self-sustains just above 0.18 (at 0.25 the earned bonus explodes: mean payout 125 → 1,519, P(level 9)
# 0.001% → 29.7%), so never interpolate upward; re-measure with rtp_audit.py.
#
# Base modes drop from the old shared 0.18 to these, which is what pays for the flat 2% trigger. The
# 50-ball tier keeps the fastest climb (0.16, avg level 2.89) because its bet funds the most bonus; the
# low tiers climb slowly (0.10, avg level 1.11-1.50) since their whole bonus budget is ~2.8x the bet.
# The buy modes are deliberately ABSENT — they fall back to their own `BONUS_PEG_HIT_PROB_BY_MODE`
# value, which was always an in-bonus number (their paid drop is empty), so nothing about them moves.
BONUS_ROUND_PEG_HIT_PROB_BY_MODE: dict[str, float] = {
    "tendrop": 0.10,
    "twentydrop": 0.10,
    "fiftydrop": 0.16,
}


def bonus_round_peg_hit_prob(mode_name: str) -> float:
    """Per-ball coin-peg probability INSIDE a bonus round for a published mode. Falls back to that
    mode's drop-meter probability, which is the pre-split behaviour."""
    name = str(mode_name)
    if name in BONUS_ROUND_PEG_HIT_PROB_BY_MODE:
        return float(BONUS_ROUND_PEG_HIT_PROB_BY_MODE[name])
    return bonus_peg_hit_prob(name)


def _js_round(value: float) -> int:
    """Match apps/plinko `Math.round` (round half up, not Python banker's `round`)."""
    return int(math.floor(value + 0.5))


def spin_in_drop_for_balls(balls_per_drop: int) -> bool:
    """True for tiers that fire the free spin in-drop (10/20/50); False for 1-ball (no free spin)."""
    return int(balls_per_drop) in SPIN_METER_TIER


def spin_pocket_active_for_balls(balls_per_drop: int) -> bool:
    """True where the centre pocket is the SPIN pocket (fills the free-spin meter, pays the board's 0×).
    False on the 1-ball tier, which has no free-spin meter, so balls landing centre there are NOT
    flagged `hitSpinSlot`. The payout is identical either way — that board's centre is 0 too — but a
    tier with no meter must not report meter hits."""
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
