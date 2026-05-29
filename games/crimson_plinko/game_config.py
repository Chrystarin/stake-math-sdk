"""Crimson Plinko math config — matches stake-web-sdk apps/plinko."""

from src.config.config import BetMode, Config
from src.config.distributions import Distribution

from plinko_data import COEFFICIENT_SETS


class GameConfig(Config):
    def __init__(self):
        super().__init__()
        self.game_id = "crimson_plinko"
        self.provider_name = "crimson"
        self.provider_number = 0
        self.working_name = "crimson_plinko"
        self.wincap = 1000.0
        self.win_type = "other"
        self.rtp = 0.97
        self.construct_paths()

        self.num_reels = 0
        self.num_rows = []
        self.paytable = {}
        self.include_padding = False
        self.special_symbols = {"wild": [], "scatter": [], "multiplier": []}
        self.freespin_triggers = {self.basegame_type: {}, self.freegame_type: {}}
        self.anticipation_triggers = {self.basegame_type: 0, self.freegame_type: 0}

        # Exported to frontend config (apps/plinko defaultCoefficientSets shape).
        self.plinko_coefficient_sets = COEFFICIENT_SETS
        self.min_bet = 0.01
        self.max_bet = 1000.0

        # Default drop matches sim conditions. Stake base mode cost must be 1.0x; payout
        # multipliers are normalized to return-per-drop in game_override.update_final_win.
        self.balls_per_drop = 10
        self.stake_per_ball = 1.0

        base_conditions = {
            "difficulty": 0,
            "row_count": 14,
            "balls_per_drop": self.balls_per_drop,
            "stake_per_ball": self.stake_per_ball,
            "reel_weights": {},
            "force_wincap": False,
            "force_freegame": False,
        }

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
                        conditions=dict(base_conditions),
                    ),
                ],
            ),
        ]
