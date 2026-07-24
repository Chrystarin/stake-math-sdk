"""DEV: sweep the in-bonus level-up threshold T for the BASE (wheel-entry) bonus and report the
depth / RAM / payout tradeoff on the current x10 BONUS_LEVEL_BALLS ladder.

For each candidate T we Monte-Carlo the cascade (entry drawn from BONUS_WHEEL_FREE_BALLS, coin-peg
hits fill an energy meter, every T hits -> next level -> award BONUS_LEVEL_BALLS[level]) and report:
  avg final level, P(L>=4), P(L>=6), P(L==9), avg + p99 + MAX total balls (RAM proxy), and the
  average CAPPED feature payout (per-ball units) at a given wincap.

Optionally caps total balls per bonus (--ballcap) to model a RAM ceiling.

Run: env/Scripts/python.exe games/crimson_plinko/sweep_base_depth.py [wincap] [ballcap]
"""
import sys
import numpy as np
from plinko_data import (
    BOARD_SLOT_MULTIPLIERS, BONUS_LEVEL_LABELS, BONUS_LEVEL_BALL_MULTIPLIER, BONUS_PEG_HIT_PROB,
    BONUS_WHEEL_FREE_BALLS, MAX_BONUS_LEVEL, FREE_SPIN_SEGMENTS, scaled_spin_meter_max,
)

ROW_COUNT = 14
BOARD = np.array(BOARD_SLOT_MULTIPLIERS, dtype=float)
SPIN_IDX = (len(BOARD) - 1) // 2
SPIN_MAX = scaled_spin_meter_max(10)
FS_NUMERIC = np.array([float(s[:-1]) for s in FREE_SPIN_SEGMENTS if s != "BONUS"], dtype=float)
LEVEL_BALLS = {lvl: BONUS_LEVEL_LABELS[lvl - 1] * BONUS_LEVEL_BALL_MULTIPLIER
               for lvl in range(2, len(BONUS_LEVEL_LABELS) + 1)}
WHEEL = np.array(BONUS_WHEEL_FREE_BALLS, dtype=int)
_rng = np.random.default_rng(12345)


def sim_once(levelup_max, wincap, ballcap, maxlevel):
    """Return (final_level, total_balls, capped_feature_win) for one base bonus."""
    level = 1
    meter = 0
    spin_meter = 0
    feature_win = 0.0
    total_balls = 0
    entry = int(_rng.choice(WHEEL))
    pending = [entry]
    while pending:
        batch = pending.pop(0)
        if batch <= 0:
            continue
        # RAM ceiling: clip the batch so cumulative balls never exceed ballcap (0 = no cap).
        if ballcap > 0 and total_balls + batch > ballcap:
            batch = max(0, ballcap - total_balls)
            if batch == 0:
                break
        total_balls += batch
        rights = _rng.binomial(ROW_COUNT, 0.5, batch)
        feature_win += float(BOARD[rights].sum())
        pegs = int((_rng.random(batch) < BONUS_PEG_HIT_PROB).sum())
        spin_hits = int(np.count_nonzero(rights == SPIN_IDX))
        if level < maxlevel:
            possible = (meter + pegs) // levelup_max
            actual = min(possible, maxlevel - level)
            for _ in range(actual):
                level += 1
                extra = LEVEL_BALLS.get(level, 0)
                if extra > 0:
                    pending.append(extra)
            meter = (meter + pegs) % levelup_max if level < maxlevel else 0
        spin_meter += spin_hits
        if spin_meter >= SPIN_MAX:
            feature_win += float(_rng.choice(FS_NUMERIC))
            spin_meter = 0
    return level, total_balls, min(feature_win, wincap)


def main():
    wincap = float(sys.argv[1]) if len(sys.argv) > 1 else 400.0
    ballcap = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    maxlevel = int(sys.argv[3]) if len(sys.argv) > 3 else MAX_BONUS_LEVEL
    N = 60000
    print(f"=== base-bonus depth sweep (x{BONUS_LEVEL_BALL_MULTIPLIER} ladder, wincap={wincap}, "
          f"ballcap={ballcap or 'none'}, maxlevel={maxlevel}, n={N}) ===")
    print(f"{'T':>3} {'avgLvl':>7} {'P>=4':>7} {'P>=6':>7} {'P=9':>7} "
          f"{'avgBalls':>9} {'p99Balls':>9} {'maxBalls':>9} {'avgPay':>8}")
    for T in (15, 12, 10, 9, 8, 7, 6):
        lv = np.empty(N); tb = np.empty(N); pay = np.empty(N)
        for i in range(N):
            l, b, p = sim_once(T, wincap, ballcap, maxlevel)
            lv[i] = l; tb[i] = b; pay[i] = p
        print(f"{T:>3} {lv.mean():>7.3f} {(lv>=4).mean()*100:>6.2f}% {(lv>=6).mean()*100:>6.2f}% "
              f"{(lv>=9).mean()*100:>6.3f}% {tb.mean():>9.1f} {np.percentile(tb,99):>9.0f} "
              f"{tb.max():>9.0f} {pay.mean():>8.2f}")


if __name__ == "__main__":
    main()
