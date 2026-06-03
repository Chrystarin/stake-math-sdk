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


def write_books_jsonl_zst(books: list[dict], dest_zst: str) -> None:
    payload = "\n".join(json.dumps(book, separators=(",", ":")) for book in books) + "\n"
    compressor = zstd.ZstdCompressor()
    os.makedirs(os.path.dirname(dest_zst) or ".", exist_ok=True)
    with open(dest_zst, "wb") as f:
        f.write(compressor.compress(payload.encode("UTF-8")))


def sync_publish_files(gamestate, *, betmode: str = "base") -> None:
    """
    Copy the latest lookup table into publish_files and rebuild books_base.jsonl.zst
    from the current simulation output so ACP publish verification passes.
    """
    output = gamestate.output_files
    lut_src = output.get_final_lookup_name(betmode)
    lut_dst = output.lookups[betmode]["paths"]["optimized_lookup"]
    books_json = output.books[betmode]["paths"]["books_uncompressed"]
    books_zst = output.books[betmode]["paths"]["books_compressed"]

    if not os.path.isfile(books_json):
        raise FileNotFoundError(
            f"Missing simulation books at {books_json}. Run `make run GAME=crimson_plinko` first."
        )
    if not os.path.isfile(lut_src):
        raise FileNotFoundError(f"Missing lookup table at {lut_src}.")

    os.makedirs(output.publish_path, exist_ok=True)
    with open(lut_src, encoding="UTF-8") as src, open(lut_dst, "w", encoding="UTF-8") as dst:
        dst.write(src.read())

    with open(books_json, encoding="UTF-8") as f:
        data = json.load(f)
    books = data if isinstance(data, list) else [data]
    write_books_jsonl_zst(books, books_zst)

    book_payouts = {int(b["id"]): int(b["payoutMultiplier"]) for b in books}
    mismatches = find_lut_book_mismatches(lut_dst, book_payouts)
    if mismatches:
        sample = mismatches[:5]
        raise RuntimeError(
            "publish_files lookup table does not match book payoutMultiplier values "
            f"({len(mismatches)} mismatches). Examples (id, lut, book): {sample}. "
            "Re-run simulations from a clean library/ temp folder."
        )

    print(
        f"Synced publish_files: {os.path.basename(lut_dst)}, "
        f"{os.path.basename(books_zst)} ({len(books)} books)."
    )


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from game_config import GameConfig
    from gamestate import GameState
    from src.write_data.write_configs import generate_configs

    gs = GameState(GameConfig())
    sync_publish_files(gs)
    generate_configs(gs)
    print("Updated library/configs/config.json hashes for publish_files.")
