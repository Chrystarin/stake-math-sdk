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
| `bonusRound` | Authoritative bonus balls (`outcomes[]`, `level`, optional `ballsPlayed` for resume) |
| `freeSpinTrigger` | Free-spin wheel segment (`segment` label e.g. `5X`/`BONUS`, `multiplier`, authoritative `amount` = round drop win × segment multiplier in **×100 currency units at book stake**, same encoding as `finalWin`). **Wallet payout is in book `payoutMultiplier` / `finalWin` — settled by RGS `/wallet/end-round`, not `/bet/action`.** |
| `setTotalWin` | Running win (amount × 100, SDK convention) |
| `finalWin` | Round payout |

Meter fill chances and feature triggers are authored in math; the client animates flags from `outcomes`, plays feature book events, and runs `bonusRound` balls one at a time before settlement.

**Publish books:** `spinMeterStart` / `bonusMeterStart` on `plinkoDrop` echo distribution `conditions` for the served stratum (`spin_meter_mid` / `high` / `full` per balls tier). Live RGS must select a book whose `spin_meter_start` matches play `meta` when the session meter is partially filled; otherwise `freeSpinTrigger` and combined payout will be missing from the book.

## Session meter persistence

## Balls per drop (RGS bet modes)

Stake Engine selects books by **`/wallet/play` `mode`**, not play `meta` alone. One published mode per tier:

| UI balls | Play `mode` | Book criteria |
|----------|-------------|---------------|
| 1 | `baseone` | `basegame_balls_1` |
| 10 | `baseten` | `basegame_balls_10` |
| 20 | `basetwenty` | `basegame_balls_20` |
| 50 | `basefifty` | `basegame_balls_50` |

The web client sets `stateBet.activeBetModeKey` from the UI tier before each play (`plinkoBetMode.ts`).

Optional play `meta` still mirrors distribution `conditions` (`row_count`, `balls_per_drop`, …) for forward compatibility.

Regenerate books after math changes: `make run GAME=crimson_plinko`, then `pnpm run sync-math-books` in `apps/plinko`.

## Stateful bonus round

When a meter or free-spin `BONUS` segment triggers, the book emits `bonusRoulette` then `bonusRound` with precomputed `outcomes`. The round stays **active** on RGS until the player finishes those balls; `finalWin` / `end-round` run after the client completes the feature. Resume via `authenticate.round` with `active: true` and partial `state`.
