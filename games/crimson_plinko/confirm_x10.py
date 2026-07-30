"""Fast confirm of the ×10 buy tiers on the SHARED level-up ladder (numpy sim)."""
import numpy as np
from gate_tune import LADDER, sim  # sim(entry, peg_prob, wincap) -> (cappedPayout, level, totalBalls)
from plinko_data import BUY_BONUS_TIER_DEFS

N = 200000
print(f"FAST ×10 confirm on the shared ladder {LADDER} (n={N}/tier)")
print(f"{'tier':>10} {'entry':>5} {'pegProb':>8} {'cost':>5} {'cap':>4} {'RTP%':>7} {'capHit%':>9} {'maxPM':>6} {'L9%':>7} {'maxBalls':>8}")
rtps = []
for t in BUY_BONUS_TIER_DEFS:
    e = int(t["entry_balls"]); c = float(t["cost"]); cap = float(t["wincap"]); prob = float(t["peg_hit_prob"])
    caps = np.empty(N); lvl = np.empty(N, dtype=int); tot = np.empty(N, dtype=int)
    for i in range(N):
        caps[i], lvl[i], tot[i] = sim(e, prob, cap)
    rtp = caps.mean() / c; rtps.append(rtp)
    print(f"{t['key']:>10} {e:>5} {prob:>8.4f} {c:>5.0f} {cap:>4.0f} {rtp*100:>6.2f}% "
          f"{(caps>=cap).mean()*100:>8.4f}% {caps.max():>6.0f} {np.mean(lvl>=9)*100:>6.4f}% {tot.max():>8}")
print(f"\nbuy spread = {(max(rtps)-min(rtps))*100:.3f}%  min {min(rtps)*100:.2f}%  max {max(rtps)*100:.2f}%")
print("base modes = 95.700% (measure_tuning_capped); all 8 must be within a 1.00% band.")
