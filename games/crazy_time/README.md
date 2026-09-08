# Crazy Time (working title) — Math SDK

Stake Engine math model for a single-player money-wheel show modelled on Evolution's Crazy Time.
The matching web client lives in the separate `stake-web-sdk` repo at `apps/crazy-time/`.

**The title is a placeholder** ("Crazy Time" is Evolution's trademark). Rename `game_id`,
`game_name` and this package before publishing.

## The game

- **Wheel**: 54 segments. `x1` 19, `x2` 12, `x5` 6, `x10` 4, `plinko` 4, `wheel` 3, `chest` 3,
  `tower` 3. Layout in `SEGMENT_LAYOUT` (rooms never adjacent, Plinko on the quarter points).
- **Numbers** pay n:1 (x1 returns 2x the chip).
- **Top Slot**: before each spin one spot may be paired with a multiplier from
  `2 3 4 5 7 10 15 20 25 50`. If the wheel then lands on that spot, a number's n:1 payout is
  multiplied, a room's result is multiplied. Otherwise nothing happens.
- **Rooms**, each a weighted table of gross multipliers on the chip:
  Plinko 13 slots (4x–400x, binomial landing weights), Lucky Wheel 36 wedges (2x–200x),
  Treasure Chest 12 chests (2x–250x), Dragon Tower 10 floors (2x–250x).

## Bet modes (10)

A ticket covers a fixed set of spots at ONE chip each; `cost` = spots covered, `amount` = chip.

| Mode | Covers | Cost | Max win (x chip) |
| --- | --- | --- | --- |
| `x1` `x2` `x5` `x10` | that number | 1 | 51 / 101 / 251 / 501 |
| `plinko` `wheel` `chest` `tower` | that room | 1 | 20,000 / 10,000 / 12,500 / 12,500 |
| `bonuses` | all four rooms | 4 | 20,000 |
| `full_board` | all eight spots | 8 | 20,000 |

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

The outcome space (segment x Top Slot entry x room outcome) is small — **14,580 outcomes** — so
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

- Plinko's 400x top under a 50x Top Slot puts the 20,000x max win at ~1 in 113 million, below
  Stake's 1-in-20-million achievability floor for an advertised max win. Cap Plinko's top value
  or raise its weight before publishing.
- Room tables, Top Slot reel weights and the 4/3/3/3 room split are first-pass; three of the
  rooms are placeholders for games still being designed.
- No DOUBLE / rescue mechanics in any room yet.
