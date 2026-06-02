"""Plinko path sampling and payout helpers."""

import random as py_random

from plinko_data import (
    BONUS_METER_MAX,
    BONUS_PEG_HIT_PROB,
    SPIN_METER_MAX,
    coefficients_for,
    spin_slot_index,
)
from src.executables.executables import Executables


class GameCalculations(Executables):
    """Galton-board style slot sampling for crimson plinko."""

    FREE_SPIN_SEGMENTS: list[str] = ["2X", "0.5X", "1X", "5X", "10X", "BONUS", "20X", "15X"]
    BONUS_WHEEL_FREE_BALLS: list[int] = [100, 20, 50, 50, 50, 80, 20, 20]

    def sample_rate_index(self, row_count: int, num_slots: int) -> int:
        """Map `row_count` binary peg deflections to a slot index."""
        if num_slots <= 1:
            return 0
        rights = sum(py_random.randint(0, 1) for _ in range(row_count))
        return min(num_slots - 1, round(rights * (num_slots - 1) / row_count))

    def build_drop_outcomes(
        self,
        *,
        difficulty: int,
        row_count: int,
        balls_per_drop: int,
        stake_per_ball: float,
    ) -> tuple[list[dict], float]:
        coeffs = coefficients_for(difficulty, row_count)
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

    def is_spin_slot(self, rate_index: int, num_slots: int) -> bool:
        return rate_index == spin_slot_index(num_slots)

    def build_bonus_round_package(
        self,
        *,
        difficulty: int,
        row_count: int,
        stake_per_ball: float,
    ) -> tuple[int, list[dict], float]:
        """Sample bonus wheel balls and precompute authoritative bonus-drop outcomes."""
        free_balls = int(py_random.choice(self.BONUS_WHEEL_FREE_BALLS))
        outcomes, bonus_total_win = self.build_drop_outcomes(
            difficulty=difficulty,
            row_count=row_count,
            balls_per_drop=free_balls,
            stake_per_ball=stake_per_ball,
        )
        return free_balls, outcomes, bonus_total_win

    def _append_bonus_round_events(
        self,
        events: list[dict],
        *,
        difficulty: int,
        row_count: int,
        stake_per_ball: float,
        bonus_level: int,
    ) -> tuple[list[dict], float, int]:
        """Emit bonusRoulette + bonusRound and return (events, feature_win, next_level)."""
        free_balls, bonus_outcomes, bonus_drop_win = self.build_bonus_round_package(
            difficulty=difficulty,
            row_count=row_count,
            stake_per_ball=stake_per_ball,
        )
        events.append({"type": "bonusRoulette", "freeBalls": free_balls})
        events.append(
            {
                "type": "bonusRound",
                "freeBalls": free_balls,
                "outcomes": bonus_outcomes,
                "level": int(bonus_level),
                "ballsPlayed": 0,
            }
        )
        next_level = int(bonus_level) + 1
        return events, bonus_drop_win, next_level

    def _resolve_free_spin_segment(
        self,
        segment: str,
        *,
        difficulty: int,
        row_count: int,
        stake_per_ball: float,
        balls_in_drop: int,
    ) -> tuple[float, int | None, list[dict] | None]:
        """Payout from one free-spin wheel segment; returns (win, freeBalls?, bonusOutcomes?)."""
        current_bet_total = max(0.0, float(stake_per_ball) * float(balls_in_drop))
        if segment == "BONUS":
            free_balls, bonus_outcomes, bonus_total_win = self.build_bonus_round_package(
                difficulty=difficulty,
                row_count=row_count,
                stake_per_ball=stake_per_ball,
            )
            return bonus_total_win, free_balls, bonus_outcomes
        if segment.endswith("X"):
            numeric = float(segment[:-1])
            if numeric > 0:
                return current_bet_total * numeric, None, None
        return 0.0, None, None

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
        difficulty: int,
        row_count: int,
        stake_per_ball: float,
        spin_meter_start: int = 0,
        bonus_meter_start: int = 0,
        bonus_level_start: int = 0,
    ) -> tuple[list[dict], float, int, int, int]:
        """
        Walk server-authored ball flags and emit meter / feature book events.

        Returns (events_to_append, feature_win_amount).
        """
        if not outcomes:
            return [], 0.0, spin_meter_start, bonus_meter_start, bonus_level_start

        events: list[dict] = []
        feature_win = 0.0
        spin_meter = max(0, int(spin_meter_start))
        bonus_meter = max(0, int(bonus_meter_start))
        bonus_level = max(0, int(bonus_level_start))
        balls_in_drop = len(outcomes)

        for outcome in outcomes:
            if outcome.get("hitBonusPeg"):
                bonus_meter = min(BONUS_METER_MAX, bonus_meter + 1)
                events.append(
                    {
                        "type": "bonusMeter",
                        "value": bonus_meter,
                        "level": bonus_level,
                    }
                )
                if bonus_meter >= BONUS_METER_MAX:
                    bonus_meter = 0
                    events, bonus_drop_win, bonus_level = self._append_bonus_round_events(
                        events,
                        difficulty=difficulty,
                        row_count=row_count,
                        stake_per_ball=stake_per_ball,
                        bonus_level=bonus_level,
                    )
                    feature_win += bonus_drop_win

            if outcome.get("hitSpinSlot"):
                spin_meter = min(SPIN_METER_MAX, spin_meter + 1)
                events.append(
                    {
                        "type": "spinMeter",
                        "value": spin_meter,
                        "max": SPIN_METER_MAX,
                    }
                )
                if spin_meter >= SPIN_METER_MAX:
                    spin_meter = 0
                    segment = py_random.choice(self.FREE_SPIN_SEGMENTS)
                    segment_win, bonus_roulette_balls, bonus_outcomes = self._resolve_free_spin_segment(
                        segment,
                        difficulty=difficulty,
                        row_count=row_count,
                        stake_per_ball=stake_per_ball,
                        balls_in_drop=balls_in_drop,
                    )
                    feature_win += segment_win
                    events.append(
                        {
                            "type": "freeSpinTrigger",
                            "segment": segment,
                            "multiplier": self._free_spin_segment_multiplier(segment),
                            "amount": segment_win,
                        }
                    )
                    if bonus_roulette_balls is not None and bonus_outcomes is not None:
                        events.append({"type": "bonusRoulette", "freeBalls": bonus_roulette_balls})
                        events.append(
                            {
                                "type": "bonusRound",
                                "freeBalls": bonus_roulette_balls,
                                "outcomes": bonus_outcomes,
                                "level": bonus_level,
                                "ballsPlayed": 0,
                            }
                        )
                        bonus_level = int(bonus_level) + 1

        return events, feature_win, spin_meter, bonus_meter, bonus_level
