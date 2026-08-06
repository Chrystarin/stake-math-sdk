"""Crimson Plinko simulation — one bet = one multi-ball plinkoDrop book.

A book may also carry feature events (spinMeter / bonusMeter / freeSpinTrigger /
bonusRoulette / bonusRound) when the meters fill. Meter carry-over across bets is
injected by RGS via distribution `conditions` (spin_meter_start / bonus_meter_start /
bonus_level_start), selected on live play through bet `meta`.
"""

from game_events import (
    bonus_meter_event,
    bonus_round_event,
    bonus_roulette_event,
    emit_plinko_settlement,
    free_spin_trigger_event,
    plinko_drop_event,
    spin_meter_event,
)
from game_override import GameStateOverride
from plinko_data import (
    BONUS_PEG_HIT_PROB,
    coefficients_for,
    scaled_bonus_meter_max,
    scaled_spin_meter_max,
)


class GameState(GameStateOverride):
    def run_spin(self, sim, simulation_seed=None):
        self.reset_seed(sim)
        conditions = self.get_current_distribution_conditions()

        # Each published book is independent. Session meter carry-over is injected by RGS
        # via conditions on live play — not chained across book-generation sims.
        spin_meter_at_bet_start = max(0, int(conditions.get("spin_meter_start", 0)))
        bonus_meter_at_bet_start = max(0, int(conditions.get("bonus_meter_start", 0)))
        bonus_level_at_bet_start = max(0, int(conditions.get("bonus_level_start", 0)))
        # The dedicated BONUS trigger mode sets this so the bonus fires unconditionally this bet.
        force_bonus = bool(conditions.get("force_bonus", False))
        # Base modes set this so the bonus meter carries over (delivered by the bonus trigger mode).
        suppress_features = bool(conditions.get("suppress_features", False))
        # FREE SPIN is per-drop + in-drop: enabled on the 10/20/50 tiers, off on 1-ball.
        spin_in_drop = bool(conditions.get("spin_in_drop", False))
        # BONUS is per-drop + in-drop (Option A): the meter fills from this drop's coin-pegs and fires
        # the bonus when full. Enabled on 10/20/50; off on 1-ball, which has no bonus at all (quota 0).
        bonus_in_drop = bool(conditions.get("bonus_in_drop", False))
        # BUY BONUS modes: bonus-only (empty paid drop) + the bonus seeded with a FIXED entry-ball count.
        # The meter is pre-filled to FULL so the client renders it full at round start (the bonus fires
        # immediately) — the bought balls then combine with the in-bonus level-up / chain balls.
        bonus_only = bool(conditions.get("bonus_only", False))
        buy_entry_balls = max(0, int(conditions.get("buy_entry_balls", 0)))
        # BUY BONUS Fury-meter head-start (in-bonus level-up meter starting fill, 0..1).
        buy_levelup_head_start = max(0.0, float(conditions.get("buy_levelup_head_start", 0.0)))
        # PER-MODE coin-peg probability. Every mode climbs the SAME in-bonus level-up ladder
        # (`bonus_levelup_pegs`); this controls how fast a mode's balls deliver those hits, and it is
        # the lever that holds each mode at TARGET_RTP under that shared ladder. Applies to the paid
        # drop's trigger meter AND to the bonus round's energy meter.
        peg_hit_prob = float(conditions.get("peg_hit_prob", BONUS_PEG_HIT_PROB))

        self.repeat = True
        while self.repeat:
            self.reset_book()

            row_count = int(conditions.get("row_count", 14))
            balls_per_drop = int(conditions.get("balls_per_drop", 10))
            stake_per_ball = float(conditions.get("stake_per_ball", 1.0))
            spin_meter_max = scaled_spin_meter_max(balls_per_drop)
            bonus_meter_max = scaled_bonus_meter_max(balls_per_drop)

            # BUY BONUS: pre-fill the bonus meter to FULL so the client shows it full at round start (the
            # bonus fires immediately). force_bonus also drives the actual fire in build_feature_meter_events.
            if bonus_only:
                bonus_meter_at_bet_start = bonus_meter_max

            # FOLDED-BONUS DESIGN: base books play the real paid drop — including the `force_bonus`
            # stratum, where the bonus round is folded ON TOP (settling `drop + bonus` in one book). The
            # free spin fires in-drop on top of the drop in either stratum. BUY BONUS modes (`bonus_only`)
            # instead play an EMPTY drop so the book settles `bonus` only.
            if bonus_only:
                outcomes, total_win = [], 0.0
            else:
                outcomes, total_win = self.build_drop_outcomes(
                    row_count=row_count,
                    balls_per_drop=balls_per_drop,
                    stake_per_ball=stake_per_ball,
                    peg_hit_prob=peg_hit_prob,
                )
            # When the bonus is FORCED this round (quota) on a meter-tier (10/20/50), make enough of the
            # drop's balls hit coin pegs so the bonus meter fills 0→max from REAL hits (no snap) — the
            # player watches the meter fill to FULL, then the bonus fires. EV-neutral (coin pegs don't
            # affect the pocket win, `hitBonusPeg` is sampled independently of the pocket). This is what
            # keeps the quota from being a second, meter-bypassing trigger path: 10/20/50 are the ONLY
            # tiers with a non-zero quota and all three set `bonus_in_drop`, so no published book can
            # carry a bonus event over a meter that isn't full. 1-ball never reaches here (quota 0).
            if force_bonus and bonus_in_drop:
                self.ensure_coin_pegs_fill_meter(outcomes, bonus_meter_max)
            (
                feature_events,
                feature_win,
                _spin_meter_end,
                _bonus_meter_end,
                _bonus_level_end,
            ) = self.build_feature_meter_events(
                outcomes=outcomes,
                row_count=row_count,
                stake_per_ball=stake_per_ball,
                balls_per_drop=balls_per_drop,
                spin_meter_start=spin_meter_at_bet_start,
                bonus_meter_start=bonus_meter_at_bet_start,
                bonus_level_start=bonus_level_at_bet_start,
                spin_meter_max=spin_meter_max,
                bonus_meter_max=bonus_meter_max,
                force_bonus=force_bonus,
                suppress_features=suppress_features,
                spin_in_drop=spin_in_drop,
                bonus_in_drop=bonus_in_drop,
                buy_entry_balls=buy_entry_balls,
                buy_levelup_head_start=buy_levelup_head_start,
                peg_hit_prob=peg_hit_prob,
            )
            total_win += feature_win

            self.win_manager.update_spinwin(total_win)
            self.win_manager.update_gametype_wins(self.gametype)
            self.win_data["totalWin"] = total_win
            self.win_data["featureWin"] = feature_win

            plinko_drop_event(
                self,
                row_count=row_count,
                balls_per_drop=balls_per_drop,
                stake_per_ball=stake_per_ball,
                # The board is per-tier (1-ball has its own table — see COEFFICIENT_SETS_BY_BALLS), so the
                # book publishes the set this drop actually paid from.
                coefficients=coefficients_for(row_count, balls_per_drop),
                spin_meter_max=spin_meter_max,
                bonus_meter_max=bonus_meter_max,
                spin_meter_start=spin_meter_at_bet_start,
                bonus_meter_start=bonus_meter_at_bet_start,
                bonus_level_start=bonus_level_at_bet_start,
                outcomes=outcomes,
            )
            for event in feature_events:
                event_type = event["type"]
                if event_type == "bonusMeter":
                    bonus_meter_event(
                        self,
                        value=event["value"],
                        level=event["level"],
                        max_value=int(event.get("max", 0)),
                    )
                elif event_type == "bonusRoulette":
                    bonus_roulette_event(self, free_balls=event["freeBalls"])
                elif event_type == "bonusRound":
                    bonus_round_event(
                        self,
                        free_balls=event["freeBalls"],
                        outcomes=event["outcomes"],
                        level=event["level"],
                        balls_played=event.get("ballsPlayed", 0),
                        # Pegs to LEAVE this level — the escalating threshold is per-level, so the
                        # client can only size each level's energy bar if the book publishes it.
                        levelup_pegs=int(event.get("levelupPegs", 0)),
                    )
                elif event_type == "spinMeter":
                    spin_meter_event(self, value=event["value"], max_value=event["max"])
                elif event_type == "freeSpinTrigger":
                    free_spin_trigger_event(
                        self,
                        multiplier=event["multiplier"],
                        segment=event["segment"],
                        amount=event.get("amount", 0.0),
                        level=int(event.get("level", 0)),
                    )

            # Index strata for RGS / force lookup (matches play `meta` condition keys).
            self.record(
                {
                    "balls_per_drop": balls_per_drop,
                    "difficulty": int(conditions.get("difficulty", 0)),
                    "row_count": row_count,
                    "stake_per_ball": stake_per_ball,
                    "spin_meter_start": spin_meter_at_bet_start,
                    "bonus_meter_start": bonus_meter_at_bet_start,
                    "bonus_level_start": bonus_level_at_bet_start,
                }
            )
            emit_plinko_settlement(self)
            self.check_repeat()
        self.imprint_wins()

    def run_freespin(self):
        pass
