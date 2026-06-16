"""Generate books and configs for crimson_plinko (Stake Web SDK apps/plinko)."""

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
    bet_mode_for_balls_per_drop,
)
from publish_verify import sync_all_publish_files


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
    batching_size = 5000
    # Local dev defaults to uncompressed books (.jsonl) for sync-math-books.
    # Set PLINKO_BOOKS_COMPRESSION=1 when generating Stake Engine publish payloads.
    compression = os.getenv("PLINKO_BOOKS_COMPRESSION", "0").lower() in {"1", "true", "yes"}
    profiling = False

    sims_per_tier = 2500
    num_sim_args = {
        bet_mode_for_balls_per_drop(balls): sims_per_tier for balls in BALLS_PER_DROP_OPTIONS
    }

    run_conditions = {"run_sims": True}

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
    print(f"Done. Books: {gamestate.output_files.book_path}")
    print(f"Publish: {gamestate.output_files.publish_path}")
    print(f"FE config: {gamestate.output_files.config_path}")
