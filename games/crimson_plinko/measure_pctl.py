"""Option B (T=12, head_start=0): per-tier uncapped RTP + payout percentiles, to pick entry (RTP~95.6%)
and a wincap set at the organic ~99.99th pct so the advertised max win is reliably achievable."""
import sys
import numpy as np
from plinko_data import (
    BOARD_SLOT_MULTIPLIERS, BONUS_LEVEL_LABELS, BONUS_PEG_HIT_PROB,
    BUY_BONUS_BALLS_PER_DROP_REF, FREE_SPIN_SEGMENTS, MAX_BONUS_LEVEL, scaled_spin_meter_max,
)

ROW_COUNT = 14
BOARD = np.array(BOARD_SLOT_MULTIPLIERS, dtype=float)
SPIN_IDX = (len(BOARD) - 1) // 2
SPIN_MAX = scaled_spin_meter_max(BUY_BONUS_BALLS_PER_DROP_REF)
FS_NUMERIC = np.array([float(s[:-1]) for s in FREE_SPIN_SEGMENTS if s != "BONUS"], dtype=float)
LEVEL_BALLS = {lvl: BONUS_LEVEL_LABELS[lvl - 1] for lvl in range(2, len(BONUS_LEVEL_LABELS) + 1)}
_rng = np.random.default_rng()
T = int(sys.argv[2]) if len(sys.argv) > 2 else 12


def sim_uncapped(entry):
    level = 1
    meter = 0
    spin_meter = 0
    win = 0.0
    pending = [int(entry)]
    while pending:
        batch = pending.pop(0)
        if batch <= 0:
            continue
        rights = _rng.binomial(ROW_COUNT, 0.5, batch)
        win += float(BOARD[rights].sum())
        pegs = int((_rng.random(batch) < BONUS_PEG_HIT_PROB).sum())
        spin_hits = int(np.count_nonzero(rights == SPIN_IDX))
        if level < MAX_BONUS_LEVEL:
            possible = (meter + pegs) // T
            actual = min(possible, MAX_BONUS_LEVEL - level)
            for _ in range(actual):
                level += 1
                extra = LEVEL_BALLS.get(level, 0)
                if extra > 0:
                    pending.append(extra)
            meter = (meter + pegs) % T if level < MAX_BONUS_LEVEL else 0
        spin_meter += spin_hits
        if spin_meter >= SPIN_MAX:
            win += float(_rng.choice(FS_NUMERIC))
            spin_meter = 0
    return win


def main():
    N = 300000
    out = []

    def pr(s=""):
        print(s, flush=True)
        out.append(s)

    pr(f"=== Option B percentiles: levelup={T}, head_start=0 (n={N}) ===")
    # (label, cost, current_wincap, entry-range)
    CONFIGS = [
        ("superfury", 250, 600, range(225, 256, 3)),
    ]
    for label, cost, cur_cap, rng in CONFIGS:
        pr(f"== {label}  cost={cost} current_wincap={cur_cap} ==")
        pr(f"{'entry':>6} {'uncapRTP%':>9} {'p99':>7} {'p99.9':>8} {'p99.99':>8} {'max':>7} "
           f"{'P>=curCap%':>10}")
        for entry in rng:
            w = np.fromiter((sim_uncapped(entry) for _ in range(N)), dtype=float, count=N)
            rtp = float(w.mean()) / cost
            p99, p999, p9999 = np.percentile(w, [99, 99.9, 99.99])
            flag = " <==" if 0.953 <= rtp <= 0.960 else ""
            pr(f"{entry:>6} {rtp*100:>8.2f}% {p99:>7.0f} {p999:>8.0f} {p9999:>8.0f} {w.max():>7.0f} "
               f"{float((w>=cur_cap).mean())*100:>9.4f}%{flag}")
        pr()

    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    main()
