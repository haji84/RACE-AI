"""Independent GitHub runner verifies newly archived A/B ciphertext by SHA.

This does not decrypt the RSA envelope or certify official result/cutoff.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json
import os

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as official_archive
from scripts import keirin_github_only_ab_day as day

SCHEMA = "RACE_AI_KEIRIN_GITHUB_ONLY_AB_SECOND_RUNNER_V1"


def _archived_rows(report):
    day.require(type(report) is dict and
                report.get("schema") == day.SCHEMA and
                type(report.get("new_encrypted_originals")) is list,
                "PRIOR_GITHUB_ONLY_REPORT_SCHEMA_REQUIRED")
    return report["new_encrypted_originals"]


def verify(*, report, repo, archive_head=None):
    """Check the producer receipt against Git, optionally at a fetched immutable archive tip."""
    found = set()
    rows = []
    for row in _archived_rows(report):
        rid = row.get("race_id")
        digest = row.get("cipher_sha256")
        day.require(type(rid) is str and rid not in found and
                    rid[:8] == report["day_jst"].replace("-", "") and
                    type(digest) is str, "BAD_ARCHIVE_OR_DUPLICATE_RACE")
        found.add(rid)
        if archive_head is None:
            verified = archive.read_original(
                repo=repo, race_id=rid, expected_cipher_sha256=digest)
            baseline_ok = verified["state"] == "ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK"
        else:
            baseline_ok = archive._read_at(repo, archive_head, rid, digest) is not None
        day.require(baseline_ok, "INDEPENDENT_GITHUB_READBACK_NOT_VERIFIED")
        checked = {"race_id": rid,
                   "state": "SECOND_RUNNER_GITHUB_SHA_CONFIRMED",
                   "cipher_sha256": digest,
                   "conditioned_state":(
                       "NO_CONDITIONED_ORIGINAL" if row.get("conditioned_state") in
                       (None, "NO_CONDITIONED_ORIGINAL", "NO_FORM_SOURCE_BASELINE_ONLY")
                       else "HOLD_CONDITIONED_SECOND_RUNNER_READBACK")}
        if row.get("conditioned_state") in {
                "GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED",
                "IDENTICAL_CONDITIONED_ORIGINAL_ALREADY_FROZEN"}:
            try:
                condition_sha = row["conditioned_cipher_sha256"]
                parent_sha = row["baseline_prediction_sha256"]
                cohort_sha = row["cohort_sha256"]
                if archive_head is None:
                    result = archive.read_conditioned_original(
                        repo=repo, race_id=rid, expected_cipher_sha256=condition_sha,
                        expected_baseline_cipher_sha256=digest,
                        expected_baseline_prediction_sha256=parent_sha, cohort_sha256=cohort_sha)
                    conditioned_ok = result["state"] == "ENCRYPTED_GIT_CONDITIONED_SHA_READBACK_OK"
                else:
                    result = archive._read_conditioned_at(repo, archive_head, rid, condition_sha,
                                                          digest, parent_sha, cohort_sha)
                    conditioned_ok = result is not None
                day.require(conditioned_ok, "INDEPENDENT_CONDITIONED_GITHUB_READBACK_NOT_VERIFIED")
                checked.update(
                    conditioned_state="SECOND_RUNNER_CONDITIONED_GITHUB_SHA_CONFIRMED",
                    conditioned_cipher_sha256=condition_sha,
                    baseline_prediction_sha256=parent_sha, cohort_sha256=cohort_sha)
            except (ValueError, TypeError, KeyError, OSError):
                checked["conditioned_state"] = "HOLD_CONDITIONED_SECOND_RUNNER_READBACK"
        rows.append(checked)
    day.require(len(rows) == report["new_A_B_git_archived"],
                "ARCHIVED_COUNT_DIFFERS_FROM_SECOND_RUNNER")
    paired = sum(row["conditioned_state"] ==
                 "SECOND_RUNNER_CONDITIONED_GITHUB_SHA_CONFIRMED" for row in rows)
    return {"schema": SCHEMA, "day_jst": report["day_jst"],
            "new_archived": len(rows), "independently_verified": len(rows),
            "independently_verified_conditioned":paired,
            "paired_cipher_originals_verified":paired,
            "RSA_private_decryption_verified": False,
            "plaintext_parent_linkage_verified":False,
            "organizer_result_verified": False,
            "records": rows}


def _verify_independently(report, checkout, temp_root):
    if not _archived_rows(report):
        return verify(report=report, repo=checkout)
    archive._remote(checkout, synthetic_local=False)
    # Keep the reader isolated from the checkout and hydrate only the immutable objects checked below.
    with TemporaryDirectory(prefix="keirin-independent-cipher-", dir=temp_root) as folder:
        reader = Path(folder)
        archive._cmd(reader, "init", "--quiet", "--template=")
        archive._cmd(reader, "remote", "add", "origin", f"https://github.com/{archive.REPO}.git")
        archive._cmd(reader, "config", "--local", "remote.origin.promisor", "true")
        archive._cmd(reader, "config", "--local", "remote.origin.partialclonefilter", "blob:none")
        head = official_archive.fetch_partial_head(reader, with_ancestry=True)
        return verify(report=report, repo=reader, archive_head=head)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--report", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        prior = json.loads(Path(a.report).read_text(encoding="utf-8"))
        target = Path(a.out)
        day.require(target.is_absolute() and not target.exists() and
                    not target.is_symlink() and
                    os.environ.get("RUNNER_TEMP") and
                    Path(os.environ["RUNNER_TEMP"]).resolve() in target.resolve().parents,
                    "READBACK_REPORT_PRIVATE_TEMP_REQUIRED")
        output = _verify_independently(prior, Path(a.repo), target.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,"O_NOFOLLOW",0)
        fd = os.open(target, flags, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write((json.dumps(output, sort_keys=True,
                                   separators=(",",":")) + "\n").encode())
        print(json.dumps({"day_jst": output["day_jst"],
                          "new_archived": output["new_archived"],
                          "independently_verified":output["independently_verified"],
                          "RSA_private_decryption_verified":False},
                         sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError,
            archive.GitCipherArchiveError):
        print('{"state":"HOLD_SECOND_RUNNER_ARCHIVED_CIPHER_NOT_VERIFIED"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
