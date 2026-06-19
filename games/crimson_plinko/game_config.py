"""One-Eyed Willy's Plinko math config — matches stake-web-sdk apps/plinko."""

import os

from src.config.config import BetMode, Config
from src.config.distributions import Distribution
from src.config.paths import PATH_TO_GAMES

from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    COEFFICIENT_SETS,
    TARGET_RTP,
    bet_mode_for_balls_per_drop,
    bonus_meter_strata_starts,
    bonus_mode_for_balls,
    scaled_spin_meter_start,
    spin_in_drop_for_balls,
)

# Math package folder (make run GAME=crimson_plinko); RGS gameID is one_eyed_willys_plinko.
PACKAGE_DIR = "crimson_plinko"

# BONUS-meter-state strata within each balls-per-drop tier. The bonus meter is a SESSION meter, so
# published base books span the range of carried bonus-meter states (the client picks/renders by its
# running meter). The SPIN meter is now per-drop (fixed per-tier start, fires in-drop), so it needs
# no strata variety. Quotas must sum to 1.0 per tier.
_FEATURE_STRATA = (
    # (criteria, bonus_start_key, quota)
    ("basegame", "zero", 0.92),
    ("bonus_meter_mid", "mid", 0.02),
    ("bonus_meter_high", "high", 0.02),
    ("bonus_meter_full", "full", 0.04),
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
        # Declared RTP = the tuned per-ball board EV (matches the actual ~95.7% every mode produces;
        # stays inside the 90.0%-96.70% compliance band, unlike the old 0.97 placeholder).
        self.rtp = TARGET_RTP
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
            force_bonus: bool = False,
            suppress_features: bool = False,
            spin_in_drop: bool = False,
        ) -> dict:
            return {
                "difficulty": 0,
                "row_count": 14,
                "balls_per_drop": int(balls_per_drop),
                "stake_per_ball": self.stake_per_ball,
                "spin_meter_start": int(spin_meter_start),
                "bonus_meter_start": int(bonus_meter_start),
                "bonus_level_start": int(bonus_level_start),
                "force_bonus": bool(force_bonus),
                "suppress_features": bool(suppress_features),
                "spin_in_drop": bool(spin_in_drop),
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
            bonus_mid, bonus_high, bonus_full = bonus_meter_strata_starts(balls)
            bonus_starts = {"zero": 0, "mid": bonus_mid, "high": bonus_high, "full": bonus_full}
            # Spin meter is per-drop: same fixed start every book; in-drop free spin on 10/20/50.
            spin_start = scaled_spin_meter_start(balls)
            spin_in_drop = spin_in_drop_for_balls(balls)

            distributions = [
                Distribution(
                    criteria=f"{criteria}_balls_{balls}",
                    quota=quota,
                    conditions=plinko_conditions(
                        balls_per_drop=balls,
                        spin_meter_start=spin_start,
                        bonus_meter_start=bonus_starts[bonus_key],
                        # Free spin fires IN-DROP (spin_in_drop) on 10/20/50; the BONUS meter is
                        # suppressed in-drop (carries over, fired by the dedicated bonus trigger mode).
                        suppress_features=True,
                        spin_in_drop=spin_in_drop,
                    ),
                )
                for criteria, bonus_key, quota in _FEATURE_STRATA
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

            # Dedicated BONUS trigger mode (client auto-fires it when the bonus meter fills).
            # Cost stays at the tier value for sims (RTP math divides by it); run.py republishes
            # config.json with the free `TRIGGER_MODE_COST`. (No freespin trigger mode — the free
            # spin is now in-drop in the base modes.)
            self.bet_modes.append(
                BetMode(
                    name=bonus_mode_for_balls(balls),
                    cost=float(balls),
                    rtp=self.rtp,
                    max_win=self.wincap,
                    auto_close_disabled=False,
                    is_feature=True,
                    is_buybonus=False,
                    distributions=[
                        Distribution(
                            criteria=f"bonus_balls_{balls}",
                            quota=1.0,
                            conditions=plinko_conditions(
                                balls_per_drop=balls, force_bonus=True
                            ),
                        ),
                    ],
                ),
            )

    def construct_paths(self) -> None:
        """Keep library output under games/crimson_plinko while publishing one_eyed_willys_plinko."""
        self.reels_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "reels")
        self.library_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "library")
        self.publish_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "library", "publish_files")
