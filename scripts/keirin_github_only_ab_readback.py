"""Independent GitHub runner verifies newly archived A/B ciphertext by SHA.

This does not decrypt the RSA envelope or certify official result/cutoff.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os

from race_ai import keirin_nationwide_cipher_history as archive
from scripts import keirin_github_only_ab_day as day

SCHEMA = "RACE_AI_KEIRIN_GITHUB_ONLY_AB_SECOND_RUNNER_V1"


def verify(*, report, repo):
    day.require(type(report) is dict and
                report.get("schema") == day.SCHEMA and
                type(report.get("new_encrypted_originals")) is list,
                "PRIOR_GITHUB_ONLY_REPORT_SCHEMA_REQUIRED")
    found = set()
    rows = []
    for row in report["new_encrypted_originals"]:
        rid = row.get("race_id")
        digest = row.get("cipher_sha256")
        day.require(type(rid) is str and rid not in found and
                    rid[:8] == report["day_jst"].replace("-", "") and
                    type(digest) is str, "BAD_ARCHIVE_OR_DUPLICATE_RACE")
        found.add(rid)
        verified = archive.read_original(
            repo=repo, race_id=rid, expected_cipher_sha256=digest)
        day.require(verified["state"] ==
                    "ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK",
                    "INDEPENDENT_GITHUB_READBACK_NOT_VERIFIED")
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
                result = archive.read_conditioned_original(
                    repo=repo, race_id=rid, expected_cipher_sha256=condition_sha,
                    expected_baseline_cipher_sha256=digest,
                    expected_baseline_prediction_sha256=row["baseline_prediction_sha256"],
                    cohort_sha256=row["cohort_sha256"])
                day.require(result["state"] == "ENCRYPTED_GIT_CONDITIONED_SHA_READBACK_OK",
                            "INDEPENDENT_CONDITIONED_GITHUB_READBACK_NOT_VERIFIED")
                checked.update(
                    conditioned_state="SECOND_RUNNER_CONDITIONED_GITHUB_SHA_CONFIRMED",
                    conditioned_cipher_sha256=condition_sha,
                    baseline_prediction_sha256=row["baseline_prediction_sha256"],
                    cohort_sha256=row["cohort_sha256"])
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


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--report", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    try:
        prior = json.loads(Path(a.report).read_text(encoding="utf-8"))
        output = verify(report=prior, repo=Path(a.repo))
        target = Path(a.out)
        day.require(target.is_absolute() and not target.exists() and
                    not target.is_symlink() and
                    os.environ.get("RUNNER_TEMP") and
                    Path(os.environ["RUNNER_TEMP"]).resolve() in target.resolve().parents,
                    "READBACK_REPORT_PRIVATE_TEMP_REQUIRED")
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
