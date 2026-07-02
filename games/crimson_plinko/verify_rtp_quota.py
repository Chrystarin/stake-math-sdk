"""Independent RTP check: sample the real stratum mixture with the CONFIGURED BONUS_IN_DROP_RATE and
report capped per-mode RTP + cross-mode spread + max balls per bonus (RAM proxy). Dev tool."""
import random, math
from game_config import GameConfig
from gamestate import GameState
from plinko_data import (BALLS_PER_DROP_OPTIONS, BOARD_SLOT_MULTIPLIERS, TARGET_RTP,
    bonus_in_drop_rate, bonus_in_drop_for_balls, spin_in_drop_for_balls,
    scaled_spin_meter_max, scaled_spin_meter_start, scaled_bonus_meter_max,
    scaled_bonus_meter_start, wincap_for_balls)
ROW=14; STAKE=1.0
gs=GameState(GameConfig())
board=sum(math.comb(14,k)*m for k,m in enumerate(BOARD_SLOT_MULTIPLIERS))/(2**14)
print(f"board={board:.5f} target={TARGET_RTP}")
rtps=[]
for balls in BALLS_PER_DROP_OPTIONS:
    wc=wincap_for_balls(balls); q=bonus_in_drop_rate(balls)
    smax,sstart=scaled_spin_meter_max(balls),scaled_spin_meter_start(balls)
    bmax,bstart=scaled_bonus_meter_max(balls),scaled_bonus_meter_start(balls)
    spin_in=spin_in_drop_for_balls(balls); bonus_in=bonus_in_drop_for_balls(balls)
    # Per-tier sample count: the LOW tiers fire a rare, high-variance capped bonus (tier-1 ~0.1%), so a
    # flat 200k under-samples them and the tier-1 RTP reads wildly off (seen swinging 94.9%↔97.6%). Low
    # tiers are cheap (few balls/drop), so give them far more samples for a trustworthy read.
    N={1:3_000_000,10:1_200_000,20:700_000,50:350_000}.get(balls,200_000); pay=0.0; nb=0; cap=0; maxb=0
    for _ in range(N):
        force = random.random()<q
        outcomes,dw=gs.build_drop_outcomes(row_count=ROW,balls_per_drop=balls,stake_per_ball=STAKE)
        ev,fw,*_=gs.build_feature_meter_events(outcomes=outcomes,row_count=ROW,stake_per_ball=STAKE,
            balls_per_drop=balls,spin_meter_start=sstart,spin_meter_max=smax,spin_in_drop=spin_in,
            bonus_meter_start=bstart,bonus_meter_max=bmax,bonus_in_drop=bonus_in,force_bonus=force)
        t=dw+fw
        if t>wc: t=wc; cap+=1
        pay+=t
        bb=sum(e["freeBalls"] for e in ev if e["type"]=="bonusRound")
        if bb>maxb: maxb=bb
        if any(e["type"]=="bonusRoulette" for e in ev): nb+=1
    rtp=pay/N/balls; rtps.append(rtp)
    print(f"tier {balls:>2}: quota={q:.5f} bonusFire={nb/N*100:.3f}% capHit={cap/N*100:.4f}% maxBalls/bonus={maxb:>4} RTP={rtp*100:.3f}%")
print(f"spread={ (max(rtps)-min(rtps))*100:.3f}%  min={min(rtps)*100:.3f}% max={max(rtps)*100:.3f}%")
