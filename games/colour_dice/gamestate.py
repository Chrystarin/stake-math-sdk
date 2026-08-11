"""Handles the state and output for a single Colour Dice simulation round."""

from game_override import GameStateOverride
from src.events.events import set_total_event

from colour_dice_data import (
    NUM_COLOURS,
    NUM_DICE,
    PAYTABLE_MATCHES,
    decode_outcome,
    layout_for_mode,
    payout_multiplier,
)


class GameState(GameStateOverride):
    """Handle all game-logic and event updates for a given simulation number."""

    def run_spin(self, sim, simulation_seed=None):
        self.reset_seed(sim)
        self.repeat = True
        while self.repeat:
            self.reset_book()

            self.draw_colour_dice(sim)

            self.evaluate_finalwin()
            self.check_game_repeat()

        self.imprint_wins()

    def run_freespin(self):
        pass

    # --- Colour Dice logic -------------------------------------------------------
    def current_layout(self):
        """Per-colour stakes for the bet mode being simulated (all equal)."""
        return layout_for_mode(self.betmode)

    @staticmethod
    def slot_label(slot: int, num_backed: int) -> str:
        """Name a colour slot relative to the player's selection.

        'B1'..'Bk' are the backed colours in selection order; 'O1'.. are the unbacked ones in
        canonical order. Books never name literal colours, so one book set serves every
        possible colour choice — the client substitutes its own picks at playback.
        """
        if slot < num_backed:
            return f"B{slot + 1}"
        return f"O{slot - num_backed + 1}"

    def draw_colour_dice(self, sim):
        """Resolve one round for the current mode and emit its events.

        The outcome is derived from the simulation index rather than sampled, so one full
        pass over a mode enumerates every (dice arrangement, wheel award) pair at exactly
        its true frequency. See colour_dice_data.decode_outcome.
        """
        layout = self.current_layout()
        num_backed = len(layout)

        slots, wheel_award = decode_outcome(sim)

        # Matches per BACKED colour, in selection order.
        matches = [0] * num_backed
        for slot in slots:
            if slot < num_backed:
                matches[slot] += 1

        # A triple takes all three dice, so at most one colour can reach NUM_DICE.
        tripled_index = next(
            (index for index, matched in enumerate(matches) if matched == NUM_DICE), None
        )
        wheel_multiplier = wheel_award if tripled_index is not None else None

        multiplier = payout_multiplier(layout, matches, wheel_multiplier)

        # Reveal: dice as selection-relative slots, plus how many colours were backed so the
        # book is self-describing for replays and the offline dev harness.
        self.book.add_event(
            {
                "index": len(self.book.events),
                "type": "reveal",
                "dice": [self.slot_label(slot, num_backed) for slot in slots],
                "backedCount": num_backed,
                "gameType": self.gametype,
            }
        )

        # Triple -> Lucky Wheel.
        if wheel_multiplier is not None:
            self.record({"kind": "wheel", "multiplier": wheel_multiplier})
            self.book.add_event(
                {
                    "index": len(self.book.events),
                    "type": "wheelSpin",
                    "slot": self.slot_label(tripled_index, num_backed),
                    "multiplier": int(wheel_multiplier),
                }
            )

        # Per-colour breakdown so the board can light up each paying colour independently.
        # `amount` is that colour's contribution to the round multiplier (x100, as elsewhere),
        # in units of `amount` — i.e. stake x pay, matching payout_multiplier. Stakes are
        # equal, so this is just pay(matches) for whichever colours landed.
        wins = []
        for index, (stake, matched) in enumerate(zip(layout, matches)):
            if matched == 0:
                continue
            pay = wheel_multiplier if matched == NUM_DICE else PAYTABLE_MATCHES[matched]
            wins.append(
                {
                    "slot": self.slot_label(index, num_backed),
                    "matches": matched,
                    "amount": int(round(stake * pay * 100, 0)),
                }
            )

        win = min(multiplier, self.config.wincap)

        self.book.add_event(
            {
                "index": len(self.book.events),
                "type": "winInfo",
                "wins": wins,
                "totalWin": int(round(win * 100, 0)),
            }
        )

        self.win_manager.update_spinwin(win)
        self.win_manager.update_gametype_wins(self.gametype)

        set_total_event(self)
