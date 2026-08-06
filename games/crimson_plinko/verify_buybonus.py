"""Buy-bonus RTP check: sample the REAL GameState.simulate_bonus_round with each tier's configured
entry_balls / head_start / peg_hit_prob (from plinko_data.BUY_BONUS_TIER_DEFS), cap at the tier wincap,
and report RTP + cap-hit + max + level depth.

⚠️ SUPERSEDED FOR SOLVING `peg_hit_prob` — USE `rtp_audit.py`. This averages the SAMPLED payout, whose
variance is dominated by the board's 100× corner pockets, so an n=30k read carries ~0.2% of noise per
tier — wider than the whole 0.50% cross-mode compliance band. `rtp_audit.py` folds the board in as its
exact analytic EV × the sampled BALL COUNT (which has no such spikes) and reads the same tiers to ±0.02%.
This one is still the useful cross-check that the shipped `simulate_bonus_round` behaves, and the place
to read raw level depth / balls-per-book / cap-hit.

Every mode now climbs the SAME level-up ladder (plinko_data.BONUS_LEVELUP_PEG_HITS_BY_LEVEL); each buy
tier is held at TARGET_RTP by its own coin-peg probability instead, so `peg_hit_prob` is the column to
tune here (~3-4 RTP points per 0.01).

Run: env/Scripts/python.exe games/crimson_plinko/verify_buybonus.py [N]
"""
import statistics
import sys

from game_config import GameConfig
from gamestate import GameState
from plinko_data import (
    BONUS_LEVELUP_PEG_HITS_BY_LEVEL,
    BUY_BONUS_BALLS_PER_DROP_REF,
    BUY_BONUS_TIER_DEFS,
    TARGET_RTP,
)

ROW = 14
STAKE = 1.0


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120000
    gs = GameState(GameConfig())
    ladder = list(BONUS_LEVELUP_PEG_HITS_BY_LEVEL.values())
    print(f"REAL simulate_bonus_round check (n={n}/tier, ref bpd={BUY_BONUS_BALLS_PER_DROP_REF})")
    print(f"shared level-up ladder = {ladder}   TARGET_RTP = {TARGET_RTP}")
    print(f"{'tier':>10} {'entry':>5} {'pegProb':>8} {'cost':>5} {'cap':>5} {'RTP%':>7} "
          f"{'capHit%':>9} {'maxPM':>7} {'avgLv':>6} {'L2%':>6} {'meanBalls':>9} {'maxBalls':>9}")
    rtps = []
    for t in BUY_BONUS_TIER_DEFS:
        entry = int(t["entry_balls"]); cost = float(t["cost"]); cap = float(t["wincap"])
        hs = float(t.get("head_start", 0.0)); prob = float(t.get("peg_hit_prob", 0.0))
        caps = []; caphit = 0; maxpm = 0.0; balls_tot = 0; balls_max = 0
        lvl_tot = 0; lvl2 = 0
        for _ in range(n):
            events, win, lvl = gs.simulate_bonus_round(
                row_count=ROW, stake_per_ball=STAKE, balls_per_drop=BUY_BONUS_BALLS_PER_DROP_REF,
                entry_balls_override=entry, levelup_head_start=hs, peg_hit_prob=prob,
            )
            pm = win / STAKE
            c = min(pm, cap)
            caps.append(c)
            if pm >= cap:
                caphit += 1
            maxpm = max(maxpm, c)
            balls = sum(e["freeBalls"] for e in events if e["type"] == "bonusRound")
            balls_tot += balls
            balls_max = max(balls_max, balls)
            lvl_tot += lvl
            lvl2 += 1 if lvl >= 2 else 0
        rtp = statistics.mean(caps) / cost
        rtps.append(rtp)
        print(f"{t['key']:>10} {entry:>5} {prob:>8.5f} {cost:>5.0f} {cap:>5.0f} {rtp*100:>6.2f}% "
              f"{caphit/n*100:>8.4f}% {maxpm:>7.1f} {lvl_tot/n:>6.2f} {lvl2/n*100:>5.1f}% "
              f"{balls_tot/n:>9.1f} {balls_max:>9}")
    if rtps:
        print(f"\nbuy-mode spread = {(max(rtps)-min(rtps))*100:.3f}%  "
              f"(min {min(rtps)*100:.2f}%  max {max(rtps)*100:.2f}%)")
        print("Target is TARGET_RTP on every tier; all 8 published modes must sit within 0.50%.")
        print("This read carries ~0.2%/tier of sampling noise at n=30k — solve with rtp_audit.py.")


if __name__ == "__main__":
    main()
