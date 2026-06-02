# Crimson Plinko — Math SDK ↔ Web SDK

## Game ID

Both sides use **`crimson_plinko`**:

- Math: `games/crimson_plinko/game_config.py`
- Web: `apps/plinko/src/game/config.ts`

## Generate math

```bash
cd stake-math-sdk
make setup
make run GAME=crimson_plinko
```

Use `compression = True` in `run.py` before publishing to RGS.

## Publish to Stake Engine

Upload contents of `games/crimson_plinko/library/publish_files/` via ACP.  
The RGS `play/` response `state` array must match book `events` from math (same as `apps/lines`).

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
| `freeSpinTrigger` | Free-spin wheel segment (`segment` label e.g. `5X`/`BONUS`, `multiplier`, authoritative `amount` = wager × segment) |
| `setTotalWin` | Running win (amount × 100, SDK convention) |
| `finalWin` | Round payout |

Meter fill chances and feature triggers are authored in math; the client animates flags from `outcomes`, plays feature book events, and runs `bonusRound` balls one at a time before settlement.

**Publish books:** `spinMeterStart` / `bonusMeterStart` on `plinkoDrop` are informational for live RGS (session-injected conditions). Lookup-table books are generated with starts at **0** — the web client does not apply them on load; session carry-over uses RGS `meta` + client storage between bets only.

## Session meter persistence

Send current meters on each `play` request via bet `meta` (snake_case or camelCase):

- `spin_meter_start` / `spinMeter`
- `bonus_meter_start` / `bonusMeter`
- `bonus_level_start` / `bonusLevel`

Math reads these from distribution `conditions` before each spin and echoes starting values on `plinkoDrop`. The web client also mirrors progress in `sessionStorage` keyed by `sessionID` for dev/resume.

Regenerate books after math changes: `make run GAME=crimson_plinko`, then `pnpm run sync-math-books` in `apps/plinko`.

## Stateful bonus round

When a meter or free-spin `BONUS` segment triggers, the book emits `bonusRoulette` then `bonusRound` with precomputed `outcomes`. The round stays **active** on RGS until the player finishes those balls; `finalWin` / `end-round` run after the client completes the feature. Resume via `authenticate.round` with `active: true` and partial `state`.
