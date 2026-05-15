Crimson Plinko (crimson_plinko)
=============================

Math for stake-web-sdk apps/plinko. Book events: plinkoDrop, setTotalWin, finalWin.

Setup (repo root):
  make setup

Run simulations + configs:
  make run GAME=crimson_plinko

Outputs:
  games/crimson_plinko/library/books/books_base.jsonl
  games/crimson_plinko/library/publish_files/  (upload to Stake Engine)
  games/crimson_plinko/library/configs/config_fe_crimson_plinko.json

RGS / local dev:
  - gameID must be crimson_plinko (matches apps/plinko/src/game/config.ts)
  - Publish library/publish_files via Stake Engine ACP
  - Point apps/plinko dev URL at your RGS session

Storybook sample books:
  node ../../stake-web-sdk/apps/plinko/scripts/import-math-books.mjs

See INTEGRATION.md in this folder.
