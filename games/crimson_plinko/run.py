"""Generate books and configs for crimson_plinko (Stake Web SDK apps/plinko)."""

import csv
import json
import os

from game_config import GameConfig
from gamestate import GameState
from src.state.run_sims import create_books
from src.write_data.write_configs import generate_configs

from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    BUY_BONUS_TIER_DEFS,
    BONUS_IN_DROP_RATE,
    BONUS_LEVEL_BALLS,
    BONUS_LEVELUP_PEG_HITS_BY_LEVEL,
    BONUS_METER_MAX,
    BONUS_METER_TIER,
    BONUS_PEG_HIT_PROB,
    BONUS_PEG_HIT_PROB_BY_MODE,
    BONUS_ROUND_PEG_HIT_PROB_BY_MODE,
    BONUS_WHEEL_FREE_BALLS,
    BONUS_WHEEL_WEIGHTS_BY_BALLS,
    COEFFICIENT_SETS,
    COEFFICIENT_SETS_BY_BALLS,
    FREE_SPIN_SEGMENTS,
    FREE_SPIN_WEIGHTS,
    SPIN_METER_MAX,
    SPIN_METER_TIER,
    bet_mode_for_balls_per_drop,
    buy_bonus_mode_name,
)
from publish_verify import sync_all_publish_files


