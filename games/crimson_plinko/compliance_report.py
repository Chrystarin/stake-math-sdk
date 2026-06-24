"""Stake Engine math-compliance report for crimson_plinko (DEV TOOL, not published).

Reads the published lookup tables (library/publish_files/lookUpTable_<mode>_0.csv) and the
index.json mode costs, then reproduces the summary statistics + hit-rate / tail-risk metrics that
the Stake Engine approval pipeline computes, and checks each against the published thresholds.

LUT row format: simID,weight,payout_x100  (weight is uniform 1; payout multiplier = col3 / 100).
The payout multiplier is normalized PER play-amount (stake_per_ball); mode `cost` (= ball count)
comes from index.json. So return-per-unit = payout_multiplier / cost and RTP = mean(mult) / cost.

Run: env/Scripts/python.exe games/crimson_plinko/compliance_report.py
"""

import csv
import json
import math
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLISH = os.path.join(HERE, "library", "publish_files")

# Stake rating thresholds (2-star tier; 3-star noted in comments where it differs).
STAR = "2-star"
MAX_PAYOUT_MULT = 25_000        # 2-star: 25k; 3-star: 100k
RTP_MIN, RTP_MAX = 0.90, 0.967  # published 90.0%-96.70% band
CROSS_MODE_BAND = 0.01          # all modes within a 1.0%-wide window (±0.5%)
STD_MIN, STD_MAX = 0.6, 50.0    # base (1.0x cost) std-dev band (3-star max is 60)
MAXWIN_HITRATE_MIN = 1 / 20_000_000  # advertised max win must be >= this frequent
CVAR_LIMIT = 700                # 2-star CVaR/cost limit (3-star: 800)
ETL_40X_LIMIT = 0.8             # 2-star ETL (>=40x cost) limit (3-star: 0.9)


def load_costs() -> dict:
    with open(os.path.join(PUBLISH, "index.json"), encoding="UTF-8") as f:
        idx = json.load(f)
    return {m["name"]: float(m["cost"]) for m in idx["modes"]}


