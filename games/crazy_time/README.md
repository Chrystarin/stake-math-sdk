# Crazy Time (working title) — Math SDK

Stake Engine math model for a single-player money-wheel show modelled on Evolution's Crazy Time.
The matching web client lives in the separate `stake-web-sdk` repo at `apps/crazy-time/`.

**The title is a placeholder** ("Crazy Time" is Evolution's trademark). Rename `game_id`,
`game_name` and this package before publishing.

## The game

- **Wheel**: 54 segments. `x1` 21, `x2` 13, `x5` 7, `x10` 4, `chest` 4, `plinko` 2, `tower` 2,
  `wheel` 1 — Crazy Time's own split, so the Jackpot Wheel is the one-off segment. Layout in
  `SEGMENT_LAYOUT`: one room every six segments, so exactly five numbers sit between any two rooms
  (chests every 12, plinko and tower opposite pairs, the wheel on its own); x10 never next to x10.
- **Numbers** pay n:1 (x1 returns 2x the chip).
- **Top Slot**: before each spin one spot may be paired with a multiplier from
  `2 3 4 5 7 10 15 20 25 50`. If the wheel then lands on that spot, a number's n:1 payout is
  multiplied, a room's result is multiplied. Otherwise nothing happens.
- **Rooms**, each a weighted table of gross multipliers on the chip:
  Plinko 13 slots (7x–400x, binomial landing weights), Jackpot Wheel 36 wedges (10x–500x),
  Treasure Chest 12 chests (2x–250x), Dragon Tower 10 floors (2x–250x). A room's table is sized
  to its segment count: the one-off Jackpot Wheel pays the most per hit, the four chests the least.

## Bet modes (10)

A ticket covers a fixed set of spots at ONE chip each; `cost` = spots covered, `amount` = chip.

| Mode | Covers | Cost | Max win (x chip) |
| --- | --- | --- | --- |
| `x1` `x2` `x5` `x10` | that number | 1 | 51 / 101 / 251 / 501 |
| `plinko` `wheel` `chest` `tower` | that room | 1 | 20,000 / 25,000 / 12,500 / 12,500 |
| `bonuses` | all four rooms | 4 | 25,000 |
| `full_board` | all eight spots | 8 | 25,000 |

Stake caps a game at 50 modes (confirmed 2026-09-04); free combination of 8 spots would be 255.

## RTP: 96.5% on every mode

Each spot is tuned to `TARGET_RTP` on its own with the Top Slot pairing weight `q[spot]` as the
lever (`crazy_time_data._solve_pairing`). For a number paying n:1

    P(hit) * (1 + n * (1 + q * (E[m] - 1))) = 0.965

and for a room with mean multiplier R

    P(hit) * R * (1 + q * (E[m] - 1)) = 0.965

Because every spot returns 96.5%, every bundle does too (linearity), so all ten modes certify
at one number.

## How the books are made

The outcome space (segment x Top Slot entry x room outcome) is small — **11,583 outcomes** — so
every mode's books list each outcome exactly once (`decode_outcome(sim)`), and the lookup table
carries each outcome's **exact probability weight** (`run.py: write_exact_weights`, run after
`create_books`). No RNG, no optimizer; the served RTP is the analytic value. All ten modes share
the outcome list and differ only in the payout column.

Book events per round: `topSlot`, `wheelSpin`, an optional room event (`plinkoBonus` /
`wheelBonus` / `chestBonus` / `towerBonus`, always authored when the wheel lands on a room, with
`covered` telling the client whether the ticket was in it), `winInfo`, `setTotalWin`, `finalWin`.
Room events carry everything the client draws (board values, drop zone, wedge, chest decoys,
tower path), all derived deterministically from the simulation index.

## Files

```
crazy_time_data.py   wheel, tables, Top Slot solver, enumeration, payout, presentation extras
game_config.py       GameConfig + 10 BetModes (is_feature=True: the board picks the mode)
gamestate.py         one round: decode -> events -> win
run.py               create_books, then rewrite LUT weights, then generate_configs
library/             GENERATED: publish_files/ is the RGS upload set
```

## Run

From the repo root:

```sh
make run GAME=crazy_time
# or
PYTHONPATH=. env/Scripts/python.exe games/crazy_time/run.py
PYTHONPATH=. env/Scripts/python.exe utils/rgs_verification.py -g crazy_time
```

Then in the web repo: `pnpm --filter crazy-time sync-math-books`.

## Known gaps (prototype)

- Plinko's 400x top under a 50x Top Slot puts its 20,000x max win at ~1 in 113 million, below
  Stake's 1-in-20-million achievability floor for an advertised max win. Cap Plinko's top value
  or raise its weight before publishing. (The game's 25,000x max — the Jackpot Wheel's 500x wedge
  under a 50x Top Slot — is at ~1 in 6.4 million, above the floor.)
- Room tables and Top Slot reel weights are first-pass (the 4/2/2/1 room split mirrors Crazy
  Time); three of the rooms are placeholders for games still being designed.
- No DOUBLE / rescue mechanics in any room yet.
