"""Low-variance per-mode RTP audit + lever solver for all 8 published modes (DEV TOOL, not published).

WHY THIS EXISTS. `measure_tuning_capped.py` / `verify_buybonus.py` average the SAMPLED payout, whose
variance is dominated by the board's 100x corner pockets (p = 2/16384 per ball, sd ~3.2 per ball). At
their sample counts that leaves ~0.2% of noise on every mode's RTP read — the same order as the whole
0.50% cross-mode compliance band, so a lever solved from those reads can miss target by more than the
band allows (the published tendrop LUT came out 0.69% under TARGET_RTP).

HOW THIS IS DIFFERENT: nothing about the pocket draw is sampled. The two feature-fire probabilities are
BINOMIAL IN CLOSED FORM (a drop's coin-peg hits and centre-pocket hits are both iid per ball), and the
board is folded in as its EXACT analytic EV times the BALL COUNT:

    E[win of a batch of N balls] = board_EV(tier) * E[N]        (N is peg/level driven, pockets are iid)

Coin-peg flags are sampled independently of the landing pocket (`build_drop_outcomes`), and the level-up
ladder reads only those flags, so the ball COUNT of a bonus is independent of what its balls pay. The
only sampled quantities left are E[bonus ball count], the free-spin cash, and the wincap excess — all of
them either low-variance or multiplied by a ~0.3% quota, which is why this lands ~20x tighter per sample.

Everything is measured through the REAL `simulate_bonus_round` / `build_drop_outcomes`, so the bonus
model is the published one, not a re-implementation.

Run: python games/crimson_plinko/rtp_audit.py [N_BONUS_SAMPLES]
"""

import math
import sys

from game_config import GameConfig
from gamestate import GameState
from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    BONUS_PEG_HIT_PROB,
    BUY_BONUS_BALLS_PER_DROP_REF,
    BUY_BONUS_TIER_DEFS,
    FREE_SPIN_SEGMENTS,
    FREE_SPIN_WEIGHTS,
    TARGET_RTP,
    bet_mode_for_balls_per_drop,
    board_ev_per_ball,
    bonus_in_drop_for_balls,
    bonus_in_drop_rate,
    bonus_peg_hit_prob,
    bonus_round_peg_hit_prob,
    bonus_wheel_mean_entry,
    buy_bonus_mode_name,
    deep_bonus_total_rate,
    coefficients_for,
    scaled_bonus_meter_max,
    scaled_bonus_meter_start,
    scaled_spin_meter_max,
    scaled_spin_meter_start,
    spin_in_drop_for_balls,
    spin_slot_index,
    wincap_for_balls,
)

ROW = 14
STAKE = 1.0


# ---------------------------------------------------------------------------
# Closed-form pieces.
# ---------------------------------------------------------------------------

