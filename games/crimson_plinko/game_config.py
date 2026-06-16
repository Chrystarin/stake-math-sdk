"""One-Eyed Willy's Plinko math config — matches stake-web-sdk apps/plinko."""

import os

from src.config.config import BetMode, Config
from src.config.distributions import Distribution
from src.config.paths import PATH_TO_GAMES

from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    COEFFICIENT_SETS,
    bet_mode_for_balls_per_drop,
    bonus_meter_strata_starts,
    spin_meter_strata_starts,
)

# Math package folder (make run GAME=crimson_plinko); RGS gameID is one_eyed_willys_plinko.
PACKAGE_DIR = "crimson_plinko"

# Feature strata within each balls-per-drop tier. `spin`/`bonus` are the meter-start values
# the stratum carries (None -> filled in from the per-tier strata helper). Quotas are
# placeholder weights (tune RTP later); they must sum to 1.0 per tier. Feature strata are
# weighted up vs. real RTP so published books actually contain triggers for testing.
_FEATURE_STRATA = (
    # (criteria, spin_start_key, bonus_start_key, quota)
    ("basegame", "zero", "zero", 0.90),
    ("spin_meter_mid", "mid", "zero", 0.02),
    ("spin_meter_high", "high", "zero", 0.02),
    ("spin_meter_full", "full", "zero", 0.02),
    ("bonus_meter_mid", "zero", "mid", 0.005),
    ("bonus_meter_high", "zero", "high", 0.005),
    ("bonus_meter_full", "zero", "full", 0.03),
)


class GameConfig(Config):

    def __init__(self):
        super().__init__()
        self.game_id = "one_eyed_willys_plinko"
        self.game_name = "One-Eyed Willy's Plinko"
        self.provider_name = "casino_tv"
        self.provider_number = 0
        self.working_name = "One-Eyed Willy's Plinko"
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

        # Exported to frontend config (apps/plinko coefficientSets shape).
        self.plinko_coefficient_sets = COEFFICIENT_SETS
        self.min_bet = 0.01
        self.max_bet = 1000.0

        # Default drop matches sim conditions. Stake mode cost = balls per tier; payout
        # multipliers are normalized to return-per-drop in game_override.update_final_win.
        self.balls_per_drop = 10
        self.stake_per_ball = 1.0

        def plinko_conditions(
            *,
            balls_per_drop: int,
            spin_meter_start: int = 0,
            bonus_meter_start: int = 0,
            bonus_level_start: int = 0,
        ) -> dict:
            return {
                "difficulty": 0,
                "row_count": 14,
                "balls_per_drop": int(balls_per_drop),
                "stake_per_ball": self.stake_per_ball,
                "spin_meter_start": int(spin_meter_start),
                "bonus_meter_start": int(bonus_meter_start),
                "bonus_level_start": int(bonus_level_start),
                "reel_weights": {},
                "force_wincap": False,
                "force_freegame": False,
            }

        # One RGS bet mode per balls-per-drop tier (LUT contains only that tier's books).
        # Each tier carries meter-start strata so RGS can serve a carry-over book matching
        # the player's running meter (selected via bet `meta` on live play).
        self.bet_modes = []
        for balls in BALLS_PER_DROP_OPTIONS:
            mode_name = bet_mode_for_balls_per_drop(balls)
            spin_mid, spin_high, spin_full = spin_meter_strata_starts(balls)
            bonus_mid, bonus_high, bonus_full = bonus_meter_strata_starts(balls)
            spin_starts = {"zero": 0, "mid": spin_mid, "high": spin_high, "full": spin_full}
            bonus_starts = {"zero": 0, "mid": bonus_mid, "high": bonus_high, "full": bonus_full}

            distributions = [
                Distribution(
                    criteria=f"{criteria}_balls_{balls}",
                    quota=quota,
                    conditions=plinko_conditions(
                        balls_per_drop=balls,
                        spin_meter_start=spin_starts[spin_key],
                        bonus_meter_start=bonus_starts[bonus_key],
                    ),
                )
                for criteria, spin_key, bonus_key, quota in _FEATURE_STRATA
            ]

            self.bet_modes.append(
                BetMode(
                    name=mode_name,
                    # Play `amount` = per-ball stake from betLevels; cost = balls per tier.
                    cost=float(balls),
                    rtp=self.rtp,
                    max_win=self.wincap,
                    auto_close_disabled=False,
                    is_feature=True,
                    is_buybonus=False,
                    distributions=distributions,
                ),
            )

    def construct_paths(self) -> None:
        """Keep library output under games/crimson_plinko while publishing one_eyed_willys_plinko."""
        self.reels_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "reels")
        self.library_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "library")
        self.publish_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "library", "publish_files")
