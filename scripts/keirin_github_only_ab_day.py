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
from race_ai import keirin_github_capture_selection as selection_history
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


def archived_day(repo, day, *, provider_day=None):
    """Read and authenticate prior Git-only encrypted originals BEFORE GETs."""
    repo = archive._remote(repo, synthetic_local=False)
    head = archive._refresh(repo)
    if provider_stop.read_for_observed_day(
            repo=repo, day=provider_day or day, head=head) is not None:
        raise GitHubOnlyDayError("HOLD_PROVIDER_PREVIOUS_DAY_DENIAL_NO_RETRY")
    prefix = f"{archive.ROOT}/{day}/"
    _, paths = archive._cmd(repo, "ls-tree", "-r", "--name-only",
                            head, "--", prefix)
    found = {}
    named = set(paths.splitlines()) if paths else set()
    form_paths = {path for path in named if path.endswith(
        (".form.sealed.json", ".form.receipt.json"))}
    for path in sorted(named - form_paths):
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
    for path in named - form_paths:
        if path.endswith(".receipt.json"):
            race_id = path[len(prefix):-len(".receipt.json")]
            require(race_id in found, "ARCHIVE_ORPHAN_RECEIPT")
    for path in sorted(form_paths):
        suffix = ".form.sealed.json" if path.endswith(".form.sealed.json") else ".form.receipt.json"
        race_id = path[len(prefix):-len(suffix)]
        require(race_id in found, "ARCHIVE_CONDITIONED_WITHOUT_BASELINE")
        sealed, receipt = archive._form_refs(race_id)
        require(sealed in form_paths and receipt in form_paths,
                "ARCHIVE_INCOMPLETE_CONDITIONED_PAIR")
        if path == receipt:
            continue
        metadata = archive._show(repo, head, receipt)
        require(metadata is not None, "ARCHIVE_CONDITIONED_RECEIPT_MISSING")
        try:
            rec = json.loads(metadata[1])
            archive._read_conditioned_at(repo, head, race_id, rec["cipher_sha256"],
                found[race_id], rec["baseline_prediction_sha256"], rec["cohort_sha256"])
        except (ValueError, KeyError, TypeError):
            raise GitHubOnlyDayError("ARCHIVE_CONDITIONED_READBACK_INVALID") from None
    return found


def guarded_provider_fetch(repo, clock):
    """Latch a refusal before persistence, even if a downstream parser catches it."""
    stopped = None

    def fetch(url):
        nonlocal stopped
        if stopped is not None:
            raise stopped
        try:
            return collector.fetch_once(url)
        except collector.SourceCaptureError as exc:
            if str(exc) in provider_stop.CODES:
                stopped = exc
                provider_stop.record_denial(
                    repo=repo, code=str(exc),
                    observed_at=clock().astimezone(timezone.utc).isoformat())
            raise

    return fetch


def select_unfrozen(manifest, already, max_races=MAX_RACES, *, now=None,
                    selection_counts=None):
    """Bound GETs without letting expired/failed early race IDs starve the rest.

    Published hints only prioritize capture; source bytes and the actual save
    clock still determine whether a forecast can be created. Within ten minutes
    of the earliest eligible hint, fewer past selections take priority so a
    repeatedly failing prefix cannot block nearby races. Later deadline cohorts
    fill unused budget in order. Unknown clocks retain their bounded rotation.
    """
    require(type(manifest) is dict and type(manifest.get("races")) is list,
            "CURRENT_DAY_MANIFEST_REQUIRED")
    require(type(already) is dict and type(max_races) is int and
            1 <= max_races <= MAX_RACES,
            "ARCHIVE_FILTER_OR_BUDGET_INVALID")
    selection_counts = {} if selection_counts is None else selection_counts
    require(type(selection_counts) is dict and all(
        type(rid) is str and RID.fullmatch(rid) and
        rid[:8] == manifest.get("day_jst", "").replace("-", "") and
        type(count) is int and 0 <= count <= selection_history.MAX_EVENTS
        for rid, count in selection_counts.items()), "CAPTURE_SELECTION_COUNTS_INVALID")
    require(now is None or (isinstance(now, datetime) and
            now.utcoffset() is not None and
            now.astimezone(JST).date().isoformat() == manifest.get("day_jst")),
            "CAPTURE_SELECTION_CURRENT_DAY_CLOCK_REQUIRED")
    remaining = [r for r in manifest["races"] if r["race_id"] not in already]
    timed = []
    unknown = []
    for row in remaining:
        hint = row.get("cutoff_hint")
        if hint is None:
            unknown.append(row)
            continue
        cutoff = collector.when(hint)
        require(cutoff.astimezone(JST).date().isoformat() == manifest["day_jst"],
                "CUTOFF_SORT_HINT_MISSING_DAY_BINDING")
        if now is not None and cutoff < now + timedelta(seconds=65):
            continue
        timed.append((cutoff, row))
    timed.sort(key=lambda item: (item[0], item[1]["race_id"]))
    ordered_timed = []
    offset = 0
    while offset < len(timed):
        end = offset + 1
        horizon = timed[offset][0] + timedelta(minutes=10)
        while end < len(timed) and timed[end][0] <= horizon:
            end += 1
        cohort = sorted(timed[offset:end], key=lambda item: (
            selection_counts.get(item[1]["race_id"], 0), item[0], item[1]["race_id"]))
        ordered_timed.extend(row for _, row in cohort)
        offset = end
    unknown.sort(key=lambda row: row["race_id"])
    if now is not None and unknown:
        local = now.astimezone(JST)
        slot = (local.hour * 60 + local.minute) // 10
        batches = (len(unknown) + max_races - 1) // max_races
        offset = (slot % batches) * max_races
        unknown = unknown[offset:] + unknown[:offset]
    # This limits pair GETs, not registry population or forecast denominators.
    selected = ordered_timed + unknown
    return dict(manifest, races=selected[:max_races]), len(remaining)


