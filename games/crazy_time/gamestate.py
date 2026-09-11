"""One Crazy Time round: decode the enumerated outcome and emit its events."""

from game_override import GameStateOverride
from src.events.events import set_total_event

from crazy_time_data import (
    coverage,
    NUM_CHESTS,
    NUMBER_PAY,
    PLINKO_SLOTS,
    TILES_PER_DEPTH,
    VOYAGE_DEPTHS,
    WHEEL_LAYOUT,
    chest_layout,
    decode_outcome,
    outcome_details,
    payout_multiplier,
    plinko_drop_zone,
    dive_path,
    wheel_wedge_for_value,
)


def _cents(x) -> int:
    return int(round(x * 100, 0))


class GameState(GameStateOverride):
    """Handle all game-logic and event updates for a given simulation number."""

    def run_spin(self, sim, simulation_seed=None):
        self.reset_seed(sim)
        self.repeat = True
        while self.repeat:
            self.reset_book()

            self.play_round(sim)

            self.evaluate_finalwin()
            self.check_game_repeat()

        self.imprint_wins()

    def run_freespin(self):
        pass

    # --- Crazy Time logic --------------------------------------------------------
    def add(self, event: dict):
        self.book.add_event({"index": len(self.book.events), **event})

    def play_round(self, sim):
        """Resolve one round for the current mode and emit its events.

        The outcome is derived from the simulation index, not sampled: one pass over a mode
        visits every (segment, top-slot, room) combination once. Its probability lives in
        the lookup-table weight column (run.py), not in repetition.
        """
        mode = self.betmode
        covered = coverage(mode)
        outcome = decode_outcome(sim, mode)
        d = outcome_details(outcome)
        spot = d["spot"]
        is_covered = spot in covered
        applied = d["appliedMultiplier"]

        # 1. Top Slot: which spot (if any) carries a multiplier this spin.
        self.add(
            {
                "type": "topSlot",
                "spot": d["topSlotSpot"],
                "multiplier": d["topSlotMultiplier"],
                "gameType": self.gametype,
            }
        )

        # 2. The wheel stops. `covered` tells the client whether the player is in the result.
        self.add(
            {
                "type": "wheelSpin",
                "segment": d["segment"],
                "spot": spot,
                "covered": is_covered,
                "topSlotApplied": d["topSlotApplied"],
                "multiplier": applied,
            }
        )

        # 3. A room, if the wheel landed on one. Always authored, even when the player was not
        #    in it, so the client can show the "you were not in this round" preview.
        if spot in NUMBER_PAY:
            base_value = NUMBER_PAY[spot]
        else:
            base_value = d["roomValue"]
            self.record({"kind": spot, "value": base_value, "topSlot": applied})
            self.add(self.room_event(sim, spot, d["roomIndex"], base_value, applied))

        # 4. Payout for THIS mode.
        win = payout_multiplier(mode, outcome)
        assert win <= self.config.wincap, (mode, win, self.config.wincap)
        self.add(
            {
                "type": "winInfo",
                "spot": spot,
                "covered": is_covered,
                "baseValue": base_value,
                "topSlotMultiplier": applied,
                "totalWin": _cents(win),
            }
        )

        self.win_manager.update_spinwin(win)
        self.win_manager.update_gametype_wins(self.gametype)
        set_total_event(self)

    def room_event(self, sim: int, room: str, room_index: int, value: int, top_slot: int) -> dict:
        """Presentation payload for the bonus room. Everything here is authored by the math."""
        common = {"multiplier": value, "topSlotMultiplier": top_slot, "total": value * top_slot}
        if room == "piratePlinko":
            return {
                "type": "piratePlinkoRoom",
                "board": [v * top_slot for v in PLINKO_SLOTS],
                "dropZone": plinko_drop_zone(sim),
                "slot": room_index,
                **common,
            }
        if room == "bonusWheel":
            return {
                "type": "bonusWheelRoom",
                "wedges": [v * top_slot for v in WHEEL_LAYOUT],
                "wedge": wheel_wedge_for_value(sim, value),
                **common,
            }
        if room == "chest":
            opened, values = chest_layout(sim, value)
            return {
                "type": "chestRoom",
                "chests": [v * top_slot for v in values],
                "opened": opened,
                "chestCount": NUM_CHESTS,
                **common,
            }
        if room == "oceanVoyage":
            depths_dived = room_index + 1
            path, fail = dive_path(sim, depths_dived)
            return {
                "type": "oceanVoyageRoom",
                "depths": [v * top_slot for v in VOYAGE_DEPTHS],
                "tilesPerDepth": TILES_PER_DEPTH,
                "dived": depths_dived,
                "path": path,
                "krakenTile": fail,
                **common,
            }
        raise KeyError(room)
