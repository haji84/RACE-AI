"""Existing PR71 four models -> GitHub-hosted AES-GCM state branch (no owner PC).

Uses the already deployed AES-256-GCM codec and SQLite backup routines.
Production is in its OWN lineage on the existing Git state branch; synthetic
history stays untouched. Only main schedule/dispatch may carry a real key.
Without an independently reviewed source-grant bundle or new complete
pre-cutoff data, return HOLD, never fabricate features or predictions.

The public repo contains only encrypted SQLite, public-size ciphertext and
digest-bound metadata. A compromise of the production key would expose the
historical plaintext: the owner must approve that risk explicitly.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import base64
import io
import json
import os
import re
import shutil
import sqlite3
import sys

from scripts.keirin_github_git_archive import (
    ArchiveError, REPO, REPOSITORY_ID, STATE_BRANCH,
    command, _scope, _create_once
)
from scripts.keirin_github_sqlite_snapshot import (
    backup_sqlite, validate_snapshot
)
from race_ai.keirin_owner_sqlite import PrivateKeirinStore
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.keirin_result_delivery import canonical, utc

BASE=Path("state/keirin/pr71-production/v1")
HEAD=BASE/"latest.json"
SCHEMA="RACE_AI_KEIRIN_PR71_GITHUB_CLOUD_STATE_V1"
PROOF="RACE_AI_KEIRIN_PR71_CLOUD_CIPHER_PROOF_V1"
SHA=re.compile(r"^[0-9a-f]{64}$")
FULL_SHA=re.compile(r"^[0-9a-f]{40}$")


def need(ok,reason):
    if not ok:
        raise ArchiveError(reason)


def git(repo,*args):
    return command(["git",*args],cwd=repo)


def require_main_event():
    e=os.environ
    need(e.get("GITHUB_ACTIONS")=="true" and
         e.get("GITHUB_REPOSITORY")==REPO and
         e.get("GITHUB_REPOSITORY_ID")==REPOSITORY_ID and
         e.get("GITHUB_REF")=="refs/heads/main" and
         e.get("GITHUB_EVENT_NAME") in ("schedule","workflow_dispatch"),
         "TRUSTED_GITHUB_MAIN_SCHEDULE_REQUIRED")


def check_owner_cipher_consent(source_root):
    path=Path(source_root)/"docs/evidence/2026-11-09/keirin_public_ciphertext_owner_consent_v1.json"
    need(path.is_file() and not path.is_symlink(),
         "OWNER_PUBLIC_CIPHERTEXT_CONSENT_MISSING")
    try:
        consent=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        raise ArchiveError("OWNER_CIPHER_CONSENT_INVALID") from None
    need(consent.get("target_repository")==REPO and
         consent.get("target_branch")==STATE_BRANCH and
         consent.get("plaintext_publication_allowed") is False and
         consent.get("encryption_key_publication_allowed") is False and
         consent.get("source_license_requirements_unchanged") is True and
         consent.get("allowed_material")==
             "AES-256-GCM-encrypted production forecast SQLite snapshots only",
         "OWNER_CIPHER_CONSENT_INVALID")
    return True


def _git_worktree(repo):
    repo=Path(repo).resolve()
    need((repo/".git").exists(),"GITHUB_CHECKOUT_REQUIRED")
    remote=git(repo,"remote","get-url","origin")
    need(remote in ("https://github.com/"+REPO,
                    "https://github.com/"+REPO+".git",
                    "git@github.com:"+REPO+".git"),
         "UNEXPECTED_GIT_REMOTE")
    git(repo,"fetch","--no-tags","origin",
        "refs/heads/"+STATE_BRANCH+":refs/remotes/origin/"+STATE_BRANCH)
    return repo


def _read_head(tree):
    pointer=tree/HEAD
    if not pointer.is_file():
        return None
    need(not pointer.is_symlink() and pointer.stat().st_size<=3072,
         "CIPHER_HEAD_UNSAFE")
    try:head=json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError,ValueError):
        raise ArchiveError("CIPHER_HEAD_BAD_JSON") from None
    keys={"schema","repository_id","mode","generation",
          "cipher_sha256","previous_cipher_sha256","snapshot_file",
          "scope_file","proof_file"}
    need(type(head) is dict and set(head)==keys and
         head["schema"]==SCHEMA and
         head["repository_id"]==REPOSITORY_ID and
         head["mode"]=="production" and
         type(head["generation"]) is int and
         1<=head["generation"]<=100000 and
         type(head["cipher_sha256"]) is str and
         SHA.fullmatch(head["cipher_sha256"]),
         "PRODUCTION_HISTORY_HEAD_INVALID")
    scope={
        "schema":"RACE_AI_GITHUB_SQLITE_V1",
        "repository_id":REPOSITORY_ID,
        "mode":"production",
        "generation":head["generation"],
        "previous_cipher_sha256":head["previous_cipher_sha256"],
    }
    _scope(scope)
    prefix=BASE/"snapshots"/(
        f"g{head['generation']:06d}-{head['cipher_sha256']}")
    for key,ext in (("snapshot_file",".enc"),
                    ("scope_file",".scope.json"),
                    ("proof_file",".proof.json")):
        need(head[key]==(str(prefix)+ext),
             "CIPHER_PATH_NOT_BOUND_TO_SHA_AND_GENERATION")
        path=tree/head[key]
        need(path.is_file() and not path.is_symlink(),
             "CIPHER_HISTORY_FILE_MISSING")
    file_scope=json.loads((tree/head["scope_file"]).read_text())
    need(file_scope==scope,"CIPHER_SCOPE_CHAIN_MISMATCH")
    file_proof=json.loads((tree/head["proof_file"]).read_text())
    need(type(file_proof) is dict and set(file_proof)=={
        "schema","cipher_sha256","repository_id","production_pr71_only"} and
        file_proof["schema"]==PROOF and
        file_proof["repository_id"]==REPOSITORY_ID and
        file_proof["cipher_sha256"]==head["cipher_sha256"] and
        file_proof["production_pr71_only"] is True,
        "CIPHER_PROOF_MISMATCH")
    raw=(tree/head["snapshot_file"]).read_bytes()
    need(0<len(raw)<=12*1024*1024 and
         sha256(raw).hexdigest()==head["cipher_sha256"],
         "CIPHER_BYTES_SHA_MISMATCH")
    return head


def _pr71_inventory(db):
    validate_snapshot(db)
    with sqlite3.connect(Path(db).resolve().as_uri()+"?mode=ro",
                         uri=True,timeout=5) as con:
        con.execute("PRAGMA trusted_schema=OFF")
        names={x[0] for x in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        need({"keirin_pr71_four_model_suites","result_revisions"}<=names,
             "PR71_FOUR_MODEL_DB_SCHEMA_REQUIRED")
    with PrivateKeirinStore(db) as store:
        ledger=FourModelRankLedger(store)
        rows=store.db.execute(
            "SELECT race_id FROM keirin_pr71_four_model_suites "
            "ORDER BY race_id").fetchall()
        need(0<len(rows)<=2000,"PR71_REAL_FROZEN_RACES_REQUIRED")
        digests=[]
        for row in rows:
            rec=ledger.read_suite(row["race_id"])
            need(rec is not None and
                 tuple(rec["suite"]["models"])==tuple(ALL_MODELS),
                 "PR71_ALL_FOUR_ORIGINAL_MODELS_REQUIRED")
            cutoff=utc(rec["source"]["official_cutoff_at"])
            persisted=utc(rec["persisted_at"])
            need((cutoff-persisted).total_seconds()>65,
                 "PR71_ORIGINAL_NOT_PROSPECTIVELY_FROZEN")
            digests.append((row["race_id"],rec["source_sha256"],
                            rec["suite"]["suite_sha256"]))
        revision_rows=store.db.execute(
            "SELECT race_id,revision,payload_sha256 FROM result_revisions "
            "ORDER BY race_id,revision").fetchall()
        digest=sha256(canonical({
            "four_model_originals":digests,
            "result_revision_digests":[tuple(r) for r in revision_rows],
        })).hexdigest()
    return {"internal_digest":digest,"frozen":len(rows),
            "revisions":len(revision_rows)}


def _node(source_root,*argv,extra_env=None):
    env={**os.environ,**(extra_env or {})}
    code=Path(source_root)/"scripts/keirin_github_checkpoint.mjs"
    need(code.is_file(),"EXISTING_AES_GCM_CODEC_REQUIRED")
    return command(["node",str(code),*map(str,argv)],
                   cwd=source_root,env=env)


def restore(repo,source_root,target):
    """True independent checkpoint restoration. Returns (state head, inventory)."""
    repo=_git_worktree(repo)
    target=Path(target)
    need(target.is_absolute() and not target.exists() and
         target.parent.is_dir(),"PRIVATE_RESTORE_CREATE_ONCE_REQUIRED")
    with TemporaryDirectory(prefix="pr71-state-read-") as temp:
        tree=Path(temp)/"state"
        git(repo,"worktree","add","--detach",str(tree),
            "refs/remotes/origin/"+STATE_BRANCH)
        try:
            head=_read_head(tree)
            if head is None:return None,None
            _node(source_root,"unseal",tree/head["snapshot_file"],
                  target,tree/head["scope_file"],
                  extra_env={"RACE_AI_EXPECTED_CIPHER_SHA256":head["cipher_sha256"]})
            verified=_pr71_inventory(target)
            return head,verified
        finally:
            git(repo,"worktree","remove","--force",str(tree))


def commit(repo,source_root,db,prior):
    """Append an independently-readback AES-GCM generation, never overwrite."""
    repo=_git_worktree(repo)
    inventory=_pr71_inventory(db)
    generation=(prior["generation"]+1 if prior else 1)
    prev=prior["cipher_sha256"] if prior else None
    scope={"schema":"RACE_AI_GITHUB_SQLITE_V1",
           "repository_id":REPOSITORY_ID,"mode":"production",
           "generation":generation,"previous_cipher_sha256":prev}
    _scope(scope)
    with TemporaryDirectory(prefix="pr71-state-write-") as temp:
        tmp=Path(temp); dbcopy=tmp/"consistent.sqlite3"
        backup_sqlite(db,dbcopy)
        sc=tmp/"scope.json"
        sc.write_bytes(canonical(scope)+b"\n")
        cipher=tmp/"state.enc"
        _node(source_root,"seal",dbcopy,cipher,sc)
        digest=sha256(cipher.read_bytes()).hexdigest()
        # Decrypt with existing codec in a fresh file, without writing to Git.
        readback=tmp/"readback.sqlite3"
        _node(source_root,"unseal",cipher,readback,sc,
              extra_env={"RACE_AI_EXPECTED_CIPHER_SHA256":digest})
        again=_pr71_inventory(readback)
        need(again==inventory,
             "INDEPENDENT_AES_SQLITE_MODEL_READBACK_MISMATCH")
        tree=tmp/"state"
        git(repo,"worktree","add","--detach",str(tree),
            "refs/remotes/origin/"+STATE_BRANCH)
        try:
            latest=_read_head(tree)
            need((latest is None and prior is None) or
                 (latest is not None and prior is not None and
                  latest["cipher_sha256"]==prior["cipher_sha256"] and
                  latest["generation"]==prior["generation"]),
                 "STATE_BRANCH_CHANGED_SINCE_LAST_RESTORE")
            stem=f"g{generation:06d}-{digest}"
            rel=BASE/"snapshots"/stem
            _create_once(tree/(str(rel)+".enc"),cipher.read_bytes())
            _create_once(tree/(str(rel)+".scope.json"),
                         canonical(scope)+b"\n")
            proof={"schema":PROOF,"cipher_sha256":digest,
                   "repository_id":REPOSITORY_ID,
                   "production_pr71_only":True}
            _create_once(tree/(str(rel)+".proof.json"),
                         canonical(proof)+b"\n")
            head={"schema":SCHEMA,"repository_id":REPOSITORY_ID,
                  "mode":"production","generation":generation,
                  "cipher_sha256":digest,"previous_cipher_sha256":prev,
                  "snapshot_file":str(rel)+".enc",
                  "scope_file":str(rel)+".scope.json",
                  "proof_file":str(rel)+".proof.json"}
            (tree/HEAD).parent.mkdir(parents=True,exist_ok=True)
            (tree/HEAD).write_bytes(canonical(head)+b"\n")
            git(tree,"add","--",str(rel)+".enc",
                str(rel)+".scope.json",str(rel)+".proof.json",str(HEAD))
            git(tree,"-c","user.name=github-actions[bot]",
                "-c","user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit","-m",f"archive(keirin): AES-GCM PR71 production g{generation:06d}")
            sent=git(tree,"rev-parse","HEAD")
            git(tree,"push","origin","HEAD:refs/heads/"+STATE_BRANCH)
            git(repo,"fetch","--no-tags","origin",
                "refs/heads/"+STATE_BRANCH+":refs/remotes/origin/"+STATE_BRANCH)
            need(git(repo,"rev-parse","refs/remotes/origin/"+STATE_BRANCH)==sent,
                 "REMOTE_ENCRYPTED_COMMIT_READBACK_MISMATCH")
            return {"state":"CLOUD_PR71_ENCRYPTED_GIT_HISTORY_READBACK_VERIFIED",
                    "generation":generation,
                    "cipher_sha256":digest,
                    "owner_plaintext_public":False,
                    "all_four_original_models_verified":True}
        finally:
            git(repo,"worktree","remove","--force",str(tree))


def _licensed_inputs(inbox,source_root):
    """Optional provider-controlled real feed; absent means HOLD, not fake races.

    The GitHub Secrets must carry the *real* owner-reviewed licence manifest
    (with actual documented use rights) and its SHA-pinned private document.
    No vendor URL or contract is manufactured by this adapter.
    """
    e=os.environ
    needed=("RACE_AI_KEIRIN_FEED_ENDPOINT","RACE_AI_KEIRIN_FEED_RIGHTS_REF",
            "RACE_AI_KEIRIN_LICENSE_MANIFEST_B64",
            "RACE_AI_KEIRIN_LICENSE_DOCUMENT_B64")
    if any(not e.get(k) for k in needed):
        return None,None,"SOURCE_FEED_NOT_CONFIGURED"
    from race_ai.keirin_permissioned_owner import (
        load_operator_grants,stage_permissioned_deliveries
    )
    from race_ai.keirin_licensed_api_ingest import fetch_authorized_exports
    docs=Path(inbox)/"license"
    docs.mkdir(mode=0o700)
    try:
        manifest=json.loads(base64.b64decode(
            e[needed[2]],validate=True))
        document=base64.b64decode(e[needed[3]],validate=True)
        need(type(manifest) is dict and type(manifest.get("grants")) is list and
             bool(manifest["grants"]) and len(document)<=1_000_000,
             "OWNER_PRIVATE_LICENSE_BUNDLE_INVALID")
        file=docs/"provider-rights-document"
        file.write_bytes(document)
        file.chmod(0o600)
        original=sha256(document).hexdigest()
        for grant in manifest["grants"]:
            need(grant.get("license_document_sha256")==original,
                 "PROVIDER_RIGHTS_DOCUMENT_SHA_NOT_MATCHED")
            grant["license_document_path"]=str(file)
        path=docs/"manifest.json"
        path.write_bytes(canonical(manifest))
        path.chmod(0o600)
        grants=load_operator_grants(
            path,now=datetime.now(timezone.utc).isoformat())
        fetched=fetch_authorized_exports(
            inbox,grants,sources=[(e[needed[0]],e[needed[1]])],
            token=e.get("RACE_AI_KEIRIN_FEED_TOKEN") or None)
        staged=stage_permissioned_deliveries(
            inbox,grants,now=datetime.now(timezone.utc).isoformat())
        return grants,staged,"LICENSED_SOURCE_AUDITED"
    except (ValueError,KeyError,TypeError,OSError):
        raise ArchiveError("LICENSED_CLOUD_SOURCE_NOT_ADMITTED") from None


def cycle(repo,source_root):
    require_main_event()
    check_owner_cipher_consent(source_root)
    need(bool(os.getenv("RACE_AI_STATE_KEY")),
         "PRODUCTION_STATE_KEY_NOT_CONFIGURED")
    with TemporaryDirectory(prefix="keirin-pr71-cloud-owner-") as temp:
        root=Path(temp)
        db=root/"private.sqlite3"
        inbox=root/"inbox"
        inbox.mkdir(mode=0o700)
        prior,old=restore(repo,source_root,db)
        grants,stage,status=_licensed_inputs(inbox,source_root)
        if prior is None and grants is None:
            return {"state":"HOLD_NO_LICENSED_FUTURE_SOURCE_AND_NO_PRODUCTION_ORIGINAL",
                    "new_forecasts":0,"source_state":status,
                    "private_key_used_without_writing_public_data":True}
        # A genesis is permitted ONLY when a real license-admitted full PR71
        # packet is present. No artificial new empty "production archive".
        if prior is None and (stage or {}).get("new_pre_race_inputs",0)==0:
            return {"state":"HOLD_NO_COMPLETE_PRE_CUTOFF_INPUT",
                    "new_forecasts":0,"source_state":status}
        from race_ai.keirin_pr71_four_model_rank import stage_existing_owner_pre_races
        # Results share the already authorized source feed, but are not model
        # features. Only an ORIGINAL four-model suite frozen before the cutoff
        # can receive a later source result. Never create a retroactive model.
        from race_ai.keirin_licensed_result_stage import (
            apply_existing_frozen_results
        )
        with PrivateKeirinStore(db) as store:
            before=old
            frozen=stage_existing_owner_pre_races(
                inbox,store,source_admission=grants.allowed
                if grants is not None else None)
            results=(apply_existing_frozen_results(
                inbox,store,grants,checked_at=store.clock().isoformat())
                if grants is not None else {
                    "results_appended":0,"results_already_present":0,
                    "results_held":0,"no_forecast_backfilled":True})
            replay=FourModelRankLedger(store).replay_all()
        after=_pr71_inventory(db)
        if before is not None and after==before:
            return {"state":"CLOUD_PR71_RESTORED_NO_CHANGED_MODEL_OR_RESULT",
                    "originals_preserved":True,"new_forecasts":0,
                    "source_state":status,
                    "result_rows_appended":results["results_appended"],
                    "result_rows_held":results["results_held"],
                    "official_result_independently_authenticated":False}
        if prior is None and frozen.get("private_four_model_predictions_saved",0)==0:
            return {"state":"HOLD_NOTHING_PRE_CUTOFF_TO_ARCHIVE",
                    "new_forecasts":0,"source_state":status}
        out=commit(repo,source_root,db,prior)
        # Do not publish model output, rider details or result amounts.
        return {**out,"source_state":status,
                "new_forecast_stage_nonzero":bool(
                    frozen.get("private_four_model_predictions_saved",0)),
                "existing_pdca_invoked":True,
                "result_rows_appended":results["results_appended"],
                "result_rows_held":results["results_held"],
                # A configured provider URL and a local licence manifest
                # are not independently authenticated official results.
                "official_result_independently_authenticated":False,
                "legal_provider_rights_independently_certified_by_code":False,
                "all_race_results_acquired":False,
                "formal_accuracy_calculated":False}


def main(argv=None):
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode",choices=("cycle","verify"))
    p.add_argument("--repo",required=True)
    p.add_argument("--source-root",required=True)
    args=p.parse_args(argv)
    try:
        require_main_event()
        check_owner_cipher_consent(args.source_root)
        if args.mode=="cycle":
            report=cycle(args.repo,args.source_root)
        else:
            with TemporaryDirectory(prefix="keirin-pr71-independent-") as tmp:
                head,verified=restore(args.repo,args.source_root,
                                      Path(tmp)/"readback.sqlite3")
                need(head is not None and verified is not None,
                     "PRODUCTION_PR71_CHECKPOINT_NOT_YET_CREATED")
                report={"state":"PR71_SEPARATE_GITHUB_RUNNER_AES_GCM_READBACK_OK",
                        "generation":head["generation"],
                        "four_models_and_private_sqlite_verified":True,
                        "plaintext_public":False}
        print(json.dumps(report,sort_keys=True))
        return 0
    except (ArchiveError,OSError,ValueError,TypeError,KeyError,sqlite3.Error):
        print('{"state":"HOLD_PR71_CLOUD_GATE_NOT_VERIFIED","real_forecasts_claimed":false}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
