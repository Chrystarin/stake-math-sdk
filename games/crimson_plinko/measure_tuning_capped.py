"""Wincap-aware RTP tuner for the ×10 bonus-level ladder (dev tool, NOT published).

The stock measure_tuning.py measures the UNCAPPED bonus payout, which the ×10 ladder inflates far past
the per-tier wincaps. This tool Monte-Carlos the REAL stratified mode payout WITH the wincap applied
(mirroring gamestate + game_override), so the solved quota is correct, and lets us sweep
BONUS_LEVELUP_PEG_HITS (the lever that controls how often a bonus snowballs to deep levels).

Run: env/Scripts/python.exe games/crimson_plinko/measure_tuning_capped.py [LEVELUP_PEG_HITS]
"""

import sys
import math

import game_calculations as gc_mod
from game_config import GameConfig
from gamestate import GameState
from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    BOARD_SLOT_MULTIPLIERS,
    TARGET_RTP,
    bonus_in_drop_for_balls,
    scaled_bonus_meter_max,
    scaled_bonus_meter_start,
    scaled_spin_meter_max,
    scaled_spin_meter_start,
    spin_in_drop_for_balls,
    wincap_for_balls,
)

ROW_COUNT = 14
STAKE = 1.0


def analytic_board_ev() -> float:
    n = 14
    return sum(math.comb(n, k) * m for k, m in enumerate(BOARD_SLOT_MULTIPLIERS)) / (2 ** n)


def stratum_stats(gs, balls, *, force_bonus, n, wincap):
    """Mean CAPPED payout multiple (per stake) + level/ball stats for one stratum."""
    smax, sstart = scaled_spin_meter_max(balls), scaled_spin_meter_start(balls)
    bmax, bstart = scaled_bonus_meter_max(balls), scaled_bonus_meter_start(balls)
    spin_in = spin_in_drop_for_balls(balls)
    bonus_in = bonus_in_drop_for_balls(balls)
    pay_sum = 0.0
    cap_hits = 0
    lvl_sum = 0
    lvl_max = 0
    ball_max = 0
    for _ in range(n):
        outcomes, drop_win = gs.build_drop_outcomes(
            row_count=ROW_COUNT, balls_per_drop=balls, stake_per_ball=STAKE
        )
        events, feat_win, _sp, _bo, blevel = gs.build_feature_meter_events(
            outcomes=outcomes, row_count=ROW_COUNT, stake_per_ball=STAKE, balls_per_drop=balls,
            spin_meter_start=sstart, spin_meter_max=smax, spin_in_drop=spin_in,
            bonus_meter_start=bstart, bonus_meter_max=bmax, bonus_in_drop=bonus_in,
            force_bonus=force_bonus,
        )
        total = drop_win + feat_win  # payout multiple per stake (stake=1)
        if total > wincap:
            cap_hits += 1
            total = wincap
        pay_sum += total
        if blevel:
            lvl_sum += blevel
            lvl_max = max(lvl_max, blevel)
        bballs = sum(e["freeBalls"] for e in events if e["type"] == "bonusRound")
        ball_max = max(ball_max, bballs)
    return {
        "mean_pay": pay_sum / n,
        "cap_rate": cap_hits / n,
        "avg_level": lvl_sum / n,
        "max_level": lvl_max,
        "max_balls": ball_max,
    }


def main():
    if len(sys.argv) > 1:
        gc_mod.BONUS_LEVELUP_PEG_HITS = int(sys.argv[1])
    if len(sys.argv) > 2:
        import plinko_data as _pd
        mult = int(sys.argv[2])
        labels = [1, 2, 4, 8, 16, 32, 64, 128, 256]
        _pd.BONUS_LEVEL_BALLS = {l: labels[l - 1] * mult for l in range(2, len(labels) + 1)}
        print(f"(ladder multiplier = {mult}: L9 award = {labels[8] * mult})")
    threshold = gc_mod.BONUS_LEVELUP_PEG_HITS
    gs = GameState(GameConfig())
    board = analytic_board_ev()
    print(f"board_EV/ball = {board:.5f}   TARGET_RTP = {TARGET_RTP}   LEVELUP_PEG_HITS = {threshold}\n")
    print(f"{'tier':>4} {'wincap':>7} {'E_norm':>8} {'E_bonus':>9} {'bcapHit':>8} {'bAvgLv':>7} {'bMaxLv':>7} {'quota':>9} {'modeRTP':>9}")
    solved = {}
    rtps = []
    for balls in BALLS_PER_DROP_OPTIONS:
        wincap = wincap_for_balls(balls)
        # Normal stratum needs many samples (feature is rare); bonus stratum is always a bonus.
        norm = stratum_stats(gs, balls, force_bonus=False, n=120_000, wincap=wincap)
        bon = stratum_stats(gs, balls, force_bonus=True, n=20_000, wincap=wincap)
        e_norm = norm["mean_pay"]
        e_bonus = bon["mean_pay"]
        need = TARGET_RTP * balls  # target payout multiple per drop
        denom = e_bonus - e_norm
        rate = 0.0 if denom <= 1e-9 else max(0.0, min(1.0, (need - e_norm) / denom))
        mode_rtp = ((1 - rate) * e_norm + rate * e_bonus) / balls
        solved[balls] = rate
        rtps.append(mode_rtp)
        print(f"{balls:>4} {wincap:>7.0f} {e_norm:>8.4f} {e_bonus:>9.3f} {bon['cap_rate']*100:>7.1f}% "
              f"{bon['avg_level']:>7.2f} {bon['max_level']:>7} {rate:>9.5f} {mode_rtp*100:>8.3f}%")
    spread = (max(rtps) - min(rtps)) * 100
    print(f"\nspread = {spread:.3f}%   min={min(rtps)*100:.3f}%  max={max(rtps)*100:.3f}%")
    print("BONUS_IN_DROP_RATE = {")
    for balls in BALLS_PER_DROP_OPTIONS:
        print(f"    {balls}: {solved[balls]:.5f},")
    print("}")


if __name__ == "__main__":
    main()
