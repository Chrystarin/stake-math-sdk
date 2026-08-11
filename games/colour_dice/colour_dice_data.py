"""Colour Dice shared data — colours, wheel, bet modes and payout maths.

Mirrored on the web side by `apps/colour-dice/src/game/constants.ts`. Keep the two in sync.

THE MODEL
---------
The player backs between 1 and `MAX_COLOURS` of the six colours, EVERY ONE AT THE SAME
STAKE, then rolls three dice. Each backed colour pays independently on how many dice show it:

    1 die   -> 2x        2 dice -> 3x        3 dice -> Lucky Wheel (4x .. 200x)

Payout is expressed in units of `amount` (the per-colour stake):

    multiplier = sum(pay(matches_c)) over the backed colours

WHY 6 MODES
-----------
The RGS settles a round from a precomputed book — one hashed `payoutMultiplier` per book,
selected by `mode` — so the shape of the bet must be known before the book is drawn.

Because the stake is equal on every backed colour, and the six colours are statistically
identical, a round is fully described by HOW MANY colours were backed. Which ones is
irrelevant. That gives exactly one mode per count:

    mode   = '3_colours'      three colours backed
    cost   = 3                total stake = cost x amount
    amount = stake per colour

Same `cost`/`amount` shape as `games/crimson_plinko` (cost = balls per drop). Note `amount`
is submitted verbatim with no scaling, so it is always a chip-tray denomination — which
keeps every reachable bet trivially on the RGS betLevels grid.

RTP
---
Any single colour's match count is Binomial(3, 1/6), so per unit staked on one colour:

    E[pay] = 75/216*2 + 15/216*3 + 1/216*E[wheel]

With E[wheel] = 13.42 that is 208.42/216 = 0.964907.

By linearity of expectation the mean multiplier is `k * 0.964907` for k backed colours, and
dividing by cost k returns that same figure — so all 6 modes certify at one identical RTP,
comfortably inside Stake's published 90.00%-96.70% band.
"""

import math
from typing import Dict, Sequence, Tuple

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
# Canonical order, shared with the web client. Dice in a book are encoded as SLOTS relative
# to the player's layout ("B1".. = backed colours heaviest-first, "O1".. = unbacked in
# canonical order), never as literal colours — so one book set serves every colour choice.
COLOURS: Tuple[str, ...] = ("yellow", "blue", "white", "green", "pink", "red")
NUM_COLOURS = len(COLOURS)

NUM_DICE = 3

# ---------------------------------------------------------------------------
# Paytable
# ---------------------------------------------------------------------------
# Gross return multiplier per matching die count, per unit staked on that colour.
# 3 matches is not listed: a triple resolves on the wheel instead.
PAYTABLE_MATCHES: Dict[int, float] = {0: 0.0, 1: 2.0, 2: 3.0}

# ---------------------------------------------------------------------------
# Lucky Wheel (triple match)
# ---------------------------------------------------------------------------
# (gross_multiplier, weight); weights sum to WHEEL_WEIGHT_TOTAL. RETUNED 2026-08: the
# previous ladder (E = 14.538) put the game at 97.01% RTP, ABOVE the 96.70% compliance
# ceiling. Weight was moved off the 200x/100x tiers onto 4x, bringing E down to 13.42 ->
# 96.49% RTP with ~0.21pt of headroom under the cap.
#
# The 200x top prize is unchanged, so the advertised max win is untouched; it lands at
# (1/216)*(1/100) = 1/21,600, far above Stake's 1/20,000,000 achievability floor.
#
# Weights are expressed out of 100 (not 1000) deliberately: books are enumerated
# exhaustively at exact frequency (see BOOKS_PER_MODE), and the denominator sets how many
# books each mode needs. 100 keeps that at a practical 21,600 per mode.
WHEEL: Tuple[Tuple[int, int], ...] = (
    (4, 58),
    (10, 22),
    (20, 12),
    (50, 5),
    (100, 2),
    (200, 1),
)

WHEEL_VALUES: Tuple[int, ...] = tuple(value for value, _ in WHEEL)
WHEEL_WEIGHTS: Tuple[int, ...] = tuple(weight for _, weight in WHEEL)
WHEEL_WEIGHT_TOTAL = sum(WHEEL_WEIGHTS)
WHEEL_TOP = max(WHEEL_VALUES)

