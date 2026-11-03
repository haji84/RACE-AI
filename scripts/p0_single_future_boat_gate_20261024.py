"""2026-10-24 one-shot, real, future びわこ11R B-LITE admission gate.

One bounded official daily B GET. All downloaded bytes, racer IDs, stats and
temporary candidate values remain memory-only. No invented publication time,
sample_n or rights. If proof is missing, record NO_FORECAST, not a sham pick.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import race_ai

PARSER = ROOT / "pr64-parser-reference" / "race_ai"
if PARSER.is_dir():
    race_ai.__path__.append(str(PARSER))

DAY = "2026-10-24"
TARGET = "https://www1.mbrace.or.jp/od2/B/202610/b261024.lzh"
RACE = "20261024-11-11"
EXPECTED_REGISTRATIONS = ("4512", "4144", "4550", "5319", "4746", "3874")
EXPECTED_PUBLISHED_SCHEDULE = "2026-10-24T15:09:00+09:00"
OFFICIAL_RACECARD = "https://www.boatrace.jp/owpc/pc/race/racelist?hd=20261024&jcd=11&rno=11"
BRANCH = "refs/heads/p0-b-live-gate-20261024"
TOKEN = "20261024-BIWAKO11R-ONE"
MAX_BYTES = 4_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError("redirect disallowed")


def _time():
    return datetime.now(timezone.utc)


def pre_cutoff_gate(*, env=None, opener=None, extractor=None, parser=None, now=None):
    e = os.environ if env is None else env
    if (e.get("GITHUB_EVENT_NAME") != "push" or e.get("GITHUB_REF") != BRANCH
        or e.get("RACE_AI_B_LIVE_ONE_SHOT") != TOKEN
        or len(e.get("GITHUB_SHA", "")) != 40):
        raise ValueError("not admitted to one-shot workflow")
    current = now or _time()
    if current.tzinfo is None or current >= datetime.fromisoformat(EXPECTED_PUBLISHED_SCHEDULE):
        return {"schema": "RACE_AI_REAL_BOAT_LIVE_GATE_V1", "race_id": "boat:2026-10-24:boatrace-jcd-11:11",
                "status": "NO_FORECAST_GATE_STARTED_AFTER_PUBLISHED_CUTOFF",
                "one_shot_official_get_count": 0, "prediction_sha256": None,
                "formal_hit_at_8_eligible": False, "external_freeze_verified": False}
    state = {
        "schema": "RACE_AI_REAL_BOAT_LIVE_GATE_V1",
        "race_id": "boat:2026-10-24:boatrace-jcd-11:11",
        "source": TARGET,
        "official_racecard_url": OFFICIAL_RACECARD,
        "scheduled_cutoff_observed_independently_from_B_but_not_attested": EXPECTED_PUBLISHED_SCHEDULE,
        "runner_clock_started_at_unattested": current.isoformat(),
        "one_shot_official_get_count": 0,
        "raw_B_retained": False,
        "source_player_stats_republished": False,
        "official_source_publication_at_proven": False,
        "source_sample_n_verified": False,
        "source_use_rights_admitted": False,
        "source_metadata_complete": False,
        "research_shadow_predictions_created": 0,
        "model_executed": False,
        "prediction_sha256": None,
        "external_freeze_verified": False,
        "formal_hit_at_8_eligible": False,
        "official_result_verified": False,
        "status": "NO_FORECAST",
    }
    try:
        transport = opener or build_opener(NoRedirect(), HTTPSHandler())
        req = Request(TARGET, headers={"Accept": "application/octet-stream",
                      "User-Agent": "RACE-AI-one-B-day-bounded-validation/1"}, method="GET")
        state["one_shot_official_get_count"] = 1
        with transport.open(req, timeout=10) as response:
            if response.status != 200 or response.geturl() != TARGET:
                raise ValueError("unexpected upstream status or redirect")
            state["http_status"] = response.status
            state["http_date_hint_unattested"] = response.headers.get("Date")
            state["http_last_modified_hint_unattested"] = response.headers.get("Last-Modified")
            raw = response.read(MAX_BYTES + 1)
        if (not 25 <= len(raw) <= MAX_BYTES or raw[2:7] not in
            (b"-lh0-", b"-lh1-", b"-lh4-", b"-lh5-", b"-lh6-", b"-lh7-")):
            raise ValueError("invalid bounded LZH archive")
        state["archive_bytes"] = len(raw)
        state["archive_sha256"] = hashlib.sha256(raw).hexdigest()
        if extractor is None:
            from race_ai.official_lzh_extract import extract_daily_lzh
            extractor = extract_daily_lzh
        expanded = extractor(raw, "B261024.TXT")
        if len(expanded) > MAX_BYTES:
            raise ValueError("oversized expanded B")
        state["expanded_text_sha256"] = hashlib.sha256(expanded).hexdigest()
        if parser is None:
            from race_ai.core import parse_b
            from race_ai.official_b_snapshot_adapter import program_details
            def parser(value):
                return parse_b(value, DAY), *program_details(value, date(2026, 10, 24))
        entries, details, deadlines = parser(expanded)
        state["parsed_race_count"] = len(deadlines)
        state["parsed_entrant_count"] = len(entries)
        if len(entries) != 6 * len(deadlines) or len(details) != len(entries):
            raise ValueError("official B detailed join incomplete")
        observed_cutoff = deadlines.get(RACE)
        if observed_cutoff != EXPECTED_PUBLISHED_SCHEDULE:
            state["scheduled_cutoff_mismatch"] = True
            raise ValueError("independently observed and B-file scheduled cutoff disagree")
        roster = sorted(
            (x["lane"], x["racer_id"]) for x in entries if x["race_id"] == RACE
        )
        if roster != list(enumerate(EXPECTED_REGISTRATIONS, 1)):
            state["official_racelist_consistency"] = False
            raise ValueError("B and first-party official web roster differ")
        state["official_racelist_consistency"] = True
        if current >= datetime.fromisoformat(observed_cutoff):
            raise ValueError("no forecast after official scheduled cutoff")
        # Real B numeric candidates have been validated structurally, but
        # sample_n, upstream initial publish time and permissions are unknown.
        from race_ai.boat_b_feature_bridge import candidate_bridge
        mapped = candidate_bridge(
            entries, details, deadlines, event_date_jst=DAY,
            archive_url=TARGET, archive_sha256=state["archive_sha256"],
            observed_at_claimed=current.isoformat(),
            required_runner_keys=("ability", "recent_form", "start_reliability",
                "finishing_power", "course_compatibility", "stamina",
                "tactical_adaptability", "consistency", "motor_form",
                "start_timing", "lane_course_fit"),
            required_environment_keys=("wind_mps", "rain_mm_h", "humidity_pct",
                "air_temp_c", "surface_wetness", "wave_cm", "water_current_strength",
                "crosswind_factor", "tide_activity"),
        )
        selected = next((x for x in mapped["private_candidate_projection"]
                         if x["race_id"] == RACE), None)
        if selected is None:
            raise ValueError("missing target event in parsed B")
        state["real_B_candidate_count_for_selected_race"] = sum(
            len(x["candidates"]) for x in selected["participants"])
        state["real_B_feature_admitted_count"] = 0
        state["missing_required_B_LITE_metadata"] = [
            "source_publication_timestamp", "actual_statisical_sample_n",
            "source_purpose_specific_rights", "independent_freeze_receipt",
        ]
        state["status"] = "NO_FORECAST_B_LITE_INPUT_EVIDENCE_INSUFFICIENT"
    except (HTTPError, URLError, TimeoutError, OSError, RuntimeError, ValueError,
            ImportError, TypeError) as exc:
        state["status"] = "NO_FORECAST_SOURCE_OR_IDENTITY_VALIDATION_FAILED"
        state["error_type"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            state["http_status"] = exc.code
    finally:
        state["runner_clock_finished_at_unattested"] = _time().isoformat()
    return state


def main():
    try:
        report = pre_cutoff_gate()
    except ValueError:
        print("LIVE_GATE_NOT_ADMITTED")
        return 2
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    # Explicitly NO_FORECAST is expected: do not mark actual model as PASS.
    return 0 if report["status"] == "NO_FORECAST_B_LITE_INPUT_EVIDENCE_INSUFFICIENT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
