"""Acceptance gate for a REGENERATED library (DEV TOOL, not published).

Run this after `make run` and BEFORE uploading `publish_files/`. It answers the questions the other
tools don't: `rtp_audit.py` grades the MODEL, `publish_verify` grades payout arithmetic — neither
checks that the library actually contains the rounds the game promises, nor that the CLIENT will play
what the books authored.

Checks, per published mode:

  1. DEEP-BONUS STRATUM PRESENT. At least one book reaching `DEEP_BONUS_TARGET_LEVEL`, and every such
     book settling at exactly that mode's wincap. Without this the top four rungs of the on-screen
     ladder are unreachable again and `InfoModal`'s level table is lying — which is the state the
     library was in before this stratum existed.
  2. THE CLIMB IS MADE OF REAL COIN-PEG HITS. Replays each deep book's walk and asserts every rung was
     reached by `hitBonusPeg` flags actually on the balls, not assigned. This is the compliance claim
     ("the meter fills as balls strike the gold coin pegs"), so it is checked, not assumed.
  3. PER-BATCH SPIN BAR published and MONOTONIC (`bonusRound.spinMeterMax`). A bar that shrinks between
     batches would leave a carry-in above its own max and fire a wheel on the batch's first hit.
  4. CLIENT/BOOK AGREEMENT. Ports the client's in-bonus free-spin meter and asserts the bar completes
     exactly as many times as the book authored `freeSpinTrigger` events. This is the invariant
     `creditInBonusSpinMeter` warns about in DEV; a mismatch means the player sees a full bar with no
     wheel, or a wheel with no bar.
  5. PAYOUT ARITHMETIC via `publish_verify.find_feature_payout_mismatches`.
  6. LEVEL HISTOGRAM, so a re-tune that quietly changes bonus depth is visible.

⚠️ CHECK 4 IS THE ONE THAT HAS ALREADY CAUGHT A REAL BUG. The client reads every event of a round
before the first bonus ball drops, so a later batch's `spinMeter` event used to leave the running max
on the DEEPEST batch's value and early batches could never fill their bar — 1,881 of 8,400 replayed
bonus rounds came up short of the wheels their book had paid for. Keep this check in the loop for any
change to the in-bonus meter on either side.

Run:  python games/crimson_plinko/verify_deep_bonus.py [SAMPLE_BONUS_BOOKS_PER_MODE]
      (default 4000; deep books are always scanned in full — they are far too rare to sample)
"""

import json
import os
import sys
from collections import Counter

import zstandard

from plinko_data import (
    BALLS_PER_DROP_OPTIONS,
    BUY_BONUS_TIER_DEFS,
    DEEP_BONUS_TARGET_LEVEL,
    DEEP_BONUS_TARGET_LEVELS,
    bet_mode_for_balls_per_drop,
    bonus_levelup_pegs,
    bonus_possible_for_balls,
    buy_bonus_mode_name,
    deep_bonus_rate,
    wincap_for_balls,
)
from publish_verify import find_feature_payout_mismatches

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLISH = os.path.join(HERE, "library", "publish_files")


def iter_books(path: str):
    """Stream one book dict at a time from a .jsonl.zst (never holds the multi-GB set)."""
    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as f, dctx.stream_reader(f) as r:
        buf = b""
        while True:
            chunk = r.read(1 << 22)
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                if line.strip():
                    yield line
        if buf.strip():
            yield buf


