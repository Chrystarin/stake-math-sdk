"""Generate books and configs for crimson_plinko (Stake Web SDK apps/plinko)."""

import json
import os

from game_config import GameConfig
from gamestate import GameState
from src.state.run_sims import create_books
from src.write_data.write_configs import generate_configs

from plinko_data import COEFFICIENT_SETS


def write_plinko_fe_config(gamestate: GameState) -> None:
    """Extend standard FE config with plinko coefficient tables."""
    path = os.path.join(
        gamestate.output_files.config_path,
        f"config_fe_{gamestate.config.game_id}.json",
    )
    with open(path, encoding="UTF-8") as f:
        fe = json.load(f)
    fe["defaultCoefficientSets"] = COEFFICIENT_SETS
    fe["minBet"] = gamestate.config.min_bet
    fe["maxBet"] = gamestate.config.max_bet
    with open(path, "w", encoding="UTF-8") as f:
        json.dump(fe, f, indent=4)


if __name__ == "__main__":
    num_threads = 4
    batching_size = 5000
    # Local dev defaults to uncompressed books (.jsonl) for sync-math-books.
    # Set PLINKO_BOOKS_COMPRESSION=1 when generating Stake Engine publish payloads.
    compression = os.getenv("PLINKO_BOOKS_COMPRESSION", "0").lower() in {"1", "true", "yes"}
    profiling = False

    num_sim_args = {
        "base": 10000,
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
    generate_configs(gamestate)
    write_plinko_fe_config(gamestate)
    print(f"Done. Books: {gamestate.output_files.book_path}")
    print(f"FE config: {gamestate.output_files.config_path}")
