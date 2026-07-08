"""Colour Dice game configuration.

Stake Engine port of the Filipino "Colour Game / Perya": three 6-sided dice, each
face one of six colours. The player backs a single colour per round; the payout
scales with how many of the three dice show that colour:

    1 die  (single) -> 2x
    2 dice (double) -> 3x
    3 dice (triple) -> Lucky/Bonus wheel award (4x .. 200x)

Because every colour is statistically identical, a round's outcome is stored
*relative to the backed colour*: each die is either ``MATCH`` (the backed colour)
or one of ``C1``..``C5`` (the five other colours, in canonical order). The web
client substitutes the player's picked colour for ``MATCH`` and the remaining five
colours for ``C1``..``C5``.

RTP (analytic, since books are served uniformly):
    P(1 match)=75/216, P(2)=15/216, P(3)=1/216
    base = 75/216*2 + 15/216*3 = 0.902778
    wheel E = sum(value*weight)/sum(weight) = 14.538
    RTP  = 0.902778 + (1/216)*14.538 = 0.97008
"""

from src.config.config import Config
from src.config.distributions import Distribution
from src.config.config import BetMode


class GameConfig(Config):
    """Colour Dice configuration class."""

    def __init__(self):
        super().__init__()
        self.game_id = "colour_dice"
        self.provider_numer = 0
        self.working_name = "Colour Dice"
        self.wincap = 200.0
        self.win_type = "other"
        self.rtp = 0.9701
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
        # Canonical colour order shared with the web client. Index 0 is the
        # reference ("MATCH") colour used when generating relative outcomes.
        self.colours = ["yellow", "blue", "white", "green", "pink", "red"]

        # Gross return multiplier per number of matching dice (0 = loss).
        self.paytable_matches = {0: 0.0, 1: 2.0, 2: 3.0}

        # Triple-match wheel: (gross_multiplier, weight). The top value == wincap.
        # E[value] = 14.538 which tunes the total RTP to ~0.9701.
        self.wheel = [
            (4, 597),
            (10, 210),
            (20, 100),
            (50, 55),
            (100, 23),
            (200, 15),
        ]

        self.bet_modes = [
            BetMode(
                name="base",
                cost=1.0,
                rtp=self.rtp,
                max_win=self.wincap,
                auto_close_disabled=False,
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
            ),
        ]
