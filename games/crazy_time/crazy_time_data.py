"""Crazy Time (working title) — pure data + math for the prototype.

Money-wheel game show, single-player RNG, modelled on Evolution's Crazy Time:

  * a 54-segment wheel with 8 bet spots — four numbers (x1 x2 x5 x10) and four bonus rooms
    (plinko, multiplier wheel, treasure chest, dragon tower);
  * a Top Slot that, before every spin, may attach a multiplier to ONE spot;
  * ten bet modes: the eight single spots, `bonuses` (all four rooms, cost 4) and
    `full_board` (all eight spots, cost 8). The player's chip is `amount`; the RGS charges
    `cost x amount` (same shape as colour_dice / crimson_plinko).

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
Because every spot returns TARGET_RTP, every bundle does too (linearity), so all ten modes
certify at one number.
"""

from fractions import Fraction
from math import comb, lcm
from typing import Dict, List, Optional, Sequence, Tuple

TARGET_RTP = Fraction(965, 1000)  # 96.5%

# ---------------------------------------------------------------------------
# Spots and wheel
# ---------------------------------------------------------------------------
NUMBER_SPOTS: Tuple[str, ...] = ("x1", "x2", "x5", "x10")
ROOM_SPOTS: Tuple[str, ...] = ("plinko", "wheel", "chest", "tower")
SPOTS: Tuple[str, ...] = NUMBER_SPOTS + ROOM_SPOTS

# n:1 payout of each number spot (x1 pays 1:1 -> gross 2x the chip).
NUMBER_PAY: Dict[str, int] = {"x1": 1, "x2": 2, "x5": 5, "x10": 10}

# Physical order around the rim, clockwise from the flapper. 54 entries.
# Counts: x1 19, x2 12, x5 6, x10 4, plinko 4, wheel 3, chest 3, tower 3.
# Rules: rooms never adjacent, plinko on the quarter points, x10 never next to x10.
SEGMENT_LAYOUT: Tuple[str, ...] = (
    "plinko", "x1", "x2", "x1", "wheel", "x1", "x5", "x1", "x2", "chest", "x1", "x10", "x2",
    "plinko", "x1", "x2", "x1", "x5", "tower", "x1", "x2", "x1", "wheel", "x1", "x10", "x2", "x1",
    "plinko", "x2", "x1", "x5", "chest", "x1", "x2", "x1", "tower", "x1", "x5", "x2", "x1",
    "plinko", "x1", "x10", "x2", "x5", "wheel", "x1", "x5", "x2", "chest", "x1", "x10", "tower", "x2",
)
NUM_SEGMENTS = len(SEGMENT_LAYOUT)
SEGMENT_COUNT: Dict[str, int] = {spot: SEGMENT_LAYOUT.count(spot) for spot in SPOTS}

assert NUM_SEGMENTS == 54, NUM_SEGMENTS
assert SEGMENT_COUNT == {"x1": 19, "x2": 12, "x5": 6, "x10": 4, "plinko": 4, "wheel": 3, "chest": 3, "tower": 3}, SEGMENT_COUNT
for _i, _spot in enumerate(SEGMENT_LAYOUT):
    _next = SEGMENT_LAYOUT[(_i + 1) % NUM_SEGMENTS]
    assert not (_spot in ROOM_SPOTS and _next in ROOM_SPOTS), f"rooms adjacent at {_i}"

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
# Plinko: 13 landing slots, symmetric, binomial(12) landing weights. Min 4x, top 400x.
PLINKO_SLOTS: Tuple[int, ...] = (400, 80, 40, 20, 12, 7, 4, 7, 12, 20, 40, 80, 400)
PLINKO_TABLE: Tuple[Tuple[int, int], ...] = tuple((v, comb(12, i)) for i, v in enumerate(PLINKO_SLOTS))

# Multiplier wheel: 36 wedges. Weight == number of wedges carrying that value.
WHEEL_TABLE: Tuple[Tuple[int, int], ...] = ((2, 13), (3, 9), (5, 6), (10, 3), (20, 2), (50, 1), (100, 1), (200, 1))
WHEEL_WEDGES = sum(w for _, w in WHEEL_TABLE)  # 36
# Wedge order around the bonus wheel (index -> value), spreading the big values apart.
WHEEL_LAYOUT: Tuple[int, ...] = (
    2, 3, 2, 5, 2, 10, 3, 2, 5, 2, 3, 100, 2, 3, 5, 2, 20, 3, 2, 5, 2, 3, 50, 2,
    3, 5, 2, 10, 3, 2, 200, 2, 5, 3, 20, 10,
)
assert len(WHEEL_LAYOUT) == WHEEL_WEDGES
for _v, _w in WHEEL_TABLE:
    assert WHEEL_LAYOUT.count(_v) == _w, (_v, _w)

# Treasure chest: the player opens one of 12 chests; the awarded value comes from this table.
CHEST_TABLE: Tuple[Tuple[int, int], ...] = (
    (2, 20), (3, 18), (5, 16), (8, 12), (10, 10), (15, 8), (20, 6), (25, 4), (50, 3), (100, 2), (250, 1),
)
NUM_CHESTS = 12

