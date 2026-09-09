"""Crazy Time (working title) — pure data + math for the prototype.

Money-wheel game show, single-player RNG, modelled on Evolution's Crazy Time:

  * a 54-segment wheel with 8 bet spots — four numbers (x1 x2 x5 x10) and four bonus rooms
    (plinko, jackpot wheel, treasure chest, dragon tower);
  * a Top Slot that, before every spin, may attach a multiplier to ONE spot;
  * one bet mode per COMBINATION of spots: every non-empty subset of the eight that clears
    Stake's hit-rate floor (252 of the 255), so the player can chip any spots they like at
    one chip each. The player's chip is `amount`; the RGS charges `cost x amount`, cost being
    the number of spots covered (same shape as colour_dice / crimson_plinko).

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
    segments, which excludes the three one-room bets on plinko (2), tower (2) and wheel (1);
  * the advertised max win of every mode reached at >= 1 in 20,000,000. The binding case is
    the Plinko 400x slot under a 50x Top Slot, which is why the Plinko landing weights carry a
    flat floor on top of the binomial (see PLINKO_TABLE).
"""

from fractions import Fraction
from itertools import combinations
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
# Counts: x1 21, x2 13, x5 7, x10 4, chest 4, plinko 2, tower 2, wheel 1 — Crazy Time's own
# split (21/13/7/4 numbers; Coin Flip 4, Pachinko 2, Cash Hunt 2, Crazy Time 1), so the rooms
# rank chest < plinko = tower < wheel in rarity and the jackpot wheel is the one-off.
# Rules: one room every six segments (exactly five numbers between any two rooms, so the nine
# rooms are spread evenly: chests every 12, plinko and tower each an opposite pair, the jackpot
# wheel on its own), x10 never next to x10.
SEGMENT_LAYOUT: Tuple[str, ...] = (
    "chest", "x1", "x2", "x1", "x5", "x2",
    "plinko", "x1", "x10", "x1", "x2", "x1",
    "chest", "x2", "x1", "x5", "x1", "x2",
    "tower", "x1", "x2", "x1", "x5", "x1",
    "chest", "x1", "x10", "x2", "x1", "x2",
    "plinko", "x1", "x5", "x1", "x2", "x1",
    "chest", "x2", "x1", "x10", "x1", "x5",
    "tower", "x1", "x2", "x1", "x5", "x2",
    "wheel", "x1", "x10", "x2", "x1", "x5",
)
NUM_SEGMENTS = len(SEGMENT_LAYOUT)
SEGMENT_COUNT: Dict[str, int] = {spot: SEGMENT_LAYOUT.count(spot) for spot in SPOTS}

assert NUM_SEGMENTS == 54, NUM_SEGMENTS
assert SEGMENT_COUNT == {"x1": 21, "x2": 13, "x5": 7, "x10": 4, "plinko": 2, "wheel": 1, "chest": 4, "tower": 2}, SEGMENT_COUNT
for _i, _spot in enumerate(SEGMENT_LAYOUT):
    _next = SEGMENT_LAYOUT[(_i + 1) % NUM_SEGMENTS]
    assert (_spot in ROOM_SPOTS) == (_i % 6 == 0), f"room spacing broken at {_i}"
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
# Plinko: 13 landing slots, symmetric. Min 7x, top 400x. Landing weights are binomial(12) plus a
# flat floor of PLINKO_WEIGHT_FLOOR per slot: a pure binomial puts the 400x edges at 2 in 4096,
# which under a 50x Top Slot is a 20,000x that lands about once in 91 million, below Stake's
# 1-in-20,000,000 achievability floor for an advertised max win. The floor lifts the edges to
# 18 in 4200 (about 1 in 14.6 million with the Top Slot) at the cost of a slightly richer mean,
# which the pairing solver absorbs.
PLINKO_SLOTS: Tuple[int, ...] = (400, 100, 50, 30, 20, 12, 7, 12, 20, 30, 50, 100, 400)
PLINKO_WEIGHT_FLOOR = 8
PLINKO_TABLE: Tuple[Tuple[int, int], ...] = tuple(
    (v, comb(12, i) + PLINKO_WEIGHT_FLOOR) for i, v in enumerate(PLINKO_SLOTS)
)

