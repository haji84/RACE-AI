"""GitHub-only, source-bound daily KEIRIN A/B intake and immutable archive.

No S3, Cloudflare, Vercel, automatic wagering, retroactive forecasts or
false nationwide claims. Runs ONLY in the owner-enabled trusted main job.
The public calendar may be incomplete; the run reports that explicitly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import re

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_github_provider_stop as provider_stop
from scripts import keirin_register_public_day as registration
from scripts import keirin_capture_public_two_sources as collector
from scripts import keirin_nationwide_auto_forecast as generator

JST = timezone(timedelta(hours=9))
RID = re.compile(r"^20[0-9]{10}$")
MAX_RACES = 8
SCHEMA = "RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1"


class GitHubOnlyDayError(ValueError):
    pass


def require(cond, code):
    if not cond:
        raise GitHubOnlyDayError(code)


def private_root(path):
    root = collector.private_dir(path)
    for label in ("raw", "cards", "sealed", "safe"):
        p = root / label
        p.mkdir(mode=0o700, exist_ok=True)
        p.chmod(0o700)
        collector.private_dir(p)
    return root


def archived_day(repo, day):
    """Read and authenticate prior Git-only encrypted originals BEFORE GETs."""
    repo = archive._remote(repo, synthetic_local=False)
    head = archive._refresh(repo)
    if provider_stop.read(repo=repo, day=day, head=head) is not None:
        raise GitHubOnlyDayError("HOLD_PROVIDER_PREVIOUS_DAY_DENIAL_NO_RETRY")
    prefix = f"{archive.ROOT}/{day}/"
    _, paths = archive._cmd(repo, "ls-tree", "-r", "--name-only",
                            head, "--", prefix)
    found = {}
    named = set(paths.splitlines()) if paths else set()
    for path in sorted(named):
        require(path.startswith(prefix), "ARCHIVE_DAY_PATH_MISMATCH")
        if not path.endswith(".sealed.json"):
            require(path.endswith(".receipt.json"), "ARCHIVE_UNKNOWN_FILE")
            continue
        race_id = path[len(prefix):-len(".sealed.json")]
        require(RID.fullmatch(race_id) is not None and
                race_id[:8] == day.replace("-", ""),
                "ARCHIVE_DAY_RACE_ID_MISMATCH")
        sealed, receipt = archive._refs(race_id)
        require(sealed in named and receipt in named,
                "ARCHIVE_INCOMPLETE_CIPHER_RECEIPT_PAIR")
        raw = archive._show(repo, head, receipt)
        require(raw is not None, "ARCHIVE_RECEIPT_NOT_FOUND")
        try:
            digest = json.loads(raw[1])["cipher_sha256"]
        except (ValueError, KeyError, TypeError):
            raise GitHubOnlyDayError("ARCHIVE_RECEIPT_NOT_AUTHENTIC") from None
        archive._read_at(repo, head, race_id, digest)
        found[race_id] = digest
    for path in named:
        if path.endswith(".receipt.json"):
            race_id = path[len(prefix):-len(".receipt.json")]
            require(race_id in found, "ARCHIVE_ORPHAN_RECEIPT")
    return found


def select_unfrozen(manifest, already, max_races=MAX_RACES):
    """Do not request a previously frozen race, even on a later runner."""
    require(type(manifest) is dict and type(manifest.get("races")) is list,
            "CURRENT_DAY_MANIFEST_REQUIRED")
    require(type(already) is dict and 1 <= max_races <= MAX_RACES,
            "ARCHIVE_FILTER_OR_BUDGET_INVALID")
    remaining = [r for r in manifest["races"] if r["race_id"] not in already]
    # This limits pair GETs, not registry population or forecast denominators.
    return dict(manifest, races=remaining[:max_races]), len(remaining)


def run_day(*, day, workspace, private_dir_path, owner_public_pem,
            max_races=MAX_RACES, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    require(now.utcoffset() is not None and
            now.astimezone(JST).date().isoformat() == day,
            "NO_RETROSPECTIVE_OR_FUTURE_DAY_FORECAST")
    require(1 <= max_races <= MAX_RACES, "RACE_PROVIDER_BUDGET_INVALID")
    root = private_root(private_dir_path)
    repo = Path(workspace).resolve()
    key_path = Path(owner_public_pem)
    require(key_path.is_file() and not key_path.is_symlink(),
            "EXISTING_OWNER_RSA_PUBLIC_KEY_REQUIRED")

    # Preflight the Git state branch; never silently start a new empty archive.
    previous = archived_day(repo, day)

    def guarded_fetch(url):
        try:
            return collector.fetch_once(url)
        except collector.SourceCaptureError as exc:
            if str(exc) in provider_stop.CODES:
                provider_stop.append_once(
                    repo=repo, day=day, code=str(exc),
                    observed_at=clock().astimezone(timezone.utc).isoformat())
            raise

    registry, manifest, day_status = registration.register_day(
        day_jst=day, private_raw_dir=root / "raw", clock=clock,
        fetch=guarded_fetch)
    require(day_status.get("stopped_after_provider_error") is not True,
            "HOLD_PROVIDER_DENIED_BEFORE_RACECARD_GET_NO_RETRY")
    eligible, remaining = select_unfrozen(
        manifest, previous, max_races=max_races)
    if eligible["races"]:
        capture_status = collector.capture_cycle(
            day_manifest=eligible,
            registered_ids=generator.registered_race_ids(registry),
            private_cards_dir=root / "cards", private_raw_dir=root / "raw",
            clock=clock, fetch=guarded_fetch, max_races=max_races)
    else:
        capture_status = {"normalized_private_cards": 0,
                          "GET_pair_attempts": 0,
                          "states": {"ALL_LINKED_RACES_ALREADY_FROZEN": 1}}
    prediction = generator.run_cycle(
        registry=registry, private_racecards_dir=root / "cards",
        raw_pages_dir=root / "raw", private_cipher_dir=root / "sealed",
        owner_public_key_pem=key_path.read_bytes(), clock=clock)

    newly = []
    for row in prediction["records"]:
        if row["ciphertext_local_created"] is not True:
            continue
        race_id = row["race_id"]
        require(race_id not in previous and
                race_id in {r["race_id"] for r in eligible["races"]},
                "EXISTING_OR_UNLISTED_RACE_MUST_NOT_BE_REFORECAST")
        cipher = (root / "sealed" / (race_id + ".sealed.json")).read_bytes()
        expected = row["cipher_file_sha256"]
        require(sha256(cipher).hexdigest() == expected,
                "PRIVATE_CIPHER_SHA_CHANGED_BEFORE_GIT")
        written = archive.append_once(
            repo=repo, raw_cipher=cipher,
            expected_cipher_sha256=expected,
            producer_run_id=os.environ["GITHUB_RUN_ID"],
            producer_commit=os.environ["GITHUB_SHA"])
        require(written["state"] in {
            "GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED",
            "IDENTICAL_ORIGINAL_ALREADY_FROZEN_NO_NEW_WRITE"},
            "GITHUB_CIPHER_ARCHIVE_NOT_VERIFIED")
        newly.append({"race_id": race_id, "cipher_sha256": expected})
    require(len(newly) == prediction["same_job_sealed"],
            "CIPHER_GENERATED_BUT_NOT_PERSISTED")
    return {
        "schema": SCHEMA,
        "day_jst": day,
        "source_calendar_observed": True,
        "national_universe_verified": False,  # Kdreams alone is insufficient.
        "observed_races": prediction["registered_races"],
        "already_frozen_prior": len(previous),
        "unfrozen_linked_races_before_budget": remaining,
        "racecard_pairs_attempted": capture_status["GET_pair_attempts"],
        "normalized_cards": capture_status["normalized_private_cards"],
        "new_A_B_sealed": len(newly),
        "new_A_B_git_archived": len(newly),
        "official_results_scored": 0,
        "no_result_implies_no_miss": True,
        "provider_states": capture_status["states"],
        "prediction_states": prediction["statuses"],
        "new_encrypted_originals": newly,
        "no_plaintext_forecast_uploaded": True,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--private-root", required=True)
    ap.add_argument("--owner-public-pem", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--max-races", type=int, default=MAX_RACES)
    a = ap.parse_args(argv)
    try:
        report = run_day(
            day=a.day, workspace=a.workspace,
            private_dir_path=a.private_root, owner_public_pem=a.owner_public_pem,
            max_races=a.max_races)
        target = Path(a.report)
        require(target.is_absolute() and not target.exists() and
                not target.is_symlink() and
                target.parent.resolve() == (Path(a.private_root) / "safe").resolve(),
                "REPORT_MUST_STAY_IN_PRIVATE_SAFE_DIRECTORY")
        collector._write_once(target, generator.model.canonical(report) + b"\n")
        print(json.dumps({k: report[k] for k in (
            "day_jst", "observed_races", "already_frozen_prior",
            "racecard_pairs_attempted", "new_A_B_sealed",
            "new_A_B_git_archived", "official_results_scored",
            "national_universe_verified")}, sort_keys=True))
        return 0
    except (ValueError, KeyError, TypeError, OSError,
            archive.GitCipherArchiveError,
            provider_stop.ProviderStopError,
            collector.SourceCaptureError,
            registration.DayPublicRegistrationError):
        print('{"state":"HOLD_GITHUB_ONLY_LIVE_FORECAST_UNVERIFIED",'
              '"new_forecasts_claimed":0}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
