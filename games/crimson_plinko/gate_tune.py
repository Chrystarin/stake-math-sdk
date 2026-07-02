"""Gate-the-climb tuner for the ×10 ladder: per buy tier, sweep (level-up bar × entry) and report
RTP (capped) + cap-hit (max-win) + %reaching L9 (RAM) + mean/max book balls. Find a combo with
RTP~95.6%, L9 rare (<~0.02% => RAM-safe), and cap-hit robust (>~0.01% => max-win achievable).

Run: env/Scripts/python.exe games/crimson_plinko/gate_tune.py <out.txt>
"""
import sys
import numpy as np
from plinko_data import (
    BOARD_SLOT_MULTIPLIERS, BONUS_LEVEL_LABELS, BONUS_LEVEL_BALL_MULTIPLIER, BONUS_PEG_HIT_PROB,
    BUY_BONUS_BALLS_PER_DROP_REF, FREE_SPIN_SEGMENTS, MAX_BONUS_LEVEL, scaled_spin_meter_max,
)

ROW = 14
BOARD = np.array(BOARD_SLOT_MULTIPLIERS, dtype=float)
SPIN_IDX = (len(BOARD) - 1) // 2
SPIN_MAX = scaled_spin_meter_max(BUY_BONUS_BALLS_PER_DROP_REF)
FS = np.array([float(s[:-1]) for s in FREE_SPIN_SEGMENTS if s != "BONUS"], dtype=float)
MULT = BONUS_LEVEL_BALL_MULTIPLIER
LEVEL_BALLS = {l: BONUS_LEVEL_LABELS[l - 1] * MULT for l in range(2, len(BONUS_LEVEL_LABELS) + 1)}
_rng = np.random.default_rng()


def sim(entry, bar, wincap):
    level = 1; meter = 0; spin = 0; win = 0.0; total = 0
    pending = [int(entry)]
    while pending:
        b = pending.pop(0)
        if b <= 0:
            continue
        total += b
        r = _rng.binomial(ROW, 0.5, b)
        win += float(BOARD[r].sum())
        pegs = int((_rng.random(b) < BONUS_PEG_HIT_PROB).sum())
        spin += int(np.count_nonzero(r == SPIN_IDX))
        if level < MAX_BONUS_LEVEL:
            poss = (meter + pegs) // bar
            act = min(poss, MAX_BONUS_LEVEL - level)
            for _ in range(act):
                level += 1
                e = LEVEL_BALLS.get(level, 0)
                if e > 0:
                    pending.append(e)
            meter = (meter + pegs) % bar if level < MAX_BONUS_LEVEL else 0
        if spin >= SPIN_MAX:
            win += float(_rng.choice(FS)); spin = 0
    return min(win, wincap), level, total


def measure(entry, bar, cost, wincap, n):
    caps = np.empty(n); lvl = np.empty(n, dtype=int); tot = np.empty(n, dtype=int)
    for i in range(n):
        caps[i], lvl[i], tot[i] = sim(entry, bar, wincap)
    return caps.mean() / cost, (caps >= wincap).mean(), np.mean(lvl >= 9), tot.max(), tot.mean()


def main():
    N = 80000
    out = []

    def pr(s=""):
        print(s, flush=True); out.append(s)

    pr(f"=== gate-the-climb tune (×{MULT} ladder, n={N}) ===")
    # (label, cost, wincap, bar-list, entry-list)
    CONFIGS = [
        ("standard", 80, 260, [17, 18, 19], [74, 78, 82]),
        ("enhanced", 100, 290, [19, 21, 23], [95, 100, 105]),
        ("premium", 150, 400, [22, 25, 28], [145, 152, 159]),
        ("superfury", 250, 600, [30, 36, 42], [240, 250, 260]),
    ]
    for label, cost, wincap, bars, entries in CONFIGS:
        pr(f"== {label} cost={cost} cap={wincap} ==")
        pr(f"{'bar':>4} {'entry':>6} {'RTP%':>7} {'capHit%':>8} {'L9%':>7} {'maxBalls':>8} {'meanBalls':>9} {'flag':>5}")
        for bar in bars:
            for entry in entries:
                rtp, ch, l9, mx, mn = measure(entry, bar, cost, wincap, N)
                ok = 0.953 <= rtp <= 0.959 and l9 < 0.0003 and ch > 0.00005
                pr(f"{bar:>4} {entry:>6} {rtp*100:>6.2f}% {ch*100:>7.4f}% {l9*100:>6.4f}% {mx:>8} {mn:>9.1f} {'OK' if ok else '':>5}")
        pr()

    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    main()
