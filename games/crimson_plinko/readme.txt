One-Eyed Willy's Plinko (one_eyed_willys_plinko)
================================================

Math for stake-web-sdk apps/plinko. Book events: plinkoDrop, spinMeter, bonusMeter,
freeSpinTrigger, bonusRoulette, bonusRound, setTotalWin, finalWin.
Feature math (meters, wheels, bonus level-up) lives in game_calculations.py; tunables and
the bonus level-up ball table (BONUS_LEVEL_BALLS) in plinko_data.py. See INTEGRATION.md.
Package folder: games/crimson_plinko (make run GAME=crimson_plinko).

Setup (repo root):
  make setup

Run simulations + configs:
  make run GAME=crimson_plinko
  (run.py rebuilds publish_files/books_base.jsonl.zst from books_base.json + LUT)

Stake ACP shows "no change to publish" when upload hashes match the version already live.
After math edits you must re-run sims (not only sync) and upload ALL of publish_files/:
  index.json, lookUpTable_base_0.csv, books_base.jsonl.zst
Upload under Math / books (not Front End). Verify books_base.jsonl.zst SHA changed in
library/configs/config.json before publishing.

Balls per drop:
  RGS bet modes (use `/wallet/play` `mode`, not meta alone):
    onedrop (1 ball), tendrop (10), twentydrop (20), fiftydrop (50)
  Criteria in books: basegame_balls_1 / _10 / _20 / _50
  Optional play meta still mirrors distribution conditions (row_count, etc.).

Outputs:
  games/crimson_plinko/library/books/books_base.json
  games/crimson_plinko/library/publish_files/  (upload entire folder to Stake Engine)
  games/crimson_plinko/library/configs/config_fe_one_eyed_willys_plinko.json

RGS / local dev:
  - gameID must be one_eyed_willys_plinko (matches apps/plinko/src/game/config.ts)
  - providerName: casino_tv
  - Publish library/publish_files via Stake Engine ACP
  - Point apps/plinko dev URL at your RGS session

Storybook sample books:
  node ../../stake-web-sdk/apps/plinko/scripts/import-math-books.mjs

See INTEGRATION.md in this folder.


PLINKO_BOOKS_COMPRESSION=1 make run GAME=crimson_plinko