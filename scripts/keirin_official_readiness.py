"""Read-only configuration proof; never collect a provider or mutate Git state."""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import re
import subprocess

from cryptography.exceptions import UnsupportedAlgorithm
from scripts.keirin_official_day_pipeline import check_owner_private_key
from scripts.keirin_runtime_selection import nationwide_ab_selected


SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_SOURCE_FREE_READINESS_V1"
REPOSITORY = "haji84/RACE-AI"
REPOSITORY_ID = "1416489937"
STATE_REF = "refs/heads/state/keirin-encrypted-history"
READY = "CONFIGURATION_READY_LIVE_ACCEPTANCE_PENDING"
PRIVATE_KEY_ENV = "RACE_AI_KEIRIN_PRIVATE_RSA_PEM"


class ReadinessHold(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ReadinessHold(code)


def _git(repo, *args):
    # The RSA private key is used only by the Python validator, never handed
    # to Git. Git output/stderr and exceptions cannot become public messages.
    env = {key: value for key, value in os.environ.items() if key != PRIVATE_KEY_ENV}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        done = subprocess.run(["git", *args], cwd=repo, text=True,
                              encoding="utf-8", stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=20,
                              env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ReadinessHold("HOLD_GIT_READINESS_UNAVAILABLE") from None
    return done.returncode, done.stdout.strip()


def assess(*, repo):
    values = os.environ
    checks = {
        "trusted_main_context": False,
        "ab_autogen_enabled": values.get("RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED") == "true",
        "public_capture_enabled": values.get("RACE_AI_AB_PUBLIC_CAPTURE_ENABLED") == "true",
        "github_state_store_enabled": values.get("RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED") == "true",
        "external_source_store_unconfigured": values.get("RACE_AI_AB_SOURCE_S3_PREFIX", "") == "",
        "official_source_enabled": values.get("RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED") == "true",
        "owner_private_key_matches_pin": False,
        "origin_is_expected": False,
        "checkout_commit_matches_run": False,
        "state_branch_readable": False,
    }
    report = {"schema": SCHEMA, "checks": checks, "provider_requests": 0,
              "state_writes": 0, "live_acceptance_completed": False}
    try:
        event = values.get("GITHUB_EVENT_NAME")
        need(values.get("GITHUB_ACTIONS") == "true"
             and values.get("GITHUB_REPOSITORY") == REPOSITORY
             and values.get("GITHUB_REPOSITORY_ID") == REPOSITORY_ID
             and values.get("GITHUB_REF") == "refs/heads/main"
             and (event == "push" or (event == "workflow_dispatch"
                  and values.get("RACE_AI_KEIRIN_READINESS_MODE") == "readiness"))
             and re.fullmatch(r"[1-9][0-9]{0,16}", values.get("GITHUB_RUN_ID", ""))
             and re.fullmatch(r"[1-9][0-9]{0,8}", values.get("GITHUB_RUN_ATTEMPT", ""))
             and re.fullmatch(r"[0-9a-f]{40}", values.get("GITHUB_SHA", ""))
             and values["GITHUB_SHA"] != "0" * 40,
             "HOLD_UNTRUSTED_READINESS_CONTEXT")
        checks["trusted_main_context"] = True
        report.update(repository=REPOSITORY, run_id=values["GITHUB_RUN_ID"],
                      source_commit=values["GITHUB_SHA"])
        try:
            check_owner_private_key(values.get(PRIVATE_KEY_ENV, "").encode("utf-8"))
        except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
            fixed = {
                "EXISTING_OWNER_PRIVATE_SECRET_NOT_CONFIGURED",
                "EXISTING_OWNER_PRIVATE_SECRET_INVALID",
                "EXISTING_OWNER_RSA_PRIVATE_SECRET_REQUIRED",
                "OWNER_PUBLIC_SPKI_PIN_MISMATCH",
            }
            code = str(exc)
            raise ReadinessHold("HOLD_" + code if code in fixed else
                                "HOLD_OWNER_PRIVATE_KEY_NOT_VERIFIED") from None
        checks["owner_private_key_matches_pin"] = True
        repo = Path(repo)
        need(repo.is_absolute() and repo.is_dir() and not repo.is_symlink()
             and (repo / ".git").exists(), "HOLD_GIT_CHECKOUT_REQUIRED")
        status, origin = _git(repo, "remote", "get-url", "--all", "origin")
        need(status == 0 and origin in (
            "https://github.com/haji84/RACE-AI", "https://github.com/haji84/RACE-AI.git",
            "git@github.com:haji84/RACE-AI", "git@github.com:haji84/RACE-AI.git"),
            "HOLD_UNEXPECTED_GIT_REMOTE")
        checks["origin_is_expected"] = True
        status, commit = _git(repo, "rev-parse", "HEAD")
        need(status == 0 and commit == values["GITHUB_SHA"], "HOLD_CHECKOUT_COMMIT_MISMATCH")
        checks["checkout_commit_matches_run"] = True
        status, reference = _git(repo, "ls-remote", "--exit-code", "--refs", "origin", STATE_REF)
        need(status != 2, "HOLD_EXISTING_STATE_BRANCH_NOT_FOUND")
        need(status == 0, "HOLD_STATE_BRANCH_NOT_READABLE")
        need(re.fullmatch(r"[0-9a-f]{40}\t" + re.escape(STATE_REF), reference),
             "HOLD_STATE_BRANCH_RESPONSE_INVALID")
        checks["state_branch_readable"] = True
        report["observed_state_commit"] = reference.split("\t", 1)[0]
        # Existing frozen races can be settled without the independent new-card
        # capture opt-ins. This is configuration only, not source authority or
        # a claim that any official result was fetched or scored.
        report["independent_result_route_configured"] = bool(
            checks["github_state_store_enabled"] and
            checks["external_source_store_unconfigured"] and
            checks["official_source_enabled"])
        need(nationwide_ab_selected(values), "HOLD_NATIONWIDE_AB_NOT_SELECTED")
        need(checks["official_source_enabled"], "HOLD_OFFICIAL_AUTOMATED_SOURCE_NOT_ENABLED")
        report["state"] = READY
    except ReadinessHold as exc:
        report["state"] = str(exc)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    args = parser.parse_args(argv)
    report = assess(repo=args.repo)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
