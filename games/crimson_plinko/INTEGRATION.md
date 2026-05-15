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
| `plinkoDrop` | Multi-ball drop; `outcomes[].rateIndex` is slot index |
| `setTotalWin` | Running win (amount × 100, SDK convention) |
| `finalWin` | Round payout |

Bonus events (`bonusMeter`, `bonusRoulette`, `freeSpinTrigger`) are client/UI flows; add math distributions later if needed.
