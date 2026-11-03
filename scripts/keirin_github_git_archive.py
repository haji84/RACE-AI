"""GitHub-only immutable encrypted checkpoint history, beyond Actions artifacts.

This module stores *ciphertext only* in a dedicated Git ref of the SAME
repository. Never upload plaintext SQLite or production key. Each generation
is create-once, chained to the previous ciphertext SHA, and commits only
an allowlisted trio of encrypted state + nonsensitive metadata.

WARNING: RACE-AI is a PUBLIC repository. Ciphertexts and their sizes are
publicly observable. Production requires a separately configured strong
RACE_AI_STATE_KEY and the owner's informed decision to use public ciphertext.
Do not use this as a guarantee of permanent backups, or a certified clock.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from scripts.keirin_github_sqlite_snapshot import validate_snapshot, SnapshotError

REPO = "haji84/RACE-AI"
REPOSITORY_ID = "1416489937"
STATE_BRANCH = "state/keirin-encrypted-history"
SHA = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
RUN = re.compile(r"^[1-9][0-9]{1,15}$")
MAX_CIPHER = 12*1024*1024
MAX_METADATA = 4096


class ArchiveError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise ArchiveError(reason)


def command(args, *, cwd=None, env=None):
    try:
        result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=35,
                                check=True, text=True)
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ArchiveError("GIT_OR_CHECKPOINT_COMMAND_FAILED") from None


def checked_json(path, max_size=MAX_METADATA):
    path=Path(path)
    need(path.is_file() and not path.is_symlink()
         and 0<path.stat().st_size<=max_size, "METADATA_NOT_REGULAR_OR_BOUNDED")
    try:
        value=json.loads(path.read_bytes())
    except (UnicodeError,ValueError):
        raise ArchiveError("METADATA_JSON_INVALID") from None
    need(type(value) is dict, "METADATA_OBJECT_REQUIRED")
    return value


def cipher_file(path):
    path=Path(path)
    need(path.is_file() and not path.is_symlink() and
         0<path.stat().st_size<=MAX_CIPHER, "CIPHER_NOT_REGULAR_OR_BOUNDED")
    content=path.read_bytes()
    need(0<len(content)<=MAX_CIPHER, "CIPHER_SIZE_INVALID")
    return content


def _scope(scope):
    need(set(scope)=={
        "schema","repository_id","mode","generation","previous_cipher_sha256"
    },"SCOPE_SCHEMA_INVALID")
    need(scope["schema"]=="RACE_AI_GITHUB_SQLITE_V1" and
         scope["repository_id"]==REPOSITORY_ID, "SCOPE_REPOSITORY_INVALID")
    need(scope["mode"] in ("production","synthetic"),"SCOPE_MODE_INVALID")
    need(type(scope["generation"]) is int and 1<=scope["generation"]<=100000,
         "SCOPE_GENERATION_INVALID")
    prev=scope["previous_cipher_sha256"]
    need(prev is None if scope["generation"]==1 else
         type(prev) is str and SHA.fullmatch(prev) is not None,
         "SCOPE_PREVIOUS_CIPHER_INVALID")
    return scope


def validate_bundle(artifact, *, expected_run_id, expected_commit,
                    mode="synthetic"):
    artifact=Path(artifact)
    need(artifact.is_dir() and not artifact.is_symlink(),
         "ARTIFACT_DIRECTORY_INVALID")
    scope=_scope(checked_json(artifact/"scope.json"))
    need(scope["mode"]==mode, "UNEXPECTED_ARCHIVE_MODE")
    proof=checked_json(artifact/"fixture-proof.json")
    need(type(proof.get("cipher_sha256")) is str and
         SHA.fullmatch(proof["cipher_sha256"]) is not None,
         "CIPHER_HASH_UNVERIFIED")
    need(type(expected_run_id) is str and RUN.fullmatch(expected_run_id),
         "PRODUCER_RUN_ID_REQUIRED")
    need(type(expected_commit) is str and COMMIT.fullmatch(expected_commit),
         "PRODUCER_COMMIT_REQUIRED")
    need(str(proof.get("producer_run_id"))==expected_run_id and
         proof.get("producer_sha")==expected_commit,
         "PRODUCER_IDENTITY_MISMATCH")
    if mode=="synthetic":
        need(proof.get("synthetic_only") is True,
             "SYNTHETIC_PROOF_REQUIRED")
    else:
        # A production output cannot use the synthetic proof. A future
        # production bundle schema will need its own authenticated metadata.
        raise ArchiveError("PRODUCTION_ARCHIVE_NOT_YET_AUTHORIZED")
    cipher=cipher_file(artifact/"state.enc")
    digest=sha256(cipher).hexdigest()
    need(digest==proof["cipher_sha256"],"CIPHERTEXT_HASH_MISMATCH")
    need(type(proof.get("snapshot_sha256")) is str and
         SHA.fullmatch(proof["snapshot_sha256"]) is not None and
         type(proof.get("forecast_sha256")) is str and
         SHA.fullmatch(proof["forecast_sha256"]) is not None,
         "FIXTURE_MODEL_HASH_MISSING")
    return scope,proof,cipher,digest


def verify_aead_snapshot(artifact, expected_sha, repo):
    """Decrypt only inside runner temp, validate SQLite. Never stage plaintext."""
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="keirin-aead-") as tmp:
        db=Path(tmp)/"verified.db"
        env=dict(os.environ)
        env["RACE_AI_EXPECTED_CIPHER_SHA256"]=expected_sha
        command([
            "node",str(Path(repo)/"scripts"/"keirin_github_checkpoint.mjs"),
            "unseal",str(Path(artifact)/"state.enc"),
            str(db),str(Path(artifact)/"scope.json")
        ],cwd=repo,env=env)
        try:
            validate_snapshot(db)
        except SnapshotError:
            raise ArchiveError("SQLITE_INTEGRITY_FAILED") from None
        os.chmod(db,0o600)


def _create_once(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        with os.fdopen(fd,"wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise ArchiveError("ARCHIVE_FILE_ALREADY_EXISTS") from None


def archive_in_git(artifact, *, repo, expected_run_id, expected_commit,
                   expected_mode="synthetic", verify_snapshot=True):
    """One archive commit. Never overwrites an encrypted generation.

    The checked-out repo's credentials are required to push a *separate*
    unprotected state ref. A failed or concurrent push does not claim success.
    """
    repo=Path(repo).resolve()
    need(repo.is_dir() and (repo/".git").exists(),
         "GIT_WORKTREE_REQUIRED")
    need(expected_mode=="synthetic","PRODUCTION_AUTO_ARCHIVE_DISABLED")
    scope,proof,cipher,digest=validate_bundle(
        artifact,expected_run_id=expected_run_id,
        expected_commit=expected_commit,mode=expected_mode)
    if verify_snapshot:
        verify_aead_snapshot(artifact,digest,repo)
    runenv=os.environ
    if runenv.get("GITHUB_ACTIONS")=="true":
        need(runenv.get("GITHUB_REPOSITORY")==REPO and
             runenv.get("GITHUB_REPOSITORY_ID")==REPOSITORY_ID and
             runenv.get("GITHUB_REF")=="refs/heads/main" and
             runenv.get("GITHUB_EVENT_NAME")=="workflow_run",
             "UNTRUSTED_ACTIONS_ARCHIVE_ORIGIN")
    git=lambda *a, cwd=repo: command(["git",*a],cwd=cwd)
    remote=git("remote","get-url","origin")
    need(remote in (
            "https://github.com/"+REPO,
            "https://github.com/"+REPO+".git",
            "https://github.com/"+REPO+"/",
            "git@github.com:"+REPO+".git",
            "git@github.com:"+REPO,
         ), "GIT_REMOTE_REPOSITORY_MISMATCH")
    git("fetch","--no-tags","origin",
        "refs/heads/"+STATE_BRANCH+":refs/remotes/origin/"+STATE_BRANCH)
    with tempfile.TemporaryDirectory(prefix="keirin-state-worktree-") as tmp:
        wt=Path(tmp)/"tree"
        git("worktree","add","--detach",str(wt),
            "refs/remotes/origin/"+STATE_BRANCH)
        try:
            base=wt/"state"/"keirin"/"v1"
            current=base/"latest.json"
            prior=checked_json(current) if current.is_file() else None
            generation=scope["generation"]
            if prior is None:
                need(generation==1 and scope["previous_cipher_sha256"] is None,
                     "STATE_HISTORY_NOT_INITIALIZED")
            else:
                need(prior.get("schema")=="RACE_AI_KEIRIN_GIT_ARCHIVE_HEAD_V1" and
                     type(prior.get("generation")) is int and
                     type(prior.get("cipher_sha256")) is str and
                     SHA.fullmatch(prior["cipher_sha256"]),
                     "PREVIOUS_ARCHIVE_HEAD_INVALID")
                if (generation==prior["generation"] and
                    digest==prior["cipher_sha256"] and
                    str(prior.get("producer_run_id"))==expected_run_id):
                    return {"status":"ARCHIVE_ALREADY_COMMITTED",
                            "generation":generation,"cipher_sha256":digest,
                            "immutable_previous_preserved":True}
                need(generation==prior["generation"]+1 and
                     scope["previous_cipher_sha256"]==prior["cipher_sha256"],
                     "NONCONTIGUOUS_OR_REWINDING_ARCHIVE_HISTORY")
            basename=f"g{generation:06d}-{digest}"
            rel=Path("state")/"keirin"/"v1"/"snapshots"
            snap=str(rel/(basename+".enc"))
            scopefile=str(rel/(basename+".scope.json"))
            prooffile=str(rel/(basename+".proof.json"))
            _create_once(wt/snap,cipher)
            _create_once(wt/scopefile,
                         json.dumps(scope,sort_keys=True,
                                    separators=(",",":")).encode()+b"\n")
            _create_once(wt/prooffile,
                         json.dumps(proof,sort_keys=True,
                                    separators=(",",":")).encode()+b"\n")
            head={
                "schema":"RACE_AI_KEIRIN_GIT_ARCHIVE_HEAD_V1",
                "mode":scope["mode"],
                "repository_id":REPOSITORY_ID,
                "generation":generation,
                "cipher_sha256":digest,
                "previous_cipher_sha256":scope["previous_cipher_sha256"],
                "snapshot_file":snap,
                "scope_file":scopefile,
                "proof_file":prooffile,
                "producer_run_id":expected_run_id,
                "producer_commit":expected_commit,
            }
            # The HEAD pointer is mutable, but each version is in immutable
            # commit history. The update uses a non-force fast-forward push.
            current.write_text(json.dumps(head,sort_keys=True,
                                separators=(",",":"))+"\n",encoding="utf-8")
            git("add","--",snap,scopefile,prooffile,
                "state/keirin/v1/latest.json",cwd=wt)
            git("-c","user.name=github-actions[bot]",
                "-c","user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit","-m",f"archive(keirin): sealed synthetic generation {generation}",
                cwd=wt)
            pushed=git("rev-parse","HEAD",cwd=wt)
            need(COMMIT.fullmatch(pushed) is not None,"ARCHIVE_COMMIT_INVALID")
            # Concurrency races fail closed. No force push, ever.
            git("push","origin","HEAD:refs/heads/"+STATE_BRANCH,cwd=wt)
            remote_head=git("ls-remote","origin","refs/heads/"+STATE_BRANCH,cwd=wt)
            need(remote_head.split()[0]==pushed,
                 "REMOTE_ARCHIVE_READBACK_NOT_VERIFIED")
            need(sha256((wt/snap).read_bytes()).hexdigest()==digest,
                 "ARCHIVE_DATA_CHANGED")
            return {
                "status":"ENCRYPTED_GIT_HISTORY_ARCHIVED",
                "generation":generation,
                "cipher_sha256":digest,
                "git_commit":pushed,
                "producer_run_id":expected_run_id,
                "private_plaintext_published":False,
                "public_ciphertext_visible":True,
                "indefinite_data_retention_guaranteed":False,
            }
        finally:
            try:
                git("worktree","remove","--force",str(wt))
            except ArchiveError:
                pass


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact",required=True)
    p.add_argument("--repo",required=True)
    p.add_argument("--expected-run-id",required=True)
    p.add_argument("--expected-commit",required=True)
    args=p.parse_args()
    try:
        report=archive_in_git(
            args.artifact,repo=args.repo,
            expected_run_id=args.expected_run_id,
            expected_commit=args.expected_commit)
        print(json.dumps(report,sort_keys=True))
        return 0
    except (ArchiveError,ValueError,OSError):
        print('{"status":"GIT_ARCHIVE_NOT_VERIFIED","private_plaintext_published":false}')
        return 2


if __name__=="__main__":
    sys.exit(main())
