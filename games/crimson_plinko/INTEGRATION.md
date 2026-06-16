# One-Eyed Willy's Plinko — Math SDK ↔ Web SDK

## Game ID

Both sides use **`one_eyed_willys_plinko`** / provider **`casino_tv`**:

- Math: `games/crimson_plinko/game_config.py` (package folder `crimson_plinko`; run via `make run GAME=crimson_plinko`)
- Web: `apps/plinko/src/game/config.ts`

## Generate math

```bash
cd stake-math-sdk
make setup
make run GAME=crimson_plinko
```

Use `compression = True` in `run.py` before publishing to RGS.

## Publish to Stake Engine

Upload **all three** files from `games/crimson_plinko/library/publish_files/` via ACP (Math / books, not Front End):

- `index.json`
- `lookUpTable_base_0.csv`
- `books_base.jsonl.zst`

The RGS `play/` response `state` array must match book `events` from math (same as `apps/lines`).

### "No change to publish"

Stake compares SHA-256 hashes of uploaded files to the version already deployed. You will see **no change** when:

1. **`make run GAME=crimson_plinko` was not re-run** after editing math — `publish_files/` is unchanged.
2. **Only payout logic changed** but no book IDs / LUT weights changed (e.g. no books contained `freeSpinTrigger` before stratified `spin_meter_start` distributions were added).
3. **Wrong upload target** — front-end `apps/plinko/build/` is separate from math `publish_files/`.
4. **Incomplete upload** — missing `books_base.jsonl.zst` (required by `index.json`).

After `make run`, confirm `library/configs/config.json` → `bookShelfConfig[0].booksFile.sha256` differs from the last published value, then upload and publish math again.

## Run web client

```bash
cd stake-web-sdk
pnpm install
pnpm run dev --filter=plinko
```

Open with Stake Engine session query params (`sessionID`, `rgs_url`, …) so `Authenticate` succeeds.

## Storybook fixtures

After generating books:

```bash
cd stake-web-sdk/apps/plinko
node scripts/import-math-books.mjs
pnpm run storybook
```

Imports the first N books from math `library/books/books_base.jsonl` into `src/stories/data/`.

## Book event contract

| Event | Purpose |
|-------|---------|
| `plinkoDrop` | Multi-ball drop; `outcomes[]` includes `rateIndex`, `hitBonusPeg`, `hitSpinSlot`; optional `spinMeterStart`, `bonusMeterStart`, `bonusLevelStart` for session carry-over |
| `bonusMeter` | Bonus meter value after a coin-peg hit (`value`, `level`) |
| `bonusRoulette` | Bonus wheel award (`freeBalls`) — presentation before `bonusRound` |
| `bonusRound` | Authoritative bonus balls for one level (`outcomes[]`, `level`, optional `ballsPlayed` for resume). Nested level-ups emit **one `bonusRound` per level** with increasing `level`; the client shows a level-up between them |
| `freeSpinTrigger` | Free-spin wheel segment (`segment` label e.g. `5X`/`BONUS`, `multiplier`, authoritative `amount` = round drop win × segment multiplier in **×100 currency units at book stake**, same encoding as `finalWin`). **Wallet payout is in book `payoutMultiplier` / `finalWin` — settled by RGS `/wallet/end-round`, not `/bet/action`.** |
| `setTotalWin` | Running win (amount × 100, SDK convention) |
| `finalWin` | Round payout |

Meter fill chances and feature triggers are authored in math; the client animates flags from `outcomes`, plays feature book events, and runs `bonusRound` balls one at a time before settlement.

**Payout is authoritative and consistent.** `finalWin` = base drop win + every `bonusRound` ball + free-spin `NX` scaling. The client animates the **exact** `outcomes` from the book (`game/gameOrchestrator.ts:startAuthoritativeBonusRound`, `PlinkoBoard.svelte:bonusBallDrop`) — it never rolls its own dice — so the on-screen total always equals the wallet payout. `publish_verify.find_feature_payout_mismatches` re-derives the displayed total from each book's events and fails the build on any mismatch.

