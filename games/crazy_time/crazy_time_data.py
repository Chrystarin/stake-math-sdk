"""Crazy Time (working title) — pure data + math for the prototype.

Money-wheel game show, single-player RNG, modelled on Evolution's Crazy Time:

  * a 54-segment wheel with 8 bet spots — four numbers (x1 x2 x5 x10) and four bonus rooms
    (Pirate Plinko, Bonus Wheel, Treasure Chest, Ocean Voyage);
  * a Top Slot that, before every spin, may attach a multiplier to ONE spot;
  * one bet mode per COMBINATION of spots: every non-empty subset of the eight (all 255), so
    the player can chip any spots they like at one chip each, any room on its own included.
    The player's chip is `amount`; the RGS charges `cost x amount`, cost being the number of
    spots covered (same shape as colour_dice / crimson_plinko).

OUTCOME MODEL
-------------
One round = (segment, top-slot entry, room outcome). The outcome space is small enough to
ENUMERATE, so every mode's books list each outcome exactly once and the lookup table carries
the outcome's exact probability weight (uint64). No RNG, no optimizer: the served RTP is the
analytic value.

RTP
---
Every spot is tuned to TARGET_RTP on its own. The lever is the Top Slot pairing weight
q[spot]: for a number paying n:1 the return per unit is

    P(hit) * (1 + n * (1 + q * (E[m] - 1)))          (Top Slot multiplies the n:1 payout)

and for a room with mean multiplier R it is

    P(hit) * R * (1 + q * (E[m] - 1))                (Top Slot multiplies the room result)

Solving each for q gives the Top Slot table; the leftover mass is the "miss" reel position.
Because every spot returns TARGET_RTP, every combination does too (linearity), so all 252
modes certify at one number with zero cross-mode spread.

STAKE COMPLIANCE (checked at import, see `compliance()`)
--------------------------------------------------------
  * RTP inside the published band and identical across modes;
  * non-zero hit rate >= 1 in 20 per mode: a combination must cover at least 3 of the 54
    segments. Every spot does on its own (the rarest rooms have 3), so every one of the 255
    combinations is a published mode. (Crazy Time's own 4/2/2/1 room split was tried first:
    its 2- and 1-segment rooms could not be bet alone under this rule.)
  * the advertised max win of every mode reached at >= 1 in 20,000,000. The binding case is
    Ocean Voyage's 400x depth under a 50x Top Slot (1 in 14.2 million); Pirate Plinko's 400x
    edges are next (1 in 10.7 million), which is why its landing weights carry a flat floor on
    top of the binomial (see PLINKO_TABLE); the Bonus Wheel's 1,000x sliver is 1 in 9.5 million.
"""

from fractions import Fraction
from itertools import combinations
from math import comb, lcm
from typing import Dict, List, Optional, Sequence, Tuple

# Stake's ceiling for Engine games. The Top Slot weights round DOWN (see TOP_SLOT_TABLE) so every
# mode lands a hair under it, never over.
TARGET_RTP = Fraction(967, 1000)  # 96.7%

# ---------------------------------------------------------------------------
# Spots and wheel
# ---------------------------------------------------------------------------
NUMBER_SPOTS: Tuple[str, ...] = ("x1", "x2", "x5", "x10")
ROOM_SPOTS: Tuple[str, ...] = ("piratePlinko", "bonusWheel", "chest", "oceanVoyage")
SPOTS: Tuple[str, ...] = NUMBER_SPOTS + ROOM_SPOTS

# n:1 payout of each number spot (x1 pays 1:1 -> gross 2x the chip).
NUMBER_PAY: Dict[str, int] = {"x1": 1, "x2": 2, "x5": 5, "x10": 10}

