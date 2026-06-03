One-Eyed Willy's Plinko (one_eyed_willys_plinko)
================================================

Math for stake-web-sdk apps/plinko. Book events: plinkoDrop, setTotalWin, finalWin.
Package folder: games/crimson_plinko (make run GAME=crimson_plinko).

Setup (repo root):
  make setup

Run simulations + configs:
  make run GAME=crimson_plinko
  (run.py rebuilds publish_files/books_base.jsonl.zst from books_base.json + LUT)

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
                                                                                                                                                                                                                                                                                                                