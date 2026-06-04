from game_executables import GameExecutables


class GameStateOverride(GameExecutables):
    def reset_book(self):
        super().reset_book()
        self.row_count = 14
        self.balls_per_drop = 10
        self.stake_per_ball = 1.0

    def assign_special_sym_function(self):
        pass

    def drop_wager_units(self) -> float:
        """Internal stake units per drop (books normalize payout to mode cost 1.0)."""
        conditions = self.get_current_distribution_conditions()
        balls = int(conditions.get("balls_per_drop", self.balls_per_drop))
        stake = float(conditions.get("stake_per_ball", self.stake_per_ball))
        return max(balls * stake, 1.0)

    def update_final_win(self) -> None:
        """Map raw drop win to Stake payoutMultiplier (return multiple at cost 1.0)."""
        drop_wager = self.drop_wager_units()
        raw_final = round(min(self.win_manager.running_bet_win, self.config.wincap), 2)
        raw_base = round(min(self.win_manager.basegame_wins, self.config.wincap), 2)
        raw_free = round(min(self.win_manager.freegame_wins, self.config.wincap), 2)

        self.final_win = round(raw_final / drop_wager, 2)
        self.book.payout_multiplier = self.final_win
        self.book.basegame_wins = round(raw_base / drop_wager, 2)
        self.book.freegame_wins = round(raw_free / drop_wager, 2)

        assert min(
            round(self.book.basegame_wins + self.book.freegame_wins, 2),
            round(self.config.wincap / drop_wager, 2),
        ) == min(round(self.book.payout_multiplier, 2), round(self.config.wincap / drop_wager, 2)), (
            "Base + Free game payout mismatch!"
        )