# Physical order around the rim, clockwise from the flapper. 54 entries.
# Counts: x1 19, x2 12, x5 6, x10 4, chest 4, Pirate Plinko 3, Ocean Voyage 3, Bonus Wheel 3.
# Every room has at least THREE segments so that a chip on any room alone pays at least once in
# 20 spins (Stake's floor for a base mode, see MIN_HIT_RATE): 3 of 54 is 1 in 18. Crazy Time's
# own 4/2/2/1 split was used before this and made the three rarer rooms company-only. The chest
# keeps its fourth segment as the most frequent room; the Bonus Wheel's rarity now lives INSIDE
# its room, in the 1,000x sliver (see WHEEL_TABLE), rather than on the rim.
# Rules: rooms cycle chest -> Pirate Plinko -> Bonus Wheel -> Ocean Voyage around the rim
# (thirteen rooms, the chest closing the loop), never adjacent, with three numbers between any
# two rooms — four in two places, opposite each other, to make the 54 — and x10 never next to x10.
SEGMENT_LAYOUT: Tuple[str, ...] = (
    "chest", "x1", "x2", "x1",
    "piratePlinko", "x2", "x10", "x1",
    "bonusWheel", "x1", "x5", "x2",
    "oceanVoyage", "x1", "x2", "x1", "x5",
    "chest", "x2", "x10", "x1",
    "piratePlinko", "x1", "x5", "x2",
    "bonusWheel", "x2", "x1", "x1",
    "oceanVoyage", "x1", "x10", "x2",
    "chest", "x1", "x5", "x2", "x1",
    "piratePlinko", "x2", "x1", "x5",
    "bonusWheel", "x1", "x10", "x2",
    "oceanVoyage", "x1", "x2", "x1",
    "chest", "x1", "x5", "x1",
)
NUM_SEGMENTS = len(SEGMENT_LAYOUT)
SEGMENT_COUNT: Dict[str, int] = {spot: SEGMENT_LAYOUT.count(spot) for spot in SPOTS}

assert NUM_SEGMENTS == 54, NUM_SEGMENTS
assert SEGMENT_COUNT == {"x1": 19, "x2": 12, "x5": 6, "x10": 4, "piratePlinko": 3, "bonusWheel": 3, "chest": 4, "oceanVoyage": 3}, SEGMENT_COUNT
_ROOM_CYCLE = ("chest", "piratePlinko", "bonusWheel", "oceanVoyage")
_rooms_in_order = [s for s in SEGMENT_LAYOUT if s in ROOM_SPOTS]
assert _rooms_in_order == [_ROOM_CYCLE[k % 4] for k in range(len(_rooms_in_order))], _rooms_in_order
_room_at = [i for i, s in enumerate(SEGMENT_LAYOUT) if s in ROOM_SPOTS]
_gaps = [(_room_at[(k + 1) % len(_room_at)] - _room_at[k]) % NUM_SEGMENTS - 1 for k in range(len(_room_at))]
assert sorted(_gaps) == [3] * 11 + [4] * 2, _gaps
for _i, _spot in enumerate(SEGMENT_LAYOUT):
    _next = SEGMENT_LAYOUT[(_i + 1) % NUM_SEGMENTS]
    assert not (_spot in ROOM_SPOTS and _next in ROOM_SPOTS), f"rooms adjacent at {_i}"
    assert not (_spot == "x10" and _next == "x10"), f"x10 adjacent at {_i}"

# ---------------------------------------------------------------------------
# Top Slot
# ---------------------------------------------------------------------------
# Right reel: (multiplier, weight) GIVEN the reel did not miss. Same shape as Crazy Time.
TOP_SLOT_MULTS: Tuple[Tuple[int, int], ...] = (
    (2, 250), (3, 213), (4, 102), (5, 90), (7, 53), (10, 34), (15, 17), (20, 13), (25, 8), (50, 3),
)
TOP_SLOT_MAX = max(m for m, _ in TOP_SLOT_MULTS)
# Integer resolution of the pairing table. Weights are exact to 1e-6 of a spin.
TOP_SLOT_TOTAL = 1_000_000

# ---------------------------------------------------------------------------
# Bonus rooms: (gross multiplier on the chip, weight)
# ---------------------------------------------------------------------------
# Pirate Plinko: 13 landing slots, symmetric. Min 5x, top 400x. Landing weights are binomial(12) plus a
# flat floor of PLINKO_WEIGHT_FLOOR per slot: a pure binomial puts the 400x edges at 2 in 4096,
# which under a 50x Top Slot is a 20,000x that lands too rarely for Stake's 1-in-20,000,000
# achievability floor for an advertised max win. The floor lifts the edges to 18 in 4200 (about
# 1 in 10.7 million with the Top Slot) at the cost of a slightly richer mean, which the pairing
# solver absorbs. The inner slots are lean (12.7x mean) because a 3-segment room may only return
# 17.4x per visit, Top Slot included — see _solve_pairing.
PLINKO_SLOTS: Tuple[int, ...] = (400, 80, 30, 20, 12, 8, 5, 8, 12, 20, 30, 80, 400)
PLINKO_WEIGHT_FLOOR = 8
PLINKO_TABLE: Tuple[Tuple[int, int], ...] = tuple(
    (v, comb(12, i) + PLINKO_WEIGHT_FLOOR) for i, v in enumerate(PLINKO_SLOTS)
)

