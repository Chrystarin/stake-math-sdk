"""Crimson Plinko book events (Stake Web SDK apps/plinko types)."""

from src.events.events import EventConstants, final_win_event


def plinko_drop_event(
    gamestate,
    *,
    difficulty: int,
    row_count: int,
    balls_per_drop: int,
    stake_per_ball: float,
    coefficients: list[float],
    spin_meter_max: int,
    bonus_meter_max: int,
    spin_meter_start: int,
    bonus_meter_start: int,
    bonus_level_start: int,
    outcomes: list[dict],
) -> None:
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": "plinkoDrop",
            "difficulty": difficulty,
            "rowCount": row_count,
            "ballsPerDrop": balls_per_drop,
            "stakePerBall": stake_per_ball,
            "coefficients": list(coefficients),
            "spinMeterMax": int(spin_meter_max),
            "bonusMeterMax": int(bonus_meter_max),
            "spinMeterStart": int(spin_meter_start),
            "bonusMeterStart": int(bonus_meter_start),
            "bonusLevelStart": int(bonus_level_start),
            "outcomes": outcomes,
        }
    )


def bonus_meter_event(gamestate, *, value: int, level: int) -> None:
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": "bonusMeter",
            "value": int(value),
            "level": int(level),
        }
    )


def spin_meter_event(gamestate, *, value: int, max_value: int) -> None:
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": "spinMeter",
            "value": int(value),
            "max": int(max_value),
        }
    )


def bonus_roulette_event(gamestate, *, free_balls: int) -> None:
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": "bonusRoulette",
            "freeBalls": int(free_balls),
        }
    )


def bonus_round_event(
    gamestate,
    *,
    free_balls: int,
    outcomes: list[dict],
    level: int,
    balls_played: int = 0,
) -> None:
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": "bonusRound",
            "freeBalls": int(free_balls),
            "outcomes": outcomes,
            "level": int(level),
            "ballsPlayed": int(balls_played),
        }
    )


def free_spin_trigger_event(gamestate, *, multiplier: float, segment: str) -> None:
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": "freeSpinTrigger",
            "multiplier": float(multiplier),
            "segment": str(segment),
        }
    )


def plinko_set_total_event(gamestate) -> None:
    """setTotalWin using normalized return (mode cost 1.0)."""
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": EventConstants.SET_TOTAL_WIN.value,
            "amount": int(
                round(
                    min(gamestate.final_win, gamestate.config.wincap / gamestate.drop_wager_units()) * 100,
                    0,
                )
            ),
        }
    )


def emit_plinko_settlement(gamestate) -> None:
    """Normalize payout, then setTotalWin and finalWin."""
    gamestate.update_final_win()
    plinko_set_total_event(gamestate)
    final_win_event(gamestate)
