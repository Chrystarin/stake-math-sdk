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
    BONUS_LEVEL_BALLS,
    BONUS_METER_MAX,
    BONUS_PEG_HIT_PROB,
    BONUS_WHEEL_RELATIVE,
    COEFFICIENT_SETS,
    FREE_SPIN_SEGMENTS,
    METER_TIER_CONFIG,
    SPIN_METER_MAX,
    SPIN_METER_TIER,
    bet_mode_for_balls_per_drop,
    bonus_mode_for_balls,
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
    fe["minBet"] = gamestate.config.min_bet
    fe["maxBet"] = gamestate.config.max_bet
    fe["spinMeterMax"] = SPIN_METER_MAX
    fe["bonusMeterMax"] = BONUS_METER_MAX
    fe["bonusPegHitProb"] = BONUS_PEG_HIT_PROB
    fe["freeSpinSegments"] = list(FREE_SPIN_SEGMENTS)
    # Bonus wheel RELATIVE multipliers (avg ≈ 1). The client renders per-tier values = round(m × tier
    # balls) on the data-driven `bonus-roulette-wheel-empty.png` (mirror in constants.ts).
    fe["bonusWheelRelative"] = list(BONUS_WHEEL_RELATIVE)
    # Level-up table keyed by level string (JSON object) for the client to mirror.
    fe["bonusLevelBalls"] = {str(level): balls for level, balls in BONUS_LEVEL_BALLS.items()}
    fe["meterTierConfig"] = {
        str(balls): {"startRatio": cfg["start_ratio"], "maxRatio": cfg["max_ratio"]}
        for balls, cfg in METER_TIER_CONFIG.items()
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
    num_threads = 4
    batching_size = int(os.getenv("PLINKO_BATCH", "20000"))
    # Local dev defaults to uncompressed books (.jsonl) for sync-math-books.
    # Set PLINKO_BOOKS_COMPRESSION=1 when generating Stake Engine publish payloads.
    compression = os.getenv("PLINKO_BOOKS_COMPRESSION", "0").lower() in {"1", "true", "yes"}
    profiling = False

    # Base mode RTP = board EV (+ the rare in-drop free spin). Convergence is set by the heavy 100x corner
    # pocket (p≈6e-5), so low tiers need many sims (mean over uniform weights); bump them (or use
    # PLINKO_BOOKS_COMPRESSION=1) if the ±0.5% band/spread is noisy on the low tiers.
    sims_div = max(1, int(os.getenv("PLINKO_SIM_DIV", "1")))  # set >1 for a fast smoke test
    base_sims = {1: 400_000, 10: 200_000, 20: 120_000, 50: 80_000}
    num_sim_args = {
        bet_mode_for_balls_per_drop(balls): max(1000, base_sims[balls] // sims_div)
        for balls in BALLS_PER_DROP_OPTIONS
    }
    # Bonus modes are forced + SIZED (avg free balls ≈ tier, low variance), so they converge fast.
    for balls in BALLS_PER_DROP_OPTIONS:
        num_sim_args[bonus_mode_for_balls(balls)] = max(1000, 20_000 // sims_div)

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
    print(f"Done. Books: {gamestate.output_files.book_path}")
    print(f"Publish: {gamestate.output_files.publish_path}")
    print(f"FE config: {gamestate.output_files.config_path}")