# Bonus Wheel: 36 wedges, 35 of them full width and one JACKPOT SLIVER a quarter as wide. Weight
# is the wedge's width in units of WHEEL_SLIVER_UNITS (a full wedge is WHEEL_WEDGE_UNITS of them),
# so the wheel is honest: a wedge lands in proportion to the arc it shows.
#
# The sliver is what keeps the game's 50,000x max win (1,000x under a 50x Top Slot) on a room
# that now has three segments of the main wheel. A 3-segment room may only return 17.4x per visit
# (see _solve_pairing); a 1,000x wedge landing 1 in 36 would be 27.8x on its own, so the jackpot
# has to be rarer INSIDE the room — 1 in 141 visits at quarter width — and the rest of the wheel
# lean around it (2x floor, 13.9x mean). Stake's 1-in-20,000,000 max-win floor holds it from the
# other side: at 1 in 141 the 50,000x lands about 1 in 9.5 million, and a sliver much narrower
# than this (an eighth, say) would leave the room no Top Slot lift and miss that floor.
WHEEL_WEDGE_UNITS = 4
WHEEL_SLIVER_UNITS = 1
WHEEL_SLIVER_VALUE = 1000
WHEEL_TABLE: Tuple[Tuple[int, int], ...] = (
    (2, 16 * WHEEL_WEDGE_UNITS),
    (3, 8 * WHEEL_WEDGE_UNITS),
    (5, 6 * WHEEL_WEDGE_UNITS),
    (10, 3 * WHEEL_WEDGE_UNITS),
    (25, 1 * WHEEL_WEDGE_UNITS),
    (100, 1 * WHEEL_WEDGE_UNITS),
    (WHEEL_SLIVER_VALUE, WHEEL_SLIVER_UNITS),
)
WHEEL_UNITS = sum(w for _, w in WHEEL_TABLE)  # 141
# Wedge order around the bonus wheel (index -> value): the sliver at the top, the 100x opposite
# it, the 25x a quarter turn on, the 10s a third of a turn apart, 5s and 3s spaced, 2s filling in.
WHEEL_LAYOUT: Tuple[int, ...] = (
    1000, 2, 3, 2, 5, 2, 10, 2, 3, 25, 2, 5, 2, 3, 2, 10, 2, 5,
    100, 2, 3, 2, 5, 2, 10, 2, 3, 5, 2, 3, 2, 5, 2, 3, 2, 3,
)
WHEEL_WEDGES = len(WHEEL_LAYOUT)  # 36
# Width of each wedge, in the table's units; what the client draws and what the LUT weighs.
WHEEL_WIDTHS: Tuple[int, ...] = tuple(
    WHEEL_SLIVER_UNITS if v == WHEEL_SLIVER_VALUE else WHEEL_WEDGE_UNITS for v in WHEEL_LAYOUT
)
assert sum(WHEEL_WIDTHS) == WHEEL_UNITS
for _v, _w in WHEEL_TABLE:
    assert sum(u for v, u in zip(WHEEL_LAYOUT, WHEEL_WIDTHS) if v == _v) == _w, (_v, _w)

# Treasure chest: the player opens one of 12 chests; the awarded value comes from this table.
CHEST_TABLE: Tuple[Tuple[int, int], ...] = (
    (2, 24), (3, 22), (5, 18), (8, 12), (10, 9), (15, 6), (20, 4), (25, 2), (50, 2), (100, 1), (250, 1),
)
NUM_CHESTS = 12

# Ocean Voyage: 10 depths, 4 tiles per depth. The dive ends at depth k (1..10); depth k
# pays VOYAGE_DEPTHS[k-1]. Surfacing from the deepest one pays 400x, which under the 50x Top
# Slot is a 20,000x, the same ceiling as Pirate Plinko's edge slots; it is reached 1 in 102
# dives (1 in 14.2 million with the Top Slot). The middle depths are lean (15.5x mean) for the
# same reason as Plinko's: a 3-segment room returns 17.4x per visit, Top Slot included.
VOYAGE_DEPTHS: Tuple[int, ...] = (2, 3, 5, 8, 12, 20, 30, 50, 80, 400)
VOYAGE_DEPTH_WEIGHTS: Tuple[int, ...] = (22, 19, 16, 13, 10, 8, 6, 4, 3, 1)
VOYAGE_TABLE: Tuple[Tuple[int, int], ...] = tuple(zip(VOYAGE_DEPTHS, VOYAGE_DEPTH_WEIGHTS))
TILES_PER_DEPTH = 4

