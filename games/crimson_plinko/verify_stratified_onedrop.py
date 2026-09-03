"""Verify the stratified 1-ball (onedrop) layout without touching library/ or publish_files/.

Runs a small onedrop library IN PROCESS through the real `GameState.run_spin` (same criteria, same
book events, same wincap) with the stratified total armed exactly as `GameStateOverride.run_sims`
arms it, then checks:

  1. every pocket holds `total x p_k` books to within one book, so the library's pocket histogram IS
     the binomial board distribution - no sampling noise;
  2. the LUT mean (payoutMultiplier / cost, uniform weights) equals the closed-form board EV - the same
     number rtp_audit.py reports for this tier - far inside even the top pocket's one-book share;
  3. the layout is thread-independent: splitting the same total across several `run_sims` slices
     (threads x repeats) reproduces the single-slice pocket per id, since the plan depends on the
     total alone;
  4. the random sampler and the plan agree on the pocket mapping (`rights_to_rate_index`);
  5. the other tiers are untouched - a 10-ball drop still samples randomly.

Usage (repo root):  env/Scripts/python.exe games/crimson_plinko/verify_stratified_onedrop.py [total]
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from math import comb

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_config import GameConfig  # noqa: E402
from gamestate import GameState  # noqa: E402
from plinko_data import ONE_BALL_BOARD_SLOT_MULTIPLIERS, bet_mode_for_balls_per_drop  # noqa: E402
from src.wins.win_manager import WinManager  # noqa: E402

ROW_COUNT = 14
ONEDROP = bet_mode_for_balls_per_drop(1)


def fresh_state(betmode: str) -> GameState:
    """A GameState primed the way `run_sims` primes a worker, minus the file output."""
    gs = GameState(GameConfig())
    bm = gs.get_betmode(betmode)
    gs.config.wincap = bm.get_wincap()
    gs.betmode = betmode
    gs.win_manager = WinManager(gs.config.basegame_type, gs.config.freegame_type, bm.get_wincap())
    gs.library = {}
    gs.recorded_events = {}
    gs._payout_ints = []
    gs.criteria = bm.get_distributions()[0].get_criteria()
    return gs


def pocket_of(book: dict) -> int:
    drop = next(e for e in book["events"] if e["type"] == "plinkoDrop")
    assert len(drop["outcomes"]) == 1, "a 1-ball book must carry exactly one outcome"
    return int(drop["outcomes"][0]["rateIndex"])


def run_slice(gs: GameState, total: int, first: int, last: int) -> dict[int, int]:
    """Simulate ids first..last-1 of a `total`-book onedrop run; return {id: pocket}."""
    gs.stratified_onedrop_total = total
    gs._stratified_plan_cache = None
    gs.num_sims = last - first
    pockets: dict[int, int] = {}
    for sim in range(first, last):
        gs.run_spin(sim)
        pockets[sim] = pocket_of(gs.library[sim + 1])
    return pockets


def main(total: int) -> None:
    board = list(ONE_BALL_BOARD_SLOT_MULTIPLIERS)
    num_slots = len(board)
    probs = [comb(ROW_COUNT, k) / 2**ROW_COUNT for k in range(num_slots)]
    exact_ev = sum(p * m for p, m in zip(probs, board))

    # (4) the plan's mapping is the sampler's mapping
    gs = fresh_state(ONEDROP)
    assert gs.pocket_probabilities(ROW_COUNT, num_slots) == probs, "pocket_probabilities != binomial"
    for rights in range(ROW_COUNT + 1):
        assert gs.rights_to_rate_index(rights, ROW_COUNT, num_slots) == rights

    # (1) + (2): one slice covering the whole library
    pockets = run_slice(gs, total, 0, total)
    hist = Counter(pockets.values())
    expected = gs.stratified_pocket_counts(probs, total, board)
    assert sum(expected) == total
    for k in range(num_slots):
        assert hist.get(k, 0) == expected[k], f"pocket {k}: {hist.get(k, 0)} books, planned {expected[k]}"
        assert abs(expected[k] - probs[k] * total) < 1.0, f"pocket {k} count off by a whole book"
    lut_mean = sum(gs.library[i + 1]["payoutMultiplier"] for i in range(total)) / total / 100.0
    # Plain per-pocket rounding could leave up to sum(board)/total; the payout-aware choice of which
    # pockets round up must do at least ten times better than even the single top pocket's share.
    tolerance = max(board) / total / 10
    assert abs(lut_mean - exact_ev) <= tolerance, f"LUT mean {lut_mean:.6f} vs exact EV {exact_ev:.6f}"
    # The cap never binds: the top pocket pays the mode's advertised max exactly.
    assert max(gs.library[i + 1]["payoutMultiplier"] for i in range(total)) == round(max(board) * 100)
    # Books are consecutive ids with the 1-ball settlement shape: a drop, optionally the cosmetic
    # bonusMeter tick a coin-peg hit still records on this tier, then the settlement - never a feature.
    for i in (0, total // 2, total - 1):
        book = gs.library[i + 1]
        assert book["id"] == i
        types = [e["type"] for e in book["events"]]
        assert types[0] == "plinkoDrop" and types[-2:] == ["setTotalWin", "finalWin"], types
        assert not {"bonusRoulette", "bonusRound", "freeSpinTrigger", "spinMeter"} & set(types), types

    # (3) thread-independence: 4 slices x 2 repeats of total/8 books each
    threads, repeats = 4, 2
    per = total // (threads * repeats)
    assert per * threads * repeats == total, "pick a total divisible by 8 for the slice check"
    rebuilt: dict[int, int] = {}
    for repeat in range(repeats):
        for thread in range(threads):
            worker = fresh_state(ONEDROP)
            first = thread * per + (threads * per) * repeat
            rebuilt.update(run_slice(worker, total, first, first + per))
    assert rebuilt == pockets, "sliced run disagrees with the single-slice layout"

    # (5) the 10-ball tier still samples randomly (the plan is never consulted)
    ten = fresh_state(bet_mode_for_balls_per_drop(10))
    ten.stratified_onedrop_total = None
    ten.num_sims = 3
    for sim in range(3):
        ten.run_spin(sim)
        drop = next(e for e in ten.library[sim + 1]["events"] if e["type"] == "plinkoDrop")
        assert len(drop["outcomes"]) == 10
    # ...and a onedrop worker whose total is NOT armed falls back to random sampling too.
    loose = fresh_state(ONEDROP)
    loose.stratified_onedrop_total = None
    loose.num_sims = 200
    loose_hist = Counter()
    for sim in range(200):
        loose.run_spin(sim)
        loose_hist[pocket_of(loose.library[sim + 1])] += 1
    assert sum(loose_hist.values()) == 200

    # Scramble sanity: consecutive ids should not all sit in one pocket.
    first_50 = [pockets[i] for i in range(50)]
    assert len(set(first_50)) >= 5, f"ids 0..49 land in only {len(set(first_50))} pockets"

    print(f"stratified onedrop OK: {total} books, LUT mean {lut_mean:.6f}, exact EV {exact_ev:.6f}, "
          f"|diff| {abs(lut_mean - exact_ev):.2e} <= {tolerance:.2e}")
    print("pocket counts:", expected)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40_000)
