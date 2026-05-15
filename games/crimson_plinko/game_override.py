from game_executables import GameExecutables


class GameStateOverride(GameExecutables):
    def reset_book(self):
        super().reset_book()
        self.difficulty = 0
        self.row_count = 14
        self.balls_per_drop = 10
        self.stake_per_ball = 1.0

    def assign_special_sym_function(self):
        pass