ROOM_TABLES: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "piratePlinko": PLINKO_TABLE,
    "bonusWheel": WHEEL_TABLE,
    "chest": CHEST_TABLE,
    "oceanVoyage": VOYAGE_TABLE,
}
ROOM_TOTAL_WEIGHT: Dict[str, int] = {room: sum(w for _, w in tbl) for room, tbl in ROOM_TABLES.items()}
ROOM_LCM = lcm(*ROOM_TOTAL_WEIGHT.values())


def room_mean(room: str) -> Fraction:
    tbl = ROOM_TABLES[room]
    return sum(Fraction(v) * w for v, w in tbl) / ROOM_TOTAL_WEIGHT[room]


# ---------------------------------------------------------------------------
# Top Slot pairing table (solved)
# ---------------------------------------------------------------------------
_ts_reel_total = sum(w for _, w in TOP_SLOT_MULTS)
TOP_SLOT_MEAN = sum(Fraction(m) * w for m, w in TOP_SLOT_MULTS) / _ts_reel_total  # E[m | aligned]


def _solve_pairing() -> Dict[str, Fraction]:
    """q[spot] = P(top slot aligns on spot) that lifts the spot to TARGET_RTP."""
    q: Dict[str, Fraction] = {}
    lift = TOP_SLOT_MEAN - 1
    for spot in SPOTS:
        need = TARGET_RTP * NUM_SEGMENTS / SEGMENT_COUNT[spot]  # required gross return per hit
        if spot in NUMBER_PAY:
            n = NUMBER_PAY[spot]
            q[spot] = ((need - 1) / n - 1) / lift
        else:
            q[spot] = (need / room_mean(spot) - 1) / lift
        assert q[spot] > 0, f"{spot} exceeds target without Top Slot: lower its table"
    assert sum(q.values()) < 1, f"Top Slot cannot lift every spot: sum q = {float(sum(q.values()))}"
    return q


TOP_SLOT_PAIRING: Dict[str, Fraction] = _solve_pairing()

# Flat Top Slot table: (spot or None, multiplier, weight). Last entry is the miss.
TopSlotEntry = Tuple[Optional[str], int, int]
TOP_SLOT_TABLE: Tuple[TopSlotEntry, ...]
_entries: List[TopSlotEntry] = []
for _spot in SPOTS:
    for _m, _w in TOP_SLOT_MULTS:
        # Floor, not round: TARGET_RTP is Stake's ceiling, so any rounding must land under it.
        _entries.append((_spot, _m, int(TOP_SLOT_PAIRING[_spot] * Fraction(_w, _ts_reel_total) * TOP_SLOT_TOTAL)))
_miss = TOP_SLOT_TOTAL - sum(e[2] for e in _entries)
assert _miss > 0
_entries.append((None, 1, _miss))
TOP_SLOT_TABLE = tuple(_entries)
TOP_SLOT_MISS_INDEX = len(TOP_SLOT_TABLE) - 1

# ---------------------------------------------------------------------------
# Modes: one per combination of spots
# ---------------------------------------------------------------------------
# Short code per spot; a mode name is the covered spots' codes joined in SPOTS order, e.g.
# "x1" (one spot), "pp_bw_tc_ov" (all four rooms), "x1_x2_x5_x10_pp_bw_tc_ov" (full board).
# The web client derives the same name from the board, so the two must never diverge.
SPOT_CODE: Dict[str, str] = {
    "x1": "x1", "x2": "x2", "x5": "x5", "x10": "x10",
    "piratePlinko": "pp", "bonusWheel": "bw", "chest": "tc", "oceanVoyage": "ov",
}

# Stake wants a base mode to pay at least once in MIN_HIT_RATE spins...
MIN_HIT_RATE = 20
# ...and its advertised max win to land at least once in MAX_WIN_FLOOR spins.
MAX_WIN_FLOOR = 20_000_000


def mode_name(spots: Sequence[str]) -> str:
    ordered = [spot for spot in SPOTS if spot in spots]
    return "_".join(SPOT_CODE[spot] for spot in ordered)


def _clears_hit_rate(spots: Sequence[str]) -> bool:
    return sum(SEGMENT_COUNT[s] for s in spots) * MIN_HIT_RATE >= NUM_SEGMENTS


def _all_combinations() -> Dict[str, Tuple[str, ...]]:
    modes: Dict[str, Tuple[str, ...]] = {}
    for k in range(1, len(SPOTS) + 1):
        for spots in combinations(SPOTS, k):
            if _clears_hit_rate(spots):
                modes[mode_name(spots)] = spots
    return modes


