"""Frozen, odds-free, pre-exhibition seller-style shadow forecast v1.

This is a hypothesis derived from 103 prior public picks, not the seller's actual
method.  A prediction is formally eligible only when its private original and a
public SHA256 commitment are saved before 07:00 JST on race day.

No external requests, orders or side effects beyond explicitly requested file output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "seller-shadow-v1-20261104"
JST = ZoneInfo("Asia/Tokyo")
CUTOFF = time(7, 0)
MAX_RACES_PER_DAY = 5
THRESHOLD_NATIONAL = 5.6
THRESHOLD_WAKU = 7.8
VALID_CLASS = frozenset({"A1", "A2", "B1"})


def read_csv(path: str | Path) -> dict[str, dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        data = list(csv.DictReader(file))
    if not data:
        raise ValueError(f"CSV empty: {path}")
    indexed = {}
    for row in data:
        key = row.get("レースコード", "")
        if not (len(key) == 12 and key.isascii() and key.isdigit()):
            raise ValueError(f"Invalid race ID: {key!r}")
        if key in indexed:
            raise ValueError(f"Duplicate race ID: {key}")
        indexed[key] = row
    return indexed


def number(s: str | None) -> float | None:
    if s is None or not s.strip():
        return None
    try:
        x = float(s)
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def make_boats(card: dict[str, str], waku: dict[str, str]) -> list[dict]:
    boats = []
    for lane in range(1, 7):
        pre = f"艇{lane}_"
        nat = number(card.get(pre + "全国勝率"))
        course = number(waku.get(pre + "枠番別勝率"))
        if nat is None or course is None:
            raise ValueError(f"Missing nationality / course metric for lane {lane}")
        boats.append({"lane": lane, "national": nat, "course": course,
                      "class": card.get(pre + "級別", "")})
    return boats


def z(values: list[float], value: float) -> float:
    avg = sum(values) / len(values)
    variance = sum((v - avg) ** 2 for v in values) / len(values)
    return (value - avg) / math.sqrt(variance) if variance > 0 else 0.0


def purchase_tickets(boats: list[dict]) -> dict[str, list[dict]]:
    # 1st lane is always 1. Rank all remaining lanes as the second-position
    # candidate on z(national win) + z(same-lane historical win).
    rivals = boats[1:]
    national = [b["national"] for b in rivals]
    course = [b["course"] for b in rivals]
    seconds = sorted(rivals,
                     key=lambda b: (-(z(national, b["national"]) + z(course, b["course"])), b["lane"]))
    first_sec, backup_sec = seconds[0]["lane"], seconds[1]["lane"]

    def thirds(second: int) -> list[int]:
        choices = [b for b in rivals if b["lane"] != second]
        return [b["lane"] for b in sorted(choices,
                  key=lambda b: (-b["course"], -b["national"], b["lane"]))]

    top_third = thirds(first_sec)
    alt_third = thirds(backup_sec)
    pairs = [(first_sec, top_third[0]), (first_sec, top_third[1]),
             (backup_sec, alt_third[0]), (first_sec, top_third[2]),
             (backup_sec, alt_third[1])]
    picks = [f"1-{a}-{b}" for a, b in pairs]
    if len(picks) != len(set(picks)) or any(a == b for a, b in pairs):
        raise AssertionError("Unexpected repeated ticket")
    return {
        "three": [{"ticket": pick, "yen": stake} for pick, stake in
                  zip(picks[:3], [5000, 3000, 2000])],
        "five": [{"ticket": pick, "yen": 2000} for pick in picks],
    }


def race_score(boats: list[dict]) -> float:
    first = boats[0]
    return (2 * (first["national"] - 6.0) + (first["course"] - 8.0)
            + 0.5 * (first["national"] - max(b["national"] for b in boats[1:])))


def generate(cards: dict[str, dict[str, str]], waku: dict[str, dict[str, str]],
             day: date, at: datetime, *, dry_run: bool = False) -> dict:
    if at.tzinfo is None:
        raise ValueError("A timezone-aware execution timestamp is required")
    jst = at.astimezone(JST)
    cutoff = datetime.combine(day, CUTOFF, JST)
    # A user-provided clock can never establish a compliant freeze receipt.
    can_forecast = jst < cutoff
    if not can_forecast and not dry_run:
        raise ValueError("Past 07:00 JST; prospective predictions forbidden")
    if day.isoformat() < "2026-11-04" and not dry_run:
        raise ValueError("Historical dates must be explicitly tagged dry-run")
    if not cards or not waku:
        raise ValueError("Missing input datasets; do not pretend to predict")
    discovered = [k for k in sorted(cards) if k[:8] == day.strftime("%Y%m%d")]
    if not discovered:
        raise ValueError("No cards for target date")
    data = []
    eligible = []
    for race_id in discovered:
        card, w = cards[race_id], waku.get(race_id)
        if w is None:
            data.append({"race_id": race_id, "status": "NO_WAKU10"})
            continue
        try:
            boats = make_boats(card, w)
        except ValueError as e:
            data.append({"race_id": race_id, "status": "MISSING_INPUT", "reason": str(e)})
            continue
        first = boats[0]
        if (first["class"] not in VALID_CLASS or
                first["national"] < THRESHOLD_NATIONAL or
                first["course"] < THRESHOLD_WAKU):
            data.append({"race_id": race_id, "status": "FILTERED"})
            continue
        eligible.append((race_score(boats), race_id, boats))
    eligible.sort(key=lambda x: (-x[0], x[1]))
    for pos, (score, race_id, boats) in enumerate(eligible):
        if pos >= MAX_RACES_PER_DAY:
            data.append({"race_id": race_id, "status": "RANK_LIMIT"})
        else:
            data.append({"race_id": race_id, "status": "SHADOW_DRY_RUN" if dry_run else "LOCAL_UNATTESTED",
                         "score": round(score, 6), "tickets": purchase_tickets(boats)})
    data.sort(key=lambda x: x["race_id"])
    return {"model": VERSION, "date": day.isoformat(), "built_at_jst": jst.isoformat(),
            "status": "DRY_RUN_NOT_PROSPECTIVE" if dry_run else "AWAITING_INDEPENDENT_TIMESTAMP",
            "source": "locally supplied day-stamped race_cards + waku10 CSV",
            "discovered": len(discovered), "forecasted": sum("tickets" in x for x in data),
            "rows": data}


def commit_digest(forecast: dict) -> str:
    raw = json.dumps(forecast, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def settle(forecast: dict, payouts: dict[str, dict[str, str]],
           realtime: dict[str, dict[str, str]]) -> dict:
    # Never generate any new tickets from actual race outcomes.
    settled = []
    for row in forecast["rows"]:
        if "tickets" not in row:
            continue
        key = row["race_id"]
        p, rt = payouts.get(key), realtime.get(key)
        if not p or not rt:
            settled.append({"race_id": key, "status": "RESULT_UNVERIFIED"})
            continue
        win = p.get("3連単_組番", "")
        amount = number(p.get("3連単_払戻金"))
        if not win or amount is None:
            settled.append({"race_id": key, "status": "RESULT_UNVERIFIED"})
            continue
        cancelled = [str(i) for i in range(1, 7)
                     if (rt.get(f"{i}コース_F", "") or "").strip()]
        # F flags refer to physical entered lanes, which can differ from boat #.
        refund_boats = set()
        for lane in cancelled:
            number_entry = rt.get(f"{lane}コース_艇番", "")
            if not number_entry:
                raise ValueError(f"F course lacks boat ID {key}")
            refund_boats.add(number_entry)
        stats = {}
        for series in ("three", "five"):
            stake_total = 0
            returned = 0
            hit = False
            for ticket in row["tickets"][series]:
                stake = ticket["yen"]
                stake_total += stake
                nums = ticket["ticket"].split("-")
                if any(num in refund_boats for num in nums):
                    returned += stake
                elif ticket["ticket"] == win:
                    returned += stake / 100 * amount
                    hit = True
            stats[series] = {"hit": hit, "stake_yen": stake_total,
                             "return_yen": round(returned),
                             "profit_yen": round(returned - stake_total)}
        settled.append({"race_id": key, "status": "SETTLED", "result": win,
                        "payout_per_100yen": amount, "refund_boats": sorted(refund_boats),
                        "series": stats})
    return {"model": forecast["model"], "date": forecast["date"],
            "forecast_sha256": commit_digest(forecast), "rows": settled}


def cli() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["forecast", "settle"])
    parser.add_argument("--cards", help="Authorized race_cards daily CSV")
    parser.add_argument("--waku", help="Authorized waku10 daily CSV")
    parser.add_argument("--date", help="Race date YYYY-MM-DD")
    parser.add_argument("--forecast", help="Frozen original forecast JSON (settle only)")
    parser.add_argument("--payouts", help="Official results payouts CSV")
    parser.add_argument("--realtime", help="Official race results realtime CSV")
    parser.add_argument("--out", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.mode == "forecast":
        if not args.cards or not args.waku or not args.date:
            parser.error("forecast requires --cards --waku --date")
        result = generate(read_csv(args.cards), read_csv(args.waku),
                          date.fromisoformat(args.date), datetime.now(JST), dry_run=args.dry_run)
    else:
        if not args.forecast or not args.payouts or not args.realtime:
            parser.error("settle requires --forecast --payouts --realtime")
        original = json.loads(Path(args.forecast).read_text(encoding="utf-8"))
        if original.get("model") != VERSION:
            raise ValueError("Incompatible forecast version")
        result = settle(original, read_csv(args.payouts), read_csv(args.realtime))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create: no overwriting a pre-race frozen original.
    with out.open("x", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, sort_keys=True, indent=2)
        file.write("\n")
    print(json.dumps({"output": str(out), "sha256": commit_digest(result),
                      "status": result.get("status", "RESULTS_ONLY"),
                      "forecasted": result.get("forecasted")}, ensure_ascii=False))


if __name__ == "__main__":
    cli()