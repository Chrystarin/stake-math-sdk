"""Plinko path sampling, feature meter walking, and payout helpers.

All randomness for features lives here so the published books are authoritative:
the client animates exactly these outcomes and never rolls its own dice.
"""

import random as py_random

from plinko_data import (
    BONUS_LEVELUP_PEG_HITS,
    BONUS_METER_MAX,
    BONUS_PEG_HIT_PROB,
    FREE_SPIN_SEGMENTS,
    FREE_SPIN_WEIGHTS,
    MAX_BONUS_LEVEL,
    SPIN_METER_MAX,
    bonus_level_balls,
    bonus_wheel_free_balls,
    coefficients_for,
    spin_slot_index,
)
from src.executables.executables import Executables


class GameCalculations(Executables):
    """Galton-board style slot sampling for crimson plinko."""

    FREE_SPIN_SEGMENTS: list[str] = list(FREE_SPIN_SEGMENTS)
    FREE_SPIN_WEIGHTS: list[float] = list(FREE_SPIN_WEIGHTS)

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
        Simulate a MULTI-LEVEL bonus round (FOLDED-bonus design — the bonus is FREE, funded by the base).

        Entry free balls come from the ABSOLUTE Aztec bonus wheel (`bonus_wheel_free_balls`, avg ≈ 60,
        tier-independent) and drop on the board. Coin-peg hits during the falling balls accumulate
        "energy"; every `BONUS_LEVELUP_PEG_HITS` hits advances a level and unlocks the next batch of free
        balls (`bonus_level_balls`, up to `MAX_BONUS_LEVEL`) — the inout "accumulate energy → unlock more
        drops, up to ~250 balls" escalation (a rare jackpot). Each level emits its own `bonusRound` so the
        client animates the level-ups in order. Returns (events, feature_win, final_level).
        """
        events: list[dict] = []
        feature_win = 0.0
        entry_balls = int(py_random.choice(bonus_wheel_free_balls(balls_per_drop)))
        events.append({"type": "bonusRoulette", "freeBalls": entry_balls})

        level = 1
        peg_hits = 0
        pending: list[tuple[int, int]] = [(1, entry_balls)]
        while pending:
            cur_level, batch_balls = pending.pop(0)
            outcomes, batch_win = self.build_drop_outcomes(
                row_count=row_count,
                balls_per_drop=batch_balls,
                stake_per_ball=stake_per_ball,
            )
            feature_win += batch_win
            events.append(
                {
                    "type": "bonusRound",
                    "freeBalls": batch_balls,
                    "outcomes": outcomes,
                    "level": cur_level,
                    "ballsPlayed": 0,
                }
            )
            # Accumulate energy across this batch's balls → level-ups unlock the next batch.
            for outcome in outcomes:
                if outcome.get("hitBonusPeg"):
                    peg_hits += 1
                    if peg_hits >= BONUS_LEVELUP_PEG_HITS and level < MAX_BONUS_LEVEL:
                        peg_hits = 0
                        level += 1
                        extra = bonus_level_balls(level)
                        if extra > 0:
                            pending.append((level, extra))
        return events, feature_win, level

    def _free_spin_segment_multiplier(self, segment: str) -> float:
        if segment == "BONUS":
            return 0.0
        if segment.endswith("X"):
            return float(segment[:-1])
        return 0.0

    def _pick_free_spin_segment(self) -> str:
        """Weighted free-spin wheel landing — the visual wheel keeps 8 equal slices, but the landing is
        weighted (FREE_SPIN_WEIGHTS) so the big 100X / BONUS jackpots are rare and 0.5X–5X land often."""
        return py_random.choices(self.FREE_SPIN_SEGMENTS, weights=self.FREE_SPIN_WEIGHTS, k=1)[0]

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
        bonus_in_drop: bool = False,
    ) -> tuple[list[dict], float, int, int, int]:
        """
        Walk server-authored ball flags and emit meter / feature book events.

        Returns (events, feature_win, spin_meter, bonus_meter, bonus_level). `feature_win`
        is the extra win on top of the base drop win, so the settled total is
        `drop_win + feature_win`.

        FREE SPIN (per-drop, in-drop): the spin meter is seeded at `spin_meter_start` (a fixed
        per-tier value, NOT carried across bets) and fills on each `hitSpinSlot`. When it reaches
        `spin_meter_max` WITHIN this drop, the free spin fires ONCE, on a TRAILING `freeSpinTrigger`
        after the drop walk. The weighted wheel multiplier applies to the BET PER BALL (a fixed base),
        so a numeric `M` adds `stake_per_ball × M`; a `BONUS` segment chains into a (free) bonus round.
        Gated by `spin_in_drop` so the 1-ball tier (off) never fires.

        BONUS (OPTION A — PER-DROP meter trigger, FREE, stateless): the bonus meter is seeded at
        `bonus_meter_start` (a fixed per-tier value, NOT carried across bets) and fills on each
        `hitBonusPeg` WITHIN this drop. When it reaches `bonus_meter_max` (gated by `bonus_in_drop`, off
        on 1-ball), the bonus fires IN-DROP — the whole multi-level `simulate_bonus_round` resolves in
        THIS book and settles `drop + bonus` (one bet, no cross-bet state). A small `force_bonus` QUOTA
        also fires the bonus (1-ball, where the meter can't fill; and a fine-tune top-up on the others);
        a quota fire snaps the meter to full first so it still reads as a completion. The board (~0.896)
        funds the free bonus. (`suppress_features` is unused now but kept for signature stability.)
        """
        _ = suppress_features  # unused (kept for signature stability)
        events: list[dict] = []
        feature_win = 0.0
        spin_meter = max(0, int(spin_meter_start))
        bonus_meter = max(0, int(bonus_meter_start))
        bonus_level = max(0, int(bonus_level_start))
        balls = balls_per_drop if balls_per_drop > 0 else 10

        # Walk the drop balls: fill the meters (visual) and detect the in-drop free spin + bonus (both
        # resolved AFTER the walk so their events trail the drop cleanly).
        free_spin_fired = False
        bonus_meter_fired = False
        for outcome in outcomes:
            if outcome.get("hitBonusPeg"):
                bonus_meter = min(bonus_meter_max, bonus_meter + 1)
                events.append(
                    {"type": "bonusMeter", "value": bonus_meter, "level": bonus_level}
                )
                if bonus_in_drop and not bonus_meter_fired and bonus_meter >= bonus_meter_max:
                    bonus_meter_fired = True
            if outcome.get("hitSpinSlot"):
                spin_meter = min(spin_meter_max, spin_meter + 1)
                events.append(
                    {"type": "spinMeter", "value": spin_meter, "max": spin_meter_max}
                )
                if spin_in_drop and not free_spin_fired and spin_meter >= spin_meter_max:
                    free_spin_fired = True

        # Resolve the in-drop free spin (trailing). Weighted wheel: numeric → stake × M; BONUS → chain a
        # (free) bonus round.
        if free_spin_fired:
            segment = self._pick_free_spin_segment()
            if segment == "BONUS":
                events.append(
                    {"type": "freeSpinTrigger", "segment": segment, "multiplier": 0.0, "amount": 0.0}
                )
                bonus_events, bonus_win, bonus_end_level = self.simulate_bonus_round(
                    row_count=row_count,
                    stake_per_ball=stake_per_ball,
                    balls_per_drop=balls,
                )
                events.extend(bonus_events)
                feature_win += bonus_win
                bonus_level = max(bonus_level, bonus_end_level)
            else:
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

        # Fire the bonus (once) when the per-drop meter filled in-drop OR the force_bonus quota selected
        # this book. The whole multi-level bonus resolves in THIS book → settles `drop + bonus`.
        if bonus_meter_fired or force_bonus:
            # A QUOTA fire (meter not full): snap the meter to full first so it reads as a completion.
            if force_bonus and bonus_meter < bonus_meter_max:
                bonus_meter = bonus_meter_max
                events.append(
                    {"type": "bonusMeter", "value": bonus_meter, "level": bonus_level}
                )
            bonus_events, bonus_win, bonus_end_level = self.simulate_bonus_round(
                row_count=row_count,
                stake_per_ball=stake_per_ball,
                balls_per_drop=balls,
            )
            events.extend(bonus_events)
            feature_win += bonus_win
            bonus_level = max(bonus_level, bonus_end_level)

        return events, feature_win, spin_meter, bonus_meter, bonus_level