# Jackpot wheel: 36 wedges. Weight == number of wedges carrying that value. The one-off
# segment of the main wheel, so it carries the richest table (min 10x, one 500x jackpot wedge).
WHEEL_TABLE: Tuple[Tuple[int, int], ...] = ((10, 10), (15, 8), (20, 6), (25, 5), (50, 3), (100, 2), (150, 1), (500, 1))
WHEEL_WEDGES = sum(w for _, w in WHEEL_TABLE)  # 36
# Wedge order around the bonus wheel (index -> value), spreading the big values apart.
WHEEL_LAYOUT: Tuple[int, ...] = (
    10, 15, 20, 10, 25, 10, 50, 15, 25, 20, 100, 10, 15, 25, 10, 20, 150, 15, 10, 50, 20, 10, 25, 15,
    100, 10, 20, 50, 15, 10, 500, 25, 15, 20, 10, 15,
)
assert len(WHEEL_LAYOUT) == WHEEL_WEDGES
for _v, _w in WHEEL_TABLE:
    assert WHEEL_LAYOUT.count(_v) == _w, (_v, _w)

# Treasure chest: the player opens one of 12 chests; the awarded value comes from this table.
CHEST_TABLE: Tuple[Tuple[int, int], ...] = (
    (2, 24), (3, 22), (5, 18), (8, 12), (10, 9), (15, 6), (20, 4), (25, 2), (50, 2), (100, 1), (250, 1),
)
NUM_CHESTS = 12

# Dragon tower: 10 floors, 4 tiles per floor. The climb ends on floor k (1..10); floor k
# pays TOWER_FLOORS[k-1]. Reaching the top pays 250x.
TOWER_FLOORS: Tuple[int, ...] = (2, 3, 5, 8, 12, 20, 35, 60, 120, 250)
TOWER_FLOOR_WEIGHTS: Tuple[int, ...] = (22, 19, 16, 13, 10, 8, 6, 4, 2, 2)
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
# Modes: one per combination of spots
# ---------------------------------------------------------------------------
# Short code per spot; a mode name is the covered spots' codes joined in SPOTS order, e.g.
# "x1" (one spot), "pk_jw_tc_dt" (all four rooms), "x1_x2_x5_x10_pk_jw_tc_dt" (full board).
# The web client derives the same name from the board, so the two must never diverge.
SPOT_CODE: Dict[str, str] = {
    "x1": "x1", "x2": "x2", "x5": "x5", "x10": "x10",
    "plinko": "pk", "wheel": "jw", "chest": "tc", "tower": "dt",
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
# Spots whose one-spot bet fails the hit-rate floor and is therefore NOT published alone.
UNPUBLISHED_ALONE: Tuple[str, ...] = tuple(s for s in SPOTS if not _clears_hit_rate((s,)))
assert len(MODE_COVERAGE) == 2 ** len(SPOTS) - 1 - len(UNPUBLISHED_ALONE), len(MODE_COVERAGE)


def mode_cost(mode: str) -> int:
    return len(MODE_COVERAGE[mode])


def mode_for_spots(spots: Sequence[str]) -> Optional[str]:
    name = mode_name(spots)
    return name if name in MODE_COVERAGE else None


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
    print(f"modes: {len(MODE_NAMES)} (not published alone: {UNPUBLISHED_ALONE})")
    worst = min(COMPLIANCE.items(), key=lambda kv: kv[1]["p_max_win"])
    print(f"rarest max win: {worst[0]} {worst[1]['max_win']}x at 1 in {float(1 / worst[1]['p_max_win']):,.0f}")
    for mode in ("x1", "pk_dt", "pk_jw_tc_dt", "x1_x2_x5_x10_pk_jw_tc_dt"):
        c = COMPLIANCE[mode]
        print(f"mode {mode:26s} cost {mode_cost(mode)}  rtp {float(c['rtp']):.6f}  hit 1 in {float(1 / c['hit_rate']):.1f}  max_win {c['max_win']}x")
