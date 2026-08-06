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
| `bonusRound` | Authoritative bonus balls for one level (`outcomes[]`, `level`, `levelupPegs` = coin-peg hits needed to LEAVE this level, optional `ballsPlayed` for resume). Nested level-ups emit **one `bonusRound` per level** with increasing `level`; the client shows a level-up between them, and sizes each level's energy bar from `levelupPegs` |
| `freeSpinTrigger` | Free-spin wheel segment (`segment` label e.g. `5X`/`BONUS`, `multiplier`, authoritative `amount` = round drop win × segment multiplier in **×100 currency units at book stake**, same encoding as `finalWin`). **Wallet payout is in book `payoutMultiplier` / `finalWin` — settled by RGS `/wallet/end-round`, not `/bet/action`.** |
| `setTotalWin` | Running win (amount × 100, SDK convention) |
| `finalWin` | Round payout |

Meter fill chances and feature triggers are authored in math; the client animates flags from `outcomes`, plays feature book events, and runs `bonusRound` balls one at a time before settlement.

**Payout is authoritative and consistent.** `finalWin` = base drop win + every `bonusRound` ball + free-spin `NX` scaling. The client animates the **exact** `outcomes` from the book (`game/gameOrchestrator.ts:startAuthoritativeBonusRound`, `PlinkoBoard.svelte:bonusBallDrop`) — it never rolls its own dice — so the on-screen total always equals the wallet payout. `publish_verify.find_feature_payout_mismatches` re-derives the displayed total from each book's events and fails the build on any mismatch.

**Publish books:** `spinMeterStart` / `bonusMeterStart` on `plinkoDrop` echo the distribution `conditions`, which are now a **fixed per-tier constant** (`scaled_spin_meter_start` / `scaled_bonus_meter_start`), not a stratum selector. Book selection therefore never has to match a carried meter value — any book of the right `mode` is servable at any time, and every feature it can pay is already inside it.

## Feature tunables (single source of truth)

> ⚠️ The dedicated-trigger-mode and cross-bet-meter design this file used to document is **gone** —
> features are folded in-drop (see *Feature triggering*). Individual **values** below can still lag the
> math; `plinko_data.py` is the source of truth, and for bonus mechanics/probabilities see
> `stake-web-sdk/apps/plinko/docs/` — `bonus-mode.md` (mechanics), `bonus-values.md` (every value
> and its derived probability, per mode).

All in `plinko_data.py`, mirrored to the FE config by `run.py:write_plinko_fe_config` (keys: `spinMeterMax`, `bonusMeterMax`, `bonusPegHitProb`, `bonusPegHitProbByMode`, `bonusLevelupPegs`, `freeSpinSegments`, `bonusWheelFreeBalls`, `bonusLevelBalls`, `bonusMeterTier`, `spinMeterTier`). The client mirrors `BONUS_LEVEL_BALLS` and `BONUS_LEVELUP_PEGS` in `apps/plinko/src/game-logic/constants.ts`.

| Tunable | Default | Meaning |
|---------|---------|---------|
| `SPIN_METER_MAX` / `BONUS_METER_MAX` | 10 / 20 | Pocket / coin-peg hits to fill a meter |
| `BONUS_PEG_HIT_PROB` | 0.18 | Per-ball chance to hit a bonus (coin) peg — the DEFAULT |
| `BONUS_PEG_HIT_PROB_BY_MODE` | base 0.18; buys 0.0447 / 0.0292 / 0.0252 / 0.0283 | PER-MODE coin-peg chance, published on each distribution's `peg_hit_prob` condition. The RTP lever that lets every mode share one level-up ladder |
| `BONUS_LEVELUP_PEG_HITS_BY_LEVEL` | `5 8 14 25 42 71 121 205` | Coin-peg hits to leave level L. **Identical in every mode** |
| `FREE_SPIN_SEGMENTS` | `2X 0.5X 1X 5X 10X BONUS 20X 15X` | Free-spin wheel; `NX` multiplies the round drop win, `BONUS` chains into a bonus round |
| `BONUS_WHEEL_FREE_BALLS` | `100 90 80 70 60 50 40 30 20` | Bonus wheel entry free balls (level 1) |
| `BONUS_LEVEL_BALLS` | `{2:20,3:30,4:50,5:75,6:100,7:150,8:200,9:300}` | Extra balls when the bonus meter re-fills during a round (level-up) |

