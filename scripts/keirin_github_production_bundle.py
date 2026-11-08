"""Create a production-mode encrypted snapshot ONLY from an EXISTING owner DB.

Uses the existing backup_sqlite + AES-256-GCM implementation and source/odds
grants. Do not run this from untrusted PRs. The bundle itself is local only;
publishing even its ciphertext requires separate explicit owner acknowledgement
and the trusted main archive job.

The test suite runs with invented riders and a freshly generated random key.
No machine data licence or production accuracy is inferred by tests.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from hashlib import sha256
from pathlib import Path
import json
import os
import sqlite3
from tempfile import TemporaryDirectory

from race_ai.keirin_permissioned_owner import load_operator_grants
from race_ai.keirin_result_delivery import canonical,utc
from scripts.keirin_github_sqlite_snapshot import backup_sqlite
from scripts.keirin_github_git_archive import REPOSITORY_ID, SHA, RUN, COMMIT, command
from scripts.keirin_github_production_archive import (
    ArchiveError,PROOF_SCHEMA,check_private_pair,validate_production_bundle,need
)


def checked_existing_pair(db,race_id):
    """Read source/odds hashes from an existing DB, with no schema creation."""
    path=Path(db)
    need(path.is_absolute() and path.is_file() and
         not path.is_symlink(),
         "OWNER_EXISTING_DATABASE_REQUIRED")
    try:
        with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",
                             uri=True,timeout=4) as con:
            con.row_factory=sqlite3.Row
            con.execute("PRAGMA trusted_schema=OFF")
            need(con.execute("PRAGMA quick_check").fetchall()==[("ok",)],
                 "OWNER_DATABASE_NOT_INTEGRITY_VALID")
            pair=con.execute(
                "SELECT shadow_sha256,variable_sha256,odds_sha256,"
                "persisted_at,shadow_payload "
                "FROM keirin_shadow_variable_pairs WHERE race_id=?",
                (race_id,)).fetchone()
            source=con.execute(
                "SELECT source_sha256 FROM keirin_shadow_source_inputs "
                "WHERE race_id=?", (race_id,)).fetchone()
            need(pair is not None and source is not None,
                 "EXISTING_FROZEN_TWO_VERSION_PAIR_REQUIRED")
            shadow=json.loads(pair["shadow_payload"])
            return {
                "race_id_sha256":sha256(race_id.encode("utf-8")).hexdigest(),
                "original_sha256":pair["shadow_sha256"],
                "variable_sha256":pair["variable_sha256"],
                "odds_sha256":pair["odds_sha256"],
                "source_packet_sha256":source["source_sha256"],
                "forecast_cutoff_at":shadow["declared_cutoff"],
                "pair_persisted_at":pair["persisted_at"],
            }
    except ArchiveError:
        raise
    except (sqlite3.Error,KeyError,ValueError):
        raise ArchiveError("EXISTING_OWNER_PAIR_READ_FAILED") from None


def create_production_bundle(db, license_manifest, output, *,
                             source_repo, race_id, generation,
                             previous_cipher_sha256,producer_run_id,
                             producer_sha, checked_at=None):
    """Seal a single existing source-linked future race. No Git write."""
    from scripts.keirin_github_production_archive import REPO
    need(os.environ.get("GITHUB_ACTIONS")!="true" or
         checked_at is None,"UNTRUSTED_PRODUCTION_CLOCK_OVERRIDE")
    now=utc(checked_at or datetime.now(timezone.utc).isoformat())
    need(type(generation) is int and 1<=generation<=100000 and
         (previous_cipher_sha256 is None if generation==1 else
          type(previous_cipher_sha256) is str and
          SHA.fullmatch(previous_cipher_sha256)),
         "PRODUCTION_GENERATION_PROVENANCE_REQUIRED")
    need(type(producer_run_id) is str and RUN.fullmatch(producer_run_id) and
         type(producer_sha) is str and COMMIT.fullmatch(producer_sha),
         "EXACT_TRUSTED_PRODUCER_ID_REQUIRED")
    repo=Path(source_repo).resolve()
    need((repo/"scripts/keirin_github_checkpoint.mjs").is_file(),
         "EXISTING_PRODUCTION_CODEC_REQUIRED")
    paths=[Path(db).resolve(),Path(license_manifest).resolve(),
           Path(output).resolve()]
    need(all(repo not in p.parents and p!=repo for p in paths),
         "PRIVATE_PRODUCTION_BYTES_INSIDE_PUBLIC_CHECKOUT")
    grants=load_operator_grants(license_manifest,now=now.isoformat())
    data=checked_existing_pair(db,race_id)
    need(now+timedelta(seconds=65)<utc(data["forecast_cutoff_at"]),
         "PRODUCTION_ARCHIVE_CUTOFF_ALREADY_TOO_NEAR")
    proof={
        "schema":PROOF_SCHEMA,"repository_id":REPOSITORY_ID,
        "mode":"production","synthetic_only":False,
        "producer_run_id":producer_run_id,"producer_sha":producer_sha,
        "cipher_sha256":"0"*64,**data,
        # Neither external timestamp nor legal correctness are magically
        # proven by a local user document or encrypted material.
        "external_timestamp_attested":False,
        "independent_provider_license_attested":False,
        "real_bet_placed":False
    }
    # This checks the source snapshots, all 210/504 odds, timestamps, original
    # hashes, and the allowlisted machine-feed rights for EACH observation.
    check_private_pair(db,proof,grants)
    dest=Path(output)
    need(dest.is_absolute() and not dest.exists(),
         "PRODUCTION_BUNDLE_TARGET_MUST_BE_NEW")
    dest.mkdir(mode=0o700)
    with TemporaryDirectory(prefix="keirin-prod-existing-db-") as temp:
        snapshot=Path(temp)/"snapshot.sqlite3"
        backup_sqlite(db,snapshot)
        scope={
            "schema":"RACE_AI_GITHUB_SQLITE_V1",
            "repository_id":REPOSITORY_ID,
            "mode":"production",
            "generation":generation,
            "previous_cipher_sha256":previous_cipher_sha256
        }
        (dest/"scope.json").write_bytes(canonical(scope)+b"\n")
        os.chmod(dest/"scope.json",0o600)
        command([
            "node",str(repo/"scripts/keirin_github_checkpoint.mjs"),
            "seal",str(snapshot),str(dest/"state.enc"),
            str(dest/"scope.json")
        ],cwd=repo)
    cipher=sha256((dest/"state.enc").read_bytes()).hexdigest()
    proof["cipher_sha256"]=cipher
    (dest/"proof.json").write_bytes(canonical(proof)+b"\n")
    os.chmod(dest/"proof.json",0o600)
    validate_production_bundle(
        dest,repo=repo,license_manifest=license_manifest,
        expected_run_id=producer_run_id,
        expected_commit=producer_sha)
    return {
        "schema":"RACE_AI_KEIRIN_PRODUCTION_SEALED_BUNDLE_READY_V1",
        "state":"READY_BUT_NOT_PUBLISHED",
        "cipher_sha256":cipher,
        "generation":generation,
        "owner_existing_database_checked":True,
        "research_pair_frozen_before_cutoff":True,
        "full_210_or_504_odds_checked":True,
        "production_key_used_locally":True,
        "trusted_git_archive_committed":False,
        "independent_external_pre_cutoff_witness":False,
        "provider_license_independently_certified_by_code":False,
        "plaintext_published":False,
    }
