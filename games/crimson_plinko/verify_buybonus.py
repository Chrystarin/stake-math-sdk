"""Authoritative buy-bonus RTP check: sample the REAL GameState.simulate_bonus_round with each tier's
configured entry_balls / head_start / levelup_pegs (from plinko_data.BUY_BONUS_TIER_DEFS), cap at the
tier wincap, and report RTP + cap-hit + max. Confirms Option B before the full run.py LUT build.

Run: env/Scripts/python.exe games/crimson_plinko/verify_buybonus.py [N]
"""
import statistics
import sys

from game_config import GameConfig
from gamestate import GameState
from plinko_data import BUY_BONUS_BALLS_PER_DROP_REF, BUY_BONUS_TIER_DEFS

ROW = 14
STAKE = 1.0


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120000
    gs = GameState(GameConfig())
    print(f"REAL simulate_bonus_round check (n={n}/tier, ref bpd={BUY_BONUS_BALLS_PER_DROP_REF})")
    print(f"{'tier':>10} {'entry':>5} {'pegs':>4} {'cost':>5} {'cap':>5} {'RTP%':>7} "
          f"{'capHit%':>9} {'maxPM':>7} {'meanBalls':>9}")
    rtps = []
    for t in BUY_BONUS_TIER_DEFS:
        entry = int(t["entry_balls"]); cost = float(t["cost"]); cap = float(t["wincap"])
        hs = float(t.get("head_start", 0.0)); pegs = int(t.get("levelup_pegs", 0))
        caps = []; caphit = 0; maxpm = 0.0; balls_tot = 0
        for _ in range(n):
            events, win, _lvl = gs.simulate_bonus_round(
                row_count=ROW, stake_per_ball=STAKE, balls_per_drop=BUY_BONUS_BALLS_PER_DROP_REF,
                entry_balls_override=entry, levelup_head_start=hs, levelup_pegs_override=pegs,
            )
            pm = win / STAKE
            c = min(pm, cap)
            caps.append(c)
            if pm >= cap:
                caphit += 1
            maxpm = max(maxpm, c)
            balls_tot += sum(e["freeBalls"] for e in events if e["type"] == "bonusRound")
        rtp = statistics.mean(caps) / cost
        rtps.append(rtp)
        print(f"{t['key']:>10} {entry:>5} {pegs:>4} {cost:>5.0f} {cap:>5.0f} {rtp*100:>6.2f}% "
              f"{caphit/n*100:>8.4f}% {maxpm:>7.1f} {balls_tot/n:>9.1f}")
    if rtps:
        print(f"\nbuy-mode spread = {(max(rtps)-min(rtps))*100:.3f}%  "
              f"(min {min(rtps)*100:.2f}%  max {max(rtps)*100:.2f}%)")
        print("base modes are ~95.59-95.80%; all 8 must sit within a 1.00% band.")


if __name__ == "__main__":
    main()