MODE_COVERAGE: Dict[str, Tuple[str, ...]] = _all_combinations()
MODE_NAMES: Tuple[str, ...] = tuple(MODE_COVERAGE)
# Spots whose one-spot bet would fail the hit-rate floor. Every spot covers at least 3 of the 54
# segments (see SEGMENT_LAYOUT), so this is empty and all 255 combinations are published; it is
# kept as the guard that says so, should the rim ever change again.
UNPUBLISHED_ALONE: Tuple[str, ...] = tuple(s for s in SPOTS if not _clears_hit_rate((s,)))
assert not UNPUBLISHED_ALONE, f"rooms too rare to bet alone: {UNPUBLISHED_ALONE}"
assert len(MODE_COVERAGE) == 2 ** len(SPOTS) - 1, len(MODE_COVERAGE)


def mode_for_spots(spots: Sequence[str]) -> Optional[str]:
    name = mode_name(spots)
    return name if name in MODE_COVERAGE else None


# ---------------------------------------------------------------------------
# Buy-bonus modes
# ---------------------------------------------------------------------------
# A buy skips the wait for the wheel and goes straight into a room, at the room's natural odds
# of ALSO carrying a Top Slot multiplier. Four per-room buys and one "any bonus" buy that lands on
# a room the way the wheel would, weighted by segments (chest 4, plinko 3, voyage 3, wheel 3).
#
# PRICE. Every spot returns TARGET_RTP on one chip, so a room's mean gross return per hit
# (Top Slot included) is TARGET_RTP * 54 / segments. Charging 54 / segments chips for one hit
# therefore returns exactly TARGET_RTP again: plinko 18, wheel 18, voyage 18, chest 13.5.
#
# The any-bonus buy is priced at a WHOLE number, BUY_ANY_PRICE = 17. Picking the room the way the
# wheel would (4 : 3 : 3 : 3) would make it 4 x 54 / 13 = 16.62, so instead the room is picked
# with BUY_ANY_PICK weights chosen so the expected fair price is exactly 17: the chest (13.5) is
# drawn 6 in 27, each 18-chip room 7 in 27, and 13.5 x 6/27 + 18 x 21/27 = 17. Same RTP as every
# other mode, and the buy disc's four equal quarters are closer to honest for it (22 / 26 / 26 /
# 26 % against the rim's 31 / 23 / 23 / 23). The client shows the price on the card and the
# book authors the room, so nothing else needs to know the weights.
#
# STAKE RULES. Buy modes are not base modes, so the 1-in-20 hit-rate floor does not apply (they
# always pay at least the room's minimum anyway); RTP must still sit with the other modes, and the
# max win must still be reachable at 1 in MAX_WIN_FLOOR (a bought Bonus Wheel hits 50,000x about
# 1 in 220,000). Books are enumerated exactly like the base game, restricted to the bought rooms'
# segments, so the book also carries the wheel landing on that room for the presentation.
BUY_MODES: Dict[str, Tuple[str, ...]] = {
    "buy_pp": ("piratePlinko",),
    "buy_bw": ("bonusWheel",),
    "buy_tc": ("chest",),
    "buy_ov": ("oceanVoyage",),
    "buy_any": ROOM_SPOTS,
}
BUY_MODE_NAMES: Tuple[str, ...] = tuple(BUY_MODES)
ALL_MODE_NAMES: Tuple[str, ...] = MODE_NAMES + BUY_MODE_NAMES

BUY_ANY_PRICE = 17
# How often the any-bonus buy opens each room (weights, not segments); see PRICE above.
BUY_ANY_PICK: Dict[str, int] = {"chest": 6, "piratePlinko": 7, "bonusWheel": 7, "oceanVoyage": 7}


def _fair_price(room: str) -> Fraction:
    """Chips that buy one visit to `room` at TARGET_RTP: 54 / its segments."""
    return Fraction(NUM_SEGMENTS, SEGMENT_COUNT[room])


assert set(BUY_ANY_PICK) == set(ROOM_SPOTS)
assert sum(Fraction(w, sum(BUY_ANY_PICK.values())) * _fair_price(r) for r, w in BUY_ANY_PICK.items()) == BUY_ANY_PRICE, (
    "BUY_ANY_PICK does not price the any-bonus buy at BUY_ANY_PRICE"
)


def buy_price(mode: str) -> Fraction:
    """Cost of a buy in chips: 54 / segments for a room, BUY_ANY_PRICE for any bonus."""
    if mode == "buy_any":
        return Fraction(BUY_ANY_PRICE)
    (room,) = BUY_MODES[mode]
    return _fair_price(room)


