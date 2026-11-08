"""Production-only gate for archiving an owner-approved encrypted KEIRIN SQLite.

Reuses the existing repository and AES-256-GCM codec. Never modifies or
reinterprets state/keirin/v1/latest.json (synthetic history). Production
snapshots use a SEPARATE lineage on the EXISTING state branch, and are never
written from a pull_request, fork, synthetic cipher, untrusted process, or
without an explicit public-ciphertext owner acknowledgement.

IMPORTANT: this is code for the already chosen GitHub-only design, not a
data-provider licence. No workflow supplies a live production bundle yet.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from itertools import permutations
import json
import os
import re
import sqlite3

from scripts.keirin_github_git_archive import (
    ArchiveError, REPOSITORY_ID, REPO, STATE_BRANCH, SHA, COMMIT, RUN,
    command, checked_json, cipher_file, _scope, _create_once
)
from race_ai.keirin_result_delivery import utc, canonical
from race_ai.keirin_shadow_variable_pair import (
    checked_shadow,checked_selection
)
from race_ai.keirin_permissioned_owner import (
    load_operator_grants, OperatorLicenseGrants
)

PROD="state/keirin/production/v1"
HEAD=PROD+"/latest.json"
PROOF_SCHEMA="RACE_AI_KEIRIN_PRODUCTION_SEALED_PAIR_PROOF_V1"
HEAD_SCHEMA="RACE_AI_KEIRIN_PRODUCTION_ARCHIVE_HEAD_V1"
ACK="OWNER_APPROVED_PUBLIC_AES_GCM_CIPHERTEXT_V1"
NAME=re.compile(r"^g[0-9]{6}-[a-f0-9]{64}$")
MAX_SECONDS=65


def need(ok,code):
    if not ok:
        raise ArchiveError(code)


def check_private_pair(db, proof, grants):
    """Read only. This cannot create a missing DB or amend a frozen forecast."""
    need(isinstance(grants,OperatorLicenseGrants),
         "CURRENT_MACHINE_SOURCE_GRANTS_REQUIRED")
    need(type(proof) is dict and set(proof)=={
        "schema","repository_id","synthetic_only","mode",
        "producer_run_id","producer_sha","cipher_sha256",
        "race_id_sha256","source_packet_sha256","original_sha256",
        "variable_sha256","odds_sha256",
        "forecast_cutoff_at","pair_persisted_at",
        "external_timestamp_attested","independent_provider_license_attested",
        "real_bet_placed"
    },"PRODUCTION_RECEIPT_FIELDS_INVALID")
    need(proof["schema"]==PROOF_SCHEMA and
         proof["repository_id"]==REPOSITORY_ID and
         proof["mode"]=="production" and
         proof["synthetic_only"] is False and
         proof["real_bet_placed"] is False and
         proof["external_timestamp_attested"] is False and
         proof["independent_provider_license_attested"] is False,
         "PRODUCTION_RECEIPT_CANNOT_CLAIM_EXTERNAL_PROOFS")
    for field in ("race_id_sha256","source_packet_sha256",
                  "original_sha256","variable_sha256","odds_sha256",
                  "cipher_sha256"):
        need(type(proof[field]) is str and SHA.fullmatch(proof[field]),
             "PRODUCTION_SHA_INVALID")
    p=Path(db)
    need(p.is_file() and not p.is_symlink(),"PRODUCTION_RESTORED_DB_MISSING")
    try:
        with sqlite3.connect(p.resolve().as_uri()+"?mode=ro",
                             uri=True,timeout=4) as con:
            con.row_factory=sqlite3.Row
            con.execute("PRAGMA trusted_schema=OFF")
            need(con.execute("PRAGMA integrity_check").fetchone()[0]=="ok",
                 "PRODUCTION_SQLITE_INTEGRITY_FAILED")
            names={r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            need({"keirin_shadow_variable_pairs",
                  "keirin_shadow_source_inputs",
                  "forecasts","result_revisions"}<=names,
                 "PRODUCTION_DB_SCHEMA_MISSING")
            pairs=con.execute(
                "SELECT race_id,shadow_sha256,variable_sha256,odds_sha256,"
                "shadow_payload,variable_payload,odds_payload,persisted_at "
                "FROM keirin_shadow_variable_pairs").fetchall()
            matches=[r for r in pairs if sha256(
                r["race_id"].encode("utf-8")).hexdigest()==
                proof["race_id_sha256"]]
            need(len(matches)==1,
                 "PRODUCTION_FROZEN_RACE_NOT_FOUND_OR_DUPLICATED")
            p0=matches[0]
            shadow=json.loads(p0["shadow_payload"])
            variable=json.loads(p0["variable_payload"])
            odds=json.loads(p0["odds_payload"])
            checked_shadow(shadow)
            checked_selection(variable)
            need(shadow["race_id"]==p0["race_id"]==
                 variable["race_id"]==odds["race_id"] and
                 p0["shadow_sha256"]==shadow["research_sha256"]==
                 proof["original_sha256"]==
                 variable["original_shadow_sha256"] and
                 p0["variable_sha256"]==variable["selection_sha256"]==
                 proof["variable_sha256"] and
                 p0["odds_sha256"]==sha256(canonical(odds)).hexdigest()==
                 proof["odds_sha256"] and
                 shadow["input_sha256"]==proof["source_packet_sha256"]==
                 variable["source_packet_sha256"] and
                 shadow["declared_cutoff"]==proof["forecast_cutoff_at"]==
                 variable["official_cutoff_at"] and
                 p0["persisted_at"]==proof["pair_persisted_at"],
                 "PRODUCTION_FROZEN_PAIR_ORIGINAL_HASH_MISMATCH")
            source=con.execute(
                "SELECT source_sha256,source_payload "
                "FROM keirin_shadow_source_inputs WHERE race_id=?",
                (p0["race_id"],)).fetchone()
            need(source is not None and
                 source["source_sha256"]==proof["source_packet_sha256"]==
                 sha256(source["source_payload"]).hexdigest(),
                 "PRODUCTION_FROZEN_SOURCE_PACKET_MISSING")
            packet=json.loads(source["source_payload"])
            need(packet.get("race",{}).get("race_id")==p0["race_id"] and
                 packet["race"].get("permission_ref")==grants.bundle_id,
                 "PRODUCTION_SOURCE_RACE_OR_GRANT_MISMATCH")
            # Do not accept a packet that claims only owner personal/manual
            # acceptance as a machine-feed licence for unattended production.
            need(packet["race"].get("permission_ref") not in (
                None,"","RACE_AI_PRIVATE_OWNER_MANUAL_OBSERVATION_V1"
            ), "PRODUCTION_NON_MACHINE_SOURCE_NOT_CERTIFIED")
            need(type(packet.get("observations")) is list and
                 len(packet["observations"])>0,
                 "PRODUCTION_SOURCE_EVIDENCE_REQUIRED")
            for item in packet["observations"]:
                need(type(item) is dict and
                     all(grants.allowed(item.get("source_url"),
                                        item.get("rights_ref"),purpose)
                         for purpose in (
                             "automated_fetch","analysis","pre_race",
                             "model_inference","private_retention")),
                     "PRODUCTION_SOURCE_MACHINE_RIGHTS_MISSING")
            need(all(grants.allowed(
                         odds.get("source_ref"),
                         odds.get("source_rights_ref"),purpose)
                     for purpose in (
                         "automated_fetch","analysis","pre_race",
                         "private_retention")),
                 "PRODUCTION_ODDS_MACHINE_RIGHTS_MISSING")
            starters=[r["number"] for r in packet["race"]["starters"]]
            universe=set(permutations(starters,3))
            need(len(starters) in (7,9) and len(universe) in (210,504)
                 and len(odds["prices"])==len(universe),
                 "PRODUCTION_FULL_PRICE_UNIVERSE_MISSING")
            available=set()
            for x in odds["prices"]:
                need(type(x) is dict and
                     set(x)=={"triple","decimal_odds"} and
                     type(x["triple"]) is list and
                     len(x["triple"])==3 and
                     all(type(n) is int for n in x["triple"]),
                     "PRODUCTION_PRICE_ROW_INVALID")
                combo=tuple(x["triple"])
                need(combo in universe and combo not in available,
                     "PRODUCTION_PRICE_MISSING_OR_DUPLICATED")
                available.add(combo)
            need(available==universe,
                 "PRODUCTION_PRICE_UNIVERSE_MISSING")
            # Before using the production key or publishing ciphertext,
            # regenerate both versions from the EXACT stored pre-race input.
            # This prevents retroactive relabelling of a saved JSON as a
            # model output and rejects odds/result leakage into features.
            from race_ai.keirin_real_rider_shadow import (
                forecast_from_real_observations
            )
            from race_ai.keirin_shadow_variable_pair import (
                choose_shadow_variable
            )
            recalculated_shadow=forecast_from_real_observations(
                packet,grant_check=grants.allowed,
                issued_at=shadow["generated_at"])
            need(recalculated_shadow==shadow,
                 "PRODUCTION_SHADOW_NOT_REPRODUCIBLE_FROM_SOURCE")
            recalculated_variable=choose_shadow_variable(
                shadow,odds,decided_at=variable["selected_at"],
                odds_allowed=grants.allowed)
            need(recalculated_variable==variable,
                 "PRODUCTION_VARIABLE_NOT_REPRODUCIBLE")
            frozen=utc(p0["persisted_at"])
            cutoff=utc(shadow["declared_cutoff"])
            need(utc(shadow["generated_at"])<=utc(
                 variable["selected_at"])<=frozen and
                 frozen+timedelta(seconds=MAX_SECONDS)<cutoff,
                 "PRODUCTION_PAIR_NOT_GENUINELY_FROZEN_PRE_CUTOFF")
            return {
                "pair_exists_and_immutable":True,
                "pre_cutoff_verified_by_stored_clocks":True,
                "official_timestamp_verified":False,
                "official_provider_rights_verified_by_code":False,
                "legacy_pr71_forecasts_count":con.execute(
                    "SELECT COUNT(*) FROM forecasts").fetchone()[0],
                "frozen_variable_pair_count":len(pairs),
            }
    except (sqlite3.Error,ValueError,KeyError,TypeError):
        raise ArchiveError("PRODUCTION_DB_RESTORE_AUDIT_FAILED") from None


def validate_production_bundle(artifact, *, repo, license_manifest,
                               expected_run_id,expected_commit):
    """Strong key is needed at the trusted runner. Never output plaintext."""
    artifact=Path(artifact)
    need(artifact.is_dir() and not artifact.is_symlink(),
         "PRODUCTION_SEALED_BUNDLE_REQUIRED")
    scope=_scope(checked_json(artifact/"scope.json"))
    need(scope["mode"]=="production","PRODUCTION_SCOPE_REQUIRED")
    proof=checked_json(artifact/"proof.json")
    # Strong proof must be accompanied by a SHA-checked private licence
    # manifest and the operator-verified document. URLs alone grant nothing.
    from datetime import datetime,timezone
    grants=load_operator_grants(
        license_manifest,now=datetime.now(timezone.utc).isoformat())
    need(proof.get("schema")==PROOF_SCHEMA and
         proof.get("synthetic_only") is False and
         proof.get("mode")=="production" and
         type(expected_run_id) is str and RUN.fullmatch(expected_run_id) and
         type(expected_commit) is str and COMMIT.fullmatch(expected_commit) and
         str(proof.get("producer_run_id"))==expected_run_id and
         proof.get("producer_sha")==expected_commit,
         "PRODUCTION_PRODUCER_ATTESTATION_MISSING")
    cipher=cipher_file(artifact/"state.enc")
    digest=sha256(cipher).hexdigest()
    need(proof.get("cipher_sha256")==digest,
         "PRODUCTION_CIPHER_SHA_MISMATCH")
    from scripts.keirin_github_git_archive import verify_aead_snapshot
    verify_aead_snapshot(artifact,digest,repo)
    # verify_aead_snapshot already requires the existing 32-byte production
    # secret for unseal, SQLite quick_check and create-once local writes.
    with TemporaryDirectory(prefix="keirin-prod-verify-") as temp:
        restored=Path(temp)/"snapshot.sqlite3"
        env={**os.environ,"RACE_AI_EXPECTED_CIPHER_SHA256":digest}
        command([
            "node",str(Path(repo)/"scripts/keirin_github_checkpoint.mjs"),
            "unseal",str(artifact/"state.enc"),str(restored),
            str(artifact/"scope.json")
        ],cwd=repo,env=env)
        check_private_pair(restored,proof,grants)
    return scope,proof,cipher,digest


def archive_production_in_git(artifact, *, repo, license_manifest,
                              expected_run_id, expected_commit):
    """Separate production head under existing state ref; never overwrite.

    Requires operator's explicit acknowledgement that ciphertext, sizes and
    commit times become PUBLIC in the existing RACE-AI repository. Only
    a successful trusted main producer may trigger this. No sideband files
    or plaintext may be staged in Git.
    """
    env=os.environ
    need(env.get("GITHUB_ACTIONS")=="true" and
         env.get("GITHUB_REPOSITORY")==REPO and
         env.get("GITHUB_REPOSITORY_ID")==REPOSITORY_ID and
         env.get("GITHUB_REF")=="refs/heads/main" and
         env.get("GITHUB_EVENT_NAME")=="workflow_run" and
         env.get("RACE_AI_PUBLIC_CIPHERTEXT_APPROVED")==ACK,
         "TRUSTED_MAIN_AND_EXPLICIT_CIPHERTEXT_APPROVAL_REQUIRED")
    event=env.get("GITHUB_EVENT_PATH")
    need(type(event) is str and Path(event).is_file() and
         not Path(event).is_symlink(),
         "TRUSTED_PRODUCER_WORKFLOW_EVENT_REQUIRED")
    event_json=checked_json(event,max_size=200000)
    workflow=event_json.get("workflow_run")
    repository=event_json.get("repository")
    need(type(workflow) is dict and type(repository) is dict and
         str(repository.get("id"))==REPOSITORY_ID and
         str(workflow.get("id"))==expected_run_id and
         workflow.get("head_sha")==expected_commit and
         workflow.get("head_branch")=="main" and
         workflow.get("conclusion")=="success" and
         workflow.get("event") in ("push","workflow_dispatch") and
         workflow.get("name")==
            "KEIRIN admitted real-race private producer" and
         not workflow.get("pull_requests") and
         type(workflow.get("head_repository")) is dict and
         str(workflow["head_repository"].get("id"))==REPOSITORY_ID,
         "UNTRUSTED_OR_INCORRECT_PRODUCER_WORKFLOW")
    root=Path(repo).resolve()
    need((root/".git").exists(),"TRUSTED_CHECKOUT_REQUIRED")
    private_paths=(Path(artifact).resolve(),Path(license_manifest).resolve())
    need(all(root not in p.parents and p!=root for p in private_paths),
         "PRODUCTION_PRIVATE_MATERIAL_INSIDE_PUBLIC_CHECKOUT")
    scope,proof,cipher,digest=validate_production_bundle(
        artifact,repo=root,license_manifest=license_manifest,
        expected_run_id=expected_run_id,
        expected_commit=expected_commit)
    from datetime import datetime,timezone
    need(datetime.now(timezone.utc)+timedelta(seconds=MAX_SECONDS)<
         utc(proof["forecast_cutoff_at"]),
         "PRODUCTION_ARCHIVE_TOO_LATE_TO_ASSERT_PRE_CUTOFF")
    git=lambda *a,cwd=root:command(["git",*a],cwd=cwd)
    url=git("remote","get-url","origin")
    need(url in (
       "https://github.com/"+REPO,
       "https://github.com/"+REPO+".git",
       "git@github.com:"+REPO+".git"
    ),"EXPECTED_REPOSITORY_REMOTE_REQUIRED")
    git("fetch","--no-tags","origin",
        "refs/heads/"+STATE_BRANCH+":refs/remotes/origin/"+STATE_BRANCH)
    with TemporaryDirectory(prefix="keirin-prod-archive-") as temp:
        wt=Path(temp)/"checkout"
        git("worktree","add","--detach",str(wt),
            "refs/remotes/origin/"+STATE_BRANCH)
        try:
            old=wt/HEAD
            previous=checked_json(old) if old.exists() else None
            if previous is None:
                need(scope["generation"]==1 and
                     scope["previous_cipher_sha256"] is None,
                     "PRODUCTION_GENESIS_STATE_MISMATCH")
            else:
                need(previous.get("schema")==HEAD_SCHEMA and
                     previous.get("repository_id")==REPOSITORY_ID and
                     previous.get("mode")=="production" and
                     type(previous.get("generation")) is int and
                     type(previous.get("cipher_sha256")) is str and
                     SHA.fullmatch(previous["cipher_sha256"]),
                     "PRODUCTION_OLD_HEAD_INVALID")
                if (previous["generation"]==scope["generation"] and
                    previous["cipher_sha256"]==digest and
                    previous.get("producer_run_id")==expected_run_id):
                    return {"state":"PRODUCTION_ARCHIVE_ALREADY_SAME",
                            "public_ciphertext":True,
                            "production_forecast_verified":False}
                need(scope["generation"]==previous["generation"]+1 and
                     scope["previous_cipher_sha256"]==
                     previous["cipher_sha256"],
                     "PRODUCTION_ARCHIVE_REWIND_REFUSED")
            stem=f"g{scope['generation']:06d}-{digest}"
            need(NAME.fullmatch(stem) is not None,
                 "PRODUCTION_ARCHIVE_SNAPSHOT_NAME_INVALID")
            base=PROD+"/snapshots/"+stem
            files={
                base+".enc":cipher,
                base+".scope.json":canonical(scope)+b"\n",
                base+".proof.json":canonical(proof)+b"\n"
            }
            for p,body in files.items():
                _create_once(wt/p,body)
            head={
                "schema":HEAD_SCHEMA,"mode":"production",
                "repository_id":REPOSITORY_ID,
                "generation":scope["generation"],
                "cipher_sha256":digest,
                "previous_cipher_sha256":scope["previous_cipher_sha256"],
                "snapshot_file":base+".enc",
                "scope_file":base+".scope.json",
                "proof_file":base+".proof.json",
                "producer_run_id":expected_run_id,
                "producer_commit":expected_commit,
            }
            old.parent.mkdir(parents=True,exist_ok=True)
            old.write_bytes(canonical(head)+b"\n")
            git("add","--",*files.keys(),HEAD,cwd=wt)
            git("-c","user.name=github-actions[bot]",
                "-c","user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit","-m","archive(keirin): sealed production research generation "+
                str(scope["generation"]),cwd=wt)
            pushed=git("rev-parse","HEAD",cwd=wt)
            git("push","origin","HEAD:refs/heads/"+STATE_BRANCH,cwd=wt)
            remote_head=git("ls-remote","origin",
                            "refs/heads/"+STATE_BRANCH,cwd=wt)
            need(remote_head.split()[0]==pushed,
                 "PRODUCTION_ARCHIVE_REMOTE_READBACK_FAILED")
            return {
                "state":"PRODUCTION_RESEARCH_CIPHERTEXT_COMMITTED",
                "generation":scope["generation"],
                "cipher_sha256":digest,
                "git_commit":pushed,
                "public_ciphertext":True,
                "production_original_integrity_verified":True,
                "independent_pre_cutoff_receipt":False,
                "provider_rights_independently_certified_by_code":False,
                "plaintext_uploaded":False,
                "production_accuracy_verified":False,
            }
        finally:
            try:
                git("worktree","remove","--force",str(wt))
            except ArchiveError:
                pass


def main(argv=None):
    """Trusted workflow_run consumer. Never accepts producer identity on CLI."""
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact",required=True)
    p.add_argument("--repo",required=True)
    p.add_argument("--license-manifest",required=True)
    a=p.parse_args(argv)
    try:
        event=checked_json(os.environ.get("GITHUB_EVENT_PATH",""),
                           max_size=200000)
        producer=event.get("workflow_run")
        need(type(producer) is dict,
             "TRUSTED_PRODUCTION_WORKFLOW_EVENT_REQUIRED")
        report=archive_production_in_git(
            a.artifact,repo=a.repo,license_manifest=a.license_manifest,
            expected_run_id=str(producer["id"]),
            expected_commit=producer["head_sha"])
        print(json.dumps(report,sort_keys=True,separators=(",",":")))
        return 0
    except (ArchiveError,KeyError,OSError,ValueError,TypeError):
        print('{"state":"PRODUCTION_GIT_ARCHIVE_NOT_VERIFIED","plaintext_published":false}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
