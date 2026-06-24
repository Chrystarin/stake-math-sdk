"""Verify and sync Stake Engine publish_files (books + lookup table must match)."""

from __future__ import annotations

import csv
import json
import os
from io import TextIOWrapper

import zstandard as zstd


def _load_lut_payouts(lut_path: str) -> dict[int, int]:
    payouts: dict[int, int] = {}
    with open(lut_path, encoding="UTF-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            payouts[int(row[0])] = int(row[2])
    return payouts


def _load_book_payouts_from_json(path: str) -> dict[int, int]:
    with open(path, encoding="UTF-8") as f:
        data = json.load(f)
    books = data if isinstance(data, list) else [data]
    return {int(b["id"]): int(b["payoutMultiplier"]) for b in books}


def _load_book_payouts_from_jsonl(path: str) -> dict[int, int]:
    payouts: dict[int, int] = {}
    with open(path, encoding="UTF-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            blob = json.loads(line)
            payouts[int(blob["id"])] = int(blob["payoutMultiplier"])
    return payouts


def _load_book_payouts_from_zst(path: str) -> dict[int, int]:
    payouts: dict[int, int] = {}
    with open(path, "rb") as f:
        decompressor = zstd.ZstdDecompressor()
        with decompressor.stream_reader(f) as reader:
            for line in TextIOWrapper(reader, encoding="UTF-8"):
                line = line.strip()
                if not line:
                    continue
                blob = json.loads(line)
                payouts[int(blob["id"])] = int(blob["payoutMultiplier"])
    return payouts


def find_lut_book_mismatches(lut_path: str, book_payouts: dict[int, int]) -> list[tuple[int, int, int]]:
    lut = _load_lut_payouts(lut_path)
    mismatches: list[tuple[int, int, int]] = []
    for book_id, book_pm in book_payouts.items():
        lut_pm = lut.get(book_id)
        if lut_pm is None:
            mismatches.append((book_id, -1, book_pm))
        elif lut_pm != book_pm:
            mismatches.append((book_id, lut_pm, book_pm))
    for book_id in lut:
        if book_id not in book_payouts:
            mismatches.append((book_id, lut[book_id], -1))
    return mismatches


def _nonspin_win(outcomes: list[dict]) -> float:
    """Sum currency win for a list of ball outcomes (spin-pocket balls pay 0)."""
    total = 0.0
    for outcome in outcomes:
        if outcome.get("hitSpinSlot"):
            continue
        total += float(outcome.get("amount", 0) or 0) * float(outcome.get("multiplier", 0) or 0)
    return total


def find_feature_payout_mismatches(books_json: str, *, wincap: float = 1000.0) -> list[tuple]:
    """
    Reconstruct the on-screen total from a book's events the way the client accumulates it
    (base drop + bonus-round balls + free-spin multiply) and compare to `finalWin`.

    This guards the exact bug that previously caused features to be stripped: book payout
    must equal what the player watches land. Returns a list of (id, finalWin, expected).
    """
    if not os.path.isfile(books_json):
        return []
    with open(books_json, encoding="UTF-8") as f:
        data = json.load(f)
    books = data if isinstance(data, list) else [data]

    mismatches: list[tuple] = []
    for book in books:
        events = book.get("events", [])
        drop = next((e for e in events if e["type"] == "plinkoDrop"), None)
        final = next((e for e in events if e["type"] == "finalWin"), None)
        if drop is None or final is None:
            continue
        # payoutMultiplier is relative to the play amount (per-ball stake), not the total wager.
        play_amount = max(1e-9, float(drop["stakePerBall"]))
        round_drop = _nonspin_win(drop["outcomes"])
        recon = round_drop
        for event in events:
            if event["type"] == "bonusRound":
                recon += _nonspin_win(event["outcomes"])
            elif event["type"] == "freeSpinTrigger":
                # In-drop free spin: the multiplier applies to the BET PER BALL, so it adds
                # play_amount × M on top of the drop. A BONUS segment carries multiplier 0 here —
                # its win comes from the bonusRound events handled above.
                mult = float(event.get("multiplier", 0) or 0)
                recon += play_amount * mult
        expected = round(min(recon / play_amount, wincap) * 100)
        if abs(int(final["amount"]) - expected) > 1:
            mismatches.append((book.get("id"), int(final["amount"]), expected))
    return mismatches


def write_books_jsonl_zst(books: list[dict], dest_zst: str) -> None:
    payload = "\n".join(json.dumps(book, separators=(",", ":")) for book in books) + "\n"
    compressor = zstd.ZstdCompressor()
    os.makedirs(os.path.dirname(dest_zst) or ".", exist_ok=True)
    with open(dest_zst, "wb") as f:
        f.write(compressor.compress(payload.encode("UTF-8")))


def _resolve_book_payouts(
    *,
    books_json: str,
    books_jsonl: str,
    books_zst: str,
) -> tuple[dict[int, int], bool]:
    """
    Load book payout multipliers from simulation output.

    Returns (payouts, wrote_zst). When compression runs during sim, books are already
    at books_zst — verify only and skip rebuilding the archive.
    """
    if os.path.isfile(books_json):
        with open(books_json, encoding="UTF-8") as f:
            data = json.load(f)
        books = data if isinstance(data, list) else [data]
        write_books_jsonl_zst(books, books_zst)
        return {int(b["id"]): int(b["payoutMultiplier"]) for b in books}, True

    if os.path.isfile(books_jsonl):
        book_payouts = _load_book_payouts_from_jsonl(books_jsonl)
        write_books_jsonl_zst(
            [json.loads(line) for line in open(books_jsonl, encoding="UTF-8") if line.strip()],
            books_zst,
        )
        return book_payouts, True

    if os.path.isfile(books_zst):
        return _load_book_payouts_from_zst(books_zst), False

    raise FileNotFoundError(
        f"Missing simulation books for publish sync. Expected one of: "
        f"{books_json}, {books_jsonl}, {books_zst}. Run `make run GAME=crimson_plinko` first."
    )


def sync_publish_files(gamestate, *, betmode: str = "base") -> None:
    """
    Copy the latest lookup table into publish_files and ensure books_{mode}.jsonl.zst
    matches simulation output so ACP publish verification passes.
    """
    output = gamestate.output_files
    lut_src = output.get_final_lookup_name(betmode)
    lut_dst = output.lookups[betmode]["paths"]["optimized_lookup"]
    books_json = output.books[betmode]["paths"]["books_uncompressed"]
    books_jsonl = books_json.replace(".json", ".jsonl") if books_json.endswith(".json") else books_json
    books_zst = output.books[betmode]["paths"]["books_compressed"]

    if not os.path.isfile(lut_src):
        raise FileNotFoundError(f"Missing lookup table at {lut_src}.")

    os.makedirs(output.publish_path, exist_ok=True)
    with open(lut_src, encoding="UTF-8") as src, open(lut_dst, "w", encoding="UTF-8") as dst:
        dst.write(src.read())

    book_payouts, wrote_zst = _resolve_book_payouts(
        books_json=books_json,
        books_jsonl=books_jsonl,
        books_zst=books_zst,
    )
    mismatches = find_lut_book_mismatches(lut_dst, book_payouts)
    if mismatches:
        sample = mismatches[:5]
        raise RuntimeError(
            "publish_files lookup table does not match book payoutMultiplier values "
            f"({len(mismatches)} mismatches). Examples (id, lut, book): {sample}. "
            "Re-run simulations from a clean library/ temp folder."
        )

    # Per-mode wincap: after create_books, gamestate.config.wincap is left at the LAST simulated mode's
    # value, but each mode has its own cap (plinko_data.WINCAP_BY_BALLS) and update_final_win capped this
    # mode's books at that per-mode value during the sim (run_sims sets config.wincap = bm.get_wincap()).
    # Reconstruct the feature payout with the SAME per-mode cap, else a tier whose books capped below the
    # global wincap (e.g. onedrop 200x vs fiftydrop 400x) is falsely flagged as a feature mismatch.
    mode_wincap = next(
        (bm.get_wincap() for bm in gamestate.config.bet_modes if bm.get_name() == betmode),
        float(gamestate.config.wincap),
    )
    feature_mismatches = find_feature_payout_mismatches(
        books_json, wincap=float(mode_wincap)
    )
    if feature_mismatches:
        sample = feature_mismatches[:5]
        raise RuntimeError(
            f"Feature payout does not match displayed outcomes ({len(feature_mismatches)} books). "
            f"Examples (id, finalWin, expected): {sample}. "
            "Book finalWin must equal base drop + bonus-round balls + free-spin multiply."
        )

    action = "rebuilt" if wrote_zst else "verified"
    print(
        f"Synced publish_files: {os.path.basename(lut_dst)}, "
        f"{os.path.basename(books_zst)} ({len(book_payouts)} books, {action})."
    )


def sync_all_publish_files(gamestate, *, betmodes: list[str] | None = None) -> None:
    """Rebuild publish_files for every configured bet mode."""
    modes = betmodes
    if modes is None:
        modes = [bm.get_name() for bm in gamestate.config.bet_modes]
    for betmode in modes:
        sync_publish_files(gamestate, betmode=betmode)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from game_config import GameConfig
    from gamestate import GameState
    from src.write_data.write_configs import generate_configs

    gs = GameState(GameConfig())
    sync_all_publish_files(gs)
    generate_configs(gs)
    print("Updated library/configs/config.json hashes for publish_files.")
