"""DEV: measure the bonus depth distribution under a PER-LEVEL (escalating) level-up threshold.

Goal: leveling up is MORE FREQUENT at low levels but HARDER at high levels, while the awarded free
balls per level (BONUS_LEVEL_BALLS, the x10 ladder) stay UNCHANGED and deep levels stay rare enough for
RAM (max total balls) + RTP. Threshold to go FROM level L = round(BASE * GROWTH**(L-1)), clamped >= 2.

Reports, per candidate (BASE, GROWTH): the full reach distribution P(L>=k), avg level, avg/p99/max total
balls (RAM proxy), and avg CAPPED feature payout (drives the RTP re-tune). Entry balls from the current
BONUS_WHEEL_FREE_BALLS unless --entry is given.

Run: env/Scripts/python.exe games/crimson_plinko/sweep_escalation.py [wincap] [entryAvgOverride]
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
_rng = np.random.default_rng(20260724)


def thresholds_for(base, growth):
    """Peg-hits needed to leave each level L (1..MAX-1)."""
    return [max(2, round(base * (growth ** (l - 1)))) for l in range(1, MAX_BONUS_LEVEL)]


def sim_once(thr, wincap, entry_avg):
    level = 1
    meter = 0
    spin_meter = 0
    feature_win = 0.0
    total_balls = 0
    entry = int(_rng.choice(WHEEL)) if entry_avg <= 0 else int(entry_avg)
    pending = [entry]
    while pending:
        batch = pending.pop(0)
        if batch <= 0:
            continue
        total_balls += batch
        rights = _rng.binomial(ROW_COUNT, 0.5, batch)
        feature_win += float(BOARD[rights].sum())
        # Coin-peg hits in this batch are fungible, so consume them against the escalating per-level
        # thresholds as a lump (identical level count to a ball-by-ball walk, far faster).
        avail = int((_rng.random(batch) < BONUS_PEG_HIT_PROB).sum())
        while level < MAX_BONUS_LEVEL and avail > 0:
            need = thr[level - 1] - meter
            if avail >= need:
                avail -= need
                meter = 0
                level += 1
                extra = LEVEL_BALLS.get(level, 0)
                if extra > 0:
                    pending.append(extra)
            else:
                meter += avail
                avail = 0
        spin_meter += int(np.count_nonzero(rights == SPIN_IDX))
        if spin_meter >= SPIN_MAX:
            feature_win += float(_rng.choice(FS_NUMERIC))
            spin_meter = 0
    return level, total_balls, min(feature_win, wincap)


def run(label, thr, wincap, entry_avg, N):
    lv = np.empty(N); tb = np.empty(N); pay = np.empty(N)
    for i in range(N):
        l, b, p = sim_once(thr, wincap, entry_avg)
        lv[i] = l; tb[i] = b; pay[i] = p
    dist = " ".join(f"L{k}:{(lv>=k).mean()*100:6.3f}%" for k in range(2, 10))
    print(f"\n{label}  thr={thr}")
    print(f"  avgLvl={lv.mean():.3f} avgBalls={tb.mean():7.1f} p99={np.percentile(tb,99):5.0f} "
          f"p999={np.percentile(tb,99.9):5.0f} max={tb.max():5.0f} avgPay={pay.mean():7.2f}")
    print(f"  reach: {dist}", flush=True)


def main():
    wincap = float(sys.argv[1]) if len(sys.argv) > 1 else 400.0
    entry_avg = float(sys.argv[2]) if len(sys.argv) > 2 else 0  # 0 = draw from wheel
    N = 40000
    print(f"=== escalation sweep (x{BONUS_LEVEL_BALL_MULTIPLIER} ladder, wincap={wincap}, "
          f"entry={'wheel' if entry_avg<=0 else int(entry_avg)}, n={N}) ===")
    run("FLAT-15 (current)", [15] * (MAX_BONUS_LEVEL - 1), wincap, entry_avg, N)
    for base, growth in [(5, 1.5), (5, 1.6), (4, 1.7), (5, 1.7), (6, 1.7), (5, 1.8), (6, 1.75)]:
        run(f"BASE={base} GROWTH={growth}", thresholds_for(base, growth), wincap, entry_avg, N)


if __name__ == "__main__":
    main()
