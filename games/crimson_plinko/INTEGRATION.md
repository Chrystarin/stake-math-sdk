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

**RTP is tuned for compliance (90.0%–96.70%, cross-mode variance < 1%).** Every mode reads ~`TARGET_RTP` (95.7%, `plinko_data.py`):
- **Base modes** pay the flat per-ball board EV (`BOARD_SLOT_MULTIPLIERS`, ~0.957/ball) with **no in-drop feature** (see *Feature triggering* below), so all four tiers land at the same RTP regardless of ball count.
- **Trigger modes** are EV-priced like buy-feature modes: `run.py:set_trigger_mode_index_costs` sets each one's `index.json` cost = `mean_payout / TARGET_RTP`, so the Stake math summary reads them at ~`TARGET_RTP` too (they stay free for players — `config.json` cost is `TRIGGER_MODE_COST`).

To re-tune, change `BOARD_SLOT_MULTIPLIERS` (base RTP) and/or `TARGET_RTP`; `FREE_SPIN_SEGMENTS` / `BONUS_WHEEL_FREE_BALLS` only change the *feel* of the feature (their EV is absorbed by the trigger-mode price).

## Bonus level-up (in `game_calculations.simulate_bonus_round`)

Level 1 entry balls come from the bonus wheel. While playing a level's balls, each `hitBonusPeg` advances an in-round bonus meter; every re-fill levels up (max level 9), awards `bonus_level_balls(level)` more balls, and emits another `bonusRound`. The accumulated win across all levels is added to `finalWin`; the client pays out when no more level-ups remain.

## Session meter persistence

Each book is one bet. The client persists the running spin / bonus meters across bets
(`game/plinkoSessionMeters.ts`) and applies each book's meter events relative to the carried value,
so the meters accumulate instead of resetting. The meter value rides along on play `meta`
(`buildBetMetaPlayConditions`), but **production RGS does not select books by `meta`** (selection is
weighted-random per `mode`), so meta is best-effort / for force-replay only.

## Feature triggering — dedicated trigger modes

Because RGS honors `mode` (not `meta`), a full meter triggers its feature via a **dedicated mode**,
not by hoping RGS serves a meter-full stratum book. When the client's spin (or bonus) meter fills,
it auto-places a bet in the matching trigger mode; that mode's books **always** emit the feature,
so RGS computes the payout (no client-side trigger or payout). The triggering meter then resets.

| When | Mode (per tier) | Book always emits | Condition flag |
|------|-----------------|-------------------|----------------|
| Spin meter full | `freespinone/ten/twenty/fifty` | `freeSpinTrigger` (+ bonus on `BONUS` segment) | `force_freespin` |
| Bonus meter full | `bonusone/ten/twenty/fifty` | `bonusRoulette` + `bonusRound`(s) | `force_bonus` |

- **Cost / free:** trigger modes simulate at the tier cost (so RTP math never divides by zero) and
  are **published at `TRIGGER_MODE_COST` (0 = free) in `config.json`** via
  `run.py:set_trigger_mode_costs_free` — RGS debit = `amount × 0` = 0 while payout still =
  `amount × payoutMultiplier`. **If your RGS rejects a zero-cost play, set `TRIGGER_MODE_COST`
  (plinko_data.py) to a paid value and mirror it in `apps/plinko/src/game/config.ts`.**
- **Math-summary cost (separate from the player debit):** `run.py:set_trigger_mode_index_costs`
  rewrites each trigger mode's `index.json` cost to `mean_payout / TARGET_RTP` so the Stake math
  tool scores them at ~`TARGET_RTP` (a forced feature pays many ×, so at the raw tier cost it would
  read as thousands-of-percent RTP and blow up the cross-mode variance check). This is metadata for
  the math eval only; it does **not** change what RGS charges (that's `config.json`, still 0).
- Client wiring: `plinkoBetMode.ts:plinkoActiveBetMode` (mode selection), `gameOrchestrator.ts:maybeAutoFireFeatureTrigger` (auto-fire when full + idle).

Base modes run with `suppress_features=True`: a meter can **fill** within a base book (emitting
`spinMeter`/`bonusMeter`, kept book-authoritative) but the feature is **never fired in-drop** — the
full meter carries over and the trigger mode fires it on the next bet. This keeps base RTP at the
flat per-ball board EV on every tier; the `_FEATURE_STRATA` meter-start strata are now only for
meter-state variety in the published books (RTP-neutral).

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
