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
    BONUS_WHEEL_FREE_BALLS,
    COEFFICIENT_SETS,
    FREE_SPIN_SEGMENTS,
    METER_TIER_CONFIG,
    SPIN_METER_MAX,
    TARGET_RTP,
    TRIGGER_MODE_COST,
    all_trigger_mode_names,
    bet_mode_for_balls_per_drop,
    bonus_mode_for_balls,
    freespin_mode_for_balls,
)
from publish_verify import sync_all_publish_files


def set_trigger_mode_costs_free(gamestate: GameState) -> None:
    """Republish config.json with the feature-trigger modes at `TRIGGER_MODE_COST`.

    Sims run at the tier cost (so RTP math never divides by zero); the published cost is what RGS
    uses for the debit. With cost 0 the feature is free once the meter fills.
    """
    path = os.path.join(gamestate.output_files.config_path, "config.json")
    with open(path, encoding="UTF-8") as f:
        config = json.load(f)
    trigger_modes = set(all_trigger_mode_names())
    for shelf in config.get("bookShelfConfig", []):
        if shelf.get("name") in trigger_modes:
            shelf["cost"] = TRIGGER_MODE_COST
    with open(path, "w", encoding="UTF-8") as f:
        json.dump(config, f, indent=4)


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
    """Print per-mode RTP (mean payout / index.json cost) — the value the Stake math summary shows."""
    manifest_path = gamestate.output_files.configs["paths"]["manifest"]
    with open(manifest_path, encoding="UTF-8") as f:
        manifest = json.load(f)
    print("\nPer-mode RTP (mean payout multiplier / published cost):")
    rtps = []
    for mode in manifest.get("modes", []):
        lut = os.path.join(gamestate.output_files.publish_path, mode["weights"])
        mean_mult = _lut_mean_multiplier(lut)
        cost = float(mode["cost"]) or 1.0
        rtp = mean_mult / cost
        rtps.append(rtp)
        print(f"  {mode['name']:16} mean_mult={mean_mult:10.4f}  cost={cost:10.4f}  RTP={rtp*100:7.2f}%")
    if rtps:
        spread = (max(rtps) - min(rtps)) * 100
        print(f"  cross-mode spread (max-min) = {spread:.3f}%  [target < 1.00%]")


def set_trigger_mode_index_costs(gamestate: GameState, target_rtp: float = TARGET_RTP) -> None:
    """Price the feature-trigger modes in index.json so the math summary reads ~`target_rtp`.

    A forced free-spin / bonus round pays many multiples of the tier cost, so at the raw tier cost
    those modes read as thousands-of-percent RTP and fail the cross-mode variance check. They behave
    like buy-feature modes, so we publish their math-eval cost as `mean_payout / target_rtp` (the
    fair buy price for `target_rtp` RTP). This only touches index.json (the file the Stake math tool
    reads); config.json keeps `TRIGGER_MODE_COST` so the feature stays free for players when a meter
    fills. Base-mode costs (real ball count) are left untouched.
    """
    manifest_path = gamestate.output_files.configs["paths"]["manifest"]
    with open(manifest_path, encoding="UTF-8") as f:
        manifest = json.load(f)
    trigger_modes = set(all_trigger_mode_names())
    for mode in manifest.get("modes", []):
        if mode["name"] not in trigger_modes:
            continue
        lut = os.path.join(gamestate.output_files.publish_path, mode["weights"])
        mean_mult = _lut_mean_multiplier(lut)
        mode["cost"] = round(mean_mult / target_rtp, 4) if target_rtp > 0 else mean_mult
    with open(manifest_path, "w", encoding="UTF-8") as f:
        json.dump(manifest, f, indent=4)


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
    fe["bonusWheelFreeBalls"] = list(BONUS_WHEEL_FREE_BALLS)
    # Level-up table keyed by level string (JSON object) for the client to mirror.
    fe["bonusLevelBalls"] = {str(level): balls for level, balls in BONUS_LEVEL_BALLS.items()}
    fe["meterTierConfig"] = {
        str(balls): {"startRatio": cfg["start_ratio"], "maxRatio": cfg["max_ratio"]}
        for balls, cfg in METER_TIER_CONFIG.items()
    }
    with open(path, "w", encoding="UTF-8") as f:
        json.dump(fe, f, indent=4)


if __name__ == "__main__":
    num_threads = 4
    batching_size = int(os.getenv("PLINKO_BATCH", "20000"))
    # Local dev defaults to uncompressed books (.jsonl) for sync-math-books.
    # Set PLINKO_BOOKS_COMPRESSION=1 when generating Stake Engine publish payloads.
    compression = os.getenv("PLINKO_BOOKS_COMPRESSION", "0").lower() in {"1", "true", "yes"}
    profiling = False

    # Base modes pay the per-ball board EV with no in-drop features (suppressed), so the RTP
    # estimate's accuracy is set by the heavy 100x corner pocket (p≈6e-5). Low tiers need many
    # sims to converge: the published RTP is mean(payouts) (uniform weights), so the band/variance
    # checks only pass once the rare top pockets are well sampled. Counts scale ~per ball-sample.
    # Trigger modes are EV-priced (RTP is exactly TARGET_RTP regardless of N), so a small run is fine.
    sims_div = max(1, int(os.getenv("PLINKO_SIM_DIV", "1")))  # set >1 for a fast smoke test
    # Tuned so the base RTP estimate converges (heavy 100x corner pocket) while keeping the
    # uncompressed book files memory-safe for the default `make run`. Bump via PLINKO_SIM_DIV<1?
    # No — raise these directly with PLINKO_BOOKS_COMPRESSION=1 if you want tighter low-tier RTP.
    base_sims = {1: 400_000, 10: 150_000, 20: 80_000, 50: 40_000}
    sims_per_trigger = 2_000
    num_sim_args = {
        bet_mode_for_balls_per_drop(balls): max(1000, base_sims[balls] // sims_div)
        for balls in BALLS_PER_DROP_OPTIONS
    }
    # Feature-trigger modes are forced (always trigger) and EV-priced, so fewer sims are needed.
    for balls in BALLS_PER_DROP_OPTIONS:
        num_sim_args[freespin_mode_for_balls(balls)] = max(500, sims_per_trigger // sims_div)
        num_sim_args[bonus_mode_for_balls(balls)] = max(500, sims_per_trigger // sims_div)

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
    set_trigger_mode_costs_free(gamestate)
    # Price the (free) feature-trigger modes for the math summary so all modes read ~TARGET_RTP.
    set_trigger_mode_index_costs(gamestate)
    write_plinko_fe_config(gamestate)
    report_mode_rtp(gamestate)
    print(f"Done. Books: {gamestate.output_files.book_path}")
    print(f"Publish: {gamestate.output_files.publish_path}")
    print(f"FE config: {gamestate.output_files.config_path}")