**RTP is tuned for compliance (90.0%–96.70%, cross-mode variance < 1%).** Every mode reads ~`TARGET_RTP` (95.7%, `plinko_data.py`):
- **Feature tiers (10 / 20 / 50)** pay the shared board's `0.89635×`/ball (`BOARD_SLOT_MULTIPLIERS`); the free in-drop features — folded into the same book (see *Feature triggering* below) — make up the remaining ~6 points to `TARGET_RTP` on every tier.
- **`onedrop`** is feature-free, so its RTP *is* its board: `COEFFICIENT_SETS_BY_BALLS[1]` at `0.95396×`/ball (`declared_rtp_for_balls(1)`), clear of the 90% floor without any feature funding.
- **Buy-bonus modes** are EV-priced: each tier's `cost` (80 / 100 / 150 / 250 × bet-per-ball) is tuned against its fixed `entry_balls` so the mode also lands at ~`TARGET_RTP`.

To re-tune, change `BOARD_SLOT_MULTIPLIERS` (base EV) and/or `TARGET_RTP`, then re-solve the per-tier `BONUS_IN_DROP_RATE` quotas with `measure_tuning_capped.py`. Changing `FREE_SPIN_SEGMENTS` / `BONUS_WHEEL_FREE_BALLS` / `BONUS_LEVEL_BALLS` moves real EV now that the features are free and folded — the quota (and, if it bottoms out at zero, the tier's `BONUS_METER_TIER` max) is the lever that absorbs it.

## Bonus level-up (in `game_calculations.simulate_bonus_round`)

Level 1 entry balls come from the bonus wheel (or, for a buy, the tier's fixed `entry_balls`). While playing a level's balls, each `hitBonusPeg` advances an in-round bonus meter; reaching `bonus_levelup_pegs(level)` levels up (max level 9), awards `bonus_level_balls(level)` more balls, and emits another `bonusRound`. The threshold ESCALATES per level and is the SAME in every mode — a buy is gated by its lower `peg_hit_prob`, not by a taller bar. The accumulated win across all levels is added to `finalWin`; the client pays out when no more level-ups remain.

## Session meter persistence

**The math is stateless — there is no cross-bet meter.** Each book is one bet: both meters reset to
their fixed per-tier start (`scaled_spin_meter_start` / `scaled_bonus_meter_start`) at the top of every
drop and must fill within that drop to fire. A book never depends on, or carries out, meter state.

The client's `game/plinkoSessionMeters.ts` keeps its own per-tier running value for **display
continuity only** — the book is authoritative for every trigger and payout, so that store cannot
create or suppress a feature. The value still rides along on play `meta`
(`buildBetMetaPlayConditions`), but **production RGS does not select books by `meta`** (selection is
weighted-random per `mode`), so meta is best-effort / for force-replay only.

## Feature triggering — folded, in-drop (Option A)

Both features resolve **inside the base book that paid for them**. There are no dedicated trigger
modes, no second auto-placed bet, and no cross-bet meter state — each book is one self-contained bet,
and both meters reset every drop.

| Feature | Meter (`plinko_data`) | Fires when | Book emits |
|---------|----------------------|------------|------------|
| Free spin | `SPIN_METER_TIER` — max 6 / 10 / 21, start 0 / 1 / 5 | balls landing in the centre SPIN pocket fill it to `max` **within this drop** | `freeSpinTrigger` (chains `bonusRoulette` + `bonusRound` on the `BONUS` segment) |
| Bonus | `BONUS_METER_TIER` — max 7 / 9 / 17, start **0 on every tier** | balls striking the gold coin pegs fill it to `max` **within this drop** | `bonusRoulette` + one `bonusRound` per level |

Gated by the `spin_in_drop` / `bonus_in_drop` conditions — both off on `onedrop`, which has neither
feature. The whole feature (including a multi-level bonus) resolves in the same book, so one round
settles `drop + free spin + bonus` in a single `finalWin`.

Each feature tier publishes **two** base distributions:

| Criteria | Quota | Role |
|----------|-------|------|
| `basegame_balls_X` | `1 − BONUS_IN_DROP_RATE[X]` | Normal paid drop; the meter fires the bonus organically when this drop's coin pegs fill it |
| `basegame_bonus_balls_X` | `BONUS_IN_DROP_RATE[X]` — 0.283% / 0.253% / 1.350% | `force_bonus`: a guaranteed bonus, used to fine-tune the tier onto `TARGET_RTP` |

**The quota is not a second trigger path.** The natural fire rate is discrete
(`P(Binomial(balls, peg_hit_prob) ≥ max)`) and can't be dialled onto an exact RTP, so a small share of
books is pre-selected to contain a bonus. Those books do **not** bypass the meter: `gamestate.py`
calls `ensure_coin_pegs_fill_meter`, turning on enough of the drop's `hitBonusPeg` flags — spread
across the drop — that the meter fills 0 → max from **real coin-peg hits** and fires down the ordinary
in-drop path. `hitBonusPeg` is sampled independently of the ball's pocket, so this is EV-neutral on the
drop itself. Every tier with a non-zero quota sets `bonus_in_drop`, so **no published book can carry a
bonus event over a meter that isn't full** — which is exactly what the player-facing rules promise
(`InfoModal.svelte`: "the Bonus meter fills as balls strike the 3 gold coin pegs"). The snap-to-full
branch in `game_calculations.build_feature_meter_events` is an **unreachable** safety net, kept only
for a hypothetical future tier that pairs a quota with `bonus_in_drop=False`.

**Funding.** The shared board pays `0.89635×`/ball; the folded free features lift every feature tier to
`TARGET_RTP` (95.7%). `onedrop` has no features and plays its own board at `0.95396×`/ball.

**Client wiring.** `gameOrchestrator.ts:maybeAutoFireFeatureTrigger` is a retained **no-op** — nothing
auto-fires, the client just animates the book's events. `plinkoBetMode.ts:plinkoActiveBetMode` still
selects the mode from the UI tier, and `isSingleBallMode` independently blocks feature events on
`onedrop`. `suppress_features` survives only as an ignored `build_feature_meter_events` kwarg (kept for
signature stability).

## Balls per drop (RGS bet modes)

Stake Engine selects books by **`/wallet/play` `mode`**, not play `meta` alone. Eight published modes —
one base mode per tier, plus one buy-bonus mode per tier:

| UI balls | Play `mode` | Cost | Book criteria |
|----------|-------------|------|---------------|
| 1 | `onedrop` | 1 | `basegame_balls_1` |
| 10 | `tendrop` | 10 | `basegame_balls_10`, `basegame_bonus_balls_10` |
| 20 | `twentydrop` | 20 | `basegame_balls_20`, `basegame_bonus_balls_20` |
| 50 | `fiftydrop` | 50 | `basegame_balls_50`, `basegame_bonus_balls_50` |

| Buy tier | Play `mode` | Cost (× bet-per-ball) | Entry balls | Book criteria |
|----------|-------------|-----------------------|-------------|---------------|
| Standard | `buystandard` | 80 | 72 | `buybonus_buystandard` |
| Enhanced | `buyenhanced` | 100 | 95 | `buybonus_buyenhanced` |
| Premium | `buypremium` | 150 | 145 | `buybonus_buypremium` |
| Super Fury | `buysuperfury` | 250 | 239 | `buybonus_buysuperfury` |

Buy modes are `bonus_only`: the paid drop is **empty**, the bonus meter enters pre-filled to `max`, and
the bonus starts immediately with the tier's fixed `entry_balls` (in-bonus level-ups add more on top).
Mirror the tier list in `apps/plinko/src/game/plinkoBetMode.ts:BUY_BONUS_TIERS`.

**`onedrop` is FEATURE-FREE.** It is the only mode with a single distribution: `spin_in_drop` and
`bonus_in_drop` are off and its `BONUS_IN_DROP_RATE` is 0, so `game_config.py` omits the
`basegame_bonus_balls_1` stratum entirely (`Distribution` asserts `quota > 0`). An `onedrop` book can
never contain `bonusRoulette` / `bonusRound` / `freeSpinTrigger`, and the client enforces the same rule
independently (`isSingleBallMode` in `apps/plinko/src/game/gameOrchestrator.ts`). Because nothing but the
board pays there, that tier plays its own board (`COEFFICIENT_SETS_BY_BALLS[1]`: center 0.1×, the two
pockets either side 0.3×) for an RTP of ~95.4%, and its advertised max win is the top pocket, 100×.

Those are **all** the criteria a mode publishes — there are no meter-start strata
(`spin_meter_full_balls_10` and friends are gone with the cross-bet meter design).

The web client sets `stateBet.activeBetModeKey` from the UI tier before each play (`plinkoBetMode.ts`).

Optional play `meta` still mirrors distribution `conditions` (`row_count`, `balls_per_drop`, `spin_meter_start`, `bonus_meter_start`, …) for stratum selection.

Regenerate books after math changes: `make run GAME=crimson_plinko`, then `pnpm run sync-math-books` in `apps/plinko`.

## Stateful bonus round

When a meter or free-spin `BONUS` segment triggers, the book emits `bonusRoulette` then `bonusRound` with precomputed `outcomes`. The round stays **active** on RGS until the player finishes those balls; `finalWin` / `end-round` run after the client completes the feature. Resume via `authenticate.round` with `active: true` and partial `state`.
