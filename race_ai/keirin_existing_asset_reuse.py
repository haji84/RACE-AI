"""Read-only preflight for reusing existing RACE-AI state (never initialize it).

This tool deliberately cannot create a new SQLite or decrypt an archive.
Even a valid ciphertext/index is NOT proof of real KEIRIN forecasts or an
external timestamp. Reuse state/keirin-encrypted-history metadata and existing
owner DB before proposing a new state or a backfill.
"""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3

REPOSITORY_ID="1416489937"
ARCHIVE_SCHEMA="RACE_AI_KEIRIN_GIT_ARCHIVE_HEAD_V1"
SCOPE_SCHEMA="RACE_AI_GITHUB_SQLITE_V1"
SHA=re.compile(r"^[0-9a-f]{64}$")
COMMIT=re.compile(r"^[0-9a-f]{40}$")
RUN=re.compile(r"^[1-9][0-9]{1,15}$")
REQUIRED_DB_TABLES=frozenset(("race_index","snapshots","forecasts",
                              "result_revisions","audits"))


class ExistingStateError(ValueError):
    pass


def need(value, reason):
    if not value:
        raise ExistingStateError(reason)


def inspect_archive_metadata(head, scope, proof):
    """Inspect trusted metadata only; never assume secret/key availability."""
    need(all(type(v) is dict for v in (head,scope,proof)),
         "ARCHIVE_METADATA_MISSING")
    need(set(head)=={
        "schema","mode","repository_id","generation","cipher_sha256",
        "previous_cipher_sha256","snapshot_file","scope_file","proof_file",
        "producer_run_id","producer_commit"
    },"ARCHIVE_HEAD_FIELDS_INVALID")
    need(set(scope)=={
        "schema","mode","repository_id","generation","previous_cipher_sha256"
    },"SCOPE_FIELDS_INVALID")
    need(head["schema"]==ARCHIVE_SCHEMA
         and scope["schema"]==SCOPE_SCHEMA
         and head["repository_id"]==scope["repository_id"]==REPOSITORY_ID,
         "WRONG_REPOSITORY_OR_SCHEMA")
    mode=head["mode"]
    need(mode in ("synthetic","production") and scope["mode"]==mode,
         "ARCHIVE_MODE_MISMATCH")
    generation=head["generation"]
    need(type(generation) is int and 1<=generation<=100000
         and scope["generation"]==generation,
         "ARCHIVE_GENERATION_MISMATCH")
    previous=head["previous_cipher_sha256"]
    need(previous==scope["previous_cipher_sha256"] and
         (previous is None if generation==1 else
          type(previous) is str and SHA.fullmatch(previous)),
         "PREVIOUS_GENERATION_LINK_INVALID")
    digest=head["cipher_sha256"]
    need(type(digest) is str and SHA.fullmatch(digest),
         "CIPHERTEXT_DIGEST_INVALID")
    stem=f"g{generation:06d}-{digest}"
    prefix=f"state/keirin/v1/snapshots/{stem}"
    need(head["snapshot_file"]==prefix+".enc"
         and head["scope_file"]==prefix+".scope.json"
         and head["proof_file"]==prefix+".proof.json",
         "SNAPSHOT_PATH_MISMATCH")
    need(type(head["producer_run_id"]) is str and
         RUN.fullmatch(head["producer_run_id"])
         and type(head["producer_commit"]) is str and
         COMMIT.fullmatch(head["producer_commit"]),
         "PRODUCER_IDENTITY_INVALID")
    need(proof.get("cipher_sha256")==digest
         and str(proof.get("producer_run_id"))==head["producer_run_id"]
         and proof.get("producer_sha")==head["producer_commit"],
         "ARCHIVE_PROOF_DISAGREEMENT")
    if mode=="synthetic":
        need(proof.get("synthetic_only") is True,
             "SYNTHETIC_PROOF_NOT_PRESENT")
    else:
        need(proof.get("synthetic_only") is False,
             "PRODUCTION_PROOF_NOT_AUTHORITATIVE")
    return {
        "archive_mode":mode,
        "archive_generation":generation,
        "archive_ref":"state/keirin-encrypted-history",
        "archive_metadata_consistent":True,
        "ciphertext_bytes_verified":False,
        "aead_decryption_verified":False,
        "independent_race_cutoff_witness_verified":False,
        "production_state_recovered":False,
        "status":("SYNTHETIC_ONLY_NO_OWNER_HISTORY" if mode=="synthetic"
                  else "PRODUCTION_METADATA_ONLY_NOT_RECOVERED"),
    }


def inspect_existing_sqlite(path):
    """Existing file ONLY: never sqlite3.connect() a missing filename."""
    if path is None:
        return {"status":"OWNER_SQLITE_NOT_CONNECTED",
                "existing_owner_db_verified":False}
    p=Path(path).expanduser()
    need(p.is_absolute() and p.is_file() and not p.is_symlink(),
         "EXISTING_OWNER_DB_REQUIRED_NO_AUTO_CREATE")
    try:
        with p.open("rb") as f:
            need(f.read(16)==b"SQLite format 3\x00","INVALID_SQLITE_HEADER")
        with sqlite3.connect(p.resolve().as_uri()+"?mode=ro",
                             uri=True,timeout=3) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            need(db.execute("PRAGMA quick_check").fetchall()==[("ok",)],
                 "SQLITE_INTEGRITY_FAILED")
            tables={x[0] for x in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            need(REQUIRED_DB_TABLES<=tables,"NOT_AN_EXISTING_KEIRIN_OWNER_DB")
            base=db.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0]
            result=db.execute(
                "SELECT COUNT(*) FROM result_revisions").fetchone()[0]
            dual=(db.execute(
                "SELECT COUNT(*) FROM keirin_shadow_variable_pairs"
            ).fetchone()[0] if "keirin_shadow_variable_pairs" in tables else 0)
            return {
                "status":("EXISTING_OWNER_SQLITE_READ_ONLY" if base or dual or
                          result else "EXISTING_OWNER_SQLITE_EMPTY"),
                "existing_owner_db_verified":True,
                "forecast_original_count":base,
                "shadow_variable_pair_count":dual,
                "result_revision_count":result,
                "record_origin_independently_verified":False,
            }
    except sqlite3.Error:
        raise ExistingStateError("SQLITE_READ_ONLY_VERIFICATION_FAILED") from None


def report_existing_asset_reuse(head,scope,proof,*,owner_db=None):
    archive=inspect_archive_metadata(head,scope,proof)
    owner=inspect_existing_sqlite(owner_db)
    # No entry into live inference solely from an encrypted head, index or
    # metadata: verified input, owner authorization, keys and cutoffs are
    # independent gates not asserted here.
    return {
        "schema":"RACE_AI_KEIRIN_EXISTING_ASSET_REUSE_GATE_V1",
        "repository_id":REPOSITORY_ID,
        "archive":archive,
        "owner_store":owner,
        "existing_archives_checked":True,
        "new_empty_db_created":False,
        "market_odds_obtained":False,
        "real_data_automated_feeder_verified":False,
        "full_210_odds_present":False,
        "ready_for_live_two_version_freeze":False,
        "official_performance_verified":False,
        "next_action":(
            "REUSE_EXISTING_PRODUCTION_ENCRYPTED_CHECKPOINT_AFTER"
            "_OWNER_KEY_AEAD_VERIFIED"
            if archive["archive_mode"]=="production" else
            "FIND_EXISTING_REAL_SOURCE_OR_PRODUCTION_CHECKPOINT_FIRST"),
    }
