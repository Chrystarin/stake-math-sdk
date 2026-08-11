"""Main file for generating Colour Dice results."""

from gamestate import GameState
from game_config import GameConfig
from src.state.run_sims import create_books
from src.write_data.write_configs import generate_configs

from colour_dice_data import BOOKS_PER_MODE, MODE_NAMES

if __name__ == "__main__":

    # Single-threaded on purpose: books are ENUMERATED, not sampled. Each mode runs exactly
    # BOOKS_PER_MODE sims so that simulation index -> outcome covers the space once, giving
    # the exact analytic distribution under uniform lookup-table weights. Splitting the
    # range across threads must preserve "every index exactly once" — keep this at 1 unless
    # that has been verified. The per-sim work is trivial (three dice + a wheel lookup).
    num_threads = 1
    batching_size = 50000
    compression = True
    profiling = False

    # 20 modes x 21,600 = 432,000 books.
    num_sim_args = {mode: BOOKS_PER_MODE for mode in MODE_NAMES}

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