def coverage(mode: str) -> Tuple[str, ...]:
    """The spots a mode pays on: the combination's spots, or the rooms a buy can open."""
    return MODE_COVERAGE.get(mode) or BUY_MODES[mode]


def is_buy_mode(mode: str) -> bool:
    return mode in BUY_MODES


def mode_cost(mode: str):
    """Chips charged per `amount`: spots covered for a combination, the price for a buy."""
    return buy_price(mode) if mode in BUY_MODES else len(MODE_COVERAGE[mode])


# ---------------------------------------------------------------------------
# Outcome enumeration
# ---------------------------------------------------------------------------
# outcome = (segment index, top-slot index, room index or -1)
Outcome = Tuple[int, int, int]


def _enumerate(
    spots: Optional[Sequence[str]] = None, scale: Optional[Dict[str, int]] = None
) -> Tuple[List[Outcome], List[int]]:
    """Every (segment, Top Slot entry, room outcome) with its weight; `spots` restricts the
    segments (a buy only ever lands on its rooms' segments) and `scale` multiplies a spot's
    weights (the any-bonus buy picks rooms by BUY_ANY_PICK rather than by segments)."""
    outcomes: List[Outcome] = []
    weights: List[int] = []
    for seg, spot in enumerate(SEGMENT_LAYOUT):
        if spots is not None and spot not in spots:
            continue
        mult = scale.get(spot, 1) if scale else 1
        for ts_i, (_, _, ts_w) in enumerate(TOP_SLOT_TABLE):
            if spot in ROOM_TABLES:
                unit = ROOM_LCM // ROOM_TOTAL_WEIGHT[spot]
                for r_i, (_, r_w) in enumerate(ROOM_TABLES[spot]):
                    outcomes.append((seg, ts_i, r_i))
                    weights.append(ts_w * r_w * unit * mult)
            else:
                outcomes.append((seg, ts_i, -1))
                weights.append(ts_w * ROOM_LCM * mult)
    return outcomes, weights


OUTCOMES, OUTCOME_WEIGHTS = _enumerate()
BOOKS_PER_MODE = len(OUTCOMES)  # for every combination mode; buys have their own counts
TOTAL_WEIGHT = sum(OUTCOME_WEIGHTS)
assert TOTAL_WEIGHT == NUM_SEGMENTS * TOP_SLOT_TOTAL * ROOM_LCM
assert TOTAL_WEIGHT < 2**64


def _buy_any_scale() -> Dict[str, int]:
    """Integer factor per room that turns the segment shares (4 : 3 : 3 : 3) into BUY_ANY_PICK."""
    ratios = {r: Fraction(w, SEGMENT_COUNT[r]) for r, w in BUY_ANY_PICK.items()}
    common = lcm(*(f.denominator for f in ratios.values()))
    return {r: int(f * common) for r, f in ratios.items()}


# Buy modes: the same outcome space cut down to the bought rooms' segments (and, for the
# any-bonus buy, re-weighted between rooms).
BUY_OUTCOMES: Dict[str, Tuple[List[Outcome], List[int]]] = {
    mode: _enumerate(rooms, _buy_any_scale() if mode == "buy_any" else None)
    for mode, rooms in BUY_MODES.items()
}
assert all(sum(w) < 2**64 for _, w in BUY_OUTCOMES.values())


def outcomes_for(mode: str) -> Tuple[List[Outcome], List[int]]:
    """(outcomes, weights) enumerated for `mode`."""
    return BUY_OUTCOMES[mode] if mode in BUY_MODES else (OUTCOMES, OUTCOME_WEIGHTS)


def books_for_mode(mode: str) -> int:
    return len(outcomes_for(mode)[0])


def decode_outcome(index: int, mode: Optional[str] = None) -> Outcome:
    """Simulation index -> outcome for `mode` (any combination mode when omitted). Cycles."""
    outcomes = outcomes_for(mode)[0] if mode else OUTCOMES
    return outcomes[index % len(outcomes)]


def outcome_weight(index: int, mode: Optional[str] = None) -> int:
    outcomes, weights = outcomes_for(mode) if mode else (OUTCOMES, OUTCOME_WEIGHTS)
    return weights[index % len(outcomes)]