def replay_client_meter(book: dict) -> tuple[int, int]:
    """(bar completions the CLIENT would make, in-bonus triggers the BOOK authored).

    Ported from apps/plinko gameOrchestrator.ts `registerBonusSpinBatch` / `applyBonusSpinBatch` /
    `ensureBonusSpinBatchMax` / `creditInBonusSpinMeter`, plus the `spinMeter` handler in
    bookEventHandlerMap.ts. The read-ahead is modelled deliberately — see the module docstring.
    """
    events = book.get("events", [])
    state = {"max": 0, "value": 0, "landed": -1}
    starts: list = []
    maxes: list = []
    batches: list = []

    def apply_auth_max(m):
        if m > 0:
            state["max"] = m
            state["value"] = min(state["value"], m)

    def ensure_max(o):
        bm = maxes[o]
        if bm is not None and bm > 0 and state["max"] != bm:
            apply_auth_max(bm)

    def apply_batch(o):
        state["landed"] = o
        ensure_max(o)
        if starts[o] is not None:
            state["value"] = min(state["max"] if state["max"] > 0 else 1, starts[o])

    authored = 0
    for ev in events:
        t = ev.get("type")
        if t == "plinkoDrop":
            apply_auth_max(int(ev.get("spinMeterMax", 0) or 0))
        elif t == "bonusRound":
            st, bm = ev.get("spinMeterStart"), ev.get("spinMeterMax")
            starts.append(None if st is None else max(0, int(st)))
            maxes.append(None if not bm or int(bm) <= 0 else int(bm))
            batches.append(ev.get("outcomes", []))
            if len(starts) == 1:
                apply_batch(0)
        elif t == "spinMeter":
            apply_auth_max(int(ev.get("max", 0) or 0))
        elif t == "freeSpinTrigger" and int(ev.get("level", 0) or 0) > 0:
            authored += 1

    fired = 0
    legacy_fired = False
    for o, outcomes in enumerate(batches):
        for out in outcomes:
            if not out.get("hitSpinSlot"):
                continue
            if o > state["landed"]:
                apply_batch(o)
                legacy_fired = False
            else:
                ensure_max(o)
            legacy = starts[o] is None
            if legacy and legacy_fired:
                continue
            m = state["max"] if state["max"] > 0 else 1
            state["value"] = min(m, state["value"] + 1)
            if state["value"] < m:
                continue
            if legacy:
                legacy_fired = True
            fired += 1
            state["value"] = 0
    return fired, authored


def bonus_rounds(book: dict) -> list[list[dict]]:
    """The book's `bonusRound` events, SPLIT PER BONUS ROUND.

    ⚠️ A BOOK CAN CARRY TWO BONUS ROUNDS — the meter/quota one, plus one chained by the base free-spin
    wheel's BONUS segment (~0.1-0.5% of bonus books). They are independent: each draws its own entry,
    restarts the level ladder at 1 and sizes its own spin bar, so anything that walks levels or bars
    must treat them separately. A `bonusRoulette` event is what opens each one.
    """
    out: list[list[dict]] = []
    for ev in book["events"]:
        if ev["type"] == "bonusRoulette":
            out.append([])
        elif ev["type"] == "bonusRound":
            if not out:
                out.append([])
            out[-1].append(ev)
    return [r for r in out if r]


def climb_is_organic(book: dict, target: int) -> bool:
    """True when some round climbed to `target` with every rung reached by real `hitBonusPeg` flags."""
    for rounds in bonus_rounds(book):
        meter, level = 0, 1
        for e in rounds:
            for out in e["outcomes"]:
                if out.get("hitBonusPeg"):
                    meter += 1
                    if level < DEEP_BONUS_TARGET_LEVEL and meter >= bonus_levelup_pegs(level):
                        meter, level = 0, level + 1
        if level >= target:
            return True
    return False


def modes() -> list[tuple[str, float]]:
    out = []
    for balls in BALLS_PER_DROP_OPTIONS:
        if bonus_possible_for_balls(balls):
            out.append((bet_mode_for_balls_per_drop(balls), wincap_for_balls(balls)))
    for tier in BUY_BONUS_TIER_DEFS:
        out.append((buy_bonus_mode_name(tier["key"]), float(tier["wincap"])))
    return out


