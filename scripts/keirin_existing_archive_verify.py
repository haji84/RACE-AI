"""Restore and attest an EXISTING synthetic KEIRIN Git archive, read-only.

This is a hardened regression for the *already saved* encrypted history,
not a production-key probe or new backup. Its synthetic key is intentionally
public. No production archive, owner secret, real forecast, live source or
new SQLite state is ever accepted. All plaintext is confined to a temporary
directory and is never written into the public repository or an artifact.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from tempfile import TemporaryDirectory

from scripts.keirin_existing_asset_preflight import inspect_tree, _json_at
from race_ai.keirin_existing_asset_reuse import ExistingStateError

REQUIRED_PROOF_KEYS=("cipher_sha256","snapshot_sha256","forecast_sha256",
                     "synthetic_only","producer_run_id","producer_sha")


def need(condition, why):
    if not condition:
        raise ExistingStateError(why)


def verify_existing_synthetic_archive(tree, *, repo):
    root=Path(tree).expanduser()
    project=Path(repo).expanduser()
    need(root.is_absolute() and root.is_dir() and not root.is_symlink(),
         "EXISTING_ARCHIVE_CHECKOUT_REQUIRED")
    need(project.is_dir() and (project/"scripts/keirin_github_checkpoint.mjs").is_file(),
         "REPOSITORY_DECRYPTOR_REQUIRED")
    report=inspect_tree(root)
    archive=report["archive"]
    need(archive["archive_mode"]=="synthetic",
         "PRODUCTION_ARCHIVE_NEEDS_OWNER_APPROVED_KEY_RUNTIME")
    head=_json_at(root,"state/keirin/v1/latest.json")
    scope=_json_at(root,head["scope_file"])
    proof=_json_at(root,head["proof_file"])
    need(all(k in proof for k in REQUIRED_PROOF_KEYS) and
         proof["synthetic_only"] is True,
         "SYNTHETIC_SOURCE_PROOF_REQUIRED")
    cipher=root/head["snapshot_file"]
    need(cipher.is_file() and not cipher.is_symlink()
         and 16<cipher.stat().st_size<=12*1024*1024,
         "EXISTING_CIPHER_FILE_INVALID")
    actual_cipher_sha=sha256(cipher.read_bytes()).hexdigest()
    need(actual_cipher_sha==head["cipher_sha256"]==
         proof["cipher_sha256"],"EXISTING_CIPHER_SHA_MISMATCH")
    node=project/"scripts/keirin_github_checkpoint.mjs"
    with TemporaryDirectory(prefix="keirin-existing-archive-") as tmp:
        output=Path(tmp)/"restored.sqlite3"
        env={**os.environ,
             "RACE_AI_EXPECTED_CIPHER_SHA256":actual_cipher_sha}
        # Synthetic key is derived inside the existing Node code. Never
        # pass or read RACE_AI_STATE_KEY for this fixture exercise.
        env.pop("RACE_AI_STATE_KEY",None)
        try:
            run=subprocess.run(
                ["node",str(node),"unseal",str(cipher),str(output),
                 str(root/head["scope_file"])],
                env=env,cwd=str(project),
                stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                text=True,timeout=25,check=False)
        except (OSError,subprocess.TimeoutExpired):
            raise ExistingStateError("EXISTING_SYNTHETIC_DECRYPTOR_UNAVAILABLE") from None
        need(run.returncode==0 and output.is_file(),
             "EXISTING_SYNTHETIC_AEAD_RESTORE_FAILED")
        restored=output.read_bytes()
        need(restored.startswith(b"SQLite format 3\x00") and
             sha256(restored).hexdigest()==proof["snapshot_sha256"],
             "RESTORED_SQLITE_SHA_MISMATCH")
        try:
            with sqlite3.connect(output.resolve().as_uri()+"?mode=ro",
                                 uri=True,timeout=3) as db:
                db.execute("PRAGMA trusted_schema=OFF")
                need(db.execute("PRAGMA integrity_check").fetchone()==("ok",),
                     "RESTORED_SQLITE_INTEGRITY_FAILED")
                tables={r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                need({"forecasts","result_revisions","audits"}<=tables,
                     "EXPECTED_SQLITE_OWNER_SCHEMA_MISSING")
                forecast_count=db.execute(
                    "SELECT COUNT(*) FROM forecasts").fetchone()[0]
                result_count=db.execute(
                    "SELECT COUNT(*) FROM result_revisions").fetchone()[0]
                forecast_hashes={row[0] for row in db.execute(
                    "SELECT forecast_sha256 FROM forecasts")}
                need(forecast_count==1 and
                     forecast_hashes=={proof["forecast_sha256"]},
                     "SYNTHETIC_FORECAST_PROOF_MISMATCH")
        except sqlite3.Error:
            raise ExistingStateError("RESTORED_SQLITE_READ_ERROR") from None
    return {
        "schema":"RACE_AI_EXISTING_KEIRIN_ARCHIVE_RESTORE_RECEIPT_V1",
        "archive_ref":archive["archive_ref"],
        "mode":"synthetic",
        "generation":head["generation"],
        "ciphertext_sha256":actual_cipher_sha,
        "snapshot_sha256":proof["snapshot_sha256"],
        "forecast_sha256":proof["forecast_sha256"],
        "existing_ciphertext_sha_verified":True,
        "existing_snapshot_aead_decrypted":True,
        "existing_snapshot_sqlite_integrity":"ok",
        "restored_forecast_matches_proof":True,
        "restored_fixture_forecasts":forecast_count,
        "restored_fixture_result_revisions":result_count,
        "producer_run_id":head["producer_run_id"],
        "real_keirin_forecasts_recovered":0,
        "production_key_used":False,
        "production_recovery_verified":False,
        "external_cutoff_timestamp_verified":False,
        "real_210_odds_available":False,
        "new_persistent_db_created":False,
    }


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-tree",required=True)
    p.add_argument("--source-repo",default=".")
    args=p.parse_args(argv)
    try:
        report=verify_existing_synthetic_archive(
            args.state_tree,repo=args.source_repo)
    except (ExistingStateError,OSError,ValueError,TypeError,KeyError):
        print('{"status":"EXISTING_ARCHIVE_RESTORE_FAILED_CLOSED","production_recovery_verified":false}')
        return 2
    print(json.dumps(report,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
