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
    bonus_in_drop_for_balls,
    bonus_in_drop_rate,
    scaled_bonus_meter_start,
    scaled_spin_meter_start,
    spin_in_drop_for_balls,
)

# Math package folder (make run GAME=crimson_plinko); RGS gameID is one_eyed_willys_plinko.
PACKAGE_DIR = "crimson_plinko"


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
            bonus_in_drop: bool = False,
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
                "bonus_in_drop": bool(bonus_in_drop),
                "reel_weights": {},
                "force_wincap": False,
                "force_freegame": False,
            }

        # OPTION A (per-drop meter trigger): only 4 BASE modes (cost = ball count), NO separate bonus
        # mode. The FREE bonus fires IN-DROP when this drop's coin-pegs fill the PER-DROP bonus meter
        # (`bonus_in_drop`, on 10/20/50) — fully stateless. Each mode still has TWO distributions: the
        # NORMAL drop (quota = 1 - rate; the meter fires the bonus organically) and a small `force_bonus`
        # QUOTA (quota = rate) that covers 1-ball (can't meter-fire) and fine-tunes the higher tiers to
        # exactly TARGET_RTP. The free spin fires in-drop in both. Board (~0.896) funds the free bonus.
        self.bet_modes = []
        for balls in BALLS_PER_DROP_OPTIONS:
            mode_name = bet_mode_for_balls_per_drop(balls)
            spin_start = scaled_spin_meter_start(balls)
            bonus_start = scaled_bonus_meter_start(balls)
            spin_in_drop = spin_in_drop_for_balls(balls)
            bonus_in_drop = bonus_in_drop_for_balls(balls)
            rate = bonus_in_drop_rate(balls)
            normal_quota = max(0.0, 1.0 - rate)

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
                    distributions=[
                        # Normal paid drop — the per-drop bonus meter (bonus_in_drop) fires the bonus when
                        # this drop's coin-pegs fill it; the free spin can fire in-drop too.
                        Distribution(
                            criteria=f"basegame_balls_{balls}",
                            quota=normal_quota,
                            conditions=plinko_conditions(
                                balls_per_drop=balls,
                                spin_meter_start=spin_start,
                                bonus_meter_start=bonus_start,
                                spin_in_drop=spin_in_drop,
                                bonus_in_drop=bonus_in_drop,
                            ),
                        ),
                        # QUOTA bonus stratum — guarantees a bonus (snaps the meter to full): covers
                        # 1-ball and fine-tunes the others to TARGET_RTP. One book settles `drop + bonus`.
                        Distribution(
                            criteria=f"basegame_bonus_balls_{balls}",
                            quota=rate,
                            conditions=plinko_conditions(
                                balls_per_drop=balls,
                                spin_meter_start=spin_start,
                                bonus_meter_start=bonus_start,
                                spin_in_drop=spin_in_drop,
                                bonus_in_drop=bonus_in_drop,
                                force_bonus=True,
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