# Dragon tower: 10 floors, 4 tiles per floor. The climb ends on floor k (1..10); floor k
# pays TOWER_FLOORS[k-1]. Reaching the top pays 250x.
TOWER_FLOORS: Tuple[int, ...] = (2, 3, 5, 8, 12, 20, 35, 60, 120, 250)
TOWER_FLOOR_WEIGHTS: Tuple[int, ...] = (24, 20, 16, 12, 9, 7, 5, 3, 2, 1)
TOWER_TABLE: Tuple[Tuple[int, int], ...] = tuple(zip(TOWER_FLOORS, TOWER_FLOOR_WEIGHTS))
TOWER_TILES_PER_FLOOR = 4

ROOM_TABLES: Dict[str, Tuple[Tuple[int, int], ...]] = {
    "plinko": PLINKO_TABLE,
    "wheel": WHEEL_TABLE,
    "chest": CHEST_TABLE,
    "tower": TOWER_TABLE,
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
        _entries.append((_spot, _m, round(TOP_SLOT_PAIRING[_spot] * Fraction(_w, _ts_reel_total) * TOP_SLOT_TOTAL)))
_miss = TOP_SLOT_TOTAL - sum(e[2] for e in _entries)
assert _miss > 0
_entries.append((None, 1, _miss))
TOP_SLOT_TABLE = tuple(_entries)
TOP_SLOT_MISS_INDEX = len(TOP_SLOT_TABLE) - 1

# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
MODE_COVERAGE: Dict[str, Tuple[str, ...]] = {
    **{spot: (spot,) for spot in SPOTS},
    "bonuses": ROOM_SPOTS,
    "full_board": SPOTS,
}
MODE_NAMES: Tuple[str, ...] = tuple(MODE_COVERAGE)


def mode_cost(mode: str) -> int:
    return len(MODE_COVERAGE[mode])


# ---------------------------------------------------------------------------
# Outcome enumeration
# ---------------------------------------------------------------------------
# outcome = (segment index, top-slot index, room index or -1)
Outcome = Tuple[int, int, int]


def _enumerate() -> Tuple[List[Outcome], List[int]]:
    outcomes: List[Outcome] = []
    weights: List[int] = []
    for seg, spot in enumerate(SEGMENT_LAYOUT):
        for ts_i, (_, _, ts_w) in enumerate(TOP_SLOT_TABLE):
            if spot in ROOM_TABLES:
                unit = ROOM_LCM // ROOM_TOTAL_WEIGHT[spot]
                for r_i, (_, r_w) in enumerate(ROOM_TABLES[spot]):
                    outcomes.append((seg, ts_i, r_i))
                    weights.append(ts_w * r_w * unit)
            else:
                outcomes.append((seg, ts_i, -1))
                weights.append(ts_w * ROOM_LCM)
    return outcomes, weights


OUTCOMES, OUTCOME_WEIGHTS = _enumerate()
BOOKS_PER_MODE = len(OUTCOMES)
TOTAL_WEIGHT = sum(OUTCOME_WEIGHTS)
assert TOTAL_WEIGHT == NUM_SEGMENTS * TOP_SLOT_TOTAL * ROOM_LCM
assert TOTAL_WEIGHT < 2**64


def decode_outcome(index: int) -> Outcome:
    """Simulation index -> outcome. Cycles, so any index is valid."""
    return OUTCOMES[index % BOOKS_PER_MODE]


def outcome_weight(index: int) -> int:
    return OUTCOME_WEIGHTS[index % BOOKS_PER_MODE]


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
    if d["spot"] not in MODE_COVERAGE[mode]:
        return 0
    return spot_gross_return(d["spot"], d["appliedMultiplier"], d["roomValue"])


def max_win_for_mode(mode: str) -> float:
    return float(max(payout_multiplier(mode, o) for o in OUTCOMES))


def mode_rtp(mode: str) -> Fraction:
    total = sum(Fraction(payout_multiplier(mode, o)) * w for o, w in zip(OUTCOMES, OUTCOME_WEIGHTS))
    return total / (TOTAL_WEIGHT * mode_cost(mode))


def spot_return(spot: str) -> Fraction:
    return mode_rtp(spot)


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


def tower_path(index: int, floors_climbed: int) -> Tuple[List[int], Optional[int]]:
    """(safe tile per climbed floor, dragon tile on the floor that ended the climb or None)."""
    rng = _lcg(index + 7919)
    path = [next(rng) % TOWER_TILES_PER_FLOOR for _ in range(floors_climbed)]
    fail = None if floors_climbed >= len(TOWER_FLOORS) else next(rng) % TOWER_TILES_PER_FLOOR
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
    for mode in MODE_NAMES:
        print(f"mode {mode:10s} cost {mode_cost(mode)}  rtp {float(mode_rtp(mode)):.6f}  max_win {max_win_for_mode(mode):.0f}x")
