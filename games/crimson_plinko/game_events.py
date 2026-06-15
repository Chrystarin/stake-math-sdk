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
            "outcomes": outcomes,
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
