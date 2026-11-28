"""Read-only compatibility for two SHA-bound 2026-11-18 evening batches.

Metadata must be acquired separately from authenticated GitHub HTTPS APIs.
Caller-provided dictionaries alone are not source authentication. Only the two
observed run/head/job/artifact identities and exact ZIP/original hashes below
are admitted. No clocks, original bytes, or absent legacy counters are changed.

Both original producer job logs identify CPython 3.11.18. The exact generator
blob at both heads is f899a2317cf38d1be8e8832eaa678af6666a7d4a. Python 3.12
changed float sum (https://docs.python.org/3.12/library/functions.html#sum).
The isolated, SHA-bound historical module uses 3.11 left-to-right addition;
all RSA/AES, plaintext SHA, prediction SHA, and full prediction equality checks
remain mandatory. Current generator globals and builtins are never modified.

This module has no file/network I/O, key discovery, source getter, or public
plaintext output. Missing evidence remains HOLD, never a modeled loss.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta, timezone
from hashlib import sha256
from io import BytesIO
from types import FunctionType, ModuleType
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED, ZIP_STORED
import json
import stat
import zlib

from . import keirin_github_origin_evidence as origin
from . import keirin_nationwide_auto_storage as storage
from . import keirin_nationwide_auto_settlement as settlement
from .keirin_nationwide_auto_generator import _python311_sum


DAY = "2026-11-18"
SCHEMA = "RACE_AI_KEIRIN_KNOWN_EVENING_ORIGIN_V1"
MODEL_SOURCE_SHA256 = "9aa0143192707733a9666f8d0dad70e589451f67943130796d3ed4af0387f413"
COHORT_IDS_SHA256 = "4e61297d267247b3d31640f8a0a699ba025092875bf6c31bda25288582fd8b05"
BRANCH = "research/keirin-six-phase-score-20261114"
WORKFLOW = ".github/workflows/keirin-nationwide-ab-auto.yml"
REPOSITORY = "haji84/RACE-AI"
REPOSITORY_ID = 1416489937
API = "https://api.github.com/repos/" + REPOSITORY
MAX_ARCHIVE = 8_000_000
MAX_MEMBER = 2_000_000


class LegacyEvidenceError(ValueError):
    """Stable safe reason codes; never echo source contents or keys."""


@dataclass(frozen=True)
class KnownBatch:
    run_id: int
    commit: str
    producer_job_id: int
    producer_job_name: str
    producer_artifact_id: int
    producer_artifact_name: str
    producer_zip_sha256: str
    readback_job_id: int
    readback_job_name: str
    readback_artifact_id: int
    readback_artifact_name: str
    readback_zip_sha256: str
    safe_member: str
    readback_member: str
    previous_count: int
    cipher_shas: tuple[tuple[str, str], ...]


BATCHES = {
    44290470874: KnownBatch(
        44290470874, "2f7ad8d2b9a0b40becf49dba01854b6cf86329e5",
        134754087945, "real-remaining-evening-batch", 14421950074,
        "keirin-real-evening-20261118-AB-AES",
        "0a4cd6b19ef51e7ebd115047c70457976c8f24abb1a619f4b15037eb20888b4e",
        134754399895, "real-evening-independent-cipher-runner", 14421795408,
        "keirin-real-evening-20261118-A-B-independent-SHA",
        "630ff0d678defd387a7314ee1a7bbf40934ae7b292190cae86faea21fc83649e",
        "night-batch-safe-report.json", "keirin-evening-independent-receipt.json", 2,
        (("202611182402", "81157e110140e97897729460fecf968f2435f955af8f00f1f3de639e6ecebdc3"),
         ("202611182403", "a511acebca62d696e7eda8df233cdca3cbfcd6e3367cb337a6d814336e244f54"),
         ("202611182404", "43b4ef2f958f151a5c0b2be8b650d5de1b6b7da441da53233dafced1d18b0a6f"),
         ("202611187401", "ea4666bc0ac7de67082d3f70b7318f9cce98bd89bec4659509924378a94f3cda"),
         ("202611187402", "d73bc2114e4562c02a09fef6329ffe125ce4404ae3138d35b6b875f159fcf7e9"),
         ("202611187403", "d3f073e839cb49a8b2a52a4a40d001f33e5a54edb52b194405cb2639fa2e4f7a"),
         ("202611187404", "8b8c4b28f3dadbd6a342a56b6b5eec5b1710953ec9b5828da9cbc81e3537a4f3"))),
    44291507386: KnownBatch(
        44291507386, "ff69cf8f90a4abc8bb80fe7c77fecc7f618457f5",
        134757608322, "real-night-after-previous-7-supplement", 14422440177,
        "keirin-real-evening-20261118-supplement-AB-AES",
        "449a56fe75c44761a4de8b1ddb902d9f3b2512ab188afb357692869903d26de3",
        134757864048, "real-night-supplement-independent-readback", 14420398888,
        "keirin-real-evening-20261118-supplement-independent-SHA",
        "f7ae76a1e8092d271a06ed95790be3775f2781e72944264dfe9b0f5c0d28b825",
        "supplement-safe-report.json", "keirin-night-supplement-sha.json", 9,
        (("202611182405", "67a99e78967cf86926a9b63fa96bf57c12f5822c4f238dfe72f8de912064a046"),
         ("202611182406", "60898480790faba60c23862015e0eba02645ff9d4604424d2be9142971e14cd8"),
         ("202611182407", "4bbabd3c6341f71f41082001c2cb3849d7b1692eeaa91299234f31162c727ea5"),
         ("202611182408", "fe833985905a978bbe06b105037527545925ca55f3aa2b0fa4d0f81b268e4d42"),
         ("202611182409", "582bda064972f49721306e335041c9804a5b8e735a313fa0da93fe3ccbabb0ad"),
         ("202611187406", "d4461cb5e7d9580451322c508f3f5b52b06c4d45c19efac524af3168f2b76190"),
         ("202611187407", "5b60843b367465f7f2f8c8942c562407834619eaf09e6b4848cb3d9e3eac0d0c"),
         ("202611187408", "b470e425fb3961fe9f69d30ba48df12591a199f8fc18c35f6a252412936afdad"),
         ("202611187409", "6f83bffc6d48332f18d400b711371201a6a8fc536acf02732e995e9a9e8ee731"))),
}


def _need(condition, code):
    if not condition:
        raise LegacyEvidenceError(code)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _legacy_model(source):
    _need(type(source) is bytes and sha256(source).hexdigest() == MODEL_SOURCE_SHA256,
          "LEGACY_MODEL_SOURCE_SHA_NOT_BOUND_TO_ORIGINAL_RUN")
    module = ModuleType("race_ai._sha_bound_20261118_python311_model")
    module.__dict__["sum"] = _python311_sum
    # The executable bytes above have one fixed, independently observed hash.
    exec(compile(source, "<sha-bound-20261118-generator>", "exec"), module.__dict__)
    return module


def generate_legacy_A_B(snapshot, *, generated_at, generator_source_bytes, max_tickets=12):
    return _legacy_model(generator_source_bytes).generate_A_B(
        snapshot, generated_at=generated_at, max_tickets=max_tickets)


def decrypt_legacy_original_pair(*, raw_cipher, expected_cipher_sha256,
                                 owner_private_pem, generator_source_bytes):
    """Reuse every strict crypto/lineage/replay check with isolated old runtime."""
    historic = _legacy_model(generator_source_bytes)
    original = settlement.decrypt_original_pair
    verifier = FunctionType(original.__code__, dict(original.__globals__, model=historic),
                            original.__name__, original.__defaults__, original.__closure__)
    verifier.__kwdefaults__ = original.__kwdefaults__
    return verifier(raw_cipher=raw_cipher, expected_cipher_sha256=expected_cipher_sha256,
                    owner_private_pem=owner_private_pem)


def _read_archive(raw, expected_digest, expected_members):
    _need(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE and
          sha256(raw).hexdigest() == expected_digest, "LEGACY_ZIP_DIGEST_MISMATCH")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            _need(len(entries) == len(expected_members) and
                  set(archive.namelist()) == set(expected_members) and
                  sum(entry.file_size for entry in entries) <= 4_000_000,
                  "LEGACY_ZIP_EXACT_MEMBERS_REQUIRED")
            result = {}
            for entry in entries:
                _need(not entry.is_dir() and not (entry.flag_bits & 1) and
                      not stat.S_ISLNK(entry.external_attr >> 16) and
                      entry.compress_type in (ZIP_STORED, ZIP_DEFLATED) and
                      0 < entry.file_size <= MAX_MEMBER,
                      "LEGACY_ZIP_MEMBER_TYPE_OR_BOUNDS_INVALID")
                with archive.open(entry) as source:
                    data = source.read(MAX_MEMBER + 1)
                _need(len(data) == entry.file_size, "LEGACY_ZIP_MEMBER_LENGTH_INVALID")
                result[entry.filename] = data
            return result
    except (BadZipFile, RuntimeError, NotImplementedError, zlib.error, OSError):
        raise LegacyEvidenceError("LEGACY_ZIP_UNREADABLE") from None


def _packet(packet, *, role, spec):
    _need(type(packet) is dict and all(key in packet for key in
          ("run", "job", "artifact", "archive_bytes")), "LEGACY_PACKET_REQUIRED")
    run, job, artifact = (packet[key] for key in ("run", "job", "artifact"))
    _need(all(type(obj) is dict for obj in (run, job, artifact)), "LEGACY_METADATA_REQUIRED")
    rid, job_id = spec.run_id, getattr(spec, role + "_job_id")
    artifact_id = getattr(spec, role + "_artifact_id")
    _need(type(run.get("id")) is int and run["id"] == rid and
          run.get("url") == f"{API}/actions/runs/{rid}" and
          run.get("head_sha") == spec.commit and run.get("head_branch") == BRANCH and
          run.get("event") == "pull_request" and run.get("path") == WORKFLOW,
          "LEGACY_RUN_ALLOWLIST_MISMATCH")
    for field in ("repository", "head_repository"):
        value = run.get(field)
        _need(type(value) is dict and value.get("id") == REPOSITORY_ID and
              value.get("full_name") == REPOSITORY, "LEGACY_FORK_OR_REPOSITORY_MISMATCH")
    _need(job.get("id") == job_id and job.get("run_id") == rid and
          job.get("url") == f"{API}/actions/jobs/{job_id}" and
          job.get("run_url") == run["url"] and job.get("head_sha") == spec.commit and
          job.get("name") == getattr(spec, role + "_job_name") and
          job.get("status") == "completed" and job.get("conclusion") == "success" and
          origin._id(job.get("runner_id")), "LEGACY_SUCCESSFUL_SEPARATE_RUNNER_REQUIRED")
    if "head_branch" in job:
        _need(job["head_branch"] == BRANCH, "LEGACY_JOB_BRANCH_MISMATCH")
    if "run_attempt" in job:
        _need(origin._id(job["run_attempt"]) and origin._id(run.get("run_attempt")) and
              job["run_attempt"] <= run["run_attempt"], "LEGACY_JOB_ATTEMPT_MISMATCH")
    created, started, completed = (origin._time(value) for value in
        (run.get("created_at"), job.get("started_at"), job.get("completed_at")))
    _need(created <= started <= completed, "LEGACY_SERVER_CLOCK_ORDER_INVALID")
    _need(artifact.get("id") == artifact_id and
          artifact.get("name") == getattr(spec, role + "_artifact_name") and
          artifact.get("url") == f"{API}/actions/artifacts/{artifact_id}" and
          artifact.get("archive_download_url") == f"{API}/actions/artifacts/{artifact_id}/zip",
          "LEGACY_ARTIFACT_ALLOWLIST_MISMATCH")
    lineage = artifact.get("workflow_run")
    _need(type(lineage) is dict and lineage.get("id") == rid and
          lineage.get("repository_id") == REPOSITORY_ID and
          lineage.get("head_repository_id") == REPOSITORY_ID and
          lineage.get("head_branch") == BRANCH and lineage.get("head_sha") == spec.commit,
          "LEGACY_ARTIFACT_RUN_LINEAGE_MISMATCH")
    _need(started <= origin._time(artifact.get("created_at")) <= completed,
          "LEGACY_ARTIFACT_OUTSIDE_SUCCESSFUL_JOB")
    raw, digest = packet["archive_bytes"], getattr(spec, role + "_zip_sha256")
    _need(type(raw) is bytes and type(artifact.get("size_in_bytes")) is int and
          artifact["size_in_bytes"] == len(raw) and artifact.get("digest") == "sha256:" + digest,
          "LEGACY_ZIP_API_DIGEST_OR_SIZE_MISMATCH")
    members = (("producer-summary.json", spec.safe_member) +
               tuple(f"sealed/{race}.sealed.json" for race, _ in spec.cipher_shas)
               if role == "producer" else (spec.readback_member,))
    return {"members": _read_archive(raw, digest, members), "started": started,
            "completed": completed, "runner_id": job["runner_id"]}


def _rows(report, schema):
    _need(type(report) is dict and report.get("schema") == schema and
          report.get("day_jst") == DAY and type(report.get("registered_races")) is int and
          report["registered_races"] == 79 and type(report.get("records")) is list and
          len(report["records"]) == 79, "LEGACY_REPORT_SCHEMA_OR_COHORT_INVALID")
    rows = {}
    for row in report["records"]:
        _need(type(row) is dict and type(row.get("race_id")) is str and
              origin.RID.fullmatch(row["race_id"]) and row["race_id"].startswith("20261118") and
              row["race_id"] not in rows, "LEGACY_REPORT_DUPLICATE_OR_INVALID_RACE")
        rows[row["race_id"]] = row
    _need(_digest(sorted(rows)) == COHORT_IDS_SHA256, "LEGACY_FROZEN_COHORT_CHANGED")
    return rows


def verify_known_batch(*, run_id, producer, readback, official_cutoffs_by_race,
                       generator_source_bytes):
    """Verify unchanged legacy ZIPs and conservative GitHub server time bounds."""
    _need(type(run_id) is int and run_id in BATCHES, "LEGACY_RUN_NOT_IN_ALLOWLIST")
    _legacy_model(generator_source_bytes)
    spec = BATCHES[run_id]
    expected = dict(spec.cipher_shas)
    _need(type(official_cutoffs_by_race) is dict and set(expected) <= set(official_cutoffs_by_race),
          "LEGACY_OFFICIAL_CUTOFF_REQUIRED_FOR_EACH_ORIGINAL")
    first = _packet(producer, role="producer", spec=spec)
    second = _packet(readback, role="readback", spec=spec)
    _need(first["runner_id"] != second["runner_id"] and
          second["started"] >= first["completed"], "LEGACY_INDEPENDENT_RUNNER_ORDER_REQUIRED")
    reports = first["members"]
    producer_report = origin._json_report(reports["producer-summary.json"])
    _need(set(producer_report) == {"schema", "day_jst", "registered_races", "records"},
          "LEGACY_ORIGINAL_PRODUCER_FIELDS_CHANGED")
    p_rows = _rows(producer_report, "RACE_AI_KEIRIN_NATIONWIDE_AUTO_GENERATION_CYCLE_V1")
    safe = origin._json_report(reports[spec.safe_member])
    s_rows = _rows(safe, "RACE_AI_KEIRIN_REAL_20261118_EVENING_AB_AUTO_BATCH_V1")
    reader = origin._json_report(second["members"][spec.readback_member])
    r_rows = _rows(reader, "RACE_AI_KEIRIN_NATIONWIDE_AB_CIPHER_SECOND_RUNNER_V1")
    count = len(expected)
    _need(set(p_rows) == set(r_rows) == set(s_rows) and
          type(safe.get("new_A_B_same_job_encrypted")) is int and
          safe["new_A_B_same_job_encrypted"] == count and
          type(safe.get("previously_sealed_A_B_do_not_recreate")) is int and
          safe["previously_sealed_A_B_do_not_recreate"] == spec.previous_count and
          type(safe.get("official_result_scored")) is int and safe["official_result_scored"] == 0 and
          safe.get("organizer_actual_sales_close_independently_verified") is False and
          safe.get("source_html_and_plain_predictions_not_in_this_report") is True and
          type(reader.get("independent_cipher_file_shas_ok")) is int and
          reader["independent_cipher_file_shas_ok"] == count and
          reader.get("RSA_private_decryption_verified") is False and
          reader.get("actual_official_result_verified") is False,
          "LEGACY_ORIGINAL_SUMMARY_COUNTS_OR_CLAIMS_CHANGED")
    for document, rows in ((safe, s_rows), (reader, r_rows)):
        _need(document.get("statuses") == dict(Counter(row.get("state") for row in rows.values())),
              "LEGACY_STATUS_COUNTS_MISMATCH")
    originals, proofs, counts = {}, {}, {}
    latest = max(first["completed"], second["completed"])
    for rid in sorted(p_rows):
        p, r, s = p_rows[rid], r_rows[rid], s_rows[rid]
        _need(type(p.get("ciphertext_local_created")) is bool,
              "LEGACY_ORIGINAL_CREATED_FLAG_INVALID")
        if rid not in expected:
            _need(set(p) == {"race_id", "ciphertext_local_created"} and
                  p["ciphertext_local_created"] is False and
                  r == {"race_id": rid, "state": "HOLD_NO_CIPHER_TO_VERIFY"} and
                  s.get("state") != "REAL_A_B_RSA_AES_SEALED_SAME_JOB",
                  "LEGACY_UNSAVED_RACE_CANNOT_GAIN_A_FORECAST")
            continue
        raw = reports[f"sealed/{rid}.sealed.json"]
        digest = expected[rid]
        _need(sha256(raw).hexdigest() == digest, "LEGACY_ORIGINAL_CIPHER_SHA_MISMATCH")
        envelope = storage.validate_cipher(origin._json_report(raw))
        _need(envelope["race_id"] == rid and p == {
            "race_id": rid, "ciphertext_local_created": True, "cipher_file_sha256": digest,
            "A_cipher_sha256": envelope["A"]["ciphertext_sha256"],
            "B_cipher_sha256": envelope["B"]["ciphertext_sha256"]} and r == {
            "race_id": rid, "state": "INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK",
            "cipher_file_sha256": digest}, "LEGACY_INDEPENDENT_REPORT_ORIGINAL_SHA_MISMATCH")
        _need(s.get("state") == "REAL_A_B_RSA_AES_SEALED_SAME_JOB" and
              s.get("ciphertext_file_sha256") == digest and
              s.get("public_source_facts_sha256") == envelope["original_source_sha256"] and
              s.get("cutoff_at") == envelope["published_cutoff_at"] and
              all(s.get(role + "_cipher_sha256") == envelope[role]["ciphertext_sha256"] and
                  type(s.get(role + "_tickets")) is int and 1 <= s[role + "_tickets"] <= 12
                  for role in ("A", "B")), "LEGACY_SAFE_SUMMARY_ORIGINAL_BINDING_MISMATCH")
        cutoff_text = official_cutoffs_by_race[rid]
        cutoff = origin._time(cutoff_text)
        _need(cutoff.astimezone(timezone(timedelta(hours=9))).date().isoformat() == DAY,
              "LEGACY_OFFICIAL_CUTOFF_DAY_MISMATCH")
        _need((cutoff - latest).total_seconds() >= 65,
              "LEGACY_GITHUB_SERVER_PRE_CUTOFF_MARGIN_NOT_PROVEN")
        proof = {"schema": SCHEMA, "state": "GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED",
                 "race_id": rid, "cipher_sha256": digest, "official_cutoff_at": cutoff_text,
                 "latest_server_evidence_at": latest.isoformat(), "minimum_margin_seconds": 65,
                 "producer_run_id": run_id, "readback_run_id": run_id, "producer_commit": spec.commit,
                 "readback_commit": spec.commit, "producer_job_id": spec.producer_job_id,
                 "readback_job_id": spec.readback_job_id, "producer_artifact_id": spec.producer_artifact_id,
                 "readback_artifact_id": spec.readback_artifact_id,
                 "producer_archive_sha256": spec.producer_zip_sha256,
                 "readback_archive_sha256": spec.readback_zip_sha256,
                 "generator_source_sha256": MODEL_SOURCE_SHA256, "original_python_runtime": "3.11.18",
                 "RSA_decryption_verified": False, "official_result_verified": False}
        proof["evidence_sha256"] = _digest(proof)
        proofs[rid] = proof
        originals[rid] = {"raw_cipher": raw, "cipher_sha256": digest,
                          "producer_run_id": str(run_id), "producer_commit": spec.commit}
        counts[rid] = {role: s[role + "_tickets"] for role in ("A", "B")}
    return {"originals_by_race": originals, "proofs_by_race": proofs,
            "ticket_counts_by_race": counts, "cohort_race_ids": sorted(p_rows)}
