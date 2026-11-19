"""Opt-in, single-real-race PRIVATE owner intake + bounded third-party result probe.

Existing GitHub main workflow_dispatch only. Reuses PR102 RSA/AES helper,
the original owner-approved 71R sealed ciphertext, and the existing one-shot
keirin-mobile research probe. No forecasts are created, no results are
officially authenticated, no persisted state is altered, and no HTML is
published. Source and forecast content never enter public logs.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

from race_ai.keirin_manual71_owner_encrypted_intake import ManualBundleError
from race_ai.keirin_mobile_one_shot import (
    ACK, MobileProbeError, legacy_page_url, probe_one,
)
from scripts.keirin_manual71_owner_intake_cli import (
    restore_existing_owner_bundle, require_owner_runner,
)

DATE = "2026-11-17"
RACE_ID = "202611177507"
SHORT_ID = "75-07"
SRC_KIND = "THIRD_PARTY_NOT_KEIRIN_JP"
FORECAST_SHA = "4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68"
SCHEMA = "RACE_AI_KEIRIN_MATSUYAMA7_PRIVATE_PREFLIGHT_V1"
HEX = re.compile(r"^[0-9a-f]{64}$")


class PilotHold(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise PilotHold(reason)


def parse_forecast(private_dir):
    """Assert actual owner-authored 71R snapshot, not a retroactive fake suite."""
    p = Path(private_dir) / "forecast_v3.json"
    need(p.is_file() and not p.is_symlink() and
         sha256(p.read_bytes()).hexdigest() == FORECAST_SHA,
         "OWNER_FORECAST_SHA_MISMATCH")
    try:
        doc = json.loads(p.read_bytes())
    except (UnicodeError, ValueError):
        raise PilotHold("OWNER_FORECAST_JSON_INVALID") from None
    need(type(doc) is dict and doc.get("date") == DATE and
         type(doc.get("races")) is list and len(doc["races"]) == 71,
         "OWNER_71_RACE_IDENTITY_INVALID")
    rows = [r for r in doc["races"] if type(r) is dict and
            r.get("id") == SHORT_ID]
    need(len(rows) == 1 and rows[0].get("venue") == "松山" and
         rows[0].get("race") == 7, "PILOT_RACE_NOT_IN_ORIGINAL")
    picks = rows[0].get("ranked_picks")
    need(type(picks) is list and 1 <= len(picks) <= 12,
         "PILOT_TICKETS_MISSING")
    seen = set()
    for i, row in enumerate(picks, 1):
        need(type(row) is dict and row.get("rank") == i and
             type(row.get("cars")) is list and len(row["cars"]) == 3 and
             all(type(n) is int and 1 <= n <= 9 for n in row["cars"]) and
             len(set(row["cars"])) == 3,
             "PILOT_TICKETS_INVALID")
        cars = tuple(row["cars"])
        need(cars not in seen, "DUPLICATE_OWNER_PILOT_PICK")
        seen.add(cars)
    # The earlier publication metadata is known, but official cutoff
    # as-of / amendments are NOT independently verified in this pilot.
    return seen


def classify_one_result(observation, picks):
    """One candidate from the EXISTING research-only page probe.

    Even a matching outcome is unverified third-party research evidence.
    Never upgrade this to a machine-authenticated official final result.
    """
    if type(observation) is not dict:
        return ("SOURCE_RESPONSE_INVALID", False)
    if not (
        observation.get("schema") ==
        "RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1" and
        observation.get("source_kind") == SRC_KIND and
        observation.get("source_url") ==
        legacy_page_url("20261117",75,7) and
        observation.get("result_officially_authenticated") is False and
        observation.get("machine_collection_rights_verified") is False and
        observation.get("raw_page_stored") is False and
        observation.get("page_date_marker") is True and
        observation.get("page_race_marker") is True and
        type(observation.get("source_sha256")) is str and
        HEX.fullmatch(observation["source_sha256"]) is not None
    ):
        return ("SOURCE_RACE_OR_PROVENANCE_HOLD", False)
    c = observation.get("candidate_result")
    if type(c) is not dict or c.get("state") != "ONE_UNVERIFIED_PROVIDER_CANDIDATE":
        return ("SOURCE_NO_UNAMBIGUOUS_RESULT", False)
    t = c.get("triple")
    yen = c.get("payout_100yen")
    if (type(t) is not list or len(t) != 3 or
            not all(type(n) is int and 1 <= n <= 9 for n in t) or
            len(set(t)) != 3 or type(yen) is not int or
            not 100 <= yen <= 1_000_000_000):
        return ("SOURCE_RESULT_DATA_INVALID", False)
    # Private-only comparison, never published as a formal result.
    return ("THIRD_PARTY_PROVISIONAL_RESULT_JOINED", tuple(t) in picks)


def execute(*, env, workspace, helper, runner_temp,
            fetch_one=probe_one):
    """No network unless trusted workflow_dispatch and a valid secret exist."""
    report = {
        "schema": SCHEMA,
        "date_jst": DATE,
        "race_id": RACE_ID,
        "owner_forecast_sha256": FORECAST_SHA,
        "private_decryption": "HOLD",
        "source_check": "NOT_RUN",
        "source_attempts": 0,
        "official_result_authenticated": False,
        "independent_A_E_S_readback": False,
        "owner_html_browser_verified": False,
        "all_five_stages_passed": False,
        "71_race_rollout_allowed": False,
    }
    if (not require_owner_runner(env) or
            env.get("GITHUB_EVENT_NAME") != "workflow_dispatch"):
        report["private_decryption"] = "HOLD_NOT_TRUSTED_MAIN_DISPATCH"
        return report
    if not env.get("RACE_AI_KEIRIN_PRIVATE_RSA_PEM"):
        report["private_decryption"] = "HOLD_RSA_SECRET_MISSING"
        return report
    with TemporaryDirectory(prefix="keirin-one-race-owner-",dir=runner_temp) as scratch:
        private = Path(scratch) / "private"
        try:
            got = restore_existing_owner_bundle(
                env=env, workspace=workspace, helper=helper,
                private_dir=private)
            if got.get("state") != "OWNER_MANUAL71_PRIVATE_SOURCE_STAGED":
                report["private_decryption"] = "HOLD_ORIGINAL_INTAKE"
                return report
            picks = parse_forecast(private)
            report["private_decryption"] = "REAL_ORIGINAL_SHA_RESTORED"
            report["owner_original_count"] = got.get("source_files")
        except (ManualBundleError, PilotHold, OSError, ValueError, TypeError):
            report["private_decryption"] = "HOLD_RSA_OR_ORIGINAL_REJECTED"
            return report
        # One already-existing, manually opt-in research provider request.
        # Same race, no redirects, no retry, zero raw HTML retention.
        report["source_attempts"] = 1
        response = None
        try:
            response = fetch_one(
                "20261117",75,7,acknowledgement=ACK,route="legacy")
            state, reference_hit = classify_one_result(response, picks)
        except (MobileProbeError, OSError, TimeoutError) as exc:
            if isinstance(exc, MobileProbeError) and str(exc) == "SOURCE_NOT_IN_OWNER_PROFILE":
                report["source_attempts"] = 0
                state,reference_hit = "SOURCE_NOT_IN_OWNER_PROFILE",False
            else:
                state,reference_hit = "SOURCE_GET_FAILED_NO_RETRY",False
        report["source_check"] = state
        if (type(response) is dict and state ==
                "THIRD_PARTY_PROVISIONAL_RESULT_JOINED"):
            # Source SHA is safe metadata; its existence alone does NOT prove
            # source rights, immutable official result, or final authenticity.
            report["third_party_source_sha256"] = response["source_sha256"]
        report["private_reference_comparison_available"] = (
            state == "THIRD_PARTY_PROVISIONAL_RESULT_JOINED"
        )
        # Do not log a private predicted ticket, 3連単 hit, or payout.
        return report


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--workspace",required=True)
    p.add_argument("--helper",required=True)
    p.add_argument("--runner-temp",required=True)
    args=p.parse_args(argv)
    try:
        result=execute(env=os.environ,workspace=args.workspace,
                       helper=args.helper,runner_temp=args.runner_temp)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:
            f.write("## Matsuyama 7R private 71R intake + one-shot result probe\n")
            f.write("Original: "+result["private_decryption"]+"\n")
            f.write("Result: "+result["source_check"]+"\n")
            f.write("Official result, AES production, separate runner, owner browser: HOLD\n")
            f.write("No raw page, secret, original picks, payout or private HTML logged.\n")
        # The job is read-only research, not an acceptance pass.
        return 0
    except (OSError,ValueError,TypeError):
        print('{"schema":"RACE_AI_KEIRIN_MATSUYAMA7_PRIVATE_PREFLIGHT_V1","private_decryption":"HOLD_INPUT_REJECTED","all_five_stages_passed":false}')
        return 2


if __name__=="__main__":
    sys.exit(main())
