"""Colour Dice compliance check — RTP band and max-win achievability, per bet mode.

Run from this directory:  python compliance_report.py

Verifies, for every published mode, that:
  1. RTP sits inside Stake's published 90.00%-96.70% band;
  2. the advertised max win is actually reachable at >= 1/20,000,000.

Both are computed by exhaustively walking the mode's outcome space — the same enumeration
`gamestate.py` writes books from — so these numbers are exact, not sampled. Mirrors
games/crimson_plinko/compliance_report.py, which certifies against the same two rules.
"""

from collections import Counter

from colour_dice_data import (
    BOOKS_PER_MODE,
    LAYOUTS,
    MAXWIN_HITRATE_MIN,
    NUM_DICE,
    RTP_MAX,
    RTP_MIN,
    TARGET_RTP,
    WHEEL,
    single_colour_rtp,
    decode_outcome,
    max_win_for_layout,
    max_win_hit_rate,
    max_win_vs_total_stake,
    mode_name,
    payout_multiplier,
    wheel_expected_value,
)


def walk_mode(layout):
    """Exhaustively evaluate one mode. Returns (rtp, max_win_hit_rate, top_multiplier)."""
    num_backed = len(layout)
    wincap = max_win_for_layout(layout)

    total = 0.0
    multiplier_counts = Counter()

    for index in range(BOOKS_PER_MODE):
        slots, wheel_award = decode_outcome(index)

        matches = [0] * num_backed
        for slot in slots:
            if slot < num_backed:
                matches[slot] += 1

        tripled = any(matched == NUM_DICE for matched in matches)
        multiplier = payout_multiplier(layout, matches, wheel_award if tripled else None)
        # Books are written clipped to the mode's wincap (run_sims overrides config.wincap).
        multiplier = min(multiplier, wincap)

        total += multiplier
        multiplier_counts[round(multiplier, 2)] += 1

    # The RGS charges `cost` (= total chips) x `amount` and pays `amount` x payoutMultiplier,
    # so RTP divides the mean multiplier by the mode's cost — same formula as the framework's
    # own per-thread readout in src/state/state.py.
    rtp = total / BOOKS_PER_MODE / sum(layout)
    top = max(multiplier_counts)
    hit_rate = multiplier_counts[round(wincap, 2)] / BOOKS_PER_MODE
    return rtp, hit_rate, top


def main() -> int:
    print(f"Wheel E[value] = {wheel_expected_value():.4f}   ({len(WHEEL)} tiers)")
    print(f"Declared RTP   = {TARGET_RTP:.6f}")
    print(f"RTP band       = {RTP_MIN:.4f} .. {RTP_MAX:.4f}")
    print(f"Max-win floor  = 1/{1 / MAXWIN_HITRATE_MIN:,.0f}")
    print(f"Books per mode = {BOOKS_PER_MODE:,}  (exhaustive)")
    print()
    print(
        f"{'mode':<20}{'colours':>8}{'RTP':>11}{'maxWin':>9}{'reached':>9}"
        f"{'x total':>10}{'hit rate':>14}  status"
    )
    print("-" * 92)

    exact_rtp = single_colour_rtp()
    failures = []
    for layout in LAYOUTS:
        name = mode_name(layout)
        advertised = max_win_for_layout(layout)
        rtp, hit_rate, top = walk_mode(layout)

        problems = []
        if not (RTP_MIN <= rtp <= RTP_MAX):
            problems.append(f"RTP {rtp:.6f} outside band")
        # Compare against the EXACT analytic RTP, not the 6dp figure declared to Stake.
        # max_win is an exact integer here, so nothing is clipped away and the two should
        # agree to floating-point noise. Any real gap means the payout maths has drifted.
        if abs(rtp - exact_rtp) > 1e-9:
            problems.append(f"RTP {rtp:.9f} != analytic {exact_rtp:.9f}")
        if abs(top - advertised) > 1e-9:
            problems.append(f"top multiplier {top} != advertised {advertised}")
        if hit_rate < MAXWIN_HITRATE_MIN:
            problems.append(f"max win too rare ({hit_rate:.3g})")

        status = "OK" if not problems else "FAIL: " + "; ".join(problems)
        if problems:
            failures.append(name)

        rate = f"1/{1 / hit_rate:,.0f}" if hit_rate else "never"
        print(
            f"{name:<20}{len(layout):>8}{rtp:>11.6f}{advertised:>9.0f}{top:>9.0f}"
            f"{max_win_vs_total_stake(layout):>9.2f}x{rate:>14}  {status}"
        )

    print("-" * 92)
    if failures:
        print(f"FAILED: {len(failures)} mode(s): {', '.join(failures)}")
        return 1
    print(f"All {len(LAYOUTS)} modes pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
