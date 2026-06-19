"""Plinko path sampling, feature meter walking, and payout helpers.

All randomness for features lives here so the published books are authoritative:
the client animates exactly these outcomes and never rolls its own dice.
"""

import random as py_random

from plinko_data import (
    BONUS_METER_MAX,
    BONUS_PEG_HIT_PROB,
    FREE_SPIN_SEGMENTS,
    SPIN_METER_MAX,
    bonus_wheel_free_balls,
    coefficients_for,
    spin_slot_index,
)
from src.executables.executables import Executables


class GameCalculations(Executables):
    """Galton-board style slot sampling for crimson plinko."""

    FREE_SPIN_SEGMENTS: list[str] = list(FREE_SPIN_SEGMENTS)

    def sample_rate_index(self, row_count: int, num_slots: int) -> int:
        """Map `row_count` binary peg deflections to a slot index."""
        if num_slots <= 1:
            return 0
        rights = sum(py_random.randint(0, 1) for _ in range(row_count))
        return min(num_slots - 1, round(rights * (num_slots - 1) / row_count))

    def is_spin_slot(self, rate_index: int, num_slots: int) -> bool:
        return rate_index == spin_slot_index(num_slots)

    def build_drop_outcomes(
        self,
        *,
        row_count: int,
        balls_per_drop: int,
        stake_per_ball: float,
    ) -> tuple[list[dict], float]:
        """Sample `balls_per_drop` balls; each carries pocket + feature flags."""
        coeffs = coefficients_for(row_count)
        if not coeffs:
            return [], 0.0

        outcomes: list[dict] = []
        total_win = 0.0
        num_slots = len(coeffs)
        for _ in range(balls_per_drop):
            rate_index = self.sample_rate_index(row_count, num_slots)
            hit_spin_slot = self.is_spin_slot(rate_index, num_slots)
            multiplier = 0.0 if hit_spin_slot else coeffs[rate_index]
            hit_bonus_peg = py_random.random() < BONUS_PEG_HIT_PROB
            total_win += stake_per_ball * multiplier
            outcomes.append(
                {
                    "rateIndex": rate_index,
                    "multiplier": multiplier,
                    "amount": stake_per_ball,
                    "hitBonusPeg": hit_bonus_peg,
                    "hitSpinSlot": hit_spin_slot,
                }
            )
        return outcomes, total_win

    def _drop_win_from_outcomes(self, outcomes: list[dict], stake_per_ball: float) -> float:
        """Sum slot payouts for a drop (spin-pocket balls pay 0)."""
        stake = max(0.0, float(stake_per_ball))
        total = 0.0
        for outcome in outcomes:
            if outcome.get("hitSpinSlot"):
                continue
            total += stake * float(outcome.get("multiplier", 0) or 0)
        return total

    def simulate_bonus_round(
        self,
        *,
        row_count: int,
        stake_per_ball: float,
        balls_per_drop: int,
    ) -> tuple[list[dict], float, int]:
        """
        Simulate a SINGLE-LEVEL bonus round (Option #1 — normal-bet-cost bonus).

        The bonus wheel awards free balls SIZED to the tier (`bonus_wheel_free_balls(balls_per_drop)`,
        avg ≈ balls), those balls drop, and that's the whole bonus — so the bonus mode (cost = tier cost)
        averages ≈ `cost × board_EV` ≈ TARGET_RTP and stays compliant + deducts only one normal bet.
        Returns (events, feature_win, level). NOTE (Option #1 trade-off): the big-jackpot extras — nested
        level-ups and the in-bonus free spin — are intentionally REMOVED; they can't fit a normal-cost
        bonus without operator loss.
        """
        events: list[dict] = []
        free_balls = int(py_random.choice(bonus_wheel_free_balls(balls_per_drop)))
        events.append({"type": "bonusRoulette", "freeBalls": free_balls})

        outcomes, feature_win = self.build_drop_outcomes(
            row_count=row_count,
            balls_per_drop=free_balls,
            stake_per_ball=stake_per_ball,
        )
        events.append(
            {
                "type": "bonusRound",
                "freeBalls": free_balls,
                "outcomes": outcomes,
                "level": 1,
                "ballsPlayed": 0,
            }
        )
        return events, feature_win, 1

    def _free_spin_segment_multiplier(self, segment: str) -> float:
        if segment == "BONUS":
            return 0.0
        if segment.endswith("X"):
            return float(segment[:-1])
        return 0.0

    def build_feature_meter_events(
        self,
        *,
        outcomes: list[dict],
        row_count: int,
        stake_per_ball: float,
        balls_per_drop: int = 0,
        spin_meter_start: int = 0,
        bonus_meter_start: int = 0,
        bonus_level_start: int = 0,
        spin_meter_max: int = SPIN_METER_MAX,
        bonus_meter_max: int = BONUS_METER_MAX,
        force_bonus: bool = False,
        suppress_features: bool = False,
        spin_in_drop: bool = False,
    ) -> tuple[list[dict], float, int, int, int]:
        """
        Walk server-authored ball flags and emit meter / feature book events.

        Returns (events, feature_win, spin_meter, bonus_meter, bonus_level). `feature_win`
        is the extra win on top of the base drop win, so the settled total is
        `drop_win + feature_win`.

        FREE SPIN (per-drop, in-drop): the spin meter is seeded at `spin_meter_start` (a fixed
        per-tier value, NOT carried across bets) and fills on each `hitSpinSlot`. When it reaches
        `spin_meter_max` WITHIN this drop, the free spin fires ONCE, in-drop, on the same round.
        The wheel multiplier applies to the BET PER BALL (a fixed base), so a numeric `M` adds
        `stake_per_ball × M` and a `BONUS` segment chains into a bonus round. Gated by `spin_in_drop`
        so the 1-ball tier (off) never fires — a single-hit trigger on a 1-ball bet can't be
        RTP-compliant with this wheel.

        BONUS (Option #1 — separate `bonus<tier>` mode, normal-bet cost): the bonus is its OWN mode that
        the client auto-fires when the meter fills (deterministic). Here `force_bonus` is set on that
        mode's (empty-drop) book and runs `simulate_bonus_round(balls_per_drop)` — a single-level,
        tier-sized bonus so the mode RTP ≈ TARGET_RTP at the tier cost. Base modes pass NO `force_bonus`;
        their bonus meter just fills (`bonusMeter` events, client-side visual, persists across rounds)
        and the full meter drives the client auto-fire of the bonus mode. (`suppress_features` is unused
        now but kept for signature stability.)
        """
        _ = suppress_features  # unused (kept for signature stability)
        events: list[dict] = []
        feature_win = 0.0
        spin_meter = max(0, int(spin_meter_start))
        bonus_meter = max(0, int(bonus_meter_start))
        bonus_level = max(0, int(bonus_level_start))

        # Bonus MODE: empty initial drop (`force_bonus`) → one tier-sized bonus round. Its payout is the
        # whole book, so the mode RTP ≈ TARGET_RTP at the tier cost.
        if force_bonus:
            balls = balls_per_drop if balls_per_drop > 0 else 10
            bonus_events, bonus_win, bonus_level = self.simulate_bonus_round(
                row_count=row_count,
                stake_per_ball=stake_per_ball,
                balls_per_drop=balls,
            )
            events.extend(bonus_events)
            feature_win += bonus_win
            return events, feature_win, spin_meter, bonus_meter, bonus_level

        free_spin_fired = False
        for outcome in outcomes:
            if outcome.get("hitBonusPeg"):
                bonus_meter = min(bonus_meter_max, bonus_meter + 1)
                events.append(
                    {"type": "bonusMeter", "value": bonus_meter, "level": bonus_level}
                )
                # Base modes NEVER fire the bonus in-drop — a full meter drives the CLIENT's auto-fire of
                # the dedicated `bonus<tier>` mode. The meter just fills + carries over (client session).

            if outcome.get("hitSpinSlot"):
                spin_meter = min(spin_meter_max, spin_meter + 1)
                events.append(
                    {"type": "spinMeter", "value": spin_meter, "max": spin_meter_max}
                )
                # Per-drop free spin: fires ONCE in-drop the moment the meter fills this round. The wheel
                # has no BONUS segment, so it's always a numeric `stake × M` add on top of the drop.
                if spin_in_drop and not free_spin_fired and spin_meter >= spin_meter_max:
                    free_spin_fired = True
                    segment = py_random.choice(self.FREE_SPIN_SEGMENTS)
                    multiplier = self._free_spin_segment_multiplier(segment)
                    free_spin_win = stake_per_ball * multiplier
                    feature_win += free_spin_win
                    events.append(
                        {
                            "type": "freeSpinTrigger",
                            "segment": segment,
                            "multiplier": multiplier,
                            "amount": free_spin_win,
                        }
                    )

        return events, feature_win, spin_meter, bonus_meter, bonus_level