def main() -> int:
    sample = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    failures: list[str] = []
    print(f"verify_deep_bonus — target level {DEEP_BONUS_TARGET_LEVEL}, sampling {sample:,} "
          f"bonus books/mode (deep books scanned in full)\n")
    for mode, wincap in modes():
        path = os.path.join(PUBLISH, f"books_{mode}.jsonl.zst")
        if not os.path.exists(path):
            failures.append(f"{mode}: {path} missing — has `make run` finished?")
            print(f"FAIL {mode:>13}  book file missing")
            continue

        deep = 0
        deep_by_level = Counter()
        deep_bad_pay = 0
        deep_inorganic = 0
        levels = Counter()
        sampled = 0
        bar_not_monotonic = 0
        no_bar = 0
        client_mismatch = 0
        pay_sample: list = []
        total_books = 0

        for raw in iter_books(path):
            total_books += 1
            if b'"bonusRound"' not in raw:
                continue
            book = json.loads(raw)
            rounds_split = bonus_rounds(book)
            if not rounds_split:
                continue
            top = max(e["level"] for r in rounds_split for e in r)
            levels[top] += 1

            # Monotonicity is a WITHIN-ROUND property: a second bonus round in the same book restarts
            # the ladder and re-sizes its bar from its own entry, so the concatenation legitimately
            # steps down at the boundary. See `bonus_rounds`.
            for r in rounds_split:
                bars = [e.get("spinMeterMax") for e in r]
                if any(b is None for b in bars):
                    no_bar += 1
                    break
                if bars != sorted(bars):
                    bar_not_monotonic += 1
                    break

            if top in DEEP_BONUS_TARGET_LEVELS:
                deep += 1
                deep_by_level[top] += 1
                # ⚠️ A PUBLISHED book's `payoutMultiplier` is the multiplier x100 (the same integer the
                # LUT's third column and `setTotalWin` carry — see publish_verify._load_book_payouts_*).
                # `GameState.book.payout_multiplier` is the un-scaled float; the x100 happens at
                # serialisation, so a check written against in-memory books passes and then reads every
                # published book as 100x its wincap.
                if abs(float(book["payoutMultiplier"]) / 100.0 - wincap) > 1e-6:
                    deep_bad_pay += 1
                if not climb_is_organic(book, top):
                    deep_inorganic += 1

            if sampled < sample:
                sampled += 1
                fired, authored = replay_client_meter(book)
                if fired != authored:
                    client_mismatch += 1
                pay_sample.append(book)

        mismatches = find_feature_payout_mismatches(iter(pay_sample), wincap=wincap)
        ok = (
            all(deep_by_level[t] > 0 for t in DEEP_BONUS_TARGET_LEVELS)
            and deep_bad_pay == 0
            and deep_inorganic == 0
            and no_bar == 0
            and bar_not_monotonic == 0
            and client_mismatch == 0
            and not mismatches
        )
        if not ok:
            missing = [t for t in DEEP_BONUS_TARGET_LEVELS if deep_by_level[t] == 0]
            if missing:
                failures.append(f"{mode}: NO book finishing at level(s) {missing}")
            if deep_bad_pay:
                failures.append(f"{mode}: {deep_bad_pay} deep books not paying the wincap")
            if deep_inorganic:
                failures.append(f"{mode}: {deep_inorganic} deep books climbed without real peg hits")
            if no_bar:
                failures.append(f"{mode}: {no_bar} books missing bonusRound.spinMeterMax")
            if bar_not_monotonic:
                failures.append(f"{mode}: {bar_not_monotonic} books with a SHRINKING spin bar")
            if client_mismatch:
                failures.append(f"{mode}: {client_mismatch} books where the client bar != authored wheels")
            if mismatches:
                failures.append(f"{mode}: {len(mismatches)} payout mismatches")

        hist = " ".join(f"L{k}={v}" for k, v in sorted(levels.items()))
        rate = deep / total_books if total_books else 0.0
        print(
            f"{'OK  ' if ok else 'FAIL'} {mode:>13}  books {total_books:>9,}  bonus {sum(levels.values()):>7,}  "
            f"deep {deep:>2} (1 in {round(1/rate):,} bets)" if rate else
            f"{'OK  ' if ok else 'FAIL'} {mode:>13}  books {total_books:>9,}  deep 0"
        )
        print(f"{'':>18}  levels: {hist}")
        print(f"{'':>18}  deep by target level: "
              + "  ".join(f"L{t}={deep_by_level[t]}" for t in DEEP_BONUS_TARGET_LEVELS))
        print(
            f"{'':>18}  bar missing {no_bar}  bar non-monotonic {bar_not_monotonic}  "
            f"client/book disagreements {client_mismatch}/{sampled}  payout mismatches {len(mismatches)}"
        )

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED — library is safe to upload.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
