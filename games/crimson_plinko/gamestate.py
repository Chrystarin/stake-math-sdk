"""Crimson Plinko simulation — one bet = one multi-ball plinkoDrop book."""

from game_events import emit_plinko_settlement, plinko_drop_event
from game_override import GameStateOverride


class GameState(GameStateOverride):
    def run_spin(self, sim, simulation_seed=None):
        self.reset_seed(sim)
        self.repeat = True
        while self.repeat:
            self.reset_book()

            difficulty = int(self.get_current_distribution_conditions().get("difficulty", 0))
            row_count = int(self.get_current_distribution_conditions().get("row_count", 14))
            balls_per_drop = int(self.get_current_distribution_conditions().get("balls_per_drop", 10))
            stake_per_ball = float(self.get_current_distribution_conditions().get("stake_per_ball", 1.0))

            outcomes, total_win = self.build_drop_outcomes(
                difficulty=difficulty,
                row_count=row_count,
                balls_per_drop=balls_per_drop,
                stake_per_ball=stake_per_ball,
            )

            self.win_manager.update_spinwin(total_win)
            self.win_manager.update_gametype_wins(self.gametype)
            self.win_data["totalWin"] = total_win

            plinko_drop_event(
                self,
                difficulty=difficulty,
                row_count=row_count,
                balls_per_drop=balls_per_drop,
                stake_per_ball=stake_per_ball,
                outcomes=outcomes,
            )
            emit_plinko_settlement(self)
            self.check_repeat()
        self.imprint_wins()

    def run_freespin(self):
        pass
