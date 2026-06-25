"""Tune the BUY BONUS entry-ball counts (NOT published — a dev aid like measure_tuning.py).

Each buy mode is bonus-only: payout = capped(simulate_bonus_round with a FIXED entry). cost is fixed to
the PDF (80/100/150/250 ×bet-per-ball), so we solve `entry_balls` per tier to land RTP =
mean(min(payout, wincap)) / cost ≈ TARGET_RTP. RTP is ~linear in entry near target (the wincap only
clips the thin tail), so we measure capped_mean / entry at the current estimate and back out the entry
that hits the target.

Run: env/Scripts/python.exe games/crimson_plinko/measure_buybonus.py
"""

import statistics

from game_config import GameConfig
from gamestate import GameState
from plinko_data import (
    BUY_BONUS_BALLS_PER_DROP_REF,
    BUY_BONUS_TIER_DEFS,
    TARGET_RTP,
)

ROW_COUNT = 14
STAKE = 1.0
N = 60_000

# Candidate entry-ball counts to sweep per tier (cost is fixed to the PDF; find the entry that lands RTP
# closest to TARGET_RTP). Keyed by tier key. Default = the tier's pinned entry (single high-n confirm).
CANDIDATES = {
    "enhanced": [86],
    "superfury": [180],
}


def measure(gs, entry: int, wincap: float, n: int = N):
    raw, capped, balls_total, maxwin = [], [], [], 0.0
    for _ in range(n):
        _events, win, _level = gs.simulate_bonus_round(
            row_count=ROW_COUNT,
            stake_per_ball=STAKE,
            balls_per_drop=BUY_BONUS_BALLS_PER_DROP_REF,
            entry_balls_override=entry,
        )
        pm = win / STAKE
        raw.append(pm)
        capped.append(min(pm, wincap))
        maxwin = max(maxwin, min(pm, wincap))
        balls_total.append(sum(e["freeBalls"] for e in _events if e["type"] == "bonusRound"))
    return (
        statistics.mean(raw),
        statistics.mean(capped),
        statistics.mean(balls_total),
        maxwin,
        sum(1 for c in capped if c >= wincap) / n,
    )


def main():
    gs = GameState(GameConfig())
    print(f"target RTP = {TARGET_RTP}  (n={N}/tier, ref bpd={BUY_BONUS_BALLS_PER_DROP_REF})\n")
    print(f"{'tier':>10} {'entry':>6} {'cost':>6} {'wincap':>7} {'rawPM':>9} {'cappedPM':>9} "
          f"{'meanBalls':>9} {'maxPM':>8} {'capHit%':>8} {'RTP%':>7} {'->entry@target':>14}")
    for tier in BUY_BONUS_TIER_DEFS:
        if tier["key"] not in CANDIDATES:
            continue
        cost = float(tier["cost"])
        wincap = float(tier["wincap"])
        for entry in CANDIDATES[tier["key"]]:
            raw, capped, mean_balls, maxpm, caphit = measure(gs, entry, wincap)
            rtp = capped / cost
            k = capped / entry
            entry_target = TARGET_RTP * cost / k
            flag = " <==" if abs(rtp - TARGET_RTP) <= 0.005 else ""
            print(f"{tier['key']:>10} {entry:>6} {cost:>6.0f} {wincap:>7.0f} {raw:>9.3f} {capped:>9.3f} "
                  f"{mean_balls:>9.2f} {maxpm:>8.1f} {caphit*100:>7.3f}% {rtp*100:>6.2f}% {entry_target:>14.1f}{flag}")


if __name__ == "__main__":
    main()
