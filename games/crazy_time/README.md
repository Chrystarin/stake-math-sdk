# Crazy Time (working title) — Math SDK

Stake Engine math model for a single-player money-wheel show modelled on Evolution's Crazy Time.
The matching web client lives in the separate `stake-web-sdk` repo at `apps/crazy-time/`.

**The title is a placeholder** ("Crazy Time" is Evolution's trademark). Rename `game_id`,
`game_name` and this package before publishing.

## The game

- **Wheel**: 54 segments. `x1` 19, `x2` 12, `x5` 6, `x10` 4, `chest` 4, `piratePlinko` 3,
  `oceanVoyage` 3, `bonusWheel` 3. Every room has at least three segments so that a chip on any
  room ALONE pays at least once in 20 spins (Stake's floor for a base mode; 3 of 54 is 1 in 18).
  Crazy Time's own 4/2/2/1 split was used before this and left its three rarer rooms
  company-only. Layout in `SEGMENT_LAYOUT`: thirteen rooms cycling chest → Plinko → Wheel →
  Voyage, never adjacent, three numbers between any two (four in two places, opposite each
  other); x10 never next to x10.
- **Numbers** pay n:1 (x1 returns 2x the chip).
- **Top Slot**: before each spin one spot may be paired with a multiplier from
  `2 3 4 5 7 10 15 20 25 50`. If the wheel then lands on that spot, a number's n:1 payout is
  multiplied, a room's result is multiplied. Otherwise nothing happens.
- **Rooms**, each a weighted table of gross multipliers on the chip:
  Pirate Plinko 13 slots (5x–400x, binomial landing weights), Bonus Wheel 36 wedges (2x–1,000x),
  Treasure Chest 12 chests (2x–250x), Ocean Voyage 10 depths (2x–400x). A room's table is sized
  to its segment count: a 3-segment room may return 17.4x per visit (Top Slot included), the
  4-segment chest 13.1x. The Bonus Wheel's 1,000x is a **jackpot sliver**, a quarter the width of
  the other 35 wedges (`WHEEL_WIDTHS`), so it lands 1 in 141 visits rather than 1 in 36: that is
  what keeps the game's 50,000x on a room with three segments, and the wheel is drawn to the same
  widths the book weighs.

## Bet modes (255): one per combination of spots

A bet covers any set of spots at ONE chip each; `cost` = spots covered, `amount` = chip. Every
non-empty combination of the eight spots is a mode, named by the spots' codes in SPOTS order
(`SPOT_CODE`: x1 x2 x5 x10 pp bw tc ov), e.g. `x1`, `pp_bw_tc_ov`, `x1_x2_x5_x10_pp_bw_tc_ov`.

| Combination | Cost | Max win (x chip) |
| --- | --- | --- |
| a single number | 1 | 51 / 101 / 251 / 501 |
| a single room | 1 | 12,500 (chest) / 20,000 (Plinko, Voyage) / 50,000 (Wheel) |
| anything containing the Bonus Wheel | n | 50,000 |
| anything containing Pirate Plinko or Ocean Voyage but not the Bonus Wheel | n | 20,000 |

All 255 are published: every spot covers at least 3 of the 54 segments, so even a room alone
pays at least once in 20 spins (`MIN_HIT_RATE`). `UNPUBLISHED_ALONE` is asserted empty and stays
as the guard, should the rim ever change again.

`compliance()` runs at import and asserts, for every mode: RTP in Stake's band and within
0.01% of the target (zero cross-mode spread), hit rate >= 1 in 20, and the advertised max win
reached at >= 1 in 20,000,000 (`MAX_WIN_FLOOR`). The binding max-win case is Ocean Voyage's 400x
depth under a 50x Top Slot (1 in 14.2 million); Pirate Plinko's 400x edges are next (1 in 10.7
million), which is why `PLINKO_TABLE` adds a flat weight floor to the binomial landing weights;
the Bonus Wheel's 50,000x lands 1 in 9.5 million.

## Buy-bonus modes (5)

| Mode | Opens | Price (chips) | Books | Max win |
| --- | --- | --- | --- | --- |
| `buy_any` | a room, weighted by segments (chest 4 / plinko 3 / voyage 3 / wheel 3) | 16.62 | 10,854 | 50,000 |
| `buy_tc` | Treasure Chest | 13.5 | 3,564 | 12,500 |
| `buy_pp` | Pirate Plinko | 18 | 3,159 | 20,000 |
| `buy_ov` | Ocean Voyage | 18 | 2,430 | 20,000 |
| `buy_bw` | Bonus Wheel | 18 | 1,701 | 50,000 |

A buy goes straight into the room at the room's natural odds of also carrying a Top Slot
multiplier. Price = rooms x 54 / segments covered (`buy_price`): each spot returns the target on
one chip, so a room's mean per hit is RTP x 54 / segments and that price returns the target again;
the any-bonus price is what chasing the rooms costs naturally. Books are the base enumeration cut to
the bought rooms' segments, so a buy book still carries a `wheelSpin` onto the room for the
presentation. Flagged `is_buybonus` (no hit-rate floor; RTP band, spread and max-win floor still
checked in `compliance()`).

## RTP: 96.7% on every mode

Each spot is tuned to `TARGET_RTP` on its own with the Top Slot pairing weight `q[spot]` as the
lever (`crazy_time_data._solve_pairing`). For a number paying n:1

    P(hit) * (1 + n * (1 + q * (E[m] - 1))) = 0.967

and for a room with mean multiplier R

    P(hit) * R * (1 + q * (E[m] - 1)) = 0.967

Because every spot returns 96.7%, every combination does too (linearity), so all 255 modes
certify at one number.

## How the books are made

The outcome space (segment x Top Slot entry x room outcome) is small — **14,175 outcomes** — so
every mode's books list each outcome exactly once (`decode_outcome(sim)`), and the lookup table
carries each outcome's **exact probability weight** (`run.py: write_exact_weights`, run after
`create_books`). No RNG, no optimizer; the served RTP is the analytic value. All 255 modes share
the outcome list and differ only in the payout column, so the publish is about 130 MB.

Book events per round: `topSlot`, `wheelSpin`, an optional room event (`piratePlinkoRoom` /
`bonusWheelRoom` / `chestRoom` / `oceanVoyageRoom`, always authored when the wheel lands on a
room, with `covered` telling the client whether the ticket was in it), `winInfo`, `setTotalWin`,
`finalWin`. Room events carry everything the client draws (board values, drop zone, wedge, chest
decoys, dive path), all derived deterministically from the simulation index.

## Files

```
crazy_time_data.py   wheel, tables, Top Slot solver, enumeration, payout, presentation extras
game_config.py       GameConfig + 255 combination BetModes (is_feature) + 5 buy BetModes (is_buybonus)
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

- Room tables and Top Slot reel weights are first-pass; three of the rooms are placeholders for
  games still being designed.
- No DOUBLE / rescue mechanics in any room yet.
