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

Check / re-tune RTP before a publish run:
  env/Scripts/python.exe games/crimson_plinko/rtp_audit.py [N]
  Reads all 8 modes to +-0.01-0.03% and prints the quota / peg_hit_prob each one needs to
  land on TARGET_RTP. Use THIS to solve a lever -- measure_tuning_capped.py and
  verify_buybonus.py average sampled payouts, and the board's 100x corners leave ~0.2% of
  noise on their reads, which is enough to mis-set the low tiers past the 0.50% cross-mode
  RTP limit. Sim counts in run.py are also a compliance input (see the note there).

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

  ^ REQUIRED for a publish build. The sim counts in run.py are sized so each mode's LUT RTP
  carries <=~0.10% of sampling error (Stake grades RTP off the LUT and enforces a 0.50%
  cross-mode limit), which puts onedrop at 9.6M books -- ~6GB as an uncompressed .json, and
  that format is one JSON array with no line structure, so the publish-sync step has to
  json.load it whole and will OOM. The compressed books are line-delimited and stream.
  For local dev / storybook samples keep the uncompressed default and set PLINKO_SIM_DIV.

Publish limits (ACP rejects the upload outright if either is broken):
  - <= 10,000,000 results PER MODE, else ERR_MATH_OUTSIDE_RANGE "Too many simulations!".
    onedrop is the only mode anywhere near it; keep it at 9.6M.
  - cross-mode RTP spread <= 0.50%. See rtp_audit.py and the sizing note in run.py.