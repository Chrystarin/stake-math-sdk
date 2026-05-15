"""Crimson Plinko coefficient tables (aligned with apps/plinko config)."""

# difficulty -> row tier index (row_count - 8) -> slot multipliers
# Row tiers 8..20 map to indices 0..12. Tables match 14-row crimson board (13 slots).
COEFFICIENT_SETS: list[list[list[float]]] = [
    [
        [18, 3.2, 1.6, 1.1, 1, 0.5, 0.3, 0.5, 1, 1.1, 1.6, 3.2, 18],
    ]
    * 13,
    [
        [33, 11, 4, 2, 1.1, 0.6, 0.3, 0.6, 1.1, 2, 4, 11, 33],
    ]
    * 13,
    [
        [110, 41, 10, 5, 3, 1.5, 0.5, 1.5, 3, 5, 10, 41, 110],
    ]
    * 13,
    [
        [170, 67, 20, 7, 2, 0.2, 0.2, 0.2, 2, 7, 20, 67, 170],
    ]
    * 13,
]

ROW_COUNT_OPTIONS = (10, 14, 20)
BALLS_PER_DROP_OPTIONS = (10, 20, 50)
DIFFICULTY_COUNT = 4


def row_tier_index(row_count: int) -> int:
    return max(0, min(row_count - 8, 12))


def coefficients_for(difficulty: int, row_count: int) -> list[float]:
    d = max(0, min(difficulty, DIFFICULTY_COUNT - 1))
    tier = row_tier_index(row_count)
    return list(COEFFICIENT_SETS[d][tier])


def spin_slot_index(num_slots: int) -> int:
    return (num_slots - 1) // 2