def binom_tail(n: int, p: float, k: int) -> float:
    """P(Binomial(n, p) >= k) — exact."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    return math.fsum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1))


def centre_pocket_prob(row_count: int = ROW) -> float:
    """P(a ball lands in the centre pocket) — the free-spin meter's per-ball fill chance.

    `sample_rate_index` maps `row_count` fair deflections onto `row_count + 1` pockets 1:1, so the
    pocket index is Binomial(row_count, 1/2) and the centre is the middle term."""
    slots = row_count + 1
    return math.comb(row_count, spin_slot_index(slots)) / (2**row_count)


def spin_fire_prob(balls: int) -> float:
    """P(the per-drop free-spin meter reaches max within one drop of `balls` balls)."""
    if not spin_in_drop_for_balls(balls):
        return 0.0
    need = scaled_spin_meter_max(balls) - scaled_spin_meter_start(balls)
    return binom_tail(balls, centre_pocket_prob(), need)


def bonus_fire_prob(balls: int, peg_prob: float) -> float:
    """P(the per-drop bonus meter fills from this drop's own coin-peg hits)."""
    if not bonus_in_drop_for_balls(balls):
        return 0.0
    need = scaled_bonus_meter_max(balls) - scaled_bonus_meter_start(balls)
    return binom_tail(balls, peg_prob, need)


def free_spin_cash_ev() -> tuple[float, float]:
    """(mean cash multiplier of the wheel, P(BONUS segment)) under FREE_SPIN_WEIGHTS."""
    total = math.fsum(FREE_SPIN_WEIGHTS)
    cash = 0.0
    p_bonus = 0.0
    for segment, weight in zip(FREE_SPIN_SEGMENTS, FREE_SPIN_WEIGHTS):
        if segment == "BONUS":
            p_bonus += weight / total
        else:
            cash += (weight / total) * float(segment[:-1])
    return cash, p_bonus


def board_top(balls: int) -> float:
    """Highest pocket on the board this tier plays (its no-feature payout ceiling)."""
    return max(coefficients_for(ROW, balls))


# ---------------------------------------------------------------------------
# Sampled pieces (the bonus round, through the real math).
# ---------------------------------------------------------------------------

def bonus_stats(
    gs: GameState,
    *,
    tier_balls: int,
    n: int,
    entry_balls: int = 0,
    head_start: float = 0.0,
    peg_prob: float = BONUS_PEG_HIT_PROB,
) -> dict:
    """Sample `n` real bonus rounds; return the CONTROL-VARIATE value and the raw sample.

    `value` is the low-variance estimate of E[bonus win]: board_EV * E[free balls] + E[free-spin cash].
    `raw` / `raw_sq` come from the actually-sampled win and exist only for the wincap-excess term, which
    needs the real distribution rather than its mean."""
    board = board_ev_per_ball(tier_balls)
    balls_sum = 0
    balls_sq = 0
    cash_sum = 0.0
    raw = []
    level_sum = 0
    balls_max = 0
    for _ in range(n):
        events, win, level = gs.simulate_bonus_round(
            row_count=ROW,
            stake_per_ball=STAKE,
            balls_per_drop=tier_balls,
            entry_balls_override=entry_balls,
            levelup_head_start=head_start,
            peg_hit_prob=peg_prob,
        )
        free_balls = sum(e["freeBalls"] for e in events if e["type"] == "bonusRound")
        cash = math.fsum(
            float(e.get("amount", 0.0) or 0.0) for e in events if e["type"] == "freeSpinTrigger"
        )
        balls_sum += free_balls
        balls_sq += free_balls * free_balls
        cash_sum += cash
        raw.append(win)
        level_sum += level
        balls_max = max(balls_max, free_balls)
    mean_balls = balls_sum / n
    var_balls = max(0.0, balls_sq / n - mean_balls**2)
    return {
        "value": board * mean_balls + cash_sum / n,
        # SE of `value`, ignoring the (tiny) cash term — board_EV * sd(balls) / sqrt(n).
        "se": board * math.sqrt(var_balls / n),
        "raw": raw,
        "mean_balls": mean_balls,
        "max_balls": balls_max,
        "avg_level": level_sum / n,
        "n": n,
    }


def excess_ev(gs: GameState, *, balls: int, wincap: float, bonus_raw: list, n: int) -> float:
    """E[max(0, drop_win + bonus_win - wincap)] for a book that DOES fire a bonus.

    Pairs a freshly sampled paid drop with a bonus win drawn from `bonus_raw` (independent by
    construction — the bonus's balls are separate draws from the drop's)."""
    if not bonus_raw:
        return 0.0
    total = 0.0
    count = min(n, len(bonus_raw))
    for i in range(count):
        _outcomes, drop_win = gs.build_drop_outcomes(
            row_count=ROW, balls_per_drop=balls, stake_per_ball=STAKE
        )
        total += max(0.0, drop_win + bonus_raw[i] - wincap)
    return total / count


def cap_rate(bonus_raw: list, wincap: float) -> float:
    """Share of bonus rounds whose win alone reaches the wincap (max-win achievability proxy)."""
    if not bonus_raw:
        return 0.0
    return sum(1 for w in bonus_raw if w >= wincap) / len(bonus_raw)


# ---------------------------------------------------------------------------
# Per-mode RTP.
# ---------------------------------------------------------------------------

def base_mode_rtp(
    gs: GameState, balls: int, bonus: dict, *, quota: float, wincap: float, peg: float,
    deep: float = 0.0,
) -> dict:
    """Expected payout multiple / cost for a base tier, given its bonus stats and quota.

    A book's payout is `drop + free-spin cash + bonus - cap excess`, and expectations add, so each
    trigger path contributes independently of whether the others also fired that drop:

        drop            balls * board_EV                                     (exact)
        free spin       P(meter fills) * (wheel cash + P(BONUS) * bonus)      (P exact, bonus sampled)
        bonus           P(meter fills) or 1 on the forced stratum, * bonus
        cap             - P(a bonus fired) * E[excess over wincap]
    """
    board = board_ev_per_ball(balls)
    p_spin = spin_fire_prob(balls)
    p_bonus = bonus_fire_prob(balls, peg)
    wheel_cash, p_wheel_bonus = free_spin_cash_ev()
    b_val = bonus["value"]
    # Free-spin contribution is identical on both strata (the forced quota only pre-fills coin pegs,
    # which are independent of the pockets that fill the spin meter).
    spin_add = p_spin * (wheel_cash + p_wheel_bonus * b_val)
    # Expected NUMBER of bonuses in this book, per stratum — the cap-excess weight. A book can run two
    # (the meter's and one chained off a BONUS wheel segment), in which case the real excess over the cap
    # is larger than one bonus's; weighting by the expected count approximates that. It is a correction to
    # a correction — `excess` itself is worth ~0.02% of RTP on the normal stratum — so the approximation
    # is far below the estimator's own noise floor.
    p_any_norm = p_bonus + p_spin * p_wheel_bonus
    p_any_forced = 1.0 + p_spin * p_wheel_bonus
    excess = excess_ev(gs, balls=balls, wincap=wincap, bonus_raw=bonus["raw"], n=bonus["n"])

    e_norm = balls * board + spin_add + p_bonus * b_val - p_any_norm * excess
    e_forced = balls * board + spin_add + b_val - p_any_forced * excess
    # DEEP-BONUS strata: a forced round is worth hundreds-to-thousands of x and every wincap clips it
    # from level 6 up, so EVERY target level's book settles at EXACTLY the cap — no sampling needed, and no cap-excess term (there is nothing above the
    # cap left to subtract). Tiny, but it must be in the model: a solver that ignores a stratum silently
    # mis-attributes its cost to whichever lever it IS solving.
    e_deep = wincap
    rtp = ((1.0 - quota - deep) * e_norm + quota * e_forced + deep * e_deep) / balls
    denom = e_forced - e_norm
    solved = (
        0.0
        if denom <= 1e-9
        else max(0.0, min(1.0, (TARGET_RTP * balls - (1.0 - deep) * e_norm - deep * e_deep) / denom))
    )
    return {
        "e_norm": e_norm,
        "e_forced": e_forced,
        "rtp": rtp,
        "solved_quota": solved,
        "p_spin": p_spin,
        "p_bonus": p_bonus,
        # SE of the mode RTP from the sampled bonus value only (the rest is closed-form).
        "se": (p_any_norm + quota) * bonus["se"] / balls,
    }


def buy_mode_rtp(gs: GameState, tier: dict, bonus: dict, *, deep: float = 0.0) -> dict:
    """Expected payout multiple / cost for a buy tier (bonus only, empty paid drop)."""
    wincap = float(tier["wincap"])
    cost = float(tier["cost"])
    raw = bonus["raw"]
    excess = math.fsum(max(0.0, w - wincap) for w in raw) / len(raw)
    # DEEP-BONUS stratum settles at the cap — see the note in `base_mode_rtp`.
    return {
        "rtp": ((1.0 - deep) * (bonus["value"] - excess) + deep * wincap) / cost,
        "se": bonus["se"] / cost,
        "cap_rate": cap_rate(raw, wincap),
        "max_win": min(max(raw), wincap),
    }


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60_000
    gs = GameState(GameConfig())
    print(f"rtp_audit — TARGET_RTP = {TARGET_RTP}   bonus samples/mode = {n:,}")
    print(f"board_EV/ball: shared {board_ev_per_ball(10):.6f}   1-ball {board_ev_per_ball(1):.6f}")
    wheel_cash, p_wheel_bonus = free_spin_cash_ev()
    print(f"free-spin wheel: mean cash {wheel_cash:.4f}x   P(BONUS segment) {p_wheel_bonus:.4f}")
    print(f"centre-pocket P {centre_pocket_prob():.6f}   coin-peg P {BONUS_PEG_HIT_PROB}\n")

    rows = []
    incidence: dict[str, float] = {}

    print(f"{'mode':>13} {'cost':>5} {'cap':>5} {'P(spin)':>9} {'P(bonus)':>9} {'quota':>9} "
          f"{'solved':>9} {'RTP':>9} {'+-SE':>7}")
    for balls in BALLS_PER_DROP_OPTIONS:
        mode = f"{balls}-ball"
        wincap = wincap_for_balls(balls)
        quota = bonus_in_drop_rate(balls)
        if not bonus_in_drop_for_balls(balls) and quota <= 0.0:
            # FEATURE-FREE tier: no bonus, no free spin, and the wincap IS the board's top pocket, so
            # the mode RTP is the board EV in closed form — nothing to sample.
            rtp = board_ev_per_ball(balls)
            assert wincap >= board_top(balls), (
                f"{mode}: wincap {wincap} below the board top {board_top(balls)} — the closed-form "
                "RTP would need a cap-excess term."
            )
            rows.append((mode, rtp, 0.0))
            print(f"{mode:>13} {float(balls):>5.0f} {wincap:>5.0f} {0.0:>9.5f} {0.0:>9.5f} "
                  f"{quota:>9.5f} {'  (n/a)':>9} {rtp*100:>8.3f}% {0.0:>6.3f}%")
            continue
        mode_name = bet_mode_for_balls_per_drop(balls)
        # TWO DIFFERENT PEGS since the flat-rate re-tune: `peg` fills the paid drop's trigger meter,
        # `bonus_peg` climbs the level-up ladder once the bonus is running. Passing one for both (as
        # this tool did before the split) misreads BOTH the fire rate and the bonus EV.
        peg = bonus_peg_hit_prob(mode_name)
        bonus_peg = bonus_round_peg_hit_prob(mode_name)
        bonus = bonus_stats(gs, tier_balls=balls, n=n, peg_prob=bonus_peg)
        deep = deep_bonus_total_rate(mode_name)
        r = base_mode_rtp(gs, balls, bonus, quota=quota, wincap=wincap, peg=peg, deep=deep)
        rows.append((mode, r["rtp"], r["se"]))
        # Total bonus incidence per bet — the meter/quota path OR the free-spin wheel chaining one.
        # This is the number the flat-rate design pins, so surface it next to the RTP.
        p_trigger = quota + deep + (1.0 - quota - deep) * r["p_bonus"]
        incidence[mode] = 1.0 - (1.0 - p_trigger) * (1.0 - r["p_spin"] * free_spin_cash_ev()[1])
        print(f"{mode:>13} {float(balls):>5.0f} {wincap:>5.0f} {r['p_spin']:>9.5f} "
              f"{r['p_bonus']:>9.5f} {quota:>9.5f} {r['solved_quota']:>9.5f} "
              f"{r['rtp']*100:>8.3f}% {r['se']*100:>6.3f}%")

    print()
    print(f"{'mode':>13} {'cost':>5} {'cap':>5} {'entry':>6} {'pegP':>7} {'avgLv':>6} "
          f"{'balls':>7} {'maxB':>5} {'capHit':>9} {'RTP':>9} {'+-SE':>7}")
    for tier in BUY_BONUS_TIER_DEFS:
        name = buy_bonus_mode_name(tier["key"])
        bonus = bonus_stats(
            gs,
            tier_balls=BUY_BONUS_BALLS_PER_DROP_REF,
            n=n,
            entry_balls=int(tier["entry_balls"]),
            head_start=float(tier.get("head_start", 0.0)),
            peg_prob=bonus_round_peg_hit_prob(name),
        )
        r = buy_mode_rtp(gs, tier, bonus, deep=deep_bonus_total_rate(name))
        rows.append((name, r["rtp"], r["se"]))
        print(f"{name:>13} {float(tier['cost']):>5.0f} {float(tier['wincap']):>5.0f} "
              f"{int(tier['entry_balls']):>6} {bonus_peg_hit_prob(name):>7.4f} "
              f"{bonus['avg_level']:>6.2f} {bonus['mean_balls']:>7.1f} {bonus['max_balls']:>5} "
              f"{r['cap_rate']*100:>8.4f}% {r['rtp']*100:>8.3f}% {r['se']*100:>6.3f}%")

    if incidence:
        print()
        print("bonus incidence per bet (meter/quota OR a free-spin BONUS chain) — pinned FLAT:")
        for mode, p in incidence.items():
            print(f"{mode:>13} {p*100:>8.4f}%   wheel mean entry "
                  f"{bonus_wheel_mean_entry(int(mode.split('-')[0])):>6.2f} balls")
        spread_inc = (max(incidence.values()) - min(incidence.values())) * 100
        print(f"{'spread':>13} {spread_inc:>8.4f}%")

    rtps = [r[1] for r in rows]
    spread = (max(rtps) - min(rtps)) * 100
    worst = max(rows, key=lambda r: abs(r[1] - TARGET_RTP))
    print(f"\ncross-mode spread = {spread:.3f}%  [limit 0.500%]   "
          f"range {min(rtps)*100:.3f}% .. {max(rtps)*100:.3f}%")
    print(f"furthest from target: {worst[0]} at {worst[1]*100:.3f}% "
          f"({(worst[1]-TARGET_RTP)*100:+.3f}%)")


if __name__ == "__main__":
    main()
