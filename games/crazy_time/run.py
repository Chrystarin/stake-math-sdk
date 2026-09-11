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
    ALL_MODE_NAMES,
    COMPLIANCE,
    books_for_mode,
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
    for mode in ALL_MODE_NAMES:
        src = os.path.join(lookup_dir, f"lookUpTable_{mode}.csv")
        rows = []
        with open(src, newline="", encoding="UTF-8") as f:
            for sim_id, _weight, payout in csv.reader(f):
                sim = int(sim_id)
                expected = payout_multiplier(mode, decode_outcome(sim, mode)) * 100
                assert int(payout) == expected, (mode, sim, payout, expected)
                rows.append((sim, outcome_weight(sim, mode), int(payout)))
        assert len(rows) == books_for_mode(mode), (mode, len(rows))
        with open(src, "w", newline="", encoding="UTF-8") as f:
            for sim, weight, payout in rows:
                f.write(f"{sim},{weight},{payout}\n")
        shutil.copy(src, os.path.join(publish_dir, f"lookUpTable_{mode}_0.csv"))
        print(f"[crazy_time] exact weights written for {mode}: {len(rows)} rows")


def short_modes() -> list:
    """Modes whose lookup table does not hold every enumerated outcome.

    Seen once on Windows: a mode's temp files were still locked when the SDK concatenated
    them, so its lookup table came out EMPTY while the run reported success for every mode.
    """
    lookup_dir = os.path.join(LIBRARY, "lookup_tables")
    short = []
    for mode in ALL_MODE_NAMES:
        path = os.path.join(lookup_dir, f"lookUpTable_{mode}.csv")
        rows = sum(1 for _ in open(path, encoding="UTF-8")) if os.path.exists(path) else 0
        if rows != books_for_mode(mode):
            short.append(mode)
    return short


def repair_short_modes(gamestate, config, batching_size, num_threads, compression, profiling, attempts=3):
    """Regenerate any short mode, a few times if need be, before the weights are written."""
    for attempt in range(1, attempts + 1):
        short = short_modes()
        if not short:
            return
        print(f"[crazy_time] attempt {attempt}: regenerating {len(short)} short mode(s): {short}")
        try:
            create_books(
                gamestate,
                config,
                {mode: books_for_mode(mode) for mode in short},
                batching_size,
                num_threads,
                compression,
                profiling,
            )
        except OSError as error:
            print(f"[crazy_time] cleanup failed again ({error}); re-checking")
    remaining = short_modes()
    assert not remaining, f"modes still short after {attempts} attempts: {remaining}"



if __name__ == "__main__":
    # Single-threaded on purpose: books are ENUMERATED, not sampled. Each mode runs exactly
    # BOOKS_PER_MODE sims so simulation index -> outcome covers the space once.
    num_threads = 1
    batching_size = 50000
    compression = True
    profiling = False

    num_sim_args = {mode: books_for_mode(mode) for mode in ALL_MODE_NAMES}

    run_conditions = {"run_sims": True}

    # Importing crazy_time_data already asserted Stake's rules for every mode (RTP band and
    # spread, 1-in-20 hit rate, 1-in-20M max-win frequency); say so before the long run.
    worst = min(COMPLIANCE.items(), key=lambda kv: kv[1]["p_max_win"])
    print(
        f"[crazy_time] {len(ALL_MODE_NAMES)} modes ({sum(books_for_mode(m) for m in ALL_MODE_NAMES):,} books); every mode at "
        f"{float(worst[1]['rtp']):.4f}; rarest max win {worst[0]} at 1 in {float(1 / worst[1]['p_max_win']):,.0f}"
    )

    config = GameConfig()
    gamestate = GameState(config)

    if run_conditions["run_sims"]:
        try:
            create_books(
                gamestate,
                config,
                num_sim_args,
                batching_size,
                num_threads,
                compression,
                profiling,
            )
        except OSError as error:
            # On Windows the SDK's final rmtree of its temp directory can lose a race with the
            # antivirus/indexer holding a just-written file. Every mode's output is already on
            # disk by then; the leftover temp files are harmless, so carry on to the checks.
            print(f"[crazy_time] create_books cleanup failed ({error}); continuing")
        repair_short_modes(gamestate, config, batching_size, num_threads, compression, profiling)
        write_exact_weights()
    generate_configs(gamestate)