def load_mults(mode: str) -> list:
    """All payout multipliers for a mode (one per simulated book)."""
    path = os.path.join(PUBLISH, f"lookUpTable_{mode}_0.csv")
    mults = []
    with open(path, encoding="UTF-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            # weight is col[1]; uniform 1 in this build. payout x100 in col[2].
            mults.append(int(row[2]) / 100.0)
    return mults


def pct(x: float) -> str:
    return f"{x*100:.3f}%"


def one_in(p: float) -> str:
    if p <= 0:
        return "never (0)"
    return f"1 in {1/p:,.0f}"


def analyze(mode: str, cost: float, mults: list) -> dict:
    n = len(mults)
    s = sorted(mults)
    total = math.fsum(mults)
    mean = total / n
    rtp = mean / cost

    # Std dev of the per-unit return (payout / cost) — the quantity Stake bands for the 1.0x mode.
    mean_ret = mean / cost
    var_ret = math.fsum(((m / cost) - mean_ret) ** 2 for m in mults) / n
    std_ret = math.sqrt(var_ret)

    nonzero = sum(1 for m in mults if m > 0)
    win_ge_cost = sum(1 for m in mults if m >= cost)  # "win" = returns >= stake (profit/break-even)
    p_nonzero = nonzero / n
    p_win = win_ge_cost / n

    mx = s[-1]
    n_at_max = sum(1 for m in mults if m >= mx - 1e-9)
    p_max = n_at_max / n

    uniq = Counter(mults)
    most_val, most_cnt = uniq.most_common(1)[0]
    p_most = most_cnt / n

    # Tail risk.
    # CVaR: mean of the worst-0.1% (largest) payouts, normalized by cost.
    k = max(1, int(round(n * 0.001)))
    cvar = (math.fsum(s[-k:]) / k) / cost

    # ETL (>=40x cost): share of total expected payout coming from wins >= 40x cost.
    etl_thresh = 40 * cost
    tail_sum = math.fsum(m for m in mults if m >= etl_thresh)
    etl_40x = (tail_sum / total) if total > 0 else 0.0

    # Published tail-probability gates (payout multiplier thresholds).
    p_ge_5000 = sum(1 for m in mults if m >= 5000) / n
    p_ge_10000 = sum(1 for m in mults if m >= 10000) / n

    return {
        "mode": mode, "cost": cost, "n": n, "mean": mean, "rtp": rtp,
        "std_ret": std_ret, "p_nonzero": p_nonzero, "p_win": p_win,
        "max": mx, "p_max": p_max, "uniq": len(uniq),
        "most_val": most_val, "p_most": p_most, "cvar": cvar, "etl_40x": etl_40x,
        "p_ge_5000": p_ge_5000, "p_ge_10000": p_ge_10000, "sorted": s,
    }


def hist(mults_sorted: list, cost: float) -> list:
    """Hit-rate buckets by payout multiplier; flags empty interior buckets (gaps)."""
    edges = [0, 1e-9, 0.5, 1, 2, 5, 10, 20, 50, 100, 250, 500, 1000, float("inf")]
    labels = ["=0", "(0,0.5)", "[0.5,1)", "[1,2)", "[2,5)", "[5,10)", "[10,20)",
              "[20,50)", "[50,100)", "[100,250)", "[250,500)", "[500,1000)", ">=1000"]
    n = len(mults_sorted)
    out = []
    for i in range(len(labels)):
        lo, hi = edges[i], edges[i + 1]
        c = sum(1 for m in mults_sorted if lo <= m < hi) if i > 0 else sum(1 for m in mults_sorted if m == 0)
        out.append((labels[i], c, c / n))
    return out


def main():
    costs = load_costs()
    print(f"=== Crimson Plinko — Stake Engine math compliance ({STAR}) ===\n")
    results = []
    for mode, cost in costs.items():
        mults = load_mults(mode)
        r = analyze(mode, cost, mults)
        results.append(r)

    # ---- Summary table ----
    print(f"{'mode':>11} {'cost':>5} {'sims':>9} {'RTP':>8} {'std/cost':>9} "
          f"{'maxWin':>8} {'maxHit':>16} {'P(win>0)':>16} {'uniq':>6}")
    for r in results:
        print(f"{r['mode']:>11} {r['cost']:>5.0f} {r['n']:>9,} {pct(r['rtp']):>8} "
              f"{r['std_ret']:>9.3f} {r['max']:>8.2f} {one_in(r['p_max']):>16} "
              f"{one_in(r['p_nonzero']):>16} {r['uniq']:>6}")

    rtps = [r["rtp"] for r in results]
    spread = max(rtps) - min(rtps)
    print(f"\ncross-mode RTP spread (max-min) = {pct(spread)}   [need < {pct(CROSS_MODE_BAND)}]")
    print(f"RTP range across modes          = {pct(min(rtps))} .. {pct(max(rtps))}   "
          f"[need {pct(RTP_MIN)} .. {pct(RTP_MAX)}]")

    # ---- Tail-risk table ----
    print(f"\n{'mode':>11} {'CVaR/cost':>10} {'ETL>=40x':>9} {'P(>=5000)':>11} {'P(>=10000)':>12} "
          f"{'mostFreqVal':>12} {'P(most)':>10}")
    for r in results:
        print(f"{r['mode']:>11} {r['cvar']:>10.2f} {r['etl_40x']:>9.3f} "
              f"{r['p_ge_5000']:>11.2e} {r['p_ge_10000']:>12.2e} "
              f"{r['most_val']:>12.2f} {pct(r['p_most']):>10}")

    # ---- Per-mode hit-rate buckets ----
    for r in results:
        print(f"\n-- hit-rate table: {r['mode']} (cost {r['cost']:.0f}) --")
        for label, c, p in hist(r["sorted"], r["cost"]):
            bar = "#" * min(40, int(p * 200))
            gap = "  <-- EMPTY" if (c == 0 and label not in ("=0",)) else ""
            print(f"   {label:>11}  {c:>9,}  {pct(p):>9}  {bar}{gap}")

    # ---- Compliance checklist ----
    print("\n=== Checklist ===")
    base = next(r for r in results if abs(r["cost"] - 1.0) < 1e-9)  # the 1.0x-cost mode

    def chk(ok, msg):
        print(f"  [{'PASS' if ok else 'FAIL'}] {msg}")

    chk(all(RTP_MIN <= r["rtp"] <= RTP_MAX for r in results),
        f"RTP in {pct(RTP_MIN)}-{pct(RTP_MAX)} for all modes")
    chk(spread < CROSS_MODE_BAND, f"cross-mode spread {pct(spread)} < {pct(CROSS_MODE_BAND)}")
    chk(all(r["max"] <= MAX_PAYOUT_MULT for r in results),
        f"max payout multiplier <= {MAX_PAYOUT_MULT:,}x (actual {max(r['max'] for r in results):.0f}x)")
    chk(all(r["p_max"] >= MAXWIN_HITRATE_MIN for r in results),
        f"advertised max-win achievable (>= {one_in(MAXWIN_HITRATE_MIN)})")
    chk(all(1/8 <= 1/ (1/r['p_nonzero']) for r in results) and base["p_nonzero"] >= 1/10,
        f"non-zero-win hit-rate reasonable (base {one_in(base['p_nonzero'])})")
    chk(STD_MIN <= base["std_ret"] <= STD_MAX,
        f"base (1.0x cost) std-dev {base['std_ret']:.3f} in [{STD_MIN}, {STD_MAX}]")
    chk(all(r["cvar"] <= CVAR_LIMIT for r in results),
        f"CVaR/cost <= {CVAR_LIMIT} (worst {max(r['cvar'] for r in results):.1f})")
    chk(all(r["etl_40x"] <= ETL_40X_LIMIT for r in results),
        f"ETL(>=40x cost) <= {ETL_40X_LIMIT} (worst {max(r['etl_40x'] for r in results):.3f})")
    print("\n  (manual: validation warnings, max-win == game-rules text, broad table / no gaps above)")


if __name__ == "__main__":
    main()
