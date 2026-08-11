"""Colour Dice game configuration.

Stake Engine port of the Filipino "Colour Game" / Perya: three 6-sided dice, each face one
of six colours. The player backs 1-6 colours AT AN EQUAL STAKE; every backed colour pays
independently on how many dice show it.

    1 die   -> 2x        2 dice -> 3x        3 dice -> Lucky Wheel (4x .. 200x)

BET MODES
---------
The RGS settles a round from a precomputed book, so the shape of the bet must be fixed
before the book is drawn. With the stake equal on every backed colour, and all six colours
statistically identical, a round is fully described by HOW MANY colours were backed — so
there is exactly one mode per count:

    mode   = "3_colours"       three colours backed
    cost   = 3                 (so total stake = cost x amount)
    amount = stake per colour  (submitted verbatim, so always a tray denomination)

Same cost/amount shape as games/crimson_plinko, where cost = balls per drop.

RTP is identical for every mode (linearity of expectation over the backed colours), so all
6 certify at one number: 96.49%, inside Stake's 90.00%-96.70% band.
"""

import os
import sys

from src.config.config import Config
from src.config.config import BetMode
from src.config.distributions import Distribution

# `run.py` puts this directory on sys.path automatically, but tools that import the config as
# a package module (utils/rgs_verification.py does `games.colour_dice.game_config`) do not.
# Add it so the flat `colour_dice_data` import resolves either way.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from colour_dice_data import (
    COLOURS,
    LAYOUTS,
    MAX_COLOURS,
    NUM_DICE,
    PAYTABLE_MATCHES,
    TARGET_RTP,
    WHEEL,
    WHEEL_TOP,
    max_win_for_layout,
    mode_name,
)


class GameConfig(Config):
    """Colour Dice configuration class."""

    def __init__(self):
        super().__init__()
        self.game_id = "colour_dice"
        # Published to config_fe as `gameName` and mirrored by the client's game/config.ts.
        # Without this it inherits Config's "sample_lines" default.
        self.game_name = "Colour Dice"
        self.provider_numer = 0
        self.working_name = "Colour Dice"
        # Global default only. run_sims.py overrides config.wincap with each BetMode's
        # max_win before that mode's sims, so books are capped per layout.
        self.wincap = float(WHEEL_TOP)
        self.win_type = "other"
        self.rtp = TARGET_RTP
        self.construct_paths()

        # Game dimensions (no reels/board for a dice game)
        self.num_reels = 0
        self.num_rows = [0] * self.num_reels
        self.paytable = {}
        self.include_padding = False
        self.special_symbols = {"wild": [], "scatter": [], "multiplier": []}

        self.freespin_triggers = {self.basegame_type: {}, self.freegame_type: {}}
        self.anticipation_triggers = {self.basegame_type: 0, self.freegame_type: 0}

        # --- Colour Dice specific -------------------------------------------------
        self.colours = list(COLOURS)
        self.num_dice = NUM_DICE
        self.max_colours = MAX_COLOURS
        self.paytable_matches = dict(PAYTABLE_MATCHES)
        self.wheel = list(WHEEL)
        self.layouts = LAYOUTS

        # One mode per backed-colour count. A single distribution per mode: the outcome
        # space is small enough to enumerate exhaustively (see gamestate.py), so books are
        # generated deterministically at exact frequency rather than sampled — no forced
        # strata, no reel weighting, and the served RTP is the analytic value exactly.
        self.bet_modes = [
            BetMode(
                name=mode_name(layout),
                cost=float(sum(layout)),
                rtp=self.rtp,
                max_win=max_win_for_layout(layout),
                auto_close_disabled=False,
                # The board state picks the mode, not a player-facing mode picker, so the
                # front end must keep the selected mode across bets without confirmation.
                is_feature=True,
                is_buybonus=False,
                distributions=[
                    Distribution(
                        criteria="basegame",
                        quota=1.0,
                        conditions={
                            "reel_weights": {},
                            "force_wincap": False,
                            "force_freegame": False,
                        },
                    ),
                ],
            )
            for layout in LAYOUTS
        ]