# ---------------------------------------------------------------------------
# Exhaustive outcome enumeration
# ---------------------------------------------------------------------------
# Each die independently shows one of six colours, so a round has 6**3 = 216 equally likely
# slot arrangements. Only a triple consults the wheel, which has WHEEL_WEIGHT_TOTAL
# equally-likely weight units.
#
# The whole space therefore fits in DICE_ARRANGEMENTS * WHEEL_WEIGHT_TOTAL books per mode,
# each appearing exactly once. Generating it in full (rather than sampling) means uniform
# lookup-table weights already reproduce the true distribution, so the served RTP is the
# analytic value EXACTLY — no Monte-Carlo error, and the rare 200x tail is guaranteed
# present in every mode's books rather than left to chance.
DICE_ARRANGEMENTS = NUM_COLOURS**NUM_DICE  # 216
BOOKS_PER_MODE = DICE_ARRANGEMENTS * WHEEL_WEIGHT_TOTAL  # 21,600

# Wheel value for each weight unit 0..WHEEL_WEIGHT_TOTAL-1, expanded once at import.
_WHEEL_BY_UNIT: Tuple[int, ...] = tuple(
    value for value, weight in WHEEL for _ in range(weight)
)


def decode_outcome(index: int) -> Tuple[Tuple[int, int, int], int]:
    """Map a book index to its (dice slots, wheel award).

    `index` cycles over BOOKS_PER_MODE. The low digits pick the dice arrangement and the
    high digits pick the wheel weight unit, so every (arrangement, wheel) pair occurs at
    exactly its true frequency across one full cycle.

    Returned slots are indices into the player's colour ordering: 0..k-1 are the backed
    colours heaviest-first, k..5 are the unbacked ones. The wheel award is always returned
    but is only consumed when some backed colour takes all three dice.
    """
    position = index % BOOKS_PER_MODE
    arrangement = position % DICE_ARRANGEMENTS
    wheel_unit = position // DICE_ARRANGEMENTS

    slots = (
        arrangement % NUM_COLOURS,
        (arrangement // NUM_COLOURS) % NUM_COLOURS,
        (arrangement // (NUM_COLOURS * NUM_COLOURS)) % NUM_COLOURS,
    )
    return slots, _WHEEL_BY_UNIT[wheel_unit]


def wheel_expected_value() -> float:
    """Mean wheel award."""
    total_weight = sum(WHEEL_WEIGHTS)
    return sum(value * weight for value, weight in WHEEL) / total_weight


def single_colour_rtp() -> float:
    """E[pay] per unit staked on one colour — and, by linearity, the RTP of every mode."""
    total = float(NUM_COLOURS**NUM_DICE)  # 216
    # P(k matches) * pay(k), summed over k, with k == 3 resolving on the wheel.
    expected = 0.0
    for matches, count in _match_count_distribution().items():
        pay = wheel_expected_value() if matches == NUM_DICE else PAYTABLE_MATCHES[matches]
        expected += count * pay
    return expected / total


def _match_count_distribution() -> Dict[int, int]:
    """Number of the 216 equally-likely rolls giving each match count for one colour."""
    counts: Dict[int, int] = {}
    for matches in range(NUM_DICE + 1):
        ways = math.comb(NUM_DICE, matches) * (NUM_COLOURS - 1) ** (NUM_DICE - matches)
        counts[matches] = ways
    return counts


# Declared RTP for the Stake Engine math summary. Identical for every mode (see module docstring).
TARGET_RTP = round(single_colour_rtp(), 6)

# Stake's published compliance band and max-win achievability floor (see
# games/crimson_plinko/compliance_report.py, which certifies against the same rules).
RTP_MIN, RTP_MAX = 0.90, 0.967
MAXWIN_HITRATE_MIN = 1 / 20_000_000

# ---------------------------------------------------------------------------
# Backed-colour count -> bet modes
# ---------------------------------------------------------------------------
# EQUAL STAKE: the player backs between 1 and MAX_COLOURS colours, every one carrying the
# same stake. So a round is described entirely by HOW MANY colours were backed — which colours
# is irrelevant, since all six are statistically identical.
#
# That gives exactly one mode per count:
#
#     mode   = '3_colours'      three colours backed
#     cost   = 3                total stake = cost x amount
#     amount = stake per colour (submitted verbatim, so it is always a tray denomination)
#
# A layout is still carried as a tuple of per-colour stakes so the payout maths below is
# shared, but every entry is 1 — the weights are equal by construction.
MAX_COLOURS = NUM_COLOURS

Layout = Tuple[int, ...]

# The 6 published layouts, one per backed-colour count.
LAYOUTS: Tuple[Layout, ...] = tuple((1,) * count for count in range(1, MAX_COLOURS + 1))


def mode_name(layout: Layout) -> str:
    """RGS `/wallet/play` mode: how many colours the player backed.

    (1, 1, 1) -> '3_colours'. The name is the bet, so a mode is readable straight out of a
    log, a book filename or the ACP without a lookup table.
    """
    return f"{len(layout)}_colours"


def layout_for_mode(mode: str) -> Layout:
    """Inverse of `mode_name`. Raises for an unpublished mode."""
    layout = LAYOUT_BY_MODE.get(mode)
    if layout is None:
        raise KeyError(f"unknown colour_dice bet mode: {mode!r} (published: {sorted(LAYOUT_BY_MODE)})")
    return layout


LAYOUT_BY_MODE: Dict[str, Layout] = {mode_name(layout): layout for layout in LAYOUTS}
MODE_NAMES: Tuple[str, ...] = tuple(mode_name(layout) for layout in LAYOUTS)


def max_win_for_layout(layout: Layout) -> float:
    """Max win for a layout in PAYOUT-MULTIPLIER units, i.e. as a multiple of `amount`.

    This is what `BetMode.max_win` and `config.wincap` want, matching how the RGS settles:
    payout = amount x payoutMultiplier, with `cost` charged separately. (Same convention as
    crimson_plinko's `wincap_for_balls`, which is "per stake_per_ball".)

    The biggest possible round is a backed colour taking a triple with the wheel landing on
    its top value; a triple consumes all three dice, so no other colour can also pay. Under
    equal stakes that is WHEEL_TOP for every mode — the cap against `amount` does not vary
    with how many colours were backed (the cap against TOTAL stake does; see
    `max_win_vs_total_stake`). Always an exact integer, so nothing is rounded off the
    advertised figure.
    """
    return float(max(layout) * WHEEL_TOP)


def max_win_vs_total_stake(layout: Layout) -> float:
    """Player-facing max win: a multiple of the TOTAL stake (amount x chips).

    Use this for UI copy and marketing; use `max_win_for_layout` for the math config.
    """
    return max_win_for_layout(layout) / sum(layout)


def max_win_hit_rate() -> float:
    """P(max win) — one specific colour triples, then the wheel lands top. Layout-independent."""
    p_triple_specific_colour = 1 / (NUM_COLOURS**NUM_DICE)
    p_wheel_top = WHEEL_WEIGHTS[WHEEL_VALUES.index(WHEEL_TOP)] / sum(WHEEL_WEIGHTS)
    return p_triple_specific_colour * p_wheel_top


def payout_multiplier(layout: Layout, matches: Sequence[int], wheel_award: float | None) -> float:
    """Round payout multiplier, in units of `amount` (the per-chip stake).

    Every chip stakes `amount`, so a colour carrying `chips` chips and paying `pay` returns
    `chips * pay * amount`. The RGS settles payout = amount x payoutMultiplier and charges
    `cost` (= total chips) separately, so this is deliberately NOT divided by the chip
    count — dividing here would understate the payout by a factor of `cost`.

    `matches[i]` is how many dice showed the colour carrying `layout[i]` chips.
    `wheel_award` is the wheel result when some colour tripled, else None.
    """
    total = 0.0
    for chips, matched in zip(layout, matches):
        if matched == NUM_DICE:
            if wheel_award is None:
                raise ValueError("a triple match requires a wheel award")
            total += chips * wheel_award
        else:
            total += chips * PAYTABLE_MATCHES[matched]
    return total
