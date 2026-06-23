"""Fast RTP-tuning measurement (NOT published). Measures the EXACT analytic board EV, the folded-bonus
mean payout, and the full normal-stratum feature win (free spin + wheel->bonus chain) directly — then
solves each tier's force_bonus quota to hit TARGET_RTP. Avoids slow full book sims for tuning.

Run: env/Scripts/python.exe games/crimson_plinko/measure_tuning.py
"""

import math
import statistics

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
)

ROW_COUNT = 14
STAKE = 1.0
NUM_ROWS = 14  # 15 slots → Binomial(14, 0.5)


def analytic_board_ev() -> float:
    """Exact per-ball board EV — the sampler maps Binomial(14,0.5) deflections straight to a slot."""
    n = NUM_ROWS
    total = 0.0
    denom = 2 ** n
    for k, mult in enumerate(BOARD_SLOT_MULTIPLIERS):
        total += math.comb(n, k) * mult
    return total / denom


def measure_bonus_mean(gs, balls=10, n=40_000):
    # Per-tier now: the in-bonus free spin uses the tier's spin-meter max, so bonus_mean varies by tier.
    wins, balls_total, levels = [], [], []
    fs_fires = 0
    for _ in range(n):
        events, win, level = gs.simulate_bonus_round(row_count=ROW_COUNT, stake_per_ball=STAKE, balls_per_drop=balls)
        wins.append(win)
        balls_total.append(sum(e["freeBalls"] for e in events if e["type"] == "bonusRound"))
        levels.append(level)
        if any(e["type"] == "freeSpinTrigger" for e in events):
            fs_fires += 1
    return statistics.mean(wins), statistics.mean(balls_total), statistics.mean(levels), max(balls_total), fs_fires / n


def measure_normal_feature(gs, balls, n=300_000):
    """On a NORMAL-stratum drop: mean feature_win (free spin + wheel->BONUS chain + the PER-DROP METER
    bonus when it fills), the free-spin fire rate, and the per-drop METER bonus fire rate."""
    smax, sstart = scaled_spin_meter_max(balls), scaled_spin_meter_start(balls)
    bmax, bstart = scaled_bonus_meter_max(balls), scaled_bonus_meter_start(balls)
    spin_in = spin_in_drop_for_balls(balls)
    bonus_in = bonus_in_drop_for_balls(balls)
    fs_fires = 0
    bonus_fires = 0
    win_sum = 0.0
    for _ in range(n):
        outcomes, _ = gs.build_drop_outcomes(row_count=ROW_COUNT, balls_per_drop=balls, stake_per_ball=STAKE)
        events, win, *_ = gs.build_feature_meter_events(
            outcomes=outcomes, row_count=ROW_COUNT, stake_per_ball=STAKE, balls_per_drop=balls,
            spin_meter_start=sstart, spin_meter_max=smax, spin_in_drop=spin_in,
            bonus_meter_start=bstart, bonus_meter_max=bmax, bonus_in_drop=bonus_in, force_bonus=False,
        )
        win_sum += win
        if any(e["type"] == "freeSpinTrigger" for e in events):
            fs_fires += 1
        if any(e["type"] == "bonusRoulette" for e in events):
            bonus_fires += 1
    return win_sum / n, fs_fires / n, bonus_fires / n


def main():
    gs = GameState(GameConfig())
    board = analytic_board_ev()
    print(f"board_EV/ball (analytic) = {board:.5f}")
    print(f"target RTP               = {TARGET_RTP}\n")
    print(f"{'tier':>5} {'bonus_mean':>10} {'inB_fs':>7} {'fs_rate':>8} {'norm_win_E':>10} {'quota_top':>10} {'->mode_RTP':>11}")
    solved = {}
    for balls in BALLS_PER_DROP_OPTIONS:
        bonus_mean, bballs, blevel, bmax, inbonus_fs = measure_bonus_mean(gs, balls, n=20_000)
        norm_win, fs_rate, meter_bonus_rate = measure_normal_feature(gs, balls)
        # The quota tops up whatever the meter-driven normal stratum doesn't already supply.
        need_pmult = (TARGET_RTP - board) * balls
        rate = max(0.0, (need_pmult - norm_win) / bonus_mean)
        mode_rtp = board + (norm_win + rate * bonus_mean) / balls
        solved[balls] = rate
        print(f"{balls:>5} {bonus_mean:>10.3f} {inbonus_fs*100:>6.1f}% {fs_rate*100:>7.3f}% {norm_win:>10.4f} {rate:>10.5f} {mode_rtp*100:>10.3f}%")
    print("\nBONUS_IN_DROP_RATE = {")
    for balls in BALLS_PER_DROP_OPTIONS:
        print(f"    {balls}: {solved[balls]:.5f},")
    print("}")


if __name__ == "__main__":
    main()
