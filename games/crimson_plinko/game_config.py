"""One-Eyed Willy's Plinko math config — matches stake-web-sdk apps/plinko."""

import os

from src.config.config import BetMode, Config
from src.config.distributions import Distribution
from src.config.paths import PATH_TO_GAMES

from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    COEFFICIENT_SETS,
    DEFAULT_WINCAP,
    TARGET_RTP,
    BUY_BONUS_BALLS_PER_DROP_REF,
    BUY_BONUS_TIER_DEFS,
    bet_mode_for_balls_per_drop,
    bonus_in_drop_for_balls,
    bonus_in_drop_rate,
    bonus_possible_for_balls,
    buy_bonus_mode_name,
    declared_rtp_for_balls,
    scaled_bonus_meter_start,
    scaled_spin_meter_start,
    spin_in_drop_for_balls,
    wincap_for_balls,
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
        # Default/global cap = top of the per-tier ladder (plinko_data.WINCAP_BY_BALLS). The advertised
        # max win is PER-TIER (200/250/300/400 for 1/10/20/50 balls) so that each tier's declared max is
        # actually achievable in its own books (Stake: max win must hit >= 1/20,000,000). run_sims.py
        # overrides config.wincap with each BetMode.max_win below before that mode's sims, so books +
        # config.json maxWin are capped per tier; this default only applies pre-override.
        self.wincap = DEFAULT_WINCAP
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
        self.max_bet = 2500.0

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
            bonus_only: bool = False,
            buy_entry_balls: int = 0,
            buy_levelup_head_start: float = 0.0,
            buy_levelup_pegs: int = 0,
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
                # BUY BONUS: empty paid drop (no base balls) + the bonus seeded with `buy_entry_balls`
                # fixed entry balls; the meter is pre-filled to full in gamestate. Settles `bonus` only.
                "bonus_only": bool(bonus_only),
                "buy_entry_balls": int(buy_entry_balls),
                "buy_levelup_head_start": float(buy_levelup_head_start),
                "buy_levelup_pegs": int(buy_levelup_pegs),
                "reel_weights": {},
                "force_wincap": False,
                "force_freegame": False,
            }

        # OPTION A (per-drop meter trigger): only 4 BASE modes (cost = ball count), NO separate bonus
        # mode. The FREE bonus fires IN-DROP when this drop's coin-pegs fill the PER-DROP bonus meter
        # (`bonus_in_drop`, on 10/20/50) — fully stateless. Those tiers have TWO distributions: the
        # NORMAL drop (quota = 1 - rate; the meter fires the bonus organically) and a small `force_bonus`
        # QUOTA (quota = rate) that fine-tunes them to exactly TARGET_RTP. The free spin fires in-drop
        # in both. Board (~0.896) funds the free bonus.
        #
        # ⚠️ The 1-ball tier is FEATURE-FREE: `spin_in_drop` / `bonus_in_drop` are both off AND its quota
        # is 0, so the `force_bonus` stratum is OMITTED (not quota-0 — `Distribution` asserts quota > 0).
        # onedrop therefore publishes a SINGLE full-quota normal-drop distribution and its books can never
        # contain a bonusRoulette / bonusRound / freeSpinTrigger event.
        self.bet_modes = []
        for balls in BALLS_PER_DROP_OPTIONS:
            mode_name = bet_mode_for_balls_per_drop(balls)
            spin_start = scaled_spin_meter_start(balls)
            bonus_start = scaled_bonus_meter_start(balls)
            spin_in_drop = spin_in_drop_for_balls(balls)
            bonus_in_drop = bonus_in_drop_for_balls(balls)
            rate = bonus_in_drop_rate(balls) if bonus_possible_for_balls(balls) else 0.0
            normal_quota = max(0.0, 1.0 - rate)

            distributions = [
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
            ]
            if rate > 0.0:
                # QUOTA bonus stratum — guarantees a bonus (snaps the meter to full) to fine-tune this
                # tier to TARGET_RTP. One book settles `drop + bonus`. Skipped entirely on 1-ball.
                distributions.append(
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
                )

            self.bet_modes.append(
                BetMode(
                    name=mode_name,
                    # Play `amount` = per-ball stake from betLevels; cost = balls per tier.
                    cost=float(balls),
                    # Per-tier declared RTP: TARGET_RTP for the feature tiers, the bare board EV for the
                    # feature-free 1-ball tier (~0.954 on its own board).
                    rtp=declared_rtp_for_balls(balls),
                    # Per-tier advertised max win (achievable in this tier's own books). run_sims sets
                    # gamestate.config.wincap = this value before the mode's sims, so the per-ball payout
                    # multiplier is capped here and config.json publishes it as the mode's maxWin.
                    max_win=wincap_for_balls(balls),
                    auto_close_disabled=False,
                    is_feature=True,
                    is_buybonus=False,
                    distributions=distributions,
                ),
            )

        # BUY BONUS modes (is_buybonus, one-shot) — one per tier (cost is ×bet-per-ball, independent of
        # the player's balls-per-drop → exactly 4 modes). Each is BONUS-ONLY: an EMPTY paid drop + a
        # forced bonus seeded with the tier's FIXED entry balls, with the bonus meter pre-filled to full.
        # The in-bonus level-up / chain hits add MORE balls on top (combined total). cost comes from the
        # PDF; entry_balls are tuned so RTP ≈ TARGET_RTP at that fixed cost. Per-tier max_win binds the
        # thin tail (achievable advertised max). Mirror in web config.ts.
        for tier in BUY_BONUS_TIER_DEFS:
            name = buy_bonus_mode_name(tier["key"])
            self.bet_modes.append(
                BetMode(
                    name=name,
                    cost=float(tier["cost"]),
                    rtp=self.rtp,
                    max_win=float(tier["wincap"]),
                    auto_close_disabled=False,
                    is_feature=False,
                    is_buybonus=True,
                    distributions=[
                        Distribution(
                            criteria=f"buybonus_{name}",
                            quota=1.0,
                            conditions=plinko_conditions(
                                balls_per_drop=BUY_BONUS_BALLS_PER_DROP_REF,
                                force_bonus=True,
                                bonus_only=True,
                                buy_entry_balls=int(tier["entry_balls"]),
                                buy_levelup_head_start=float(tier.get("head_start", 0.0)),
                                buy_levelup_pegs=int(tier.get("levelup_pegs", 0)),
                                # In-bonus free spin stays on (off only on 1-ball); no in-drop spin/bonus
                                # since the buy drop is empty.
                                spin_in_drop=False,
                                bonus_in_drop=False,
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
