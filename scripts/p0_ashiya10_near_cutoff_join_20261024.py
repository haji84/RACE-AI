"""One real same-race K+B+official exhibition+weather data audit.

2026-10-24 Ashiya 10R: strict capture + identity + original PR64/PR71
history formula. No fabricated information, no model inference until
independent source publication/rights/required-feature attestations.
One manual run, at most 8 GETs, bounded bytes, no retries/scheduling.
Raw provider data and athlete statistics never written to GitHub/logs.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.error import HTTPError, URLError
import hashlib
import json
import math
import os
import re
import sys

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import race_ai
for relative in ("pr64-parser-reference/race_ai", "pr71-existing-reference/race_ai"):
    p = HERE / relative
    if p.is_dir() and str(p) not in race_ai.__path__:
        race_ai.__path__.append(str(p))

from scripts.p0_real_b_k_pr71_history_join_20261024 import (
    parse_prior_K_preserving_complete_races,
)

K_DAYS = ("2026-10-18", "2026-10-19", "2026-10-20",
          "2026-10-21", "2026-10-22", "2026-10-23")
DAY = "2026-10-24"
RACE = "20261024-21-10"
CUTOFF = "2026-10-24T13:10:00+09:00"
BEFOREINFO = "https://www.boatrace.jp/owpc/pc/race/beforeinfo?hd=20261024&jcd=21&rno=10"
EVENT_REF = "refs/heads/p0-ashiya10-near-cutoff-20261024"
EVENT_ADMISSION = "20261024-ASHIYA10-SAME-RACE-ONCE"
MAX_BYTES = 4_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("unreviewed redirect")


def audit(*, env=None, opener=None, extractor=None, parser_k=None,
          parser_b=None, parser_details=None, parser_preview=None,
          form_model=None, clock=None):
    env = os.environ if env is None else env
    if (env.get("GITHUB_EVENT_NAME") != "push" or
        env.get("GITHUB_REF") != EVENT_REF or
        env.get("RACE_AI_FULL_ONE_RACE_ALLOWED") != EVENT_ADMISSION or
        len(env.get("GITHUB_SHA", "")) != 40):
        raise RuntimeError("one-shot admission missing")
    now = clock() if clock else datetime.now(timezone.utc)
    if now.utcoffset() is None:
        raise RuntimeError("timezone-aware evidence clock required")
    if now >= datetime.fromisoformat(CUTOFF):
        return {"schema": "RACE_AI_ONE_RACE_REAL_K_B_PREVIEW_JOIN_AUDIT_V1",
                "race_id": RACE, "status": "NO_FORECAST_CUTOFF_PASSED",
                "upstream_get_attempts": 0, "official_prediction": False}

    from race_ai.official_lzh_extract import extract_daily_lzh
    from race_ai.core import parse_b, parse_k
    from race_ai.official_b_snapshot_adapter import program_details
    from race_ai.official_race_updates import parse_update
    from race_ai.boat_feature_adapter import _historical_past
    extractor = extractor or extract_daily_lzh
    parser_k = parser_k or parse_k
    parser_b = parser_b or parse_b
    parser_details = parser_details or program_details
    form_model = form_model or _historical_past
    opened = opener or build_opener(NoRedirect(), HTTPSHandler())

    result = {
        "schema": "RACE_AI_ONE_RACE_REAL_K_B_PREVIEW_JOIN_AUDIT_V1",
        "race_id": RACE, "event_date_jst": DAY,
        "official_racecard_url": "https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261024&jcd=21&rno=10",
        "scheduled_cutoff_at_unattested": CUTOFF,
        "runner_started_at_claimed": now.isoformat(),
        "upstream_get_budget": 8,
        "upstream_get_attempts": 0,
        "raw_archive_retained": False,
        "original_html_republished": False,
        "individual_racer_values_logged": False,
        "original_upstream_publication_verified": False,
        "source_use_rights_independently_verified": False,
        "independent_server_receipt_for_prediction": False,
        "original_PR71_weights_changed": False,
        "official_prediction": False, "formal_hit_at_8_eligible": False,
        "model_run": False, "ordered_top8": None,
        "prediction_sha256": None,
        "status": "NO_FORECAST_UNVERIFIED"
    }

    def fetch(url, max_bytes, *, accept):
        if result["upstream_get_attempts"] >= 8:
            raise ValueError("source GET budget reached")
        result["upstream_get_attempts"] += 1
        with opened.open(Request(url, method="GET", headers={
                "Accept": accept, "User-Agent": "RACE-AI-one-race-source-audit/1"}),
                timeout=10) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("official URL or status mismatch")
            content = response.read(max_bytes+1)
            if not 0 < len(content) <= max_bytes:
                raise ValueError("source bytes exceed hard limit")
            return content

    def archive(day, kind):
        d = date.fromisoformat(day)
        url = (f"https://www1.mbrace.or.jp/od2/{kind}/{d:%Y%m}/"
               f"{kind.lower()}{d:%y%m%d}.lzh")
        compressed = fetch(url, MAX_BYTES, accept="application/octet-stream")
        if compressed[2:7] not in (
            b"-lh0-", b"-lh1-", b"-lh4-", b"-lh5-", b"-lh6-", b"-lh7-"
        ):
            raise ValueError("source LZH identity mismatch")
        clear = extractor(compressed, f"{kind}{d:%y%m%d}".upper()+".TXT")
        if not isinstance(clear, bytes) or not 0 < len(clear) <= MAX_BYTES:
            raise ValueError("expanded source invalid")
        return clear, hashlib.sha256(compressed).hexdigest()

    try:
        history = defaultdict(list)
        day_records = []
        for d in K_DAYS:
            if date.fromisoformat(d) >= date.fromisoformat(DAY):
                raise ValueError("K historical date must precede target event")
            raw, sha = archive(d, "K")
            try:
                rows = parser_k(raw, d)
                skipped = 0
                empty = 0
            except ValueError:
                rows, skipped, empty = parse_prior_K_preserving_complete_races(
                    raw, d, parser_k)
            if not rows:
                raise ValueError("K day no strictly valid past rows")
            for row in rows:
                rid = row.get("race_id")
                if not isinstance(rid, str) or not rid.startswith(d.replace("-", "")+"-"):
                    raise ValueError("K historic event day mismatch")
                pid = row.get("racer_id")
                if not isinstance(pid, str) or not re.fullmatch(r"\d{4}", pid):
                    raise ValueError("K racer key invalid")
                history[pid].append(row)
            day_records.append({"day_jst": d, "source_sha256": sha,
                                "valid_entrant_rows": len(rows),
                                "incomplete_races_excluded": skipped,
                                "empty_venue_blocks": empty})
        result["historical_K_sources"] = day_records
        result["historical_K_total_valid_entrant_rows"] = sum(
            r["valid_entrant_rows"] for r in day_records)

        raw, source_sha = archive(DAY, "B")
        entries = parser_b(raw, DAY)
        details, cutoffs = parser_details(raw, date.fromisoformat(DAY))
        if len(entries) != len(details) or cutoffs.get(RACE) != CUTOFF:
            raise ValueError("real B day or race cutoff mismatch")
        rows = sorted([x for x in entries if x["race_id"] == RACE],
                      key=lambda x: x["lane"])
        if len(rows) != 6 or [r["lane"] for r in rows] != list(range(1, 7)):
            raise ValueError("B six-lane roster incomplete")
        result["B_archive_sha256"] = source_sha
        result["B_identity_count"] = 6
        result["B_national_local_motor_candidates"] = 18

        history_counts = []
        accepted = 0
        excluded_fl = 0
        for entry in rows:
            pid = entry["racer_id"]
            detail = details.get((RACE, entry["lane"]))
            if not isinstance(detail, dict) or detail.get("racer_registration_id") != pid:
                raise ValueError("B roster to detailed motor allocation mismatch")
            prior = sorted(history.get(pid, []), key=lambda x: x["race_id"], reverse=True)
            usable = []
            for p in prior:
                if (p.get("st_status") != "OK" or
                    type(p.get("finish")) is not int or not 1 <= p["finish"] <= 6 or
                    type(p.get("st")) not in (float, int) or
                    not math.isfinite(p["st"]) or not 0 <= p["st"] <= 1):
                    excluded_fl += 1
                    continue
                rid = p["race_id"]
                usable.append({
                    "race_id": rid,
                    "race_day": rid[:4]+"-"+rid[4:6]+"-"+rid[6:8],
                    "finish_position": p["finish"], "start_seconds": p["st"]
                })
            history_counts.append(len(usable))
            if len(usable) >= 5:
                form, stability = form_model(usable[:30], DAY, now.isoformat())
                if any(type(value) not in (float, int) or not math.isfinite(value)
                       or not 0 <= value <= 100 for value in (form, stability)):
                    raise ValueError("PR71 original history score out of range")
                accepted += 1
        result["valid_K_history_counts_by_lane"] = history_counts
        result["six_lanes_with_at_least_5_K"] = accepted
        result["PR71_original_form_and_ST_candidate_count"] = 2*accepted
        result["K_F_L_or_invalid_rows_excluded_for_selected_racers"] = excluded_fl

        captured_beforeinfo = (clock() if clock else datetime.now(timezone.utc))
        if captured_beforeinfo >= datetime.fromisoformat(CUTOFF):
            raise ValueError("source cutoff reached before preview capture")
        html = fetch(BEFOREINFO, 1_000_000, accept="text/html")
        captured_at = (clock() if clock else datetime.now(timezone.utc)).isoformat()
        # A request started before cutoff but finished after cutoff cannot
        # become a valid pre-cutoff input snapshot.
        if datetime.fromisoformat(captured_at) >= datetime.fromisoformat(CUTOFF):
            raise ValueError("beforeinfo capture finished at/after sales cutoff")
        if parser_preview is None:
            info = parse_update(html, kind="beforeinfo", day=date.fromisoformat(DAY),
                                venue="21", race_no=10, source_url=BEFOREINFO,
                                captured_at=captured_at)
        else:
            info = parser_preview(html)
        if info.get("race_id") != RACE or info.get("closed_at") != CUTOFF:
            raise ValueError("beforeinfo identity or cutoff mismatch")
        result["beforeinfo_source_url"] = BEFOREINFO
        result["beforeinfo_source_sha256"] = hashlib.sha256(html).hexdigest()
        result["beforeinfo_captured_at_runner_claimed"] = captured_at
        result["beforeinfo_parser_status"] = info.get("status")
        result["beforeinfo_before_cutoff_by_runner_clock"] = bool(
            info.get("eligible_pre_race"))
        if info["status"] == "PENDING":
            result["preview_missing_reason"] = info.get("missing_reason")
            result["display_time_count"] = 0
            result["numeric_preview_ST_count"] = 0
            result["weather_wind_mps_available"] = False
            result["weather_wave_cm_available"] = False
        elif info["status"] == "AVAILABLE":
            observed = info.get("data", {})
            boats = observed.get("boats", [])
            joined = {b["lane"]: b["racer_registration_id"] for b in boats}
            expected = {r["lane"]: r["racer_id"] for r in rows}
            if joined != expected:
                raise ValueError("real K+B and beforeinfo registration IDs conflict")
            result["preview_six_registration_ids_match_B"] = True
            result["display_time_count"] = sum(
                b.get("display_time") is not None for b in boats)
            result["numeric_preview_ST_count"] = sum(
                b.get("preview_st_status") == "OK" and
                b.get("preview_st") is not None for b in boats)
            result["preview_ST_non_numeric_count"] = 6-result["numeric_preview_ST_count"]
            weather = observed.get("weather") or {}
            result["weather_wind_mps_available"] = weather.get("wind_speed_mps") is not None
            result["weather_wave_cm_available"] = weather.get("wave_height_cm") is not None
            result["weather_direction_angle_relative_to_course_verified"] = False
            result["water_surface_wet_factor_verified"] = False
            result["weather_provider_observed_at_verified"] = False
        else:
            raise ValueError("preview status unknown")

        result["joined_same_race_id"] = RACE
        result["joined_source_families"] = ["B", "PRIOR_K", "EXHIBITION", "WEATHER"]
        result["input_as_of_capture_claimed"] = captured_at
        # Required source publication/terms proofs remain absent. The existing
        # PR71 FULL adapter MUST NOT be called as if data were authorized.
        blockers = []
        if accepted < 6: blockers.append("MISSING_FIVE_PRIOR_K_SOME_LANES")
        if result["display_time_count"] < 6: blockers.append("MISSING_EXHIBITION_DISPLAY_TIME")
        if result["numeric_preview_ST_count"] < 6: blockers.append("MISSING_EXHIBITION_START_ST")
        if not result["weather_wind_mps_available"]: blockers.append("MISSING_WIND")
        if not result["weather_wave_cm_available"]: blockers.append("MISSING_WAVES")
        blockers += ["UNCERTIFIED_ORIGINAL_PUBLICATION_AT",
                     "SOURCE_PURPOSE_RIGHTS_NOT_VERIFIED",
                     "RELATIVE_WIND_ANGLE_NOT_PROVEN",
                     "WET_SURFACE_FACTOR_NOT_PROVEN",
                     "ACTUAL_FINAL_SALES_CUTOFF_UNVERIFIED"]
        result["PR71_existing_FULL_blockers"] = blockers
        result["status"] = "REAL_SAME_RACE_DATA_JOINED_MODEL_BLOCKED_BY_EVIDENCE"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError,
            ImportError, TypeError, KeyError, UnicodeError) as exc:
        result["status"] = "NO_FORECAST_SOURCE_OR_JOIN_UNVERIFIED"
        result["error_type"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            result["http_status"] = exc.code
    result["runner_finished_at_claimed"] = (
        clock() if clock else datetime.now(timezone.utc)).isoformat()
    return result


def main():
    try:
        result = audit()
    except RuntimeError:
        print("ONE_RACE_AUDIT_NOT_ADMITTED")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "REAL_SAME_RACE_DATA_JOINED_MODEL_BLOCKED_BY_EVIDENCE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
