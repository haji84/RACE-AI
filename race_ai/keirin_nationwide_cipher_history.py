"""Same-repository Git-only, create-once A/B CIPHERTEXT archive.

The existing GitHub-only encrypted-history branch is reused, without
modifying its PR71 SQLite head. A race gets one immutable RSA/AES envelope,
one SHA-bound receipt, and a normal FAST-FORWARD Git commit. Concurrent jobs
cannot silently overwrite the same race: losing a non-fast-forward push must
refresh the state and recheck the target. No plaintext, key or provider GET.

Production writes are gated by an explicit owner repository variable.
This is a repository-level research transport, NOT a certified timestamp,
private repository, reliable backup, or evidence of official data rights.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import re
import subprocess

from . import keirin_nationwide_auto_storage as storage

REPO = "haji84/RACE-AI"
REPO_ID = "1416489937"
BRANCH = "state/keirin-encrypted-history"
ROOT = "state/keirin/ab/v1"
SCHEMA = "RACE_AI_KEIRIN_AB_GIT_CIPHER_ORIGINAL_V1"
SHA = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
RUN = re.compile(r"^[1-9][0-9]{0,16}$")
MAX_BYTES = storage.MAX_CIPHER_BYTES


class GitCipherArchiveError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise GitCipherArchiveError(reason)


def _cmd(repo, *args, okay=False):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        done = subprocess.run(
            ["git", *args], cwd=repo, text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=35, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise GitCipherArchiveError("GIT_COMMAND_OR_REMOTE_UNAVAILABLE") from None
    if done.returncode != 0 and not okay:
        raise GitCipherArchiveError("GIT_COMMAND_OR_REMOTE_UNAVAILABLE")
    return done.returncode, done.stdout.strip()


def _remote(repo, *, synthetic_local):
    repo=Path(repo).resolve()
    need((repo/".git").exists(), "CHECKED_OUT_GIT_REPOSITORY_REQUIRED")
    url=_cmd(repo, "remote", "get-url", "origin")[1]
    if synthetic_local:
        need(url.startswith("file://") or Path(url).is_absolute(),
             "TEST_MODE_ONLY_LOCAL_GIT_REMOTES")
    else:
        need(url in (
            "https://github.com/haji84/RACE-AI",
            "https://github.com/haji84/RACE-AI.git",
            "git@github.com:haji84/RACE-AI",
            "git@github.com:haji84/RACE-AI.git",
        ), "UNEXPECTED_GIT_REMOTE")
        need(os.getenv("RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED") == "true",
             "OWNER_PUBLIC_CIPHERTEXT_OPT_IN_NOT_SET")
        if os.getenv("GITHUB_ACTIONS") == "true":
            need(os.getenv("GITHUB_REPOSITORY") == REPO and
                 os.getenv("GITHUB_REPOSITORY_ID") == REPO_ID and
                 os.getenv("GITHUB_REF") == "refs/heads/main",
                 "UNTRUSTED_ACTIONS_PRODUCTION_ARCHIVE_CONTEXT")
    return repo


def _refs(rid):
    need(type(rid) is str and re.fullmatch(r"20[0-9]{10}", rid),
         "BAD_RACE_ID")
    day=f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}"
    try:
        need(date.fromisoformat(day).isoformat()==day,"RACE_DATE_INVALID")
    except ValueError:
        raise GitCipherArchiveError("RACE_DATE_INVALID") from None
    stem=f"{ROOT}/{day}/{rid}"
    return stem+".sealed.json", stem+".receipt.json"


def _cipher(raw, expected_sha):
    need(type(raw) is bytes and 0<len(raw)<MAX_BYTES and
         type(expected_sha) is str and SHA.fullmatch(expected_sha) and
         sha256(raw).hexdigest()==expected_sha,
         "CIPHER_BYTES_NOT_SHA_AUTHENTICATED")
    try:
        doc=json.loads(raw)
    except (ValueError, UnicodeError):
        raise GitCipherArchiveError("CIPHER_JSON_INVALID") from None
    try:
        storage.validate_cipher(doc)
    except (ValueError,TypeError,KeyError):
        raise GitCipherArchiveError("CIPHER_ENVELOPE_INVALID") from None
    return doc


def _receipt(doc, digest, run_id, producer_sha, previous_head):
    need(type(run_id) is str and RUN.fullmatch(run_id) and
         type(producer_sha) is str and COMMIT.fullmatch(producer_sha) and
         type(previous_head) is str and COMMIT.fullmatch(previous_head),
         "PRODUCER_OR_PARENT_PROVENANCE_REQUIRED")
    return {
        "schema":SCHEMA,
        "race_id":doc["race_id"],
        "cipher_sha256":digest,
        "original_sealed_at":doc["sealed_at"],
        "producer_run_id":run_id,
        "producer_commit":producer_sha,
        "previous_archive_commit":previous_head,
        "branch":BRANCH,
        "cipher_only_not_source_or_cutoff_attestation":True,
    }


def _refresh(repo):
    _cmd(repo,"fetch","--no-tags","origin",
         f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    head=_cmd(repo,"rev-parse",f"refs/remotes/origin/{BRANCH}")[1]
    need(COMMIT.fullmatch(head), "STATE_HEAD_NOT_RETRIEVABLE")
    return head


def _show(repo, ref, path):
    done=_cmd(repo,"show",f"{ref}:{path}",okay=True)
    return done if done[0]==0 else None


def _read_at(repo, ref, race_id, expected_sha):
    cipher_path, receipt_path = _refs(race_id)
    stored=_show(repo,ref,cipher_path)
    metadata=_show(repo,ref,receipt_path)
    need((stored is None)==(metadata is None),
         "ARCHIVE_ORIGINAL_OR_RECEIPT_MISSING")
    if stored is None:
        return None
    raw=(stored[1]+"\n").encode("utf-8")
    try:
        receipt=json.loads(metadata[1])
    except (ValueError,TypeError):
        raise GitCipherArchiveError("ARCHIVE_RECEIPT_NOT_JSON") from None
    need(type(receipt) is dict and
         set(receipt)=={
            "schema","race_id","cipher_sha256","original_sealed_at",
            "producer_run_id","producer_commit","previous_archive_commit",
            "branch","cipher_only_not_source_or_cutoff_attestation"
         } and
         receipt["schema"]==SCHEMA and
         receipt["race_id"]==race_id and receipt["branch"]==BRANCH and
         receipt["cipher_sha256"]==expected_sha and
         receipt["cipher_only_not_source_or_cutoff_attestation"] is True,
         "ARCHIVE_RECEIPT_OR_SHA_MISMATCH")
    doc=_cipher(raw,expected_sha)
    need(doc["race_id"]==race_id and
         receipt["original_sealed_at"]==doc["sealed_at"] and
         RUN.fullmatch(receipt["producer_run_id"]) and
         COMMIT.fullmatch(receipt["producer_commit"]) and
         COMMIT.fullmatch(receipt["previous_archive_commit"]),
         "ARCHIVE_CIPHER_OR_RECEIPT_IDENTITY_FAILED")
    return receipt


def read_original(*, repo, race_id, expected_cipher_sha256,
                  synthetic_local=False):
    """A separate runner can independently fetch EXACT ciphertext and SHA."""
    repo=_remote(repo,synthetic_local=synthetic_local)
    need(type(expected_cipher_sha256) is str and
         SHA.fullmatch(expected_cipher_sha256), "EXPECTED_SHA_REQUIRED")
    head=_refresh(repo)
    receipt=_read_at(repo,head,race_id,expected_cipher_sha256)
    need(receipt is not None,"ARCHIVED_RACE_NOT_FOUND")
    return {
        "state":"ENCRYPTED_GIT_CIPHERTEXT_SHA_READBACK_OK",
        "race_id":race_id,"cipher_sha256":expected_cipher_sha256,
        "observed_branch_head":head,
        "producer_run_id":receipt["producer_run_id"],
        "RSA_decryption_verified":False,
        "official_cutoff_verified":False,
    }


def append_once(*,repo,raw_cipher,expected_cipher_sha256,
                producer_run_id,producer_commit,synthetic_local=False):
    """Strict fast-forward-only append; never create/reset state branch."""
    repo=_remote(repo,synthetic_local=synthetic_local)
    doc=_cipher(raw_cipher,expected_cipher_sha256)
    rid=doc["race_id"]
    cipher_path, receipt_path=_refs(rid)
    # Ensure parent does not get invented: a missing or force-lost branch holds.
    for attempt in range(3):
        head=_refresh(repo)
        prior_cipher=_show(repo,head,cipher_path)
        prior_receipt=_show(repo,head,receipt_path)
        need((prior_cipher is None)==(prior_receipt is None),
             "EXISTING_ARCHIVE_PAIR_INCOMPLETE")
        if prior_cipher is not None:
            if sha256((prior_cipher[1]+"\n").encode("utf-8")).hexdigest() != expected_cipher_sha256:
                raise GitCipherArchiveError("FORECAST_ORIGINAL_ALREADY_EXISTS_DIFFERENT_CIPHER")
            _read_at(repo,head,rid,expected_cipher_sha256)
            return {"state":"IDENTICAL_ORIGINAL_ALREADY_FROZEN_NO_NEW_WRITE",
                    "race_id":rid,"cipher_sha256":expected_cipher_sha256,
                    "readback_head":head}
        receipt=_receipt(doc,expected_cipher_sha256,producer_run_id,
                         producer_commit,head)
        with TemporaryDirectory(prefix="keirin-cipher-only-git-") as d:
            tree=Path(d)/"tree"
            _cmd(repo,"worktree","add","--detach",str(tree),head)
            try:
                dest=tree/cipher_path
                rec=tree/receipt_path
                dest.parent.mkdir(parents=True,exist_ok=True)
                rec.parent.mkdir(parents=True,exist_ok=True)
                need(not dest.exists() and not rec.exists(),
                     "ORIGINAL_RACE_CREATE_ONCE_VIOLATION")
                dest.write_bytes(raw_cipher)
                rec.write_bytes((json.dumps(receipt,sort_keys=True,
                                   separators=(",",":"))+"\n").encode("utf-8"))
                _cmd(tree,"add","--",cipher_path,receipt_path)
                _cmd(tree,"-c","user.name=RACE-AI","-c",
                     "user.email=race-ai@users.noreply.github.com",
                     "commit","-m",f"archive(keirin): sealed A/B {rid} original SHA")
                newhead=_cmd(tree,"rev-parse","HEAD")[1]
                status,_=_cmd(tree,"push","origin",
                              f"HEAD:refs/heads/{BRANCH}",okay=True)
            finally:
                _cmd(repo,"worktree","remove","--force",str(tree),okay=True)
        if status==0:
            observed=read_original(repo=repo,race_id=rid,
                                   expected_cipher_sha256=expected_cipher_sha256,
                                   synthetic_local=synthetic_local)
            # Other distinct race commits can be added after our fast-forward.
            ancestor,_=_cmd(repo,"merge-base","--is-ancestor",newhead,
                             observed["observed_branch_head"],okay=True)
            need(ancestor==0,"ARCHIVE_NEW_COMMIT_NOT_ANCESTOR_OF_READBACK")
            return {"state":"GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED",
                    "race_id":rid,"cipher_sha256":expected_cipher_sha256,
                    "write_commit":newhead,
                    "readback_head":observed["observed_branch_head"]}
        # Race in another runner? Never force-push. Fetch and check.
    raise GitCipherArchiveError("CONCURRENT_GIT_FAST_FORWARD_RETRY_EXHAUSTED")
