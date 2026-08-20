"""Solve each feature mode's IN-BONUS coin-peg probability back to TARGET_RTP (DEV TOOL, not published).

WHY THIS LEVER AND NOT THE QUOTA. `rtp_audit.py` solves `BONUS_IN_DROP_RATE`, which moves how OFTEN a
bonus arrives — and that is exactly what the flat-2% design pins (see BONUS_IN_DROP_RATE). Anything that
changes what a bonus is WORTH must be paid for on the in-bonus side instead:

    base modes   BONUS_ROUND_PEG_HIT_PROB_BY_MODE   (in-bonus only; the drop-side peg stays 0.18,
                                                     so the trigger rate and incidence do not move)
    buy modes    BUY_BONUS_TIER_DEFS[peg_hit_prob]  (a buy has no paid drop, so this is already
                                                     in-bonus only)

COMMON RANDOM NUMBERS. Every candidate is evaluated from the same seed, so the DIFFERENCE between two
candidates is far less noisy than either absolute read — which is what a local-derivative solve needs
(BUY_BONUS_TIER_DEFS: "solve it from the LOCAL derivative at the current value ... do not interpolate").

Run: python games/crimson_plinko/solve_in_bonus_peg.py [N] [SEED]
"""

import random
import sys

from game_config import GameConfig
from gamestate import GameState
from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    BUY_BONUS_BALLS_PER_DROP_REF,
    BUY_BONUS_TIER_DEFS,
    TARGET_RTP,
    bet_mode_for_balls_per_drop,
    bonus_in_drop_for_balls,
    bonus_in_drop_rate,
    bonus_peg_hit_prob,
    bonus_round_peg_hit_prob,
    buy_bonus_mode_name,
    wincap_for_balls,
)
from rtp_audit import base_mode_rtp, bonus_stats, buy_mode_rtp

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20_000
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 12345


def base_rtp_at(gs, balls, peg_in_bonus):
    random.seed(SEED)
    bonus = bonus_stats(gs, tier_balls=balls, n=N, peg_prob=peg_in_bonus)
    mode = bet_mode_for_balls_per_drop(balls)
    r = base_mode_rtp(gs, balls, bonus, quota=bonus_in_drop_rate(balls),
                      wincap=wincap_for_balls(balls), peg=bonus_peg_hit_prob(mode))
    return r["rtp"], bonus


def buy_rtp_at(gs, tier, peg_in_bonus):
    random.seed(SEED)
    bonus = bonus_stats(gs, tier_balls=BUY_BONUS_BALLS_PER_DROP_REF, n=N,
                        entry_balls=int(tier["entry_balls"]),
                        head_start=float(tier.get("head_start", 0.0)),
                        peg_prob=peg_in_bonus)
    r = buy_mode_rtp(gs, tier, bonus)
    return r["rtp"], bonus


def solve(evaluate, p0, label):
    """Secant solve on the local derivative, then confirm at the answer."""
    step = max(0.002, p0 * 0.10)
    lo, hi = max(0.001, p0 - step), min(0.60, p0 + step)
    r_lo, b_lo = evaluate(lo)
    r_hi, b_hi = evaluate(hi)
    slope = (r_hi - r_lo) / (hi - lo)
    if abs(slope) < 1e-9:
        print(f"{label:>13}  flat response — cannot solve")
        return p0, None
    p = p0 + (TARGET_RTP - (r_lo + r_hi) / 2) / slope
    p = max(0.001, min(0.60, p))
    r, b = evaluate(p)
    # one Newton refinement off the same slope
    p2 = max(0.001, min(0.60, p + (TARGET_RTP - r) / slope))
    r2, b2 = evaluate(p2)
    if abs(r2 - TARGET_RTP) < abs(r - TARGET_RTP):
        p, r, b = p2, r2, b2
    print(f"{label:>13}  p {p0:.5f} -> {p:.5f}   RTP {r*100:7.3f}%   "
          f"slope {slope*100:6.1f} pts/0.01 -> {slope*100/100:.2f}   "
          f"avgLv {b['avg_level']:.2f}  balls {b['mean_balls']:.1f}  max {b['max_balls']}")
    return p, b


def main():
    gs = GameState(GameConfig())
    print(f"solve_in_bonus_peg — TARGET_RTP {TARGET_RTP}   n={N:,}   seed={SEED}")
    print("levers: base = BONUS_ROUND_PEG_HIT_PROB_BY_MODE, buys = BUY_BONUS_TIER_DEFS[peg_hit_prob]")
    print("(quotas, meter bars, wheel values, wincaps, costs, entry balls, thresholds all held FIXED)\n")
    out = {}
    for balls in BALLS_PER_DROP_OPTIONS:
        if not bonus_in_drop_for_balls(balls) and bonus_in_drop_rate(balls) <= 0.0:
            continue
        mode = bet_mode_for_balls_per_drop(balls)
        p0 = bonus_round_peg_hit_prob(mode)
        p, _ = solve(lambda q, b=balls: base_rtp_at(gs, b, q), p0, mode)
        out[mode] = p
    print()
    for tier in BUY_BONUS_TIER_DEFS:
        name = buy_bonus_mode_name(tier["key"])
        p0 = float(tier["peg_hit_prob"])
        p, _ = solve(lambda q, t=tier: buy_rtp_at(gs, t, q), p0, name)
        out[name] = p
    print("\nsolved in-bonus peg probabilities:")
    for k, v in out.items():
        print(f"    {k:>13}: {v:.5f}")


if __name__ == "__main__":
    main()