def outcome_details(outcome: Outcome) -> dict:
    """Everything the events need, as plain values."""
    seg, ts_i, r_i = outcome
    spot = SEGMENT_LAYOUT[seg]
    ts_spot, ts_mult, _ = TOP_SLOT_TABLE[ts_i]
    applied = ts_spot == spot
    mult = ts_mult if applied else 1
    room_value = ROOM_TABLES[spot][r_i][0] if r_i >= 0 else None
    return {
        "segment": seg,
        "spot": spot,
        "topSlotSpot": ts_spot,
        "topSlotMultiplier": ts_mult if ts_spot is not None else None,
        "topSlotApplied": applied,
        "appliedMultiplier": mult,
        "roomIndex": r_i,
        "roomValue": room_value,
    }


def spot_gross_return(spot: str, applied_multiplier: int, room_value: Optional[int]) -> int:
    """Gross return on ONE chip placed on `spot` when the wheel lands on `spot`."""
    if spot in NUMBER_PAY:
        return 1 + NUMBER_PAY[spot] * applied_multiplier
    assert room_value is not None
    return room_value * applied_multiplier


def payout_multiplier(mode: str, outcome: Outcome) -> int:
    """Book payout for `mode`, in units of `amount` (the chip). Integer by construction."""
    d = outcome_details(outcome)
    if d["spot"] not in coverage(mode):
        return 0
    return spot_gross_return(d["spot"], d["appliedMultiplier"], d["roomValue"])


def max_win_for_mode(mode: str) -> float:
    return float(max(payout_multiplier(mode, o) for o in outcomes_for(mode)[0]))


def mode_rtp(mode: str) -> Fraction:
    outcomes, weights = outcomes_for(mode)
    total = sum(Fraction(payout_multiplier(mode, o)) * w for o, w in zip(outcomes, weights))
    return total / (sum(weights) * mode_cost(mode))


def spot_return(spot: str) -> Fraction:
    """Return of one chip on `spot`, computed directly (every mode is a mean of these)."""
    total = Fraction(0)
    for o, w in zip(OUTCOMES, OUTCOME_WEIGHTS):
        d = outcome_details(o)
        if d["spot"] == spot:
            total += Fraction(spot_gross_return(spot, d["appliedMultiplier"], d["roomValue"])) * w
    return total / TOTAL_WEIGHT


def spot_max_win(spot: str) -> Tuple[int, Fraction]:
    """(max gross return of one chip on `spot`, its probability per spin)."""
    n = SEGMENT_COUNT[spot]
    q50 = next(w for sp, m, w in TOP_SLOT_TABLE if sp == spot and m == TOP_SLOT_MAX)
    if spot in NUMBER_PAY:
        return 1 + NUMBER_PAY[spot] * TOP_SLOT_MAX, Fraction(n, NUM_SEGMENTS) * Fraction(q50, TOP_SLOT_TOTAL)
    tbl = ROOM_TABLES[spot]
    top = max(v for v, _ in tbl)
    top_w = sum(w for v, w in tbl if v == top)
    p = Fraction(n, NUM_SEGMENTS) * Fraction(q50, TOP_SLOT_TOTAL) * Fraction(top_w, ROOM_TOTAL_WEIGHT[spot])
    return top * TOP_SLOT_MAX, p


def compliance() -> Dict[str, dict]:
    """Per-mode RTP, hit rate and max-win frequency, asserting Stake's rules for every mode.

    Uses the per-spot figures (a mode's return is the mean of its spots' returns; its hit rate
    the sum of their segment shares; its max win the largest of their caps), so it is cheap
    enough to run at import.
    """
    returns = {s: spot_return(s) for s in SPOTS}
    caps = {s: spot_max_win(s) for s in SPOTS}
    report: Dict[str, dict] = {}
    rtps = set()
    for mode, spots in MODE_COVERAGE.items():
        rtp = sum(returns[s] for s in spots) / len(spots)
        hit = Fraction(sum(SEGMENT_COUNT[s] for s in spots), NUM_SEGMENTS)
        top = max(caps[s][0] for s in spots)
        p_top = sum(caps[s][1] for s in spots if caps[s][0] == top)
        assert Fraction(90, 100) <= rtp <= Fraction(967, 1000), (mode, float(rtp))
        assert abs(rtp - TARGET_RTP) < Fraction(1, 10_000), (mode, float(rtp))
        assert hit * MIN_HIT_RATE >= 1, (mode, float(hit))
        assert p_top * MAX_WIN_FLOOR >= 1, (mode, top, float(1 / p_top))
        rtps.add(round(float(rtp), 5))
        report[mode] = {"rtp": rtp, "hit_rate": hit, "max_win": top, "p_max_win": p_top}
    # Buy modes: computed straight off their (small) outcome lists. Not base modes, so no
    # hit-rate floor; RTP band, spread and the max-win floor still apply.
    for mode in BUY_MODE_NAMES:
        outcomes, weights = outcomes_for(mode)
        total_w = sum(weights)
        payouts = [payout_multiplier(mode, o) for o in outcomes]
        rtp = sum(Fraction(pay) * w for pay, w in zip(payouts, weights)) / (total_w * buy_price(mode))
        hit = Fraction(sum(w for pay, w in zip(payouts, weights) if pay > 0), total_w)
        top = max(payouts)
        p_top = Fraction(sum(w for pay, w in zip(payouts, weights) if pay == top), total_w)
        assert Fraction(90, 100) <= rtp <= Fraction(967, 1000), (mode, float(rtp))
        assert abs(rtp - TARGET_RTP) < Fraction(1, 10_000), (mode, float(rtp))
        assert p_top * MAX_WIN_FLOOR >= 1, (mode, top, float(1 / p_top))
        rtps.add(round(float(rtp), 5))
        report[mode] = {"rtp": rtp, "hit_rate": hit, "max_win": top, "p_max_win": p_top}
    assert max(rtps) - min(rtps) <= 0.005, rtps
    return report


