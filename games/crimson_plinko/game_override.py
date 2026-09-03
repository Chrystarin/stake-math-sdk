from game_executables import GameExecutables
from plinko_data import bet_mode_for_balls_per_drop


class GameStateOverride(GameExecutables):
    def run_sims(
        self,
        betmode_copy_list,
        betmode,
        sim_to_criteria,
        total_threads,
        total_repeats,
        num_sims,
        thread_index,
        repeat_count,
        compress=True,
        write_event_list=True,
        simulation_seeds=[],
    ) -> None:
        """Arm the stratified 1-ball layout for this worker before the SDK loop runs its sims.

        `num_sims` here is PER THREAD PER REPEAT; the SDK splits a mode's requested count into
        `total_threads x total_repeats` equal slices and numbers the books 0..total-1 across all of
        them, so the whole library is `total_threads x total_repeats x num_sims` books (the same
        arithmetic run_sims.py uses, which is why e.g. a 1,000,000 request lands on 999,984). The
        stratified plan needs that exact total, and it is only known here - pass it down."""
        self.stratified_onedrop_total = (
            int(total_threads) * int(total_repeats) * int(num_sims)
            if betmode == bet_mode_for_balls_per_drop(1)
            else None
        )
        self._stratified_plan_cache = None
        super().run_sims(
            betmode_copy_list,
            betmode,
            sim_to_criteria,
            total_threads,
            total_repeats,
            num_sims,
            thread_index,
            repeat_count,
            compress,
            write_event_list,
            simulation_seeds,
        )

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
        payout by the `cost` (balls) factor — e.g. tendrop credits 10× too little.
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
