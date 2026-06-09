"""One-Eyed Willy's Plinko math config — matches stake-web-sdk apps/plinko."""



import os



from src.config.config import BetMode, Config

from src.config.distributions import Distribution

from src.config.paths import PATH_TO_GAMES



from plinko_data import BALLS_PER_DROP_OPTIONS, COEFFICIENT_SETS, spin_meter_strata_starts



# Math package folder (make run GAME=crimson_plinko); RGS gameID is one_eyed_willys_plinko.

PACKAGE_DIR = "crimson_plinko"



# Spin-meter feature strata (within each balls-per-drop tier).

_SPIN_STRATA = (

    ("basegame", 0, 0.994),

    ("spin_meter_mid", None, 0.002),

    ("spin_meter_high", None, 0.002),

    ("spin_meter_full", None, 0.002),

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



        # Default drop matches sim conditions. Stake base mode cost must be 1.0x; payout

        # multipliers are normalized to return-per-drop in game_override.update_final_win.

        self.balls_per_drop = 10

        self.stake_per_ball = 1.0



        def plinko_conditions(

            *,

            balls_per_drop: int,

            spin_meter_start: int = 0,

            bonus_meter_start: int = 0,

        ) -> dict:

            return {

                "difficulty": 0,  # default variant (plinkoDrop.difficulty wire field)

                "row_count": 14,

                "balls_per_drop": int(balls_per_drop),

                "stake_per_ball": self.stake_per_ball,

                "spin_meter_start": int(spin_meter_start),

                "bonus_meter_start": int(bonus_meter_start),

                "bonus_level_start": 0,

                "reel_weights": {},

                "force_wincap": False,

                "force_freegame": False,

            }



        # Session carry-over is injected on live play via bet meta (`spin_meter_start`,

        # `balls_per_drop`, etc.). Lookup books must include matching strata or RGS cannot

        # serve the correct book for the player's UI selection.

        ball_tier_count = len(BALLS_PER_DROP_OPTIONS)

        tier_quota = 1.0 / ball_tier_count



        distributions: list[Distribution] = []

        for balls in BALLS_PER_DROP_OPTIONS:

            mid_spin, high_spin, near_full_spin = spin_meter_strata_starts(balls)

            spin_starts = {

                "basegame": 0,

                "spin_meter_mid": mid_spin,

                "spin_meter_high": high_spin,

                "spin_meter_full": near_full_spin,

            }

            suffix = f"_balls_{balls}" if balls != self.balls_per_drop else ""

            for criteria, _, quota in _SPIN_STRATA:

                spin_start = spin_starts[criteria]

                distributions.append(

                    Distribution(

                        criteria=f"{criteria}{suffix}",

                        quota=quota * tier_quota,

                        conditions=plinko_conditions(

                            balls_per_drop=balls,

                            spin_meter_start=spin_start,

                        ),

                    )

                )



        self.bet_modes = [

            BetMode(

                name="base",

                cost=1.0,

                rtp=self.rtp,

                max_win=self.wincap,

                auto_close_disabled=False,

                is_feature=True,

                is_buybonus=False,

                distributions=distributions,

            ),

        ]



    def construct_paths(self) -> None:

        """Keep library output under games/crimson_plinko while publishing one_eyed_willys_plinko."""

        self.reels_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "reels")

        self.library_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "library")

        self.publish_path = os.path.join(PATH_TO_GAMES, PACKAGE_DIR, "library", "publish_files")


