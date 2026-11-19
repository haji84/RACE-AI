"""Offline audit of the two genuine 2026-11-18 evening encrypted batches.

Use only JSON/ZIP evidence already obtained through authenticated GitHub APIs
and an independently saved official schedule with original source bytes.
No network requests, pickle input, forecast creation, scoring, or key discovery.
Inputs and the create-only safe audit must be outside the checkout in private
directories. The caller supplies the existing owner key explicitly.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import stat

from race_ai import keirin_github_origin_evidence as origin
from race_ai import keirin_legacy_evening_replay as legacy
from race_ai import keirin_official_public_source as official
from scripts.keirin_official_day_pipeline import restore_private_snapshot_json


ROOT = Path(__file__).resolve().parents[1]
PREFIXES = {44290470874: "evening", 44291507386: "supplement"}
SCHEMA = "RACE_AI_KEIRIN_LEGACY_EVENING_REPLAY_AUDIT_V1"


def _need(condition, code):
    if not condition:
        raise legacy.LegacyEvidenceError(code)


def _private_directory(path):
    path = Path(path)
    _need(path.is_absolute() and not path.is_symlink() and path.is_dir() and
          not path.resolve().is_relative_to(ROOT) and
          stat.S_IMODE(path.stat().st_mode) == 0o700, "PRIVATE_EXTERNAL_DIRECTORY_REQUIRED")
    return path


def _private_bytes(path, maximum):
    path = Path(path)
    _private_directory(path.parent)
    _need(not path.is_symlink() and not path.resolve().is_relative_to(ROOT),
          "PRIVATE_EXTERNAL_INPUT_REQUIRED")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        _need(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600 and
              0 < info.st_size <= maximum, "PRIVATE_INPUT_MODE_OR_SIZE_INVALID")
        raw = source.read(maximum + 1)
    _need(len(raw) == info.st_size, "PRIVATE_INPUT_CHANGED_WHILE_READING")
    return raw


def load_saved_packets(evidence_dir, run_id):
    """Read existing exact metadata and ZIP files; never contact a service."""
    _need(type(run_id) is int and run_id in PREFIXES, "LEGACY_RUN_NOT_IN_ALLOWLIST")
    folder = _private_directory(evidence_dir)
    prefix = PREFIXES[run_id]
    spec = legacy.BATCHES[run_id]
    run = origin._json_report(_private_bytes(folder / f"{prefix}-run.json", 250_000))
    jobs = origin._json_report(_private_bytes(folder / f"{prefix}-jobs.json", 1_000_000))
    artifacts = origin._json_report(_private_bytes(folder / f"{prefix}-artifacts.json", 250_000))
    _need(type(jobs) is dict and type(jobs.get("jobs")) is list and
          type(artifacts) is dict and type(artifacts.get("artifacts")) is list,
          "LEGACY_SAVED_API_METADATA_REQUIRED")
    packets = {}
    for role, suffix in (("producer", "original"), ("readback", "independent")):
        selected_jobs = [row for row in jobs["jobs"] if type(row) is dict and
                         row.get("id") == getattr(spec, role + "_job_id")]
        selected_artifacts = [row for row in artifacts["artifacts"] if type(row) is dict and
                              row.get("id") == getattr(spec, role + "_artifact_id")]
        _need(len(selected_jobs) == len(selected_artifacts) == 1,
              "LEGACY_SAVED_EXACT_JOB_AND_ARTIFACT_REQUIRED")
        packets[role] = {
            "run": run, "job": selected_jobs[0], "artifact": selected_artifacts[0],
            "archive_bytes": _private_bytes(folder / f"{prefix}-{suffix}.zip", legacy.MAX_ARCHIVE),
        }
    return packets


def audit_saved_originals(*, evidence_dir, schedule, owner_private_pem, generator_source_bytes):
    """Authenticate/replay originals only; no official result is scored here."""
    _need(official.reparse_day_schedule(schedule) and schedule.get("day_jst") == legacy.DAY,
          "OFFICIAL_SCHEDULE_ORIGINAL_BYTES_NOT_VERIFIED")
    cutoffs = {row["race_id"]: row["official_cutoff_at"] for row in schedule["races"]}
    _need(len(cutoffs) == 79 and legacy._digest(sorted(cutoffs)) == legacy.COHORT_IDS_SHA256,
          "LEGACY_OFFICIAL_COHORT_NOT_THE_ORIGINAL_79_RACES")
    rows = []
    for run_id in sorted(PREFIXES):
        packets = load_saved_packets(evidence_dir, run_id)
        batch = legacy.verify_known_batch(
            run_id=run_id, official_cutoffs_by_race=cutoffs,
            generator_source_bytes=generator_source_bytes, **packets)
        for rid, original in batch["originals_by_race"].items():
            manifest, forecast, _ = legacy.decrypt_legacy_original_pair(
                raw_cipher=original["raw_cipher"], expected_cipher_sha256=original["cipher_sha256"],
                owner_private_pem=owner_private_pem, generator_source_bytes=generator_source_bytes)
            counts = {role: len(forecast[role]["ranked_tickets"]) for role in ("A", "B")}
            _need(counts == batch["ticket_counts_by_race"][rid],
                  "LEGACY_ORIGINAL_TICKET_COUNT_DIFFERS_FROM_PRODUCER_REPORT")
            rows.append({
                "race_id": rid, "state": "ORIGIN_RSA_AES_AND_ORIGINAL_MODEL_REPLAY_VERIFIED",
                "cipher_sha256": original["cipher_sha256"],
                "prediction_sha256": forecast["prediction_sha256"],
                "original_source_sha256": manifest["original_source_sha256"],
                "A_plaintext_sha256": manifest["A"]["plaintext_sha256"],
                "B_plaintext_sha256": manifest["B"]["plaintext_sha256"],
                "A_count": counts["A"], "B_count": counts["B"],
                "original_published_cutoff_at": manifest["published_cutoff_at"],
                "official_cutoff_at": cutoffs[rid], "proof": batch["proofs_by_race"][rid],
                "official_result_scored": False,
            })
    _need(len({row["race_id"] for row in rows}) == len(rows), "LEGACY_BATCH_DUPLICATE_ORIGINAL")
    return {
        "schema": SCHEMA, "day_jst": legacy.DAY,
        "scope": "TWO_KNOWN_EVENING_BATCHES_ONLY",
        "state": "LEGACY_ORIGINALS_AND_REPLAY_VERIFIED_RESULTS_NOT_SCORED",
        "registered_races": len(cutoffs), "origin_and_replay_verified": len(rows),
        "originals_not_loaded_for_this_audit": len(cutoffs) - len(rows),
        "missing_originals_are_not_misses": True,
        "model_source_sha256": legacy.MODEL_SOURCE_SHA256,
        "original_python_runtime": "3.11.18", "predictions_never_rewritten": True,
        "official_results_scored": 0, "formal_accuracy_proven": False,
        "rows": sorted(rows, key=lambda row: row["race_id"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--schedule-json", required=True)
    parser.add_argument("--owner-private-key", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        _private_directory(output.parent)
        _need(not output.exists() and not output.is_symlink() and
              not output.resolve().is_relative_to(ROOT), "PRIVATE_CREATE_ONLY_AUDIT_REQUIRED")
        _private_directory(args.evidence_dir)
        schedule = restore_private_snapshot_json(origin._json_report(
            _private_bytes(args.schedule_json, 32_000_000)))
        key = _private_bytes(args.owner_private_key, 20_000)
        source = (ROOT / "race_ai/keirin_nationwide_auto_generator.py").read_bytes()
        report = audit_saved_originals(evidence_dir=args.evidence_dir, schedule=schedule,
                                      owner_private_pem=key, generator_source_bytes=source)
        del key
        raw = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as destination:
            destination.write(raw)
            destination.flush()
            os.fsync(destination.fileno())
        print(json.dumps({key: report[key] for key in (
            "state", "registered_races", "origin_and_replay_verified",
            "originals_not_loaded_for_this_audit", "official_results_scored")}, sort_keys=True))
        return 0
    except (ValueError, TypeError, KeyError, OSError, StopIteration):
        print('{"origin_and_replay_verified":0,"state":"HOLD_LEGACY_PRIVATE_AUDIT_FAILED"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
