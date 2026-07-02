"""Option B tuner: buy-only LEVEL-UP threshold (levelup_pegs) with head_start=0, tune free balls.

Higher levelup threshold => level-ups need more coin-peg hits => milder snowball => free-ball count
becomes a smooth, precise RTP lever. We need T high enough for fine granularity + low cap-hit, but low
enough that the wincap (advertised max win) is still hit >= 1/20M (cap-hit must stay > 0). Sweep entry
per tier at a candidate T and read RTP + cap-hit.

Run: env/Scripts/python.exe games/crimson_plinko/sweep_levelup.py <out.txt> [T]
"""
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


def sim_once(entry, head_start, wincap, levelup_max):
    level = 1
    meter = min(levelup_max - 1, int(round(max(0.0, min(1.0, head_start)) * levelup_max)))
    spin_meter = 0
    feature_win = 0.0
    pending = [int(entry)]
    while pending:
        batch = pending.pop(0)
        if batch <= 0:
            continue
        rights = _rng.binomial(ROW_COUNT, 0.5, batch)
        feature_win += float(BOARD[rights].sum())
        pegs = int((_rng.random(batch) < BONUS_PEG_HIT_PROB).sum())
        spin_hits = int(np.count_nonzero(rights == SPIN_IDX))
        if level < MAX_BONUS_LEVEL:
            possible = (meter + pegs) // levelup_max
            actual = min(possible, MAX_BONUS_LEVEL - level)
            for _ in range(actual):
                level += 1
                extra = LEVEL_BALLS.get(level, 0)
                if extra > 0:
                    pending.append(extra)
            meter = (meter + pegs) % levelup_max if level < MAX_BONUS_LEVEL else 0
        spin_meter += spin_hits
        if spin_meter >= SPIN_MAX:
            feature_win += float(_rng.choice(FS_NUMERIC))
            spin_meter = 0
    return min(feature_win, wincap)


def rtp(entry, wincap, cost, lvlup, n):
    caps = np.fromiter((sim_once(entry, 0.0, wincap, lvlup) for _ in range(n)), dtype=float, count=n)
    return float(caps.mean()) / cost, float((caps >= wincap).mean())


def main():
    T = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    N = 200000
    out = []

    def pr(s=""):
        print(s, flush=True)
        out.append(s)

    pr(f"=== Option B sweep: levelup_pegs={T}, head_start=0 (n={N}) ===")
    # (label, cost, wincap, entry-range) at head_start=0
    CONFIGS = [
        ("standard", 80, 300, range(68, 79)),
        ("enhanced", 100, 340, range(85, 98)),
        ("premium", 150, 450, range(126, 144, 2)),
        ("superfury", 250, 600, range(192, 224, 3)),
    ]
    for label, cost, wincap, rng in CONFIGS:
        pr(f"== {label}  cost={cost} wincap={wincap} ==")
        pr(f"{'entry':>6} {'RTP%':>7} {'capHit%':>9} {'flag':>6}")
        for entry in rng:
            r, ch = rtp(entry, wincap, cost, T, N)
            good = 0.952 <= r <= 0.960
            pr(f"{entry:>6} {r*100:>6.2f}% {ch*100:>8.4f}% {'OK' if good else '':>6}")
        pr()

    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    main()
