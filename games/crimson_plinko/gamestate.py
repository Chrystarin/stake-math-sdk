"""Crimson Plinko simulation — one bet = one multi-ball plinkoDrop book."""

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
from plinko_data import BONUS_METER_MAX, SPIN_METER_MAX, coefficients_for


class GameState(GameStateOverride):
    def run_spin(self, sim, simulation_seed=None):
        self.reset_seed(sim)
        conditions = self.get_current_distribution_conditions()

        # Each published book is independent. Session meter carry-over is injected by RGS
        # via conditions on live play — not chained across book generation sims.
        spin_meter_at_bet_start = max(0, int(conditions.get("spin_meter_start", 0)))
        bonus_meter_at_bet_start = max(0, int(conditions.get("bonus_meter_start", 0)))
        bonus_level_at_bet_start = max(0, int(conditions.get("bonus_level_start", 0)))

        self.server_spin_meter = spin_meter_at_bet_start
        self.server_bonus_meter = bonus_meter_at_bet_start
        self.server_bonus_level = bonus_level_at_bet_start

        self.repeat = True
        while self.repeat:
            self.reset_book()

            difficulty = int(conditions.get("difficulty", 0))
            row_count = int(conditions.get("row_count", 14))
            balls_per_drop = int(conditions.get("balls_per_drop", 10))
            stake_per_ball = float(conditions.get("stake_per_ball", 1.0))

            outcomes, total_win = self.build_drop_outcomes(
                difficulty=difficulty,
                row_count=row_count,
                balls_per_drop=balls_per_drop,
                stake_per_ball=stake_per_ball,
            )
            feature_events, feature_win, self.server_spin_meter, self.server_bonus_meter, self.server_bonus_level = self.build_feature_meter_events(
                outcomes=outcomes,
                difficulty=difficulty,
                row_count=row_count,
                stake_per_ball=stake_per_ball,
                spin_meter_start=self.server_spin_meter,
                bonus_meter_start=self.server_bonus_meter,
                bonus_level_start=self.server_bonus_level,
            )
            total_win += feature_win

            self.win_manager.update_spinwin(total_win)
            self.win_manager.update_gametype_wins(self.gametype)
            self.win_data["totalWin"] = total_win
            self.win_data["featureWin"] = feature_win

            plinko_drop_event(
                self,
                difficulty=difficulty,
                row_count=row_count,
                balls_per_drop=balls_per_drop,
                stake_per_ball=stake_per_ball,
                coefficients=coefficients_for(difficulty, row_count),
                spin_meter_max=SPIN_METER_MAX,
                bonus_meter_max=BONUS_METER_MAX,
                spin_meter_start=spin_meter_at_bet_start,
                bonus_meter_start=bonus_meter_at_bet_start,
                bonus_level_start=bonus_level_at_bet_start,
                outcomes=outcomes,
            )
            for event in feature_events:
                event_type = event["type"]
                if event_type == "bonusMeter":
                    bonus_meter_event(self, value=event["value"], level=event["level"])
                elif event_type == "bonusRoulette":
                    bonus_roulette_event(self, free_balls=event["freeBalls"])
                elif event_type == "bonusRound":
                    bonus_round_event(
                        self,
                        free_balls=event["freeBalls"],
                        outcomes=event["outcomes"],
                        level=event["level"],
                        balls_played=event.get("ballsPlayed", 0),
                    )
                elif event_type == "spinMeter":
                    spin_meter_event(self, value=event["value"], max_value=event["max"])
                elif event_type == "freeSpinTrigger":
                    free_spin_trigger_event(
                        self,
                        multiplier=event["multiplier"],
                        segment=event["segment"],
                        amount=event.get("amount", 0.0),
                    )

            emit_plinko_settlement(self)
            self.check_repeat()
        self.imprint_wins()

    def run_freespin(self):
        pass
