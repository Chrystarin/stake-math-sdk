"""Crimson Plinko book events (Stake Web SDK apps/plinko types)."""

from src.events.events import EventConstants, final_win_event

from plinko_data import DEFAULT_VARIANT_ID


def plinko_drop_event(
    gamestate,
    *,
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
            "difficulty": DEFAULT_VARIANT_ID,
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


def bonus_meter_event(gamestate, *, value: int, level: int, max_value: int = 0) -> None:
    event = {
        "index": len(gamestate.book.events),
        "type": "bonusMeter",
        "value": int(value),
        "level": int(level),
    }
    # In-bonus level-up meter carries its own max (the level-up threshold); trigger-phase events omit it
    # and the client uses the per-tier plinkoDrop bonusMeterMax.
    if max_value > 0:
        event["max"] = int(max_value)
    gamestate.book.add_event(event)


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
    levelup_pegs: int = 0,
    spin_meter_start: int = 0,
) -> None:
    """One bonus level's batch of free balls.

    `levelup_pegs` is the coin-peg count needed to LEAVE this level (`bonus_levelup_pegs(level)`) —
    the escalating threshold is per-level, so the client cannot know it from the level-1 value alone.
    It sizes the in-bonus energy bar from this field (`sizeBonusMeterForLevel` in apps/plinko
    gameOrchestrator.ts); omitting it made every level render against the level-1 threshold.

    `spin_meter_start` is the FREE-SPIN meter carried into this batch. That meter runs across levels
    (it resets only when it fires), so a batch can open part-full, and the client cannot recover the
    carry from its own level boundaries once `combineNextBonusLevelNow` has merged two levels' balls
    into one pool. Always emitted — 0 is a real, meaningful value here, unlike `levelupPegs`."""
    event = {
        "index": len(gamestate.book.events),
        "type": "bonusRound",
        "freeBalls": int(free_balls),
        "outcomes": outcomes,
        "level": int(level),
        "ballsPlayed": int(balls_played),
        "spinMeterStart": int(spin_meter_start),
    }
    if int(levelup_pegs) > 0:
        event["levelupPegs"] = int(levelup_pegs)
    gamestate.book.add_event(event)


def free_spin_trigger_event(
    gamestate, *, multiplier: float, segment: str, amount: float = 0.0, level: int = 0
) -> None:
    """`amount` is round drop win × segment multiplier in ×100 currency units at book stake.

    `level` (>0 for an in-bonus free spin) is the bonus level whose balls just finished — the client
    fires the wheel at that level boundary, before the level-up. 0 for a base (non-bonus) free spin."""
    event: dict = {
        "index": len(gamestate.book.events),
        "type": "freeSpinTrigger",
        "multiplier": float(multiplier),
        "segment": str(segment),
        "amount": int(round(float(amount) * 100, 0)),
    }
    if int(level) > 0:
        event["level"] = int(level)
    gamestate.book.add_event(event)


def plinko_set_total_event(gamestate) -> None:
    """setTotalWin = payout multiplier (relative to play amount) × 100, capped at wincap."""
    gamestate.book.add_event(
        {
            "index": len(gamestate.book.events),
            "type": EventConstants.SET_TOTAL_WIN.value,
            "amount": int(
                round(min(gamestate.final_win, gamestate.config.wincap) * 100, 0)
            ),
        }
    )


def emit_plinko_settlement(gamestate) -> None:
    """Normalize payout, then setTotalWin and finalWin."""
    gamestate.update_final_win()
    plinko_set_total_event(gamestate)
    final_win_event(gamestate)