COMPLIANCE = compliance()


# ---------------------------------------------------------------------------
# Deterministic presentation extras (authored by the math, never by the client)
# ---------------------------------------------------------------------------
def _lcg(seed: int):
    state = (seed * 2654435761 + 12345) & 0xFFFFFFFF
    while True:
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        yield state


def _weighted_pick(table: Sequence[Tuple[int, int]], r: int) -> int:
    total = sum(w for _, w in table)
    r %= total
    for v, w in table:
        if r < w:
            return v
        r -= w
    return table[-1][0]


def chest_layout(index: int, awarded: int) -> Tuple[int, List[int]]:
    """(awarded chest index, values behind all 12 chests). Decoys are cosmetic."""
    rng = _lcg(index)
    awarded_at = next(rng) % NUM_CHESTS
    values = [_weighted_pick(CHEST_TABLE, next(rng)) for _ in range(NUM_CHESTS)]
    values[awarded_at] = awarded
    return awarded_at, values


def dive_path(index: int, depths_dived: int) -> Tuple[List[int], Optional[int]]:
    """(safe tile per dived depth, kraken tile at the depth that ended the dive or None)."""
    rng = _lcg(index + 7919)
    path = [next(rng) % TILES_PER_DEPTH for _ in range(depths_dived)]
    fail = None if depths_dived >= len(VOYAGE_DEPTHS) else next(rng) % TILES_PER_DEPTH
    return path, fail


def plinko_drop_zone(index: int) -> int:
    """Spawn column (0..12) shown for the drop. Cosmetic; the slot is authored."""
    return 3 + (next(_lcg(index + 31)) % 7)


def wheel_wedge_for_value(index: int, value: int) -> int:
    """Pick one of the wedges carrying `value`, deterministically."""
    wedges = [i for i, v in enumerate(WHEEL_LAYOUT) if v == value]
    return wedges[next(_lcg(index + 101)) % len(wedges)]


if __name__ == "__main__":
    print(f"books per mode: {BOOKS_PER_MODE}, total weight {TOTAL_WEIGHT:,}")
    print(f"Top Slot E[m | aligned] = {float(TOP_SLOT_MEAN):.4f}, miss share = {_miss / TOP_SLOT_TOTAL:.4f}")
    for spot in SPOTS:
        print(f"  {spot:7s} segs {SEGMENT_COUNT[spot]:2d}  q={float(TOP_SLOT_PAIRING[spot]):.4f}  return={float(spot_return(spot)):.6f}")
    print(f"modes: {len(MODE_NAMES)} (every spot bettable alone: {not UNPUBLISHED_ALONE})")
    worst = min(COMPLIANCE.items(), key=lambda kv: kv[1]["p_max_win"])
    print(f"rarest max win: {worst[0]} {worst[1]['max_win']}x at 1 in {float(1 / worst[1]['p_max_win']):,.0f}")
    for mode in ("x1", "pp", "bw", "ov", "pp_bw_tc_ov", "x1_x2_x5_x10_pp_bw_tc_ov") + BUY_MODE_NAMES:
        c = COMPLIANCE[mode]
        print(f"mode {mode:26s} cost {float(mode_cost(mode)):5.1f}  books {books_for_mode(mode):5d}  rtp {float(c['rtp']):.6f}  hit 1 in {float(1 / c['hit_rate']):.1f}  max_win {c['max_win']}x at 1 in {float(1 / c['p_max_win']):,.0f}")
