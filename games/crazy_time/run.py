"""Main file for generating Crazy Time (working title) results."""

import csv
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gamestate import GameState
from game_config import GameConfig
from src.state.run_sims import create_books
from src.write_data.write_configs import generate_configs

from crazy_time_data import (
    BOOKS_PER_MODE,
    COMPLIANCE,
    MODE_NAMES,
    decode_outcome,
    outcome_weight,
    payout_multiplier,
)

LIBRARY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "library")


def write_exact_weights() -> None:
    """Replace the SDK's uniform `id,1,payout` lookup rows with the outcome's exact weight.

    Books are enumerated once per outcome, so the probability of a book is NOT 1/N: it is
    the product of the segment, Top Slot and room weights. The RGS draws simulation ids in
    proportion to the weight column, which is where that probability belongs. The payout
    column is re-derived independently and must agree with what gamestate wrote.
    """
    lookup_dir = os.path.join(LIBRARY, "lookup_tables")
    publish_dir = os.path.join(LIBRARY, "publish_files")
    for mode in MODE_NAMES:
        src = os.path.join(lookup_dir, f"lookUpTable_{mode}.csv")
        rows = []
        with open(src, newline="", encoding="UTF-8") as f:
            for sim_id, _weight, payout in csv.reader(f):
                sim = int(sim_id)
                expected = payout_multiplier(mode, decode_outcome(sim)) * 100
                assert int(payout) == expected, (mode, sim, payout, expected)
                rows.append((sim, outcome_weight(sim), int(payout)))
        assert len(rows) == BOOKS_PER_MODE, (mode, len(rows))
        with open(src, "w", newline="", encoding="UTF-8") as f:
            for sim, weight, payout in rows:
                f.write(f"{sim},{weight},{payout}\n")
        shutil.copy(src, os.path.join(publish_dir, f"lookUpTable_{mode}_0.csv"))
        print(f"[crazy_time] exact weights written for {mode}: {len(rows)} rows")


if __name__ == "__main__":
    # Single-threaded on purpose: books are ENUMERATED, not sampled. Each mode runs exactly
    # BOOKS_PER_MODE sims so simulation index -> outcome covers the space once.
    num_threads = 1
    batching_size = 50000
    compression = True
    profiling = False

    num_sim_args = {mode: BOOKS_PER_MODE for mode in MODE_NAMES}

    run_conditions = {"run_sims": True}

    # Importing crazy_time_data already asserted Stake's rules for every mode (RTP band and
    # spread, 1-in-20 hit rate, 1-in-20M max-win frequency); say so before the long run.
    worst = min(COMPLIANCE.items(), key=lambda kv: kv[1]["p_max_win"])
    print(
        f"[crazy_time] {len(MODE_NAMES)} modes x {BOOKS_PER_MODE} books; every mode at "
        f"{float(worst[1]['rtp']):.4f}; rarest max win {worst[0]} at 1 in {float(1 / worst[1]['p_max_win']):,.0f}"
    )

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
        write_exact_weights()
    generate_configs(gamestate)
