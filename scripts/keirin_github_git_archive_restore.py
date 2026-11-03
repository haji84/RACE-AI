"""Read a retained encrypted SQLite checkpoint from Git history, not artifacts.

Fetches the exact state branch and validates the generation/previous hash,
stored original producer identity, encrypted bytes and AES-GCM SQLite snapshot.
Synthetic-only continuation uses the existing PR71 model fixture and checks
that the first forecast remains unchanged. No secrets or source records logged.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from scripts.keirin_github_git_archive import (
    ArchiveError, REPOSITORY_ID, REPO, STATE_BRANCH, SHA, COMMIT, RUN,
    checked_json, cipher_file, command, _scope, validate_bundle,
    verify_aead_snapshot
)

ARTIFACT_ROOT = Path("state/keirin/v1")
SNAPSHOT_NAME = re.compile(r"^g[0-9]{6}-[0-9a-f]{64}$")


def need(test, reason):
    if not test:
        raise ArchiveError(reason)


def restore_from_git(*, repo, continue_synthetic=False):
    repo=Path(repo).resolve()
    need((repo/".git").exists(), "GIT_REPOSITORY_REQUIRED")
    if os.environ.get("GITHUB_ACTIONS")=="true":
        need(os.environ.get("GITHUB_REPOSITORY")==REPO and
             os.environ.get("GITHUB_REPOSITORY_ID")==REPOSITORY_ID and
             os.environ.get("GITHUB_REF")=="refs/heads/main" and
             os.environ.get("GITHUB_EVENT_NAME")=="workflow_run",
             "UNTRUSTED_RESTORE_RUNTIME")
    git=lambda *args, cwd=repo: command(["git",*args],cwd=cwd)
    remote=git("remote","get-url","origin")
    need(remote.startswith("https://github.com/"+REPO) or
         remote.startswith("git@github.com:"+REPO),
         "GIT_REMOTE_REPOSITORY_MISMATCH")
    git("fetch","--no-tags","origin",
        "refs/heads/"+STATE_BRANCH+":refs/remotes/origin/"+STATE_BRANCH)
    with tempfile.TemporaryDirectory(prefix="keirin-state-readonly-") as tmp:
        tree=Path(tmp)/"tree"
        git("worktree","add","--detach",str(tree),
            "refs/remotes/origin/"+STATE_BRANCH)
        try:
            head=checked_json(tree/ARTIFACT_ROOT/"latest.json")
            need(set(head)=={
                "schema","mode","repository_id","generation",
                "cipher_sha256","previous_cipher_sha256","snapshot_file",
                "scope_file","proof_file","producer_run_id",
                "producer_commit"
            },"ARCHIVE_HEAD_FIELDS_INVALID")
            need(head["schema"]=="RACE_AI_KEIRIN_GIT_ARCHIVE_HEAD_V1" and
                 head["mode"]=="synthetic" and
                 head["repository_id"]==REPOSITORY_ID and
                 type(head["generation"]) is int and
                 1<=head["generation"]<=100000 and
                 type(head["cipher_sha256"]) is str and
                 SHA.fullmatch(head["cipher_sha256"]) is not None and
                 type(head["producer_run_id"]) is str and
                 RUN.fullmatch(head["producer_run_id"]) is not None and
                 type(head["producer_commit"]) is str and
                 COMMIT.fullmatch(head["producer_commit"]) is not None,
                 "ARCHIVE_HEAD_INVALID")
            stem=f"g{head['generation']:06d}-{head['cipher_sha256']}"
            need(SNAPSHOT_NAME.fullmatch(stem) is not None,
                 "ARCHIVE_SNAPSHOT_FILENAME_INVALID")
            base="state/keirin/v1/snapshots/"+stem
            need(head["snapshot_file"]==base+".enc" and
                 head["scope_file"]==base+".scope.json" and
                 head["proof_file"]==base+".proof.json",
                 "ARCHIVE_PATH_TRAVERSAL_OR_MISMATCH")
            for key in ("snapshot_file","scope_file","proof_file"):
                need((tree/head[key]).is_file() and
                     not (tree/head[key]).is_symlink(),
                     "ARCHIVE_INPUT_NOT_REGULAR")
            copied=Path(tmp)/"artifact"
            copied.mkdir()
            shutil.copyfile(tree/head["snapshot_file"],copied/"state.enc")
            shutil.copyfile(tree/head["scope_file"],copied/"scope.json")
            shutil.copyfile(tree/head["proof_file"],copied/"fixture-proof.json")
            scope,proof,cipher,digest=validate_bundle(
                copied,expected_run_id=head["producer_run_id"],
                expected_commit=head["producer_commit"],mode="synthetic")
            need(digest==head["cipher_sha256"] and
                 scope["generation"]==head["generation"] and
                 scope["previous_cipher_sha256"]==
                   head["previous_cipher_sha256"],"ARCHIVE_HISTORY_CONFLICT")
            verify_aead_snapshot(copied,digest,repo)
            if continue_synthetic:
                env={**os.environ,
                    "RACE_AI_EXPECTED_CIPHER_SHA256":digest,
                    "EXPECTED_PRODUCER_RUN_ID":head["producer_run_id"],
                    "EXPECTED_PRODUCER_SHA":head["producer_commit"]}
                command([sys.executable,"-m",
                    "scripts.keirin_github_checkpoint_fixture","consume",
                    "--work",str(Path(tmp)/"continued"),
                    "--artifact",str(copied)],
                    cwd=repo,env=env)
            return {
                "schema":"RACE_AI_GIT_HISTORY_RESTORE_PROOF_V1",
                "status":"CIPHERTEXT_VERIFIED_FROM_GIT_BRANCH",
                "generation":scope["generation"],
                "cipher_sha256":digest,
                "producer_run_id":head["producer_run_id"],
                "fixture_next_model_continued":bool(continue_synthetic),
                "synthetic_only":True,
                "plaintext_published":False,
                "artifact_retention_dependency":False,
            }
        finally:
            try:
                git("worktree","remove","--force",str(tree))
            except ArchiveError:
                pass


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo",required=True)
    p.add_argument("--continue-synthetic",action="store_true")
    args=p.parse_args()
    try:
        result=restore_from_git(repo=args.repo,
                                continue_synthetic=args.continue_synthetic)
        print(json.dumps(result,sort_keys=True))
        return 0
    except (ArchiveError,ValueError,OSError):
        print('{"status":"GIT_HISTORY_RESTORE_NOT_VERIFIED","plaintext_published":false}')
        return 2

if __name__=="__main__":
    sys.exit(main())
