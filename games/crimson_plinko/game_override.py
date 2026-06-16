from game_executables import GameExecutables


class GameStateOverride(GameExecutables):
    def reset_book(self):
        super().reset_book()
        self.row_count = 14
        self.balls_per_drop = 10
        self.stake_per_ball = 1.0

    def assign_special_sym_function(self):
        pass

    def play_amount_units(self) -> float:
        """RGS play `amount` per bet = the per-ball stake.

        Stake RGS debits `amount × mode cost` but credits `amount × payoutMultiplier`, so the
        payout multiplier MUST be expressed relative to the play amount (stake_per_ball), NOT the
        total drop wager (balls × stake). Normalizing by the total wager understates the credited
        payout by the `cost` (balls) factor — e.g. baseten credits 10× too little.
        """
        conditions = self.get_current_distribution_conditions()
        stake = float(conditions.get("stake_per_ball", self.stake_per_ball))
        return max(stake, 1e-9)

    def update_final_win(self) -> None:
        """Map raw drop win to a Stake payoutMultiplier relative to the play amount (per-ball stake)."""
        play_amount = self.play_amount_units()
        wincap = self.config.wincap
        raw_final = self.win_manager.running_bet_win
        raw_base = self.win_manager.basegame_wins
        raw_free = self.win_manager.freegame_wins

        self.final_win = round(min(raw_final / play_amount, wincap), 2)
        self.book.payout_multiplier = self.final_win
        self.book.basegame_wins = round(min(raw_base / play_amount, wincap), 2)
        self.book.freegame_wins = round(min(raw_free / play_amount, wincap), 2)

        assert min(
            round(self.book.basegame_wins + self.book.freegame_wins, 2),
            wincap,
        ) == min(round(self.book.payout_multiplier, 2), wincap), (
            "Base + Free game payout mismatch!"
        )