def run_day(*, day, workspace, private_dir_path, owner_public_pem,
            max_races=MAX_RACES, clock=None, registration_data=None, fetch=None):
    """Capture either newly registered links or an already verified day cohort.

    An orchestrator supplying registration_data must also reuse its existing
    guarded_provider_fetch callable as fetch so refusal state spans both phases.
    The supplied registry digest, date and manifest are checked again here.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    require(now.utcoffset() is not None and
            now.astimezone(JST).date().isoformat() == day,
            "NO_RETROSPECTIVE_OR_FUTURE_DAY_FORECAST")
    require(1 <= max_races <= MAX_RACES, "RACE_PROVIDER_BUDGET_INVALID")
    require(fetch is None or callable(fetch), "CAPTURE_FETCH_CALLABLE_REQUIRED")
    root = private_root(private_dir_path)
    repo = Path(workspace).resolve()
    key_path = Path(owner_public_pem)
    require(key_path.is_file() and not key_path.is_symlink(),
            "EXISTING_OWNER_RSA_PUBLIC_KEY_REQUIRED")

    # Preflight the Git state branch; never silently start a new empty archive.
    previous = archived_day(repo, day)

    guarded_fetch = fetch if fetch is not None else guarded_provider_fetch(repo, clock)

    if registration_data is None:
        registry, manifest, day_status = registration.register_day(
            day_jst=day, private_raw_dir=root / "raw", clock=clock,
            fetch=guarded_fetch)
    else:
        require(type(registration_data) in (tuple, list) and
                len(registration_data) == 3 and
                all(type(part) is dict for part in registration_data),
                "PREPARED_DAY_REGISTRATION_REQUIRED")
        registry, manifest, day_status = registration_data
        require(all(doc.get("day_jst") == day
                    for doc in (registry, manifest, day_status)),
                "PREPARED_REGISTRATION_CURRENT_DAY_REQUIRED")
        registered_ids = generator.registered_race_ids(registry)
        require(all(rid[:8] == day.replace("-", "") for rid in registered_ids),
                "PREPARED_REGISTRY_RACE_DAY_MISMATCH")
        collector.manifest_check(manifest, registered_ids=registered_ids)
    require(day_status.get("stopped_after_provider_error") is not True,
            "HOLD_PROVIDER_DENIED_BEFORE_RACECARD_GET_NO_RETRY")
    prior_selections = selection_history.read_day(repo=repo, day=day)
    eligible, remaining = select_unfrozen(
        manifest, previous, max_races=max_races, now=clock(),
        selection_counts=prior_selections)
    if eligible["races"]:
        # Persist selections, not GET claims: a stop/error below may prevent
        # some or all selected races from reaching the provider in this run.
        selection_history.append_selected(
            repo=repo, day=day,
            selected_race_ids=[row["race_id"] for row in eligible["races"]],
            selected_at=clock().astimezone(timezone.utc).isoformat(),
            producer_run_id=os.environ["GITHUB_RUN_ID"],
            producer_run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
        capture_status = collector.capture_cycle(
            day_manifest=eligible,
            registered_ids=generator.registered_race_ids(registry),
            private_cards_dir=root / "cards", private_raw_dir=root / "raw",
            clock=clock, fetch=guarded_fetch, max_races=max_races)
    else:
        state = ("ALL_LINKED_RACES_ALREADY_FROZEN" if not remaining else
                 "NO_UNFROZEN_RACE_WITH_FUTURE_OR_UNKNOWN_CUTOFF_HINT")
        capture_status = {"normalized_private_cards": 0,
                          "GET_pair_attempts": 0,
                          "states": {state: 1}}
    prediction = generator.run_cycle(
        registry=registry, private_racecards_dir=root / "cards",
        raw_pages_dir=root / "raw", private_cipher_dir=root / "sealed",
        owner_public_key_pem=key_path.read_bytes(), clock=clock)

    newly = []
    cohort_sha = sha256(json.dumps(registry, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
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
            producer_commit=os.environ["GITHUB_SHA"], cohort_sha256=cohort_sha)
        require(written["state"] in {
            "GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED",
            "IDENTICAL_ORIGINAL_ALREADY_FROZEN_NO_NEW_WRITE"},
            "GITHUB_CIPHER_ARCHIVE_NOT_VERIFIED")
        archived = {"race_id": race_id, "cipher_sha256": expected,
                    "cohort_sha256":cohort_sha,
                    "conditioned_state":row.get("form_fall_shadow_state",
                                                "NO_CONDITIONED_ORIGINAL")}
        if row.get("form_fall_shadow_state") == "PRIVATE_CONDITIONED_SHADOW_SEALED":
            try:
                conditioned_path = root / "sealed" / (race_id + ".form.sealed.json")
                require(conditioned_path.is_file() and not conditioned_path.is_symlink() and
                        0 < conditioned_path.stat().st_size < archive.MAX_BYTES,
                        "CONDITIONED_CIPHER_FILE_INVALID")
                conditioned = conditioned_path.read_bytes()
                condition_sha = row["form_fall_shadow_file_sha256"]
                require(sha256(conditioned).hexdigest() == condition_sha,
                        "CONDITIONED_CIPHER_SHA_CHANGED_BEFORE_GIT")
                parent_sha = row["form_fall_baseline_sha256"]
                saved = archive.append_conditioned_once(
                    repo=repo, raw_cipher=conditioned,
                    expected_cipher_sha256=condition_sha,
                    expected_baseline_cipher_sha256=expected,
                    expected_baseline_prediction_sha256=parent_sha,
                    cohort_sha256=cohort_sha,
                    producer_run_id=os.environ["GITHUB_RUN_ID"],
                    producer_commit=os.environ["GITHUB_SHA"])
                require(saved["state"] in {
                    "GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED",
                    "IDENTICAL_CONDITIONED_ORIGINAL_ALREADY_FROZEN"},
                    "CONDITIONED_GIT_ARCHIVE_NOT_VERIFIED")
                archived.update(conditioned_state=saved["state"],
                    conditioned_cipher_sha256=condition_sha,
                    baseline_prediction_sha256=parent_sha)
            except (ValueError, TypeError, KeyError, OSError):
                # The already archived baseline stays usable. A partial pair
                # is explicit HOLD and cannot satisfy the four-arm live gate.
                archived["conditioned_state"] = "HOLD_CONDITIONED_GIT_ARCHIVE"
        newly.append(archived)
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
        "capture_selection_policy": "PERSISTED_LEAST_SELECTED_WITHIN_EARLIEST_10_MINUTES",
        "racecard_pairs_selected": len(eligible["races"]),
        "selection_record_is_not_get_evidence": True,
        "selected_unknown_cutoff_races": sum(
            row.get("cutoff_hint") is None for row in eligible["races"]),
        "racecard_pairs_attempted": capture_status["GET_pair_attempts"],
        "normalized_cards": capture_status["normalized_private_cards"],
        "new_A_B_sealed": len(newly),
        "new_A_B_git_archived": len(newly),
        "new_conditioned_A_B_git_archived": sum(
            "conditioned_cipher_sha256" in row for row in newly),
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
            provider_stop.ProviderStopPersistenceError,
            collector.SourceCaptureError,
            registration.DayPublicRegistrationError):
        print('{"state":"HOLD_GITHUB_ONLY_LIVE_FORECAST_UNVERIFIED",'
              '"new_forecasts_claimed":0}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
