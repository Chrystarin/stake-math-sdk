"""Handles the state and output for a single Colour Dice simulation round."""

import random

from game_override import GameStateOverride
from src.events.events import set_total_event


class GameState(GameStateOverride):
    """Handle all game-logic and event updates for a given simulation number."""

    def run_spin(self, sim, simulation_seed=None):
        self.reset_seed(sim)
        self.repeat = True
        while self.repeat:
            self.reset_book()

            self.draw_colour_dice()

            self.evaluate_finalwin()
            self.check_game_repeat()

        self.imprint_wins()

    def run_freespin(self):
        pass

    # --- Colour Dice logic -------------------------------------------------------
    def draw_colour_dice(self):
        """Roll three dice relative to the backed ("MATCH") colour and emit events."""
        dice = []
        match_count = 0
        for _ in range(3):
            roll = random.randint(1, 6)  # 1 => MATCH, 2..6 => C1..C5
            if roll == 1:
                dice.append("MATCH")
                match_count += 1
            else:
                dice.append(f"C{roll - 1}")

        wheel_multiplier = None
        if match_count == 3:
            wheel_multiplier = self.spin_wheel()
            multiplier = float(wheel_multiplier)
        else:
            multiplier = float(self.config.paytable_matches.get(match_count, 0.0))

        # Reveal: the three dice, encoded relative to the backed colour.
        self.book.add_event(
            {
                "index": len(self.book.events),
                "type": "reveal",
                "dice": dice,
                "selectedCount": match_count,
                "gameType": self.gametype,
            }
        )

        # Triple -> wheel bonus.
        if wheel_multiplier is not None:
            self.record({"kind": "wheel", "multiplier": wheel_multiplier})
            self.book.add_event(
                {
                    "index": len(self.book.events),
                    "type": "wheelSpin",
                    "multiplier": int(wheel_multiplier),
                }
            )

        win = min(multiplier, self.config.wincap)
        self.win_manager.update_spinwin(win)
        self.win_manager.update_gametype_wins(self.gametype)

        set_total_event(self)

    def spin_wheel(self):
        """Return a weighted-random gross multiplier for a triple match."""
        values = [v for v, _ in self.config.wheel]
        weights = [w for _, w in self.config.wheel]
        return random.choices(values, weights=weights, k=1)[0]