def _lut_mean_multiplier(lut_path: str) -> float:
    """Mean payout multiplier from a lookup table (col 3 is payout ×100; weights uniform = 1)."""
    total = 0.0
    weight = 0.0
    with open(lut_path, encoding="UTF-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            w = float(row[1])
            total += w * float(row[2])
            weight += w
    if weight <= 0:
        return 0.0
    return (total / weight) / 100.0


def verify_onedrop_stratified(gamestate: GameState, *, only_modes: set[str] | None = None) -> None:
    """Fail the run if the 1-ball LUT is not the exact board EV.

    The stratified layout (`GameCalculations.stratified_rate_index`) leaves the onedrop LUT mean within
    ~1e-6 of the closed-form 1-ball board EV at 1M books. The check allows max_payout / N (1e-4 at 1M):
    a randomly sampled onedrop carries ~3e-3 of noise at that count, so anything past the allowance
    means the layout was not armed (e.g. the SDK changed how it slices a mode across threads and the
    planned total no longer matches the books actually written) and the mode is back to a noisy sample."""
    from math import comb

    from plinko_data import ONE_BALL_BOARD_SLOT_MULTIPLIERS

    mode = bet_mode_for_balls_per_drop(1)
    if only_modes and mode not in only_modes:
        return
    manifest_path = gamestate.output_files.configs["paths"]["manifest"]
    with open(manifest_path, encoding="UTF-8") as f:
        manifest = json.load(f)
    entry = next((m for m in manifest.get("modes", []) if m["name"] == mode), None)
    if entry is None:
        return
    lut = os.path.join(gamestate.output_files.publish_path, entry["weights"])
    rows = 0
    with open(lut, encoding="UTF-8") as f:
        for row in csv.reader(f):
            rows += bool(row)
    board = list(ONE_BALL_BOARD_SLOT_MULTIPLIERS)
    row_count = 14
    exact_ev = sum(comb(row_count, k) / 2**row_count * board[k] for k in range(len(board)))
    lut_mean = _lut_mean_multiplier(lut) / float(entry["cost"])
    tolerance = max(board) / max(rows, 1)
    if abs(lut_mean - exact_ev) > tolerance:
        raise RuntimeError(
            f"{mode} LUT mean {lut_mean:.6f} is {abs(lut_mean - exact_ev):.2e} off the exact board EV "
            f"{exact_ev:.6f} (tolerance {tolerance:.2e} for {rows} rows): the stratified 1-ball layout "
            "did not take effect. Check GameStateOverride.run_sims against src/state/run_sims.py."
        )
    print(f"{mode}: {rows} books, LUT RTP {lut_mean * 100:.4f}% == exact board EV {exact_ev * 100:.4f}% "
          f"(|diff| {abs(lut_mean - exact_ev):.2e})")


def report_mode_rtp(gamestate: GameState) -> None:
    """Print per-mode RTP (mean payout / index.json cost) — the value the Stake math summary shows.

    FREE feature modes (index cost 0 — the auto-fired bonus) are listed but EXCLUDED from the
    cross-mode spread: they are free rounds (no player debit), not priced bets, so `payout / 0` is
    not a meaningful RTP to band-check against the paid base modes.
    """
    manifest_path = gamestate.output_files.configs["paths"]["manifest"]
    with open(manifest_path, encoding="UTF-8") as f:
        manifest = json.load(f)
    print("\nPer-mode RTP (mean payout multiplier / published cost):")
    rtps = []
    for mode in manifest.get("modes", []):
        lut = os.path.join(gamestate.output_files.publish_path, mode["weights"])
        mean_mult = _lut_mean_multiplier(lut)
        cost = float(mode["cost"])
        if cost <= 0:
            print(f"  {mode['name']:16} mean_mult={mean_mult:10.4f}  cost={cost:10.4f}  RTP=   FREE (excluded)")
            continue
        rtp = mean_mult / cost
        rtps.append(rtp)
        print(f"  {mode['name']:16} mean_mult={mean_mult:10.4f}  cost={cost:10.4f}  RTP={rtp*100:7.2f}%")
    if rtps:
        spread = (max(rtps) - min(rtps)) * 100
        print(f"  cross-mode spread (max-min, paid modes) = {spread:.3f}%  [target < 1.00%]")


def write_plinko_fe_config(gamestate: GameState) -> None:
    """Extend standard FE config with plinko coefficient + feature tables.

    These keys are the client's single source of truth for feature tunables
    (apps/plinko reads them from `game/config.ts` defaults, overridable here).
    """
    path = os.path.join(
        gamestate.output_files.config_path,
        f"config_fe_{gamestate.config.game_id}.json",
    )
    with open(path, encoding="UTF-8") as f:
        fe = json.load(f)
    fe["coefficientSets"] = COEFFICIENT_SETS
    # Per-balls-per-drop board override (only tiers that differ from `coefficientSets` are listed). The
    # 1-ball tier is feature-free, so nothing but the board funds it; its two 1.5× pockets pay 2.0×
    # instead. Mirror in apps/plinko game-logic/boardMultipliers.ts BOARD_SLOT_MULTIPLIERS_BY_BALLS.
    fe["coefficientSetsByBalls"] = {
        str(balls): sets for balls, sets in COEFFICIENT_SETS_BY_BALLS.items()
    }
    fe["minBet"] = gamestate.config.min_bet
    fe["maxBet"] = gamestate.config.max_bet
    fe["spinMeterMax"] = SPIN_METER_MAX
    fe["bonusMeterMax"] = BONUS_METER_MAX
    fe["bonusPegHitProb"] = BONUS_PEG_HIT_PROB
    # PER-MODE coin-peg probability. All modes share one in-bonus level-up ladder; this is the lever
    # that keeps each of them at TARGET_RTP under it (base modes 0.18, buys much lower). Informational
    # for the client — every coin-peg hit is already authored per ball in the book.
    fe["bonusPegHitProbByMode"] = dict(BONUS_PEG_HIT_PROB_BY_MODE)
    # SHARED in-bonus level-up ladder: coin-peg hits needed to leave level L, keyed by level string.
    # Identical in every mode. The book also carries it per level on `bonusRound.levelupPegs`; this is
    # the client's fallback for a book that omits the field.
    fe["bonusLevelupPegs"] = {
        str(level): pegs for level, pegs in BONUS_LEVELUP_PEG_HITS_BY_LEVEL.items()
    }
    fe["freeSpinSegments"] = list(FREE_SPIN_SEGMENTS)
    # Free-spin wheel landing WEIGHTS (index-aligned to freeSpinSegments). The wheel shows 8 equal
    # slices but lands weighted so 100X / BONUS are rare (mirror in constants.ts FREE_SPIN_WEIGHTS).
    fe["freeSpinWeights"] = list(FREE_SPIN_WEIGHTS)
    # Bonus wheel ABSOLUTE free-ball awards (Aztec values, tier-independent). The client renders these
    # directly on the data-driven `bonus-roulette-wheel-empty.png` (mirror in constants.ts).
    fe["bonusWheelFreeBalls"] = list(BONUS_WHEEL_FREE_BALLS)
    # Bonus wheel LANDING WEIGHTS per balls-per-drop tier (index-aligned to bonusWheelFreeBalls,
    # per-10,000). The painted values above never change; only how often each wedge is landed on. This
    # is what makes the flat 2% bonus trigger affordable — see BONUS_WHEEL_WEIGHTS_BY_BALLS. Tiers
    # absent here land uniformly. Mirror in constants.ts BONUS_WHEEL_WEIGHTS.
    fe["bonusWheelWeightsByBalls"] = {
        str(balls): [float(w) for w in weights]
        for balls, weights in BONUS_WHEEL_WEIGHTS_BY_BALLS.items()
    }
    # IN-BONUS coin-peg probability per mode, decoupled from `bonusPegHitProbByMode` (which fills the
    # paid drop's trigger meter). Modes absent here fall back to that value. Informational for the
    # client — every coin-peg hit is authored per ball in the book. Mirror in constants.ts.
    fe["bonusRoundPegHitProbByMode"] = dict(BONUS_ROUND_PEG_HIT_PROB_BY_MODE)
    # Per-tier in-drop bonus rate (the folded-bonus quota) — informational mirror for the client.
    fe["bonusInDropRate"] = {str(balls): rate for balls, rate in BONUS_IN_DROP_RATE.items()}
    # Level-up table keyed by level string (JSON object) for the client to mirror.
    fe["bonusLevelBalls"] = {str(level): balls for level, balls in BONUS_LEVEL_BALLS.items()}
    # Per-drop BONUS meter (max + start) per balls-per-drop tier (Option A). The client resets the meter
    # each round to this start and fills it in-drop; reaching max fires the bonus. 1-ball is absent — its
    # meter is purely cosmetic and that tier has NO bonus at all (its quota is 0 too). Mirror in
    # constants.ts BONUS_METER_TIER.
    fe["bonusMeterTier"] = {
        str(balls): {"max": int(cfg["max"]), "startRatio": cfg["start_ratio"]}
        for balls, cfg in BONUS_METER_TIER.items()
    }
    # Per-drop free-spin meter (max + start) per balls-per-drop tier; the client uses this to reset
    # the meter each round and to re-seed the meter UI when the tier is switched. 1-ball is absent
    # (no free spin). Mirror in apps/plinko game-logic/constants.ts SPIN_METER_TIER.
    fe["spinMeterTier"] = {
        str(balls): {"max": int(cfg["max"]), "startRatio": cfg["start_ratio"]}
        for balls, cfg in SPIN_METER_TIER.items()
    }
    # No separate bonus mode anymore — the bonus is folded into the base modes (fires in-drop), so there
    # are no free-trigger costs to zero here. Only the 4 base modes are published (each cost = ball count).
    with open(path, "w", encoding="UTF-8") as f:
        json.dump(fe, f, indent=4)


if __name__ == "__main__":
    # RAM control: each of `num_threads` worker processes holds a batch of books in memory at once, so
    # peak RAM ≈ num_threads × PLINKO_BATCH × avg-book-size. The escalating bonus (frequent leveling) makes
    # books bigger, so drop PLINKO_THREADS (→2 or 1) and/or PLINKO_BATCH if `make run` OOMs the machine.
    num_threads = max(1, int(os.getenv("PLINKO_THREADS", "4")))
    batching_size = int(os.getenv("PLINKO_BATCH", "20000"))
    # Local dev defaults to uncompressed books (.jsonl) for sync-math-books.
    # Set PLINKO_BOOKS_COMPRESSION=1 when generating Stake Engine publish payloads.
    compression = os.getenv("PLINKO_BOOKS_COMPRESSION", "0").lower() in {"1", "true", "yes"}
    profiling = False

    # Base mode RTP = board EV (+ the rare in-drop free spin). Convergence is set by the heavy 100x corner
    # pocket (p≈6e-5), so low tiers need many sims (mean over uniform weights); bump them (or use
    # PLINKO_BOOKS_COMPRESSION=1) if the ±0.5% band/spread is noisy on the low tiers.
    #
    # ⚠️ SIM COUNTS ARE A COMPLIANCE INPUT, NOT JUST A RUNTIME KNOB. Stake reads each mode's RTP off the
    # PUBLISHED LUT (mean payout / cost, uniform weights — see `make_lookup_tables`), so what it grades is
    # an ESTIMATE with standard error sd_book/sqrt(n). Measured per-book sd of payout/cost is onedrop
    # 3.27, tendrop 1.31, twentydrop 0.98, fiftydrop 0.62, buys 0.22-0.38 (the 1-ball tier is worst
    # because its whole book is one ball, and a lone 100x corner moves the mean a long way — a 200k-sim
    # onedrop run has been observed landing 0.38% off its board's exact EV, which is only half of the
    # 0.73% standard error it carries at that count).
    #
    # At the previous counts (1M/400k/240k/400k + 200k buys) the SEs were 0.32%/0.21%/0.20%/0.10% and
    # ~0.05-0.09%, which puts the RANGE across 8 independent estimates at a mean of 0.48% and gives a
    # ~40% chance of BREACHING the 0.50% cross-mode limit even with every mode's TRUE RTP identical. The
    # feature-tier counts below hold each of them at SE <= ~0.10%, which drops the mean range to 0.26% and
    # the breach probability to ~0.4% (onedrop contributes NO sampling error any more — see the stratified
    # layout note below). RAM scales with threads x PLINKO_BATCH x book size, not with total sims.
    # ⚠️ Do NOT trim the feature tiers back to "save time" — re-derive them from sd/sqrt(n) if the math changes.
    # ⚠️ HARD PLATFORM CEILING: 10,000,000 results PER MODE. Over it the ACP publish is rejected outright
    # with `ERR_MATH_OUTSIDE_RANGE` ("Too many simulations!"). That ceiling is NOT a serving guarantee:
    # the RGS's `/wallet/play` cost grows with the mode's LUT row count and it gives up at ~15 s. Measured
    # on math v63 (2026-09-03): 1.8M rows answer in 0.3-4.4 s, 1M rows in 0.3-1.6 s, but the 9.6M-row
    # onedrop LUT took 10.6-15.4 s and two plays in three came back HTTP 500 `ERR_GEN` — every 1-ball bet
    # died in the client's fatal error modal. Keep EVERY mode at roughly <= 1-2M rows.
    #
    # onedrop no longer needs a huge count to be quiet: the 1-ball tier is feature-free, its pocket is a
    # plain 14-step binomial walk, and `GameCalculations.stratified_rate_index` lays its books out by
    # EXACT quota (N × p_k books per pocket, rounded so the mean payout is preserved) instead of drawing
    # them, so the LUT mean equals the closed-form board EV to ~1e-6 at 1M — no sampling error at any N. The
    # count is therefore chosen for the RGS alone: 1,000,000 matches twentydrop, which serves in ~1 s,
    # and still holds ~120 copies of the 100× corner (p = 2/16384), far above the 1/20,000,000 max-win
    # floor. `verify_onedrop_stratified` below fails the run if the LUT ever drifts off that EV.
    #
    # ⚠️ A RE-RUN IS NOT A RE-ROLL. `GeneralGameState.reset_seed` seeds `random` with `sim + 1`, so the
    # books — and therefore each FEATURE mode's LUT RTP — are a deterministic function of the sim COUNT.
    # Running `make run` again at the same counts reproduces the same numbers exactly. So check the
    # spread with `compliance_report.py` BEFORE uploading, and if a feature mode landed unluckily the
    # lever is to change ITS count (e.g. tendrop 1_800_000 -> 1_790_000), which draws a different sample.
    # Re-running unchanged will not move it. (onedrop is exact at every count and needs no such nudge.)
    # ⚠️ RUN A PUBLISH BUILD WITH PLINKO_BOOKS_COMPRESSION=1. The uncompressed `books_<mode>.json` format
    # is a single JSON ARRAY with no per-line structure, so `publish_verify._resolve_book_payouts` has to
    # `json.load` it whole; at publish counts the feature tiers are gigabytes and will run out of memory.
    # The compressed path is line-delimited and streams (see `_iter_books`). The uncompressed default is
    # only for local dev, where `apps/plinko`'s `sync-math-books` wants a readable `.json` — and there
    # you want PLINKO_SIM_DIV set anyway.
    sims_div = max(1, int(os.getenv("PLINKO_SIM_DIV", "1")))  # set >1 for a fast smoke test
    # FOLDED-BONUS DESIGN: only 4 base modes. Each mode mixes a normal-drop stratum (quota 1-rate) and a
    # rare force_bonus stratum (quota = BONUS_IN_DROP_RATE). The folded bonus is RARE + HIGH-VARIANCE
    # (level-ups, big ball dumps), so the feature tiers need heavy sims to converge the bonus add. onedrop
    # is the exception: it has NO bonus stratum at all, and its books are laid out by exact quota (see
    # above), so its count only has to keep the RGS fast.
    # fiftydrop: was 1.5M ONLY to surface the rare 400× max-win spike (~1/165k on the old FLAT-bar bonus).
    # The ESCALATING level-up made bonuses bigger + frequent, so tier-50 now hits the 400× cap ~1/4,900
    # (≈33× more often) — the spike appears in ~120 books at 400k. Cut 1.5M → 400k: still converges RTP +
    # the achievable max-win, and (with 50 balls/drop) it is BY FAR the heaviest mode for RAM, so this is
    # the single biggest `make run` memory saving. Bump back up only if the observed fiftydrop max < 400×.
    # 10/20 are sized by the SE arithmetic above (sd/sqrt(n) <= ~0.10%); 50 already met it at 400k.
    base_sims = {1: 1_000_000, 10: 1_800_000, 20: 1_000_000, 50: 400_000}
    num_sim_args = {
        bet_mode_for_balls_per_drop(balls): max(1000, base_sims[balls] // sims_div)
        for balls in BALLS_PER_DROP_OPTIONS
    }
    # BUY BONUS modes (4 = one per tier) are always-bonus + high-variance (deep level-ups), so they need
    # heavy sims to converge their RTP and surface the max-win spike at the cap (>= 1/20M).
    buy_sims = 200_000
    for tier in BUY_BONUS_TIER_DEFS:
        num_sim_args[buy_bonus_mode_name(tier["key"])] = max(1000, buy_sims // sims_div)

    # Dev aid: PLINKO_ONLY_MODES=buystandard,buysuperfury restricts the SIM step to those modes (existing
    # books for the others are reused by publish/config). Lets you re-sim just the buy modes when tuning
    # entry/wincap without re-running the slow base-mode sims. Empty = sim all modes.
    only_modes = {m.strip() for m in os.getenv("PLINKO_ONLY_MODES", "").split(",") if m.strip()}
    if only_modes:
        num_sim_args = {m: n for m, n in num_sim_args.items() if m in only_modes}

    # Set PLINKO_RUN_SIMS=0 to only rebuild configs/publish files from existing books + LUTs.
    run_conditions = {"run_sims": os.getenv("PLINKO_RUN_SIMS", "1").lower() not in {"0", "false", "no"}}

    config = GameConfig()
    gamestate = GameState(config)

    if run_conditions["run_sims"]:
        create_books(
            gamestate,
            config,
            num_sim_args,
            batching_size,
            num_threads,
            compression,
            profiling,
        )
    sync_all_publish_files(gamestate)
    generate_configs(gamestate)
    write_plinko_fe_config(gamestate)
    report_mode_rtp(gamestate)
    verify_onedrop_stratified(gamestate, only_modes=only_modes or None)
    print(f"Done. Books: {gamestate.output_files.book_path}")
    print(f"Publish: {gamestate.output_files.publish_path}")
    print(f"FE config: {gamestate.output_files.config_path}")