**Publish books:** `spinMeterStart` / `bonusMeterStart` on `plinkoDrop` echo distribution `conditions` for the served stratum (`spin_meter_mid` / `high` / `full`, `bonus_meter_mid` / `high` / `full`, per balls tier). Live RGS must select a book whose `spin_meter_start` / `bonus_meter_start` matches play `meta` when the session meter is partially filled; otherwise `freeSpinTrigger` / `bonusRoulette` and combined payout will be missing from the book.

## Feature tunables (single source of truth)

All in `plinko_data.py`, mirrored to the FE config by `run.py:write_plinko_fe_config` (keys: `spinMeterMax`, `bonusMeterMax`, `bonusPegHitProb`, `freeSpinSegments`, `bonusWheelFreeBalls`, `bonusLevelBalls`, `meterTierConfig`). The client mirrors `BONUS_LEVEL_BALLS` in `apps/plinko/src/game-logic/constants.ts`.

| Tunable | Default | Meaning |
|---------|---------|---------|
| `SPIN_METER_MAX` / `BONUS_METER_MAX` | 10 / 20 | Pocket / coin-peg hits to fill a meter |
| `BONUS_PEG_HIT_PROB` | 0.14 | Per-ball chance to hit a bonus (coin) peg |
| `FREE_SPIN_SEGMENTS` | `2X 0.5X 1X 5X 10X BONUS 20X 15X` | Free-spin wheel; `NX` multiplies the round drop win, `BONUS` chains into a bonus round |
| `BONUS_WHEEL_FREE_BALLS` | `100 20 50 50 50 80 20 20` | Bonus wheel entry free balls (level 1) |
| `BONUS_LEVEL_BALLS` | `{2:20,3:30,4:50,5:75,6:100,7:150,8:200,9:300}` | Extra balls when the bonus meter re-fills during a round (level-up) |

Weights are uniform placeholders — **tune RTP** in `optimization_program` / by reweighting `FREE_SPIN_SEGMENTS`, `BONUS_WHEEL_FREE_BALLS`, and the `_FEATURE_STRATA` quotas in `game_config.py`.

## Bonus level-up (in `game_calculations.simulate_bonus_round`)

Level 1 entry balls come from the bonus wheel. While playing a level's balls, each `hitBonusPeg` advances an in-round bonus meter; every re-fill levels up (max level 9), awards `bonus_level_balls(level)` more balls, and emits another `bonusRound`. The accumulated win across all levels is added to `finalWin`; the client pays out when no more level-ups remain.

## Session meter persistence

Each book is one bet. Cross-bet meter carry-over relies on RGS selecting a stratum book whose `spin_meter_start` / `bonus_meter_start` matches the player's running meter, sent as play `meta` (`game/plinkoSessionMeters.ts:buildBetMetaPlayConditions`). `game_config.py` publishes `basegame` + `spin_meter_{mid,high,full}` + `bonus_meter_{mid,high,full}` strata per tier (see `_FEATURE_STRATA`). If RGS cannot match a stratum, the served book is still authoritative for that bet (features just won't carry across bets).

## Balls per drop (RGS bet modes)

Stake Engine selects books by **`/wallet/play` `mode`**, not play `meta` alone. One published mode per tier:

| UI balls | Play `mode` | Book criteria |
|----------|-------------|---------------|
| 1 | `baseone` | `basegame_balls_1` |
| 10 | `baseten` | `basegame_balls_10` |
| 20 | `basetwenty` | `basegame_balls_20` |
| 50 | `basefifty` | `basegame_balls_50` |

Each mode's LUT also contains the meter-start strata (`spin_meter_full_balls_10`, `bonus_meter_full_balls_10`, …) — the `basegame_balls_X` row above is just the zero-meter stratum.

The web client sets `stateBet.activeBetModeKey` from the UI tier before each play (`plinkoBetMode.ts`).

Optional play `meta` still mirrors distribution `conditions` (`row_count`, `balls_per_drop`, `spin_meter_start`, `bonus_meter_start`, …) for stratum selection.

Regenerate books after math changes: `make run GAME=crimson_plinko`, then `pnpm run sync-math-books` in `apps/plinko`.

## Stateful bonus round

When a meter or free-spin `BONUS` segment triggers, the book emits `bonusRoulette` then `bonusRound` with precomputed `outcomes`. The round stays **active** on RGS until the player finishes those balls; `finalWin` / `end-round` run after the client completes the feature. Resume via `authenticate.round` with `active: true` and partial `state`.
