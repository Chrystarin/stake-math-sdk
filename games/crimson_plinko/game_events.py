"""Crimson Plinko book events (Stake Web SDK apps/plinko types)."""

from src.events.events import set_total_event, final_win_event


def plinko_drop_event(
    gamestate,
    *,
    difficulty: int,
    row_count: int,
    balls_per_drop: int,
    stake_per_ball: float,
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
            "outcomes": outcomes,
        }
    )


def emit_plinko_settlement(gamestate) -> None:
    """setTotalWin then finalWin (SDK bookEventHandlerMap order)."""
    set_total_event(gamestate)
    gamestate.update_final_win()
    final_win_event(gamestate)
