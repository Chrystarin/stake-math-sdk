"""Plinko path sampling, feature meter walking, and payout helpers.

All randomness for features lives here so the published books are authoritative:
the client animates exactly these outcomes and never rolls its own dice.
"""

import random as py_random

from plinko_data import (
    BONUS_METER_MAX,
    BONUS_PEG_HIT_PROB,
    BONUS_WHEEL_FREE_BALLS,
    FREE_SPIN_SEGMENTS,
    MAX_BONUS_LEVEL,
    SPIN_METER_MAX,
    bonus_level_balls,
    coefficients_for,
    spin_slot_index,
)
from src.executables.executables import Executables


class GameCalculations(Executables):
    """Galton-board style slot sampling for crimson plinko."""

    FREE_SPIN_SEGMENTS: list[str] = list(FREE_SPIN_SEGMENTS)
    BONUS_WHEEL_FREE_BALLS: list[int] = list(BONUS_WHEEL_FREE_BALLS)

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
        bonus_meter_max: int,
        level_start: int,
    ) -> tuple[list[dict], float, int]:
        """
        Simulate a full bonus round, including nested level-ups, server-side.

        Entry balls come from the bonus wheel; while playing a level's balls, every
        `hitBonusPeg` advances the in-round bonus meter, and each re-fill levels up and
        grants `bonus_level_balls(level)` more balls (up to `MAX_BONUS_LEVEL`). One
        `bonusRound` event is emitted per level so the client can animate a level-up
        between them. Returns (events, feature_win, final_level).
        """
        events: list[dict] = []
        feature_win = 0.0

        free_balls = int(py_random.choice(self.BONUS_WHEEL_FREE_BALLS))
        events.append({"type": "bonusRoulette", "freeBalls": free_balls})

        level = int(level_start) + 1
        # Queue of (level, balls_to_play); index walk lets later level-ups append more.
        queue: list[tuple[int, int]] = [(level, free_balls)]
        bonus_meter = 0
        i = 0
        while i < len(queue):
            level_for_balls, balls = queue[i]
            i += 1
            if balls <= 0:
                continue
            outcomes, drop_win = self.build_drop_outcomes(
                row_count=row_count,
                balls_per_drop=balls,
                stake_per_ball=stake_per_ball,
            )
            feature_win += drop_win
            events.append(
                {
                    "type": "bonusRound",
                    "freeBalls": balls,
                    "outcomes": outcomes,
                    "level": int(level_for_balls),
                    "ballsPlayed": 0,
                }
            )
            if level >= MAX_BONUS_LEVEL:
                continue
            for outcome in outcomes:
                if not outcome.get("hitBonusPeg"):
                    continue
                bonus_meter += 1
                if bonus_meter < bonus_meter_max:
                    continue
                bonus_meter = 0
                level += 1
                queue.append((level, bonus_level_balls(level)))
                if level >= MAX_BONUS_LEVEL:
                    break

        return events, feature_win, level

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
        spin_meter_start: int = 0,
        bonus_meter_start: int = 0,
        bonus_level_start: int = 0,
        spin_meter_max: int = SPIN_METER_MAX,
        bonus_meter_max: int = BONUS_METER_MAX,
        force_freespin: bool = False,
        force_bonus: bool = False,
        suppress_features: bool = False,
    ) -> tuple[list[dict], float, int, int, int]:
        """
        Walk server-authored ball flags and emit meter / feature book events.

        Returns (events, feature_win, spin_meter, bonus_meter, bonus_level). `feature_win`
        is the extra win on top of the base drop win, so settlement totals to the displayed
        result: free-spin `NX` scales the whole base drop win; bonus rounds add their own
        precomputed ball wins.

        `force_freespin` / `force_bonus` are set by the dedicated trigger modes (selected by the
        client when a meter is full): the feature fires unconditionally and the meter resets,
        instead of walking per-ball meter hits.

        `suppress_features` is set by the base bet modes: the meters still fill and emit
        spin/bonusMeter events (so the client keeps an authoritative, book-driven meter), but the
        feature is NOT fired in-drop. A full meter simply carries over and the client auto-fires the
        dedicated trigger mode on the next bet — so base RTP is exactly the per-ball board EV across
        every tier (no tier-dependent in-drop feature inflation), while the feature itself is still
        delivered server-authoritatively via the trigger mode (payout-consistency invariant intact).
        """
        if not outcomes:
            return [], 0.0, spin_meter_start, bonus_meter_start, bonus_level_start

        events: list[dict] = []
        feature_win = 0.0
        spin_meter = max(0, int(spin_meter_start))
        bonus_meter = max(0, int(bonus_meter_start))
        bonus_level = max(0, int(bonus_level_start))
        drop_win = self._drop_win_from_outcomes(outcomes, stake_per_ball)

        # Trigger modes: the meter is full, so fire the feature now and reset that meter.
        if force_freespin:
            segment = py_random.choice(self.FREE_SPIN_SEGMENTS)
            multiplier = self._free_spin_segment_multiplier(segment)
            if segment == "BONUS":
                events.append(
                    {"type": "freeSpinTrigger", "segment": segment, "multiplier": 0.0, "amount": 0.0}
                )
                bonus_events, bonus_win, bonus_level = self.simulate_bonus_round(
                    row_count=row_count,
                    stake_per_ball=stake_per_ball,
                    bonus_meter_max=bonus_meter_max,
                    level_start=bonus_level,
                )
                events.extend(bonus_events)
                feature_win += bonus_win
            else:
                scaled_total = drop_win * multiplier if multiplier > 0 else drop_win
                feature_win += scaled_total - drop_win
                events.append(
                    {
                        "type": "freeSpinTrigger",
                        "segment": segment,
                        "multiplier": multiplier,
                        "amount": scaled_total,
                    }
                )
            return events, feature_win, 0, bonus_meter, bonus_level

        if force_bonus:
            bonus_events, bonus_win, bonus_level = self.simulate_bonus_round(
                row_count=row_count,
                stake_per_ball=stake_per_ball,
                bonus_meter_max=bonus_meter_max,
                level_start=bonus_level,
            )
            events.extend(bonus_events)
            feature_win += bonus_win
            return events, feature_win, spin_meter, 0, bonus_level

        for outcome in outcomes:
            if outcome.get("hitBonusPeg"):
                bonus_meter = min(bonus_meter_max, bonus_meter + 1)
                events.append(
                    {"type": "bonusMeter", "value": bonus_meter, "level": bonus_level}
                )
                # Base modes: keep the meter full (carry over) and let the trigger mode fire it.
                if bonus_meter >= bonus_meter_max and not suppress_features:
                    bonus_meter = 0
                    bonus_events, bonus_win, bonus_level = self.simulate_bonus_round(
                        row_count=row_count,
                        stake_per_ball=stake_per_ball,
                        bonus_meter_max=bonus_meter_max,
                        level_start=bonus_level,
                    )
                    events.extend(bonus_events)
                    feature_win += bonus_win

            if outcome.get("hitSpinSlot"):
                spin_meter = min(spin_meter_max, spin_meter + 1)
                events.append(
                    {"type": "spinMeter", "value": spin_meter, "max": spin_meter_max}
                )
                # Base modes: keep the meter full (carry over) and let the trigger mode fire it.
                if spin_meter >= spin_meter_max and not suppress_features:
                    spin_meter = 0
                    segment = py_random.choice(self.FREE_SPIN_SEGMENTS)
                    multiplier = self._free_spin_segment_multiplier(segment)
                    if segment == "BONUS":
                        # Free-spin BONUS chains directly into a bonus round.
                        events.append(
                            {
                                "type": "freeSpinTrigger",
                                "segment": segment,
                                "multiplier": 0.0,
                                "amount": 0.0,
                            }
                        )
                        bonus_events, bonus_win, bonus_level = self.simulate_bonus_round(
                            row_count=row_count,
                            stake_per_ball=stake_per_ball,
                            bonus_meter_max=bonus_meter_max,
                            level_start=bonus_level,
                        )
                        events.extend(bonus_events)
                        feature_win += bonus_win
                    else:
                        scaled_total = drop_win * multiplier if multiplier > 0 else drop_win
                        feature_win += scaled_total - drop_win
                        events.append(
                            {
                                "type": "freeSpinTrigger",
                                "segment": segment,
                                "multiplier": multiplier,
                                "amount": scaled_total,
                            }
                        )

        return events, feature_win, spin_meter, bonus_meter, bonus_level
