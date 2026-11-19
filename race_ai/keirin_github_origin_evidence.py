"""Validate GitHub-server timing for exact SHA-bound pre-race originals.

The caller MUST acquire run/job/artifact metadata from authenticated HTTPS
GitHub REST endpoints, and ZIP bytes from the corresponding artifact download.
Supplying JSON dictionaries is not itself authentication. This pure verifier
never performs network I/O, loads an RSA key, or certifies an official result.

The trusted workflow uses pinned upload-artifact v4: each artifact ID denotes
an immutable ZIP. The API digest hashes the uploaded ZIP stream, as implemented
by actions/toolkit's artifact upload and blob-upload code. We bind that digest
to the downloaded bytes, require artifact creation inside its successful job,
and use the GitHub job's completed_at as a conservative upload completion
bound. Git author/committer times and forecast self-reported clocks are ignored.
updated_at is metadata, so a later retention edit cannot invalidate unchanged
immutable bytes. No claim rests on updated_at.

API contracts: https://docs.github.com/en/rest/actions/artifacts
               https://docs.github.com/en/rest/actions/workflow-jobs
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import re
import stat
import zlib
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED


SCHEMA = "RACE_AI_KEIRIN_GITHUB_SERVER_ORIGIN_EVIDENCE_V1"
SHA = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
RID = re.compile(r"^20[0-9]{10}$")
TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$")
MAX_ARCHIVE_BYTES = 8_000_000
MAX_REPORT_BYTES = 2_000_000


class OriginEvidenceError(ValueError):
    """Only stable public error codes, never artifact contents or credentials."""


@dataclass(frozen=True)
class OriginPolicy:
    """Trusted integration configuration; never populate from provider JSON."""

    repository_full_name: str = "haji84/RACE-AI"
    repository_id: int = 1416489937
    allowed_ref: str = "refs/heads/main"
    allowed_events: tuple[str, ...] = ("schedule", "workflow_dispatch")
    producer_workflow_path: str = ".github/workflows/keirin-nationwide-ab-auto.yml"
    readback_workflow_path: str = ".github/workflows/keirin-nationwide-ab-auto.yml"
    producer_job_name: str = "github-only-owner-capture"
    readback_job_name: str = "github-only-independent-archive-readback"
    producer_artifact_name: str = "keirin-github-only-ab-receipt-{run_id}"
    readback_artifact_name: str = "keirin-github-only-ab-readback-{run_id}"
    producer_report_member: str = "summary.json"
    readback_report_member: str = "keirin-git-independent.json"
    producer_archive_members: tuple[str, ...] = ()
    readback_archive_members: tuple[str, ...] = ()
    report_format: str = "GITHUB_GIT"
    minimum_margin_seconds: int = 65


DEFAULT_POLICY = OriginPolicy()
UTSUNOMIYA_RACE = "202611182401"
UTSUNOMIYA_SHA = "dffc7303bfb722f75671751cee9a6356258263ec59b630f9dbdc6fc7953b5dfb"
UTSUNOMIYA_RUN = "44234778255"
UTSUNOMIYA_COMMIT = "0251b92e9947a6257fbd110c162665d5e4186ee8"
UTSUNOMIYA_POLICY = OriginPolicy(
    allowed_ref="refs/heads/research/keirin-six-phase-score-20261114",
    allowed_events=("pull_request",),
    producer_job_name="real-source-to-owner-aes-one-run",
    readback_job_name="real-source-cipher-independent-runner",
    producer_artifact_name="keirin-real-202611182401-source-AB-AES-20261118",
    readback_artifact_name="keirin-real-202611182401-independent-A-B-SHA",
    producer_report_member="producer-summary.json",
    readback_report_member="keirin-real-independent-readback.json",
    producer_archive_members=("producer-summary.json", "one-run-safe-summary.json",
                              "sealed/202611182401.sealed.json"),
    report_format="KNOWN_UTSUNOMIYA_V1",
)


def _need(condition, code):
    if not condition:
        raise OriginEvidenceError(code)


def _time(value):
    _need(type(value) is str and TIME.fullmatch(value),
          "GITHUB_SERVER_TIMESTAMP_REQUIRED")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc)
    except ValueError:
        raise OriginEvidenceError("GITHUB_SERVER_TIMESTAMP_INVALID") from None


def _id(value):
    return type(value) is int and 0 < value < 10**18


def _strict_pairs(pairs):
    out = {}
    for key, value in pairs:
        _need(key not in out, "ARTIFACT_DUPLICATE_JSON_FIELD")
        out[key] = value
    return out


def _json_report(content):
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=_strict_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              OriginEvidenceError("ARTIFACT_NONFINITE_JSON")))
    except OriginEvidenceError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise OriginEvidenceError("ARTIFACT_REPORT_UNREADABLE") from None


def _report(raw, member, digest, allowed_members=()):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE_BYTES and
          type(digest) is str and digest == "sha256:" + sha256(raw).hexdigest(),
          "GITHUB_ARTIFACT_ZIP_DIGEST_MISMATCH")
    try:
        expected_members = allowed_members or (member,)
        _need(type(expected_members) is tuple and 1 <= len(expected_members) <= 8 and
              member in expected_members, "ARTIFACT_MEMBER_POLICY_INVALID")
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            _need(len(entries) == len(expected_members) and
                  set(archive.namelist()) == set(expected_members),
                  "ARTIFACT_EXACT_REPORT_MEMBER_REQUIRED")
            members = {}
            for entry in entries:
                _need(not entry.is_dir() and not (entry.flag_bits & 1) and
                      not entry.filename.startswith("/") and
                      "\\" not in entry.filename and
                      all(part not in ("", ".", "..") for part in entry.filename.split("/")) and
                      not stat.S_ISLNK(entry.external_attr >> 16) and
                      entry.compress_type in (ZIP_STORED, ZIP_DEFLATED) and
                      0 < entry.file_size <= MAX_REPORT_BYTES,
                      "ARTIFACT_EXACT_REPORT_MEMBER_REQUIRED")
                with archive.open(entry) as source:
                    content = source.read(MAX_REPORT_BYTES + 1)
                _need(len(content) == entry.file_size,
                      "ARTIFACT_REPORT_SIZE_MISMATCH")
                members[entry.filename] = content
        return _json_report(members[member]), members
    except OriginEvidenceError:
        raise
    except (BadZipFile, ValueError, TypeError, KeyError, RuntimeError,
            UnicodeError, EOFError, OSError, RecursionError, zlib.error):
        raise OriginEvidenceError("ARTIFACT_REPORT_UNREADABLE") from None


def _checked_policy(policy):
    _need(isinstance(policy, OriginPolicy) and
          type(policy.repository_full_name) is str and
          re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
                       policy.repository_full_name) and
          _id(policy.repository_id) and
          type(policy.allowed_ref) is str and
          policy.allowed_ref.startswith("refs/heads/") and
          len(policy.allowed_ref) > len("refs/heads/") and
          type(policy.allowed_events) is tuple and policy.allowed_events and
          all(type(event) is str and event for event in policy.allowed_events) and
          policy.report_format in ("GITHUB_GIT", "KNOWN_UTSUNOMIYA_V1") and
          type(policy.minimum_margin_seconds) is int and
          65 <= policy.minimum_margin_seconds <= 3600,
          "TRUSTED_ORIGIN_POLICY_REQUIRED")
    return policy


def _bundle(packet, *, role, policy):
    _need(type(packet) is dict and all(k in packet for k in (
        "run", "job", "artifact", "archive_bytes")),
        "GITHUB_RUN_JOB_ARTIFACT_EVIDENCE_REQUIRED")
    run, job, artifact = (packet["run"], packet["job"], packet["artifact"])
    _need(all(type(value) is dict for value in (run, job, artifact)),
          "GITHUB_EVIDENCE_OBJECTS_REQUIRED")
    repository = policy.repository_full_name
    api = f"https://api.github.com/repos/{repository}"
    branch = policy.allowed_ref[len("refs/heads/"):]
    run_id = run.get("id")
    head = run.get("head_sha")
    _need(_id(run_id) and type(head) is str and COMMIT.fullmatch(head) and
          run.get("url") == f"{api}/actions/runs/{run_id}" and
          run.get("head_branch") == branch and
          run.get("event") in policy.allowed_events and
          run.get("path") == getattr(policy, role + "_workflow_path"),
          "GITHUB_RUN_IDENTITY_OR_TRUSTED_REF_MISMATCH")
    for name in ("repository", "head_repository"):
        repository_data = run.get(name)
        _need(type(repository_data) is dict and
              repository_data.get("id") == policy.repository_id and
              repository_data.get("full_name") == repository,
              "GITHUB_FORK_OR_REPOSITORY_MISMATCH")
    job_id = job.get("id")
    _need(_id(job_id) and job.get("run_id") == run_id and
          job.get("url") == f"{api}/actions/jobs/{job_id}" and
          job.get("run_url") == run["url"] and job.get("head_sha") == head and
          job.get("name") == getattr(policy, role + "_job_name") and
          job.get("status") == "completed" and job.get("conclusion") == "success",
          "GITHUB_SUCCESSFUL_TRUSTED_JOB_REQUIRED")
    # The REST API does not guarantee every optional runner/attempt field.
    if "head_branch" in job:
        _need(job["head_branch"] == branch, "GITHUB_JOB_BRANCH_MISMATCH")
    if "run_attempt" in job:
        # A results-only rerun increments the run attempt while retaining the
        # already successful original jobs. Their immutable IDs, same head and
        # artifact creation windows still bind the earlier upload exactly.
        _need(_id(job["run_attempt"]) and _id(run.get("run_attempt")) and
              job["run_attempt"] <= run["run_attempt"],
              "GITHUB_JOB_RUN_ATTEMPT_MISMATCH")
    created = _time(run.get("created_at"))
    started = _time(job.get("started_at"))
    completed = _time(job.get("completed_at"))
    _need(created <= started <= completed, "GITHUB_JOB_CLOCK_ORDER_INVALID")
    artifact_id = artifact.get("id")
    _need(_id(artifact_id) and
          artifact.get("url") == f"{api}/actions/artifacts/{artifact_id}" and
          artifact.get("archive_download_url") ==
              f"{api}/actions/artifacts/{artifact_id}/zip" and
          artifact.get("name") == getattr(policy, role + "_artifact_name").format(
              run_id=run_id), "GITHUB_ARTIFACT_IDENTITY_MISMATCH")
    artifact_run = artifact.get("workflow_run")
    _need(type(artifact_run) is dict and artifact_run.get("id") == run_id and
          artifact_run.get("repository_id") == policy.repository_id and
          artifact_run.get("head_repository_id") == policy.repository_id and
          artifact_run.get("head_branch") == branch and
          artifact_run.get("head_sha") == head,
          "GITHUB_ARTIFACT_RUN_LINEAGE_MISMATCH")
    artifact_created = _time(artifact.get("created_at"))
    _need(started <= artifact_created <= completed,
          "GITHUB_ARTIFACT_NOT_CREATED_IN_SUCCESSFUL_JOB")
    report, members = _report(packet["archive_bytes"],
                             getattr(policy, role + "_report_member"),
                             artifact.get("digest"),
                             getattr(policy, role + "_archive_members"))
    return {
        "run_id": run_id, "commit": head, "job_id": job_id,
        "artifact_id": artifact_id, "archive_sha256": artifact["digest"][7:],
        "started_at": started, "completed_at": completed,
        "runner_id": job.get("runner_id"), "report": report, "members": members,
    }


def _report_rows(report, *, role, day):
    producer = role == "producer"
    schema = ("RACE_AI_KEIRIN_GITHUB_ONLY_LIVE_AB_DAY_V1" if producer else
              "RACE_AI_KEIRIN_GITHUB_ONLY_AB_SECOND_RUNNER_V1")
    list_field = "new_encrypted_originals" if producer else "records"
    _need(type(report) is dict and report.get("schema") == schema and
          report.get("day_jst") == day and type(report.get(list_field)) is list and
          1 <= len(report[list_field]) <= 1000,
          "GITHUB_ORIGIN_REPORT_SCHEMA_OR_DAY_MISMATCH")
    rows = report[list_field]
    count_fields = (("new_A_B_sealed", "new_A_B_git_archived") if producer else
                    ("new_archived", "independently_verified"))
    _need(all(type(report.get(field)) is int and report[field] == len(rows)
              for field in count_fields), "GITHUB_ORIGIN_REPORT_COUNT_MISMATCH")
    found = {}
    for row in rows:
        _need(type(row) is dict, "GITHUB_ORIGIN_REPORT_RECORD_REQUIRED")
        rid, digest = row.get("race_id"), row.get("cipher_sha256")
        _need(type(rid) is str and RID.fullmatch(rid) and rid not in found and
              rid[:8] == day.replace("-", "") and type(digest) is str and
              SHA.fullmatch(digest), "GITHUB_ORIGIN_REPORT_RACE_OR_SHA_INVALID")
        if not producer:
            _need(row.get("state") == "SECOND_RUNNER_GITHUB_SHA_CONFIRMED",
                  "GITHUB_INDEPENDENT_SHA_READBACK_REQUIRED")
        found[rid] = digest
    return found


def _legacy_rows(report, *, role, day):
    producer = role == "producer"
    schema = ("RACE_AI_KEIRIN_NATIONWIDE_AUTO_GENERATION_CYCLE_V1" if producer else
              "RACE_AI_KEIRIN_NATIONWIDE_AB_CIPHER_SECOND_RUNNER_V1")
    _need(type(report) is dict and report.get("schema") == schema and
          report.get("day_jst") == day and type(report.get("records")) is list and
          1 <= len(report["records"]) <= 1000 and
          type(report.get("registered_races")) is int and
          report["registered_races"] == len(report["records"]),
          "LEGACY_ORIGIN_REPORT_SCHEMA_OR_COHORT_INVALID")
    found, cohort = {}, set()
    for row in report["records"]:
        _need(type(row) is dict, "LEGACY_ORIGIN_RECORD_REQUIRED")
        rid = row.get("race_id")
        _need(type(rid) is str and RID.fullmatch(rid) and rid not in cohort and
              rid[:8] == day.replace("-", ""), "LEGACY_ORIGIN_RACE_INVALID")
        cohort.add(rid)
        if producer:
            _need(type(row.get("ciphertext_local_created")) is bool,
                  "LEGACY_ORIGIN_CREATED_FLAG_REQUIRED")
            if not row["ciphertext_local_created"]:
                _need("cipher_file_sha256" not in row,
                      "LEGACY_UNGENERATED_RACE_CANNOT_HAVE_CIPHER")
                continue
        else:
            if row.get("state") != "INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK":
                _need(row.get("state") in (
                    "HOLD_NO_CIPHER_TO_VERIFY", "HOLD_INDEPENDENT_CIPHER_SHA_MISMATCH") and
                    "cipher_file_sha256" not in row,
                    "LEGACY_READBACK_STATUS_INVALID")
                continue
        digest = row.get("cipher_file_sha256")
        _need(type(digest) is str and SHA.fullmatch(digest),
              "LEGACY_ORIGIN_CIPHER_SHA_REQUIRED")
        found[rid] = digest
    counters = (("A_generated", "B_generated", "same_job_sealed") if producer else
                ("independent_cipher_file_shas_ok",))
    _need(all(type(report.get(field)) is int and report[field] == len(found)
              for field in counters), "LEGACY_ORIGIN_CREATED_COUNT_MISMATCH")
    return found, cohort


def verify_origin_evidence(*, race_id, raw_cipher, expected_cipher_sha256,
                           official_cutoff_at, expected_producer_run_id,
                           expected_producer_commit, producer, readback,
                           policy=DEFAULT_POLICY):
    """Return a safe origin receipt after checking separately acquired evidence.

    expected_producer_* come from the independently restored Git archive
    receipt for the exact ciphertext. policy is trusted code configuration.
    producer/readback each contain HTTPS-fetched run, job, artifact metadata
    and the exact downloaded archive_bytes. Do not accept these dictionaries
    directly from workflow_dispatch input or a caller-provided source manifest.
    """
    policy = _checked_policy(policy)
    _need(type(race_id) is str and RID.fullmatch(race_id) and
          type(expected_cipher_sha256) is str and SHA.fullmatch(expected_cipher_sha256) and
          type(raw_cipher) is bytes and 0 < len(raw_cipher) < 2_000_000 and
          sha256(raw_cipher).hexdigest() == expected_cipher_sha256,
          "IMMUTABLE_CIPHER_BYTES_OR_RACE_INVALID")
    _need(type(expected_producer_run_id) is str and
          re.fullmatch(r"[1-9][0-9]{0,16}", expected_producer_run_id) and
          type(expected_producer_commit) is str and COMMIT.fullmatch(expected_producer_commit),
          "ARCHIVED_PRODUCER_IDENTITY_REQUIRED")
    first = _bundle(producer, role="producer", policy=policy)
    second = _bundle(readback, role="readback", policy=policy)
    if policy.report_format == "KNOWN_UTSUNOMIYA_V1":
        _need(race_id == UTSUNOMIYA_RACE and
              expected_cipher_sha256 == UTSUNOMIYA_SHA and
              expected_producer_run_id == UTSUNOMIYA_RUN and
              expected_producer_commit == UTSUNOMIYA_COMMIT and
              first["job_id"] == 134568159169 and
              second["job_id"] == 134568309504 and
              first["artifact_id"] == 14396164775 and
              second["artifact_id"] == 14396547442 and
              first["run_id"] == second["run_id"] == int(UTSUNOMIYA_RUN) and
              first["commit"] == second["commit"] == UTSUNOMIYA_COMMIT,
              "KNOWN_LEGACY_ORIGIN_ALLOWLIST_MISMATCH")
    _need(str(first["run_id"]) == expected_producer_run_id and
          first["commit"] == expected_producer_commit,
          "ARCHIVED_PRODUCER_RUN_OR_COMMIT_MISMATCH")
    _need(first["job_id"] != second["job_id"] and
          first["artifact_id"] != second["artifact_id"] and
          second["started_at"] >= first["completed_at"],
          "INDEPENDENT_READBACK_JOB_REQUIRED")
    if _id(first["runner_id"]) and _id(second["runner_id"]):
        _need(first["runner_id"] != second["runner_id"],
              "INDEPENDENT_RUNNER_REQUIRED")
    cutoff = _time(official_cutoff_at)
    latest = max(first["completed_at"], second["completed_at"])
    _need((cutoff - latest).total_seconds() >= policy.minimum_margin_seconds,
          "GITHUB_SERVER_PRE_CUTOFF_MARGIN_NOT_PROVEN")
    day = f"{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}"
    if policy.report_format == "KNOWN_UTSUNOMIYA_V1":
        producer_rows, producer_cohort = _legacy_rows(
            first["report"], role="producer", day=day)
        readback_rows, readback_cohort = _legacy_rows(
            second["report"], role="readback", day=day)
        _need(producer_cohort == readback_cohort,
              "LEGACY_READBACK_COHORT_CHANGED")
        _need(first["members"].get(f"sealed/{race_id}.sealed.json") == raw_cipher,
              "LEGACY_EMBEDDED_CIPHER_BYTES_MISMATCH")
        safe = _json_report(first["members"]["one-run-safe-summary.json"])
        _need(type(safe) is dict and safe.get("schema") ==
              "RACE_AI_KEIRIN_REAL_SOURCE_ONE_RUN_AB_AES_RECEIPT_V1" and
              safe.get("race_id") == race_id and
              safe.get("cipher_sha256") == expected_cipher_sha256 and
              safe.get("same_job_AES_created") is True and
              safe.get("actual_result_scored") is False,
              "LEGACY_ONE_RUN_RECEIPT_MISMATCH")
    else:
        producer_rows = _report_rows(first["report"], role="producer", day=day)
        readback_rows = _report_rows(second["report"], role="readback", day=day)
    _need(producer_rows == readback_rows and
          producer_rows.get(race_id) == expected_cipher_sha256,
          "INDEPENDENT_REPORTS_DO_NOT_BIND_EXACT_CIPHER_SHA")
    receipt = {
        "schema": SCHEMA, "state": "GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED",
        "race_id": race_id, "cipher_sha256": expected_cipher_sha256,
        "official_cutoff_at": official_cutoff_at,
        "latest_server_evidence_at": latest.isoformat(),
        "minimum_margin_seconds": policy.minimum_margin_seconds,
        "RSA_decryption_verified": False, "official_result_verified": False,
    }
    for prefix, checked in (("producer", first), ("readback", second)):
        for key in ("run_id", "commit", "job_id", "artifact_id", "archive_sha256"):
            receipt[f"{prefix}_{key}"] = checked[key]
    receipt["evidence_sha256"] = sha256(json.dumps(
        receipt, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode()).hexdigest()
    return receipt


def verify_known_utsunomiya_origin(*, raw_cipher, official_cutoff_at,
                                  producer, readback):
    """Restore the one observed historical run; never authorize arbitrary PRs.

    The two original ZIPs, metadata, embedded sealed bytes and legacy reports
    are checked as stored. No report is relabelled into a newer schema. The
    immutable race/run/head/job/artifact allowlist cannot be supplied by input.
    """
    return verify_origin_evidence(
        race_id=UTSUNOMIYA_RACE, raw_cipher=raw_cipher,
        expected_cipher_sha256=UTSUNOMIYA_SHA,
        official_cutoff_at=official_cutoff_at,
        expected_producer_run_id=UTSUNOMIYA_RUN,
        expected_producer_commit=UTSUNOMIYA_COMMIT,
        producer=producer, readback=readback, policy=UTSUNOMIYA_POLICY)
