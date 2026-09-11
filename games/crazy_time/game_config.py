"""Crazy Time (working title) game configuration.

Ten bet modes on one shared outcome space: eight single spots, `bonuses` (all four rooms,
cost 4) and `full_board` (all eight spots, cost 8). `amount` is the chip; the RGS charges
`cost x amount`. See crazy_time_data for the outcome model and the RTP derivation.
"""

import os
import sys

from src.config.config import Config
from src.config.config import BetMode
from src.config.distributions import Distribution

# `run.py` puts this directory on sys.path; tools importing this as a package module
# (utils/rgs_verification.py does `games.crazy_time.game_config`) do not.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from crazy_time_data import (  # noqa: E402
    BUY_MODE_NAMES,
    MODE_NAMES,
    TARGET_RTP,
    TOP_SLOT_MAX,
    max_win_for_mode,
    mode_cost,
)


class GameConfig(Config):
    """Crazy Time configuration class."""

    def __init__(self):
        super().__init__()
        self.game_id = "crazy_time"
        self.game_name = "Crazy Time"
        self.provider_number = 0
        self.working_name = "Crazy Time (working title)"
        # Global default only; run_sims overrides config.wincap with each BetMode's max_win.
        self.wincap = max(max_win_for_mode(mode) for mode in MODE_NAMES)
        self.win_type = "other"
        self.rtp = float(TARGET_RTP)
        self.construct_paths()

        # No reels / board for a wheel game: stub the slot-shaped fields the SDK reads.
        self.num_reels = 0
        self.num_rows = [0] * self.num_reels
        self.paytable = {}
        self.include_padding = False
        self.special_symbols = {"wild": [], "scatter": [], "multiplier": []}
        self.freespin_triggers = {self.basegame_type: {}, self.freegame_type: {}}
        self.anticipation_triggers = {self.basegame_type: 0, self.freegame_type: 0}

        self.top_slot_max = TOP_SLOT_MAX

        # One distribution per mode: outcomes are enumerated exhaustively (see gamestate.py)
        # and the lookup table carries exact weights (see run.py), so no forced strata.
        self.bet_modes = [
            BetMode(
                name=mode,
                cost=float(mode_cost(mode)),
                rtp=self.rtp,
                max_win=max_win_for_mode(mode),
                auto_close_disabled=False,
                # The bet board picks the mode, not a mode picker: keep it sticky client-side.
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
            for mode in MODE_NAMES
        ] + [
            # Buy-bonus modes: straight into a room at the room's natural Top Slot odds. Not
            # base modes (no hit-rate floor); one-shot, so not sticky.
            BetMode(
                name=mode,
                cost=float(mode_cost(mode)),
                rtp=self.rtp,
                max_win=max_win_for_mode(mode),
                auto_close_disabled=False,
                is_feature=False,
                is_buybonus=True,
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
            for mode in BUY_MODE_NAMES
        ]
