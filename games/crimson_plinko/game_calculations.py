"""Plinko path sampling, feature meter walking, and payout helpers.

All randomness for features lives here so the published books are authoritative:
the client animates exactly these outcomes and never rolls its own dice.
"""

import random as py_random
from bisect import bisect_right
from math import comb, gcd

from plinko_data import (
    BONUS_METER_MAX,
    BONUS_PEG_HIT_PROB,
    FREE_SPIN_SEGMENTS,
    FREE_SPIN_WEIGHTS,
    MAX_BONUS_LEVEL,
    SPIN_METER_MAX,
    bonus_level_balls,
    bonus_levelup_pegs,
    bonus_wheel_free_balls,
    bonus_wheel_weights,
    coefficients_for,
    in_bonus_nominal_entry,
    in_bonus_spin_meter_max_at_level,
    scaled_spin_meter_max,
    spin_in_drop_for_balls,
    spin_pocket_active_for_balls,
    spin_slot_index,
)
from src.executables.executables import Executables


class GameCalculations(Executables):
    """Galton-board style slot sampling for crimson plinko."""

    FREE_SPIN_SEGMENTS: list[str] = list(FREE_SPIN_SEGMENTS)
    FREE_SPIN_WEIGHTS: list[float] = list(FREE_SPIN_WEIGHTS)

    # STRATIFIED 1-BALL SAMPLING. Set by `GameStateOverride.run_sims` to the mode's TOTAL book count
    # while the feature-free 1-ball mode is being simulated, None for every other mode. See
    # `stratified_rate_index`.
    stratified_onedrop_total: int | None = None
    _stratified_plan_cache: dict | None = None

    @staticmethod
    def rights_to_rate_index(rights: int, row_count: int, num_slots: int) -> int:
        """The Galton-board mapping from `rights` right-deflections (of `row_count`) to a pocket index.
        ONE definition, shared by the random sampler and the stratified plan, so the two can never
        disagree about which pocket a deflection count lands in."""
        if num_slots <= 1:
            return 0
        return min(num_slots - 1, round(rights * (num_slots - 1) / row_count))

    @classmethod
    def pocket_probabilities(cls, row_count: int, num_slots: int) -> list[float]:
        """EXACT landing probability of every pocket: the deflection count is Binomial(row_count, 1/2),
        pushed through `rights_to_rate_index`. This is the distribution `sample_rate_index` draws from."""
        probs = [0.0] * max(1, num_slots)
        for rights in range(row_count + 1):
            probs[cls.rights_to_rate_index(rights, row_count, num_slots)] += comb(row_count, rights) / 2**row_count
        return probs

    @staticmethod
    def stratified_pocket_counts(probs: list[float], total: int, payouts: list[float] | None = None) -> list[int]:
        """How many of `total` books land in each pocket: `total x p_k`, each pocket floored or ceiled
        (within one book of its exact expectation) with the counts summing to `total` exactly.

        WHICH pockets get the extra book is chosen to make the library's MEAN PAYOUT match the exact
        EV, not merely each count: with 15 pockets rounded independently (plain largest remainder) the
        mean can drift by up to sum(payouts)/total, and on this board the 100x corners dominate that. So
        among the C(15, leftover) ways to hand out the leftover books, take the one whose signed payout
        error |sum_k (count_k - total x p_k) x payout_k| is smallest (ties -> the largest remainders). At
        most 6435 subsets, evaluated once per run. Without `payouts` it is plain largest remainder."""
        raw = [p * total for p in probs]
        floors = [int(x) for x in raw]
        leftover = total - sum(floors)
        remainders = [raw[k] - floors[k] for k in range(len(probs))]
        if payouts is None:
            chosen = tuple(sorted(range(len(probs)), key=lambda k: remainders[k], reverse=True)[:leftover])
        else:
            from itertools import combinations

            base_err = sum((floors[k] - raw[k]) * payouts[k] for k in range(len(probs)))
            best_key = None
            chosen = ()
            for subset in combinations(range(len(probs)), leftover):
                err = base_err + sum(payouts[k] for k in subset)
                key = (abs(err), -sum(remainders[k] for k in subset))
                if best_key is None or key < best_key:
                    best_key, chosen = key, subset
        counts = list(floors)
        for k in chosen:
            counts[k] += 1
        return counts

    def _stratified_plan(self, row_count: int, num_slots: int, total: int, payouts: list[float]) -> dict:
        cache = self._stratified_plan_cache
        key = (row_count, num_slots, total, tuple(payouts))
        if cache and cache.get("key") == key:
            return cache
        counts = self.stratified_pocket_counts(
            self.pocket_probabilities(row_count, num_slots), total, list(payouts)
        )
        bounds = []
        running = 0
        for c in counts:
            running += c
            bounds.append(running)
        # Spread the pockets over the id range with a multiplicative scramble: rank = id x step mod total
        # is a bijection on 0..total-1 whenever gcd(step, total) = 1, so a run of consecutive ids visits
        # pockets in a mixed order instead of the LUT reading "all the 100x books first". Deterministic in
        # (row_count, num_slots, total) alone - no RNG, no per-thread state.
        step = max(1, int(total * 0.6180339887498949))
        while gcd(step, total) != 1:
            step -= 1
        self._stratified_plan_cache = {"key": key, "counts": counts, "bounds": bounds, "step": step}
        return self._stratified_plan_cache

    def stratified_rate_index(
        self, sim: int, row_count: int, num_slots: int, total: int, payouts: list[float]
    ) -> int:
        """Pocket for book `sim` of a `total`-book run, laid out so the finished library holds
        `total x p_k` books (to the book) in pocket k, rounded so the mean payout is the exact board EV
        (see `stratified_pocket_counts`; `payouts` is the board the drop pays from).

        Why: the 1-ball tier is feature-free, so its RTP is nothing but the board EV - and with random
        sampling the published LUT only ESTIMATES that EV, with sd ~ 3.27/sqrt(N) (a lone 100x corner
        moves a one-ball mean a long way). Hitting Stake's 0.50% cross-mode RTP limit that way needed
        9.6M books, and a 9.6M-row LUT is more than the RGS can serve inside its ~15 s play timeout
        (`ERR_GEN` on every 1-ball bet - see readme.txt). Laying the books out by exact quota instead
        pins the LUT mean to the board EV (payout-aware rounding leaves ~1e-6 of RTP at 1M books, and
        even the crude bound sum(payouts)/total is 0.04%) at ANY book count, so the count can be
        whatever the RGS serves comfortably.

        The board is the same one `sample_rate_index` plays - only WHICH pocket each id gets is planned
        rather than drawn. `hitBonusPeg` is still sampled per ball (it is EV-neutral on this tier)."""
        plan = self._stratified_plan(row_count, num_slots, total, payouts)
        if not 0 <= sim < total:
            raise ValueError(f"stratified onedrop: sim {sim} outside the planned 0..{total - 1} range")
        rank = (sim * plan["step"]) % total
        return bisect_right(plan["bounds"], rank)

    def sample_rate_index(self, row_count: int, num_slots: int) -> int:
        """Map `row_count` binary peg deflections to a slot index."""
        if num_slots <= 1:
            return 0
        rights = sum(py_random.randint(0, 1) for _ in range(row_count))
        return self.rights_to_rate_index(rights, row_count, num_slots)

    def is_spin_slot(self, rate_index: int, num_slots: int) -> bool:
        return rate_index == spin_slot_index(num_slots)

    def build_drop_outcomes(
        self,
        *,
        row_count: int,
        balls_per_drop: int,
        stake_per_ball: float,
        tier_balls_per_drop: int = 0,
        peg_hit_prob: float = BONUS_PEG_HIT_PROB,
    ) -> tuple[list[dict], float]:
        """Sample `balls_per_drop` balls; each carries pocket + feature flags.

        `tier_balls_per_drop` is the PLAYER'S tier, which selects the board (1-ball has its own table)
        and whether the centre is the spin pocket. It defaults to `balls_per_drop` — correct for a paid
        drop, but a bonus batch must pass the real tier explicitly (its ball count is not a tier).

        `peg_hit_prob` is the PER-MODE coin-peg probability (`plinko_data.bonus_peg_hit_prob`). It is
        the RTP lever that lets every mode share one in-bonus level-up ladder; base modes pass the
        default 0.18 and the buy modes pass their own much lower value."""
        tier = int(tier_balls_per_drop or balls_per_drop)
        coeffs = coefficients_for(row_count, tier)
        if not coeffs:
            return [], 0.0

        outcomes: list[dict] = []
        total_win = 0.0
        num_slots = len(coeffs)
        spin_pocket = spin_pocket_active_for_balls(tier)
        peg_prob = max(0.0, min(1.0, float(peg_hit_prob)))
        # The feature-free 1-ball tier lays its single ball out by exact quota (see
        # `stratified_rate_index`); every other drop, and any bonus batch, samples the board randomly.
        stratified_total = self.stratified_onedrop_total if (tier == 1 and balls_per_drop == 1) else None
        for _ in range(balls_per_drop):
            if stratified_total:
                rate_index = self.stratified_rate_index(
                    self.sim, row_count, num_slots, stratified_total, coeffs
                )
            else:
                rate_index = self.sample_rate_index(row_count, num_slots)
            # `hitSpinSlot` means "this ball fed the free-spin meter" — only on tiers that HAVE one. The
            # payout always comes from the board and is unaffected by the flag: every board pays 0 at the
            # centre, so a 1-ball centre land is worth the same 0 as elsewhere; it just isn't REPORTED as
            # a meter hit, because that tier has no meter to feed.
            hit_spin_slot = spin_pocket and self.is_spin_slot(rate_index, num_slots)
            multiplier = coeffs[rate_index]
            hit_bonus_peg = py_random.random() < peg_prob
            total_win += stake_per_ball * multiplier
            outcomes.append(
                {
                    "rateIndex": rate_index,
                    "multiplier": multiplier,
                    "amount": stake_per_ball,
                    "hitBonusPeg": hit_bonus_peg,
                    "hitSpinSlot": hit_spin_slot,
                }
            )
        return outcomes, total_win

    def ensure_coin_pegs_fill_meter(self, outcomes: list[dict], target: int) -> None:
        """Turn on enough balls' `hitBonusPeg` so the (empty-start) bonus meter fills to `target` within
        this drop. Used on the `force_bonus` trigger drop so the meter visibly fills to FULL from real
        coin-peg hits (instead of snapping). EV-NEUTRAL: `hitBonusPeg` is independent of the ball's pocket
        win, so flipping it changes nothing about the payout. Spreads the added hits across the drop so
        the meter ramps up smoothly, completing near the end."""
        if target <= 0 or not outcomes:
            return
        have = sum(1 for o in outcomes if o.get("hitBonusPeg"))
        if have >= target:
            return
        without = [i for i, o in enumerate(outcomes) if not o.get("hitBonusPeg")]
        to_add = min(target - have, len(without))
        if to_add <= 0:
            return
        # Evenly spaced indices among the no-peg balls so the fill is gradual.
        for k in range(to_add):
            idx = without[(k * len(without)) // to_add]
            outcomes[idx]["hitBonusPeg"] = True

    def _drop_win_from_outcomes(self, outcomes: list[dict], stake_per_ball: float) -> float:
        """Sum slot payouts for a drop. Each ball's `multiplier` already comes from its tier's board, and
        every board's centre is 0, so centre lands contribute nothing on every tier."""
        stake = max(0.0, float(stake_per_ball))
        total = 0.0
        for outcome in outcomes:
            total += stake * float(outcome.get("multiplier", 0) or 0)
        return total

    def simulate_bonus_round(
        self,
        *,
        row_count: int,
        stake_per_ball: float,
        balls_per_drop: int,
        entry_balls_override: int = 0,
        levelup_head_start: float = 0.0,
        peg_hit_prob: float = BONUS_PEG_HIT_PROB,
        spin_meter_max_override: int = 0,
        force_level: int = 0,
    ) -> tuple[list[dict], float, int]:
        """
        Simulate a MULTI-LEVEL bonus round (FOLDED-bonus design — the bonus is FREE, funded by the base).

        Entry free balls come from the ABSOLUTE Aztec bonus wheel (`bonus_wheel_free_balls`, avg ≈ 60,
        tier-independent) and drop on the board. Coin-peg hits during the falling balls accumulate
        "energy"; `bonus_levelup_pegs(level)` hits advances a level and unlocks the next batch of free
        balls (`bonus_level_balls`, up to `MAX_BONUS_LEVEL`) — the inout "accumulate energy → unlock more
        drops, up to ~250 balls" escalation (a rare jackpot). Each level emits its own `bonusRound` so the
        client animates the level-ups in order. Returns (events, feature_win, final_level).

        THE LADDER IS THE SAME FOR EVERY MODE — an earned bonus and a bought bonus need identical
        coin-peg counts to climb. What differs per mode is `peg_hit_prob`: how often a falling ball
        awards one of those hits. That is the per-mode RTP lever (see `BONUS_PEG_HIT_PROB_BY_MODE`).

        IN-BONUS ENERGY METER: starts EMPTY; the client fills it provisionally as bonus balls hit coin
        pegs and RESETS it on a level-up. We emit ONE `bonusMeter(value=0, max=levelup_max)` to set the
        client's in-bonus max + reset; the per-ball fill/reset is client-driven (so it tracks the balls
        smoothly instead of jumping). The level-up itself stays server-authoritative here (peg counter).

        IN-BONUS FREE SPIN: the spin meter also fills from the bonus balls' spin-pocket hits (gated by
        `spin_in_drop`, off on 1-ball) and fires the free spin THE INSTANT IT COMPLETES — mid-batch, on
        the very ball that filled it. Every step of that fill is published as a `spinMeter` event and each
        batch carries its own `spinMeterStart` carry-in, so the client's bar is BOOK-DRIVEN and completes
        on exactly the ball this walk completes it on. Numeric-only (re-pick if it lands BONUS) to avoid
        recursion.

        ⚠️ THE METER FIRES EVERY TIME IT FILLS, as many times per batch as the balls fill it — this is
        the paid-for behaviour, not a free one. Until 2026-08-19 this walk counted spin hits UNBOUNDED and
        tested the total ONCE, after the batch, so a batch paid at most one free spin however many spin
        pockets it hit and the surplus was thrown away by the reset. On the published library that surplus
        was 1.1 / 1.9 / 3.6 / 6.9 discarded fills per round on the four buy tiers — the bar spent most of
        a bonus round visibly dead, which is what QA reported.

        Honouring them costs ~7.64× stake-per-ball per extra fire (the mean numeric segment), i.e. +10.6
        to +21.1 RTP points on the buy tiers, and `BUY_BONUS_TIER_DEFS` was re-solved to pay for it. ⚠️ So
        `spin_max`, the buy tiers' `peg_hit_prob` / `entry_balls` / `cost` and this fire rule are now ONE
        tuning: moving any of them without re-running `rtp_audit.py` breaks the others.

        The client used to be told none of this (no in-bonus `spinMeter` events existed) and ran its own
        free-running bar, which is why a full bar could sit there with no wheel behind it, and why two
        book-authored free spins could fire off what looked like a single fill.
        """
        events: list[dict] = []
        feature_win = 0.0
        # BUY BONUS passes a FIXED starting-ball count (the bought tier's entry); otherwise draw the entry
        # from the random bonus wheel. Level-ups below still add MORE balls on top in either case.
        if entry_balls_override and entry_balls_override > 0:
            entry_balls = int(entry_balls_override)
        else:
            # WEIGHTED landing: the wedge VALUES are the painted ones, but each tier lands on them with
            # its own probability (`bonus_wheel_weights`) — the lever that makes a flat per-tier trigger
            # rate affordable. Uniform for any tier without a profile, i.e. the pre-weighting behaviour.
            wedges = bonus_wheel_free_balls(balls_per_drop)
            entry_balls = int(
                py_random.choices(wedges, weights=bonus_wheel_weights(balls_per_drop), k=1)[0]
            )
        events.append({"type": "bonusRoulette", "freeBalls": entry_balls})

        # The IN-BONUS bar is sized from the mode's NOMINAL ball supply — not from the tier's drop-side
        # meter, and NOT from the balls this round actually won. A buy passes its pinned `entry_balls`;
        # an earned bonus uses `in_bonus_nominal_entry(balls_per_drop)`, the tier's mean wheel entry, so
        # the bar is a FIXED per-(mode, level) table instead of moving with the roulette result. The
        # level term still grows with the ladder (`in_bonus_spin_meter_max_at_level`), so a round that
        # climbs keeps ~`IN_BONUS_TARGET_CYCLES` fills per level instead of one wheel every few balls.
        #
        # RTP-neutral in the mean and deliberately not in the spread: fills are linear in the batch's
        # balls, so a lucky big entry now fires proportionally MORE wheels than a small one instead of
        # the same ~2 either way. See `IN_BONUS_NOMINAL_ENTRY`. The override pins it flat for
        # `rtp_audit.py`; tiers with no pinned nominal (1-ball, which has no free spin at all) fall back
        # to the drawn entry, i.e. the pre-2026-08-26 behaviour.
        if entry_balls_override and entry_balls_override > 0:
            nominal_entry = int(entry_balls_override)
        else:
            nominal_entry = in_bonus_nominal_entry(balls_per_drop) or entry_balls

        def spin_max_for(level: int) -> int:
            if spin_meter_max_override > 0:
                return max(1, int(spin_meter_max_override))
            return in_bonus_spin_meter_max_at_level(nominal_entry, level)

        spin_max = spin_max_for(1)

        # Level-up peg threshold: the SHARED per-level escalating ladder (`bonus_levelup_pegs`) — frequent
        # at low levels, progressively harder at higher ones (tames the ×10 ladder's snowball). Identical
        # in every mode; the buy tiers are gated by their lower `peg_hit_prob` instead of by a taller bar.
        def threshold_for(lvl: int) -> int:
            return bonus_levelup_pegs(lvl)

        spin_in_drop = spin_in_drop_for_balls(balls_per_drop)
        level = 1
        first_max = threshold_for(1)
        # BUY BONUS "Fury Meter Head-Start": the in-bonus level-up meter starts this fraction filled, so a
        # bought higher tier reaches its first level-up (chain → extra free balls) sooner. Applies ONCE (to
        # level 1); the meter resets to 0 on each level-up below. Clamp below `first_max` so it can't
        # auto-fire a level before any ball drops.
        head_start = max(0.0, min(1.0, float(levelup_head_start)))
        meter_start = min(first_max - 1, int(round(head_start * first_max))) if first_max > 0 else 0
        meter = meter_start
        spin_meter = 0
        # One reset event → tells the client the in-bonus meter max + its starting fill (head-start). The
        # level-1 threshold seeds the bar; each `bonusRound` below carries its own level's `levelupPegs`
        # so the client re-sizes the bar as the escalating threshold changes on every level-up.
        events.append({"type": "bonusMeter", "value": meter_start, "level": level, "max": first_max})
        pending: list[tuple[int, int]] = [(1, entry_balls)]
        while pending:
            cur_level, batch_balls = pending.pop(0)
            # Re-size the bar for THIS batch's level. Monotonic (see `in_bonus_spin_meter_max_at_level`),
            # so the carry-in below is always ≤ the new bar and can never open a batch already full.
            spin_max = spin_max_for(cur_level)
            outcomes, batch_win = self.build_drop_outcomes(
                row_count=row_count,
                balls_per_drop=batch_balls,
                stake_per_ball=stake_per_ball,
                # Bonus balls play the PLAYER'S tier board, not a board keyed by the batch size.
                tier_balls_per_drop=balls_per_drop,
                peg_hit_prob=peg_hit_prob,
            )
            # DEEP-BONUS STRATUM: this book was selected to climb to `force_level`, so top this batch's
            # coin pegs up to what THIS rung costs — `threshold_for(level)` hits, less whatever the meter
            # already carries. The walk below then levels up off REAL `hitBonusPeg` flags, spread across
            # the batch by `ensure_coin_pegs_fill_meter`, so the energy bar fills 0 → threshold on screen
            # at every rung instead of the level being handed over. Same device, and the same EV-neutrality
            # argument, as the `force_bonus` trigger drop: coin pegs are sampled independently of the
            # pocket, so nothing about what these balls PAY changes.
            #
            # Every rung has room to be forced — the tightest is level 2 (8 hits from a 20-ball batch).
            # A batch that happens to roll MORE hits than its rung costs simply levels up twice inside
            # itself; both awards still queue, so the ball count and the destination are unchanged.
            if force_level > 0 and level < min(int(force_level), MAX_BONUS_LEVEL):
                self.ensure_coin_pegs_fill_meter(outcomes, max(0, threshold_for(level) - meter))
            feature_win += batch_win
            events.append(
                {
                    "type": "bonusRound",
                    "freeBalls": batch_balls,
                    "outcomes": outcomes,
                    "level": cur_level,
                    "ballsPlayed": 0,
                    # Pegs to LEAVE this level (escalating) — the client sizes the energy bar / fires the
                    # combine-level-up at this threshold while these balls drop.
                    "levelupPegs": threshold_for(cur_level),
                    # Spin meter carried INTO this batch. The meter runs across levels (it only resets
                    # when it fires), so a batch can open part-full — the client seats its bar here rather
                    # than re-deriving the carry from a level boundary the combine has already blurred.
                    "spinMeterStart": spin_meter,
                    # ...and the bar that carry is measured against, which now GROWS per level
                    # (`in_bonus_spin_meter_max_at_level`). The client cannot take this from the
                    # `spinMeter` events alone: a batch whose balls hit no centre pocket emits none, and
                    # the bar would render against the previous, smaller level's max.
                    "spinMeterMax": spin_max,
                }
            )
            # Walk this batch's balls: coin pegs fill the energy meter → queue a level-up; spin-pocket
            # hits fill the spin meter, which fires the free spin every time it completes.
            for outcome in outcomes:
                if outcome.get("hitBonusPeg"):
                    meter += 1
                    if level < MAX_BONUS_LEVEL and meter >= threshold_for(level):
                        meter = 0
                        level += 1
                        extra = bonus_level_balls(level)
                        if extra > 0:
                            pending.append((level, extra))
                if spin_in_drop and outcome.get("hitSpinSlot"):
                    spin_meter = min(spin_max, spin_meter + 1)
                    events.append(
                        {"type": "spinMeter", "value": spin_meter, "max": spin_max}
                    )
                    if spin_meter >= spin_max:
                        # THE BAR JUST COMPLETED — fire here, on this ball, so the wheel follows the fill
                        # the player watched instead of trailing to the next level boundary. No per-batch
                        # lock: the bar resets below and the batch's remaining balls fill it again, as
                        # many times as they can. Numeric only (re-roll a BONUS landing) to avoid a
                        # recursive bonus.
                        segment = self._pick_free_spin_segment()
                        while segment == "BONUS":
                            segment = self._pick_free_spin_segment()
                        multiplier = self._free_spin_segment_multiplier(segment)
                        free_spin_win = stake_per_ball * multiplier
                        feature_win += free_spin_win
                        events.append(
                            {
                                "type": "freeSpinTrigger",
                                "segment": segment,
                                "multiplier": multiplier,
                                "amount": free_spin_win,
                                "level": cur_level,
                            }
                        )
                        spin_meter = 0
                        # Publish the reset too: the client empties its bar on the same ball and starts
                        # refilling from the next spin pocket, so "fill → wheel → empty → fill again"
                        # stays in lockstep with this walk for the whole batch.
                        events.append(
                            {"type": "spinMeter", "value": 0, "max": spin_max}
                        )
        return events, feature_win, level

    def _free_spin_segment_multiplier(self, segment: str) -> float:
        if segment == "BONUS":
            return 0.0
        if segment.endswith("X"):
            return float(segment[:-1])
        return 0.0

    def _pick_free_spin_segment(self) -> str:
        """Weighted free-spin wheel landing — the visual wheel keeps 8 equal slices, but the landing is
        weighted (FREE_SPIN_WEIGHTS) so the big 100X / BONUS jackpots are rare and 0.5X–5X land often."""
        return py_random.choices(self.FREE_SPIN_SEGMENTS, weights=self.FREE_SPIN_WEIGHTS, k=1)[0]

    def build_feature_meter_events(
        self,
        *,
        outcomes: list[dict],
        row_count: int,
        stake_per_ball: float,
        balls_per_drop: int = 0,
        spin_meter_start: int = 0,
        bonus_meter_start: int = 0,
        bonus_level_start: int = 0,
        spin_meter_max: int = SPIN_METER_MAX,
        bonus_meter_max: int = BONUS_METER_MAX,
        force_bonus: bool = False,
        suppress_features: bool = False,
        spin_in_drop: bool = False,
        bonus_in_drop: bool = False,
        buy_entry_balls: int = 0,
        buy_levelup_head_start: float = 0.0,
        peg_hit_prob: float = BONUS_PEG_HIT_PROB,
        bonus_peg_hit_prob: float = -1.0,
        force_bonus_level: int = 0,
    ) -> tuple[list[dict], float, int, int, int]:
        """
        Walk server-authored ball flags and emit meter / feature book events.

        Returns (events, feature_win, spin_meter, bonus_meter, bonus_level). `feature_win`
        is the extra win on top of the base drop win, so the settled total is
        `drop_win + feature_win`.

        FREE SPIN (per-drop, in-drop): the spin meter is seeded at `spin_meter_start` (a fixed
        per-tier value, NOT carried across bets) and fills on each `hitSpinSlot`. When it reaches
        `spin_meter_max` WITHIN this drop, the free spin fires ONCE, on a TRAILING `freeSpinTrigger`
        after the drop walk. The weighted wheel multiplier applies to the BET PER BALL (a fixed base),
        so a numeric `M` adds `stake_per_ball × M`; a `BONUS` segment chains into a (free) bonus round.
        Gated by `spin_in_drop` so the 1-ball tier (off) never fires.

        BONUS (OPTION A — PER-DROP meter trigger, FREE, stateless): the bonus meter is seeded at
        `bonus_meter_start` (a fixed per-tier value, NOT carried across bets) and fills on each
        `hitBonusPeg` WITHIN this drop. When it reaches `bonus_meter_max` (gated by `bonus_in_drop`, off
        on 1-ball), the bonus fires IN-DROP — the whole multi-level `simulate_bonus_round` resolves in
        THIS book and settles `drop + bonus` (one bet, no cross-bet state). A small `force_bonus` QUOTA
        (`BONUS_IN_DROP_RATE`, a fine-tune top-up on 10/20/50 — the 1-ball tier's rate is 0.0 and its
        stratum is omitted) marks a book as a guaranteed bonus, but it does NOT bypass the meter:
        `gamestate.py` pre-fills the drop's coin-peg flags so the meter still fills 0 → max from real
        hits and `bonus_meter_fired` is already set by the time we get here. The board (~0.896) funds
        the free bonus. (`suppress_features` is unused now but kept for signature stability.)
        """
        _ = suppress_features  # unused (kept for signature stability)
        # `peg_hit_prob` fills the PAID DROP's trigger meter; `bonus_peg_hit_prob` climbs the level-up
        # ladder once a bonus is running. They are separate levers (a flat trigger rate wants a lively
        # meter but a slow climb) — a negative value means "not supplied", i.e. the pre-split behaviour
        # of using one number for both.
        bonus_peg = peg_hit_prob if bonus_peg_hit_prob < 0.0 else bonus_peg_hit_prob
        events: list[dict] = []
        feature_win = 0.0
        spin_meter = max(0, int(spin_meter_start))
        bonus_meter = max(0, int(bonus_meter_start))
        bonus_level = max(0, int(bonus_level_start))
        balls = balls_per_drop if balls_per_drop > 0 else 10

        # Walk the drop balls: fill the meters (visual) and detect the in-drop free spin + bonus (both
        # resolved AFTER the walk so their events trail the drop cleanly).
        free_spin_fired = False
        bonus_meter_fired = False
        for outcome in outcomes:
            if outcome.get("hitBonusPeg"):
                bonus_meter = min(bonus_meter_max, bonus_meter + 1)
                events.append(
                    {"type": "bonusMeter", "value": bonus_meter, "level": bonus_level}
                )
                if bonus_in_drop and not bonus_meter_fired and bonus_meter >= bonus_meter_max:
                    bonus_meter_fired = True
            if outcome.get("hitSpinSlot"):
                spin_meter = min(spin_meter_max, spin_meter + 1)
                events.append(
                    {"type": "spinMeter", "value": spin_meter, "max": spin_meter_max}
                )
                if spin_in_drop and not free_spin_fired and spin_meter >= spin_meter_max:
                    free_spin_fired = True

        # Resolve the in-drop free spin (trailing). Weighted wheel: numeric → stake × M; BONUS → chain a
        # (free) bonus round.
        if free_spin_fired:
            segment = self._pick_free_spin_segment()
            if segment == "BONUS":
                events.append(
                    {"type": "freeSpinTrigger", "segment": segment, "multiplier": 0.0, "amount": 0.0}
                )
                bonus_events, bonus_win, bonus_end_level = self.simulate_bonus_round(
                    row_count=row_count,
                    stake_per_ball=stake_per_ball,
                    balls_per_drop=balls,
                    peg_hit_prob=bonus_peg,
                )
                events.extend(bonus_events)
                feature_win += bonus_win
                bonus_level = max(bonus_level, bonus_end_level)
            else:
                multiplier = self._free_spin_segment_multiplier(segment)
                free_spin_win = stake_per_ball * multiplier
                feature_win += free_spin_win
                events.append(
                    {
                        "type": "freeSpinTrigger",
                        "segment": segment,
                        "multiplier": multiplier,
                        "amount": free_spin_win,
                    }
                )

        # Fire the bonus (once) when the per-drop meter filled in-drop OR the force_bonus quota selected
        # this book. The whole multi-level bonus resolves in THIS book → settles `drop + bonus`.
        if bonus_meter_fired or force_bonus:
            # SAFETY NET, currently UNREACHABLE — snap the meter to full so a fire always reads as a
            # completion. Every live `force_bonus` caller already arrives with a full meter: base quota
            # books get their coin-peg flags pre-filled by `ensure_coin_pegs_fill_meter` (gamestate.py),
            # and buy-bonus books enter with `bonus_meter_start = bonus_meter_max`. This only fires if a
            # future tier pairs a non-zero quota with `bonus_in_drop=False` — keep it so such a tier
            # can't emit a bonus over a half-empty meter, which the rules copy would contradict.
            if force_bonus and bonus_meter < bonus_meter_max:
                bonus_meter = bonus_meter_max
                events.append(
                    {"type": "bonusMeter", "value": bonus_meter, "level": bonus_level}
                )
            bonus_events, bonus_win, bonus_end_level = self.simulate_bonus_round(
                row_count=row_count,
                stake_per_ball=stake_per_ball,
                balls_per_drop=balls,
                # BUY BONUS: seed the bonus with the tier's FIXED entry balls (0 = draw the wheel) and the
                # tier's Fury-meter head-start (in-bonus level-up meter starting fill). The level-up
                # ladder is the shared one; the tier's own `peg_hit_prob` is what gates the climb.
                entry_balls_override=buy_entry_balls,
                levelup_head_start=buy_levelup_head_start,
                # DEEP-BONUS STRATUM: >0 makes this round climb to that level off real coin-peg hits.
                force_level=force_bonus_level,
                peg_hit_prob=bonus_peg,
            )
            events.extend(bonus_events)
            feature_win += bonus_win
            bonus_level = max(bonus_level, bonus_end_level)

        return events, feature_win, spin_meter, bonus_meter, bonus_level
