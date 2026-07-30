"""Peg-probability tuner for the buy tiers on the SHARED ×10 level-up ladder.

Every mode climbs the same ladder (`BONUS_LEVELUP_PEG_HITS_BY_LEVEL`), so a buy tier is no longer
gated by a taller bar — it is gated by how often its balls award a coin peg. Per tier this sweeps
`peg_hit_prob` × `entry_balls` and reports RTP (capped) + cap-hit (max-win achievability) +
%reaching L9 (RAM risk) + mean/max book balls. Look for RTP ~95.7%, L9 rare (<~0.02%), and cap-hit
robust (>~0.01%).

Run: env/Scripts/python.exe games/crimson_plinko/gate_tune.py <out.txt>
"""
import sys
import numpy as np
from plinko_data import (
    BOARD_SLOT_MULTIPLIERS, BONUS_LEVEL_LABELS, BONUS_LEVEL_BALL_MULTIPLIER,
    BONUS_LEVELUP_PEG_HITS_BY_LEVEL, BUY_BONUS_BALLS_PER_DROP_REF, BUY_BONUS_TIER_DEFS,
    FREE_SPIN_SEGMENTS, MAX_BONUS_LEVEL, scaled_spin_meter_max,
)

ROW = 14
BOARD = np.array(BOARD_SLOT_MULTIPLIERS, dtype=float)
SPIN_IDX = (len(BOARD) - 1) // 2
SPIN_MAX = scaled_spin_meter_max(BUY_BONUS_BALLS_PER_DROP_REF)
FS = np.array([float(s[:-1]) for s in FREE_SPIN_SEGMENTS if s != "BONUS"], dtype=float)
MULT = BONUS_LEVEL_BALL_MULTIPLIER
LEVEL_BALLS = {l: BONUS_LEVEL_LABELS[l - 1] * MULT for l in range(2, len(BONUS_LEVEL_LABELS) + 1)}
LADDER = [BONUS_LEVELUP_PEG_HITS_BY_LEVEL[l] for l in range(1, MAX_BONUS_LEVEL)]
_rng = np.random.default_rng()


def sim(entry, peg_prob, wincap):
    """One bonus round on the shared ladder. Mirrors game_calculations.simulate_bonus_round: within a
    batch only the COUNT of coin-peg hits matters (the meter is a plain counter and awards are appended
    to the END of the pending queue), so the per-ball walk collapses to arithmetic on that count."""
    level = 1; meter = 0; spin = 0; win = 0.0; total = 0
    pending = [int(entry)]
    while pending:
        b = pending.pop(0)
        if b <= 0:
            continue
        total += b
        r = _rng.binomial(ROW, 0.5, b)
        win += float(BOARD[r].sum())
        hits = int((_rng.random(b) < peg_prob).sum())
        spin += int(np.count_nonzero(r == SPIN_IDX))
        while hits > 0 and level < MAX_BONUS_LEVEL:
            need = LADDER[level - 1] - meter
            if hits >= need:
                hits -= need
                meter = 0
                level += 1
                e = LEVEL_BALLS.get(level, 0)
                if e > 0:
                    pending.append(e)
            else:
                meter += hits
                hits = 0
        if spin >= SPIN_MAX:
            win += float(_rng.choice(FS)); spin = 0
    return min(win, wincap), level, total


def measure(entry, peg_prob, cost, wincap, n):
    caps = np.empty(n); lvl = np.empty(n, dtype=int); tot = np.empty(n, dtype=int)
    for i in range(n):
        caps[i], lvl[i], tot[i] = sim(entry, peg_prob, wincap)
    return caps.mean() / cost, (caps >= wincap).mean(), np.mean(lvl >= 9), tot.max(), tot.mean()


def main():
    N = 80000
    out = []

    def pr(s=""):
        print(s, flush=True); out.append(s)

    pr(f"=== buy peg-probability tune (shared ladder {LADDER}, ×{MULT} awards, n={N}) ===")
    for t in BUY_BONUS_TIER_DEFS:
        key = t["key"]; cost = float(t["cost"]); wincap = float(t["wincap"])
        entry = int(t["entry_balls"]); p0 = float(t["peg_hit_prob"])
        probs = [round(p0 * s, 4) for s in (0.85, 0.925, 1.0, 1.075, 1.15)]
        entries = [entry - 3, entry, entry + 3]
        pr(f"== {key} cost={cost:.0f} cap={wincap:.0f} (shipped entry={entry} p={p0}) ==")
        pr(f"{'pegProb':>8} {'entry':>6} {'RTP%':>7} {'capHit%':>8} {'L9%':>7} {'maxBalls':>8} {'meanBalls':>9} {'flag':>5}")
        for prob in probs:
            for e in entries:
                rtp, ch, l9, mx, mn = measure(e, prob, cost, wincap, N)
                ok = 0.953 <= rtp <= 0.959 and l9 < 0.0003 and ch > 0.00005
                pr(f"{prob:>8.4f} {e:>6} {rtp*100:>6.2f}% {ch*100:>7.4f}% {l9*100:>6.4f}% {mx:>8} {mn:>9.1f} {'OK' if ok else '':>5}")
        pr()

    with open(sys.argv[1], "w", encoding="utf-8") as f:
        f.write("\n".join(out))


if __name__ == "__main__":
    main()
