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
from . import keirin_form_fall_shadow as condition

REPO = "haji84/RACE-AI"
REPO_ID = "1416489937"
BRANCH = "state/keirin-encrypted-history"
ROOT = "state/keirin/ab/v1"
SCHEMA = "RACE_AI_KEIRIN_AB_GIT_CIPHER_ORIGINAL_V1"
FORM_SCHEMA = "RACE_AI_KEIRIN_CONDITIONED_AB_GIT_ORIGINAL_V1"
SHA = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
RUN = re.compile(r"^[1-9][0-9]{0,16}$")
MAX_BYTES = storage.MAX_CIPHER_BYTES
MAX_BLOB_READ_BYTES = 32 * 1024 * 1024


class GitCipherArchiveError(ValueError):
    pass


class GitCipherFetchTimeout(GitCipherArchiveError):
    pass


def need(ok, reason):
    if not ok:
        raise GitCipherArchiveError(reason)


def _cmd(repo, *args, okay=False, timeout=35, index_path=None):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if index_path is not None:
        env.update(GIT_INDEX_FILE=str(index_path), GIT_NO_LAZY_FETCH="1")
    try:
        done = subprocess.run(
            ["git", *args], cwd=repo, text=True, encoding="utf-8",
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        if args[0] == "fetch":
            raise GitCipherFetchTimeout("GIT_COMMAND_OR_REMOTE_UNAVAILABLE") from None
        raise GitCipherArchiveError("GIT_COMMAND_OR_REMOTE_UNAVAILABLE") from None
    except OSError:
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


def _receipt(doc, digest, run_id, producer_sha, previous_head, cohort_sha256=None):
    need(type(run_id) is str and RUN.fullmatch(run_id) and
         type(producer_sha) is str and COMMIT.fullmatch(producer_sha) and
         type(previous_head) is str and COMMIT.fullmatch(previous_head),
         "PRODUCER_OR_PARENT_PROVENANCE_REQUIRED")
    receipt = {
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
    if cohort_sha256 is not None:
        need(type(cohort_sha256) is str and SHA.fullmatch(cohort_sha256),
             "REGISTRY_COHORT_SHA_REQUIRED")
        receipt["cohort_sha256"] = cohort_sha256
    return receipt


def _refresh(repo, *, retry_on_timeout=False, blobless=False):
    options = ("--filter=blob:none", "--no-recurse-submodules") if blobless else ()
    fetch = ("fetch", "--no-tags", *options, "origin",
             f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
    try:
        _cmd(repo, *fetch)
    except GitCipherFetchTimeout:
        if not retry_on_timeout:
            raise
        _cmd(repo, *fetch, timeout=90)
    head=_cmd(repo,"rev-parse",f"refs/remotes/origin/{BRANCH}")[1]
    need(COMMIT.fullmatch(head), "STATE_HEAD_NOT_RETRIEVABLE")
    return head


def _show(repo, ref, path):
    done=_cmd(repo,"show",f"{ref}:{path}",okay=True)
    if done[0] == 0:
        return done
    _require_absent_path(repo, ref, path)
    return None


def _require_absent_path(repo, ref, path):
    # On a promisor remote a failed blob retrieval can mean the path exists
    # but its bytes are unavailable. Only the tree can attest absence.
    _, entry = _cmd(repo, "--no-replace-objects", "ls-tree", "--full-tree", ref, "--", path)
    need(not entry, "ARCHIVE_BLOB_READ_UNAVAILABLE")


def _push_archive_files(repo, parent, files, message, *, replace_path=None):
    """Fast-forward a complete archive tree without materializing its blobs."""
    need(COMMIT.fullmatch(parent) and bool(files), "ARCHIVE_APPEND_INPUT_INVALID")
    with TemporaryDirectory(prefix="keirin-archive-index-") as folder:
        index = Path(folder) / "index"
        content = Path(folder) / "content"
        _cmd(repo, "--no-replace-objects", "read-tree", parent, index_path=index)
        for path, raw in files.items():
            _, entry = _cmd(repo, "ls-files", "--stage", "--", path, index_path=index)
            if path == replace_path:
                need(not entry or (entry.startswith("100644 ") and
                     entry.endswith("\t" + path) and "\n" not in entry), "INDEX_SYMLINK")
            else:
                need(not entry, "ARCHIVE_CREATE_ONCE_REQUIRED")
            content.write_bytes(raw)
            _, blob = _cmd(repo, "hash-object", "-w", "--no-filters", "--",
                           str(content), index_path=index)
            _cmd(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}",
                 index_path=index)
        _, tree = _cmd(repo, "write-tree", "--missing-ok", index_path=index)
        _, commit = _cmd(repo, "--no-replace-objects", "-c", "user.name=RACE-AI",
                         "-c", "user.email=race-ai@users.noreply.github.com",
                         "commit-tree", tree, "-p", parent, "-m", message, index_path=index)
        need(COMMIT.fullmatch(commit), "COMMIT_IDENTITY_INVALID")
        status, _ = _cmd(repo, "push", "origin", f"{commit}:refs/heads/{BRANCH}",
                         okay=True, index_path=index)
    return status, commit


def read_blob_bytes(repo, ref, path, *, max_bytes=MAX_BYTES):
    """Read an exact immutable Git blob without stripping or transcoding bytes.

    Text helpers remain appropriate for JSON metadata, but cannot prove a
    ciphertext file's byte SHA. Pin a full commit, check object type/size first,
    and disable replace objects and text conversion for this bounded read.
    max_bytes is an exclusive bound, at most 32 MiB. The default retains the
    existing ciphertext limit; encrypted source-history callers may opt larger.
    """
    need(type(max_bytes) is int and 1 <= max_bytes <= MAX_BLOB_READ_BYTES,
         "ARCHIVE_BLOB_READ_LIMIT_INVALID")
    need(type(ref) is str and COMMIT.fullmatch(ref) and
         type(path) is str and 0 < len(path) <= 2048 and
         not path.startswith("/") and ":" not in path and
         not any(char in path for char in ("\0", "\r", "\n", "\\")) and
         all(part not in ("", ".", "..") for part in path.split("/")),
         "IMMUTABLE_BLOB_COMMIT_AND_PATH_REQUIRED")
    target = f"{ref}:{path}"
    status, kind = _cmd(repo, "--no-replace-objects", "cat-file", "-t",
                        target, okay=True)
    if status != 0:
        _require_absent_path(repo, ref, path)
        return None
    need(kind == "blob", "ARCHIVE_BLOB_OBJECT_REQUIRED")
    _, length = _cmd(repo, "--no-replace-objects", "cat-file", "-s", target)
    need(length.isascii() and length.isdecimal() and len(length) <= 18 and
         0 <= int(length) < max_bytes, "ARCHIVE_BLOB_SIZE_INVALID")
    try:
        done = subprocess.run(
            ["git", "--no-replace-objects", "show", "--no-textconv", target],
            cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=35, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
            check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise GitCipherArchiveError("ARCHIVE_BLOB_READ_UNAVAILABLE") from None
    need(done.returncode == 0 and len(done.stdout) == int(length),
         "ARCHIVE_BLOB_BYTE_LENGTH_MISMATCH")
    return done.stdout


def _read_at(repo, ref, race_id, expected_sha):
    cipher_path, receipt_path = _refs(race_id)
    stored=read_blob_bytes(repo,ref,cipher_path)
    metadata=_show(repo,ref,receipt_path)
    need((stored is None)==(metadata is None),
         "ARCHIVE_ORIGINAL_OR_RECEIPT_MISSING")
    if stored is None:
        return None
    raw=stored
    try:
        receipt=json.loads(metadata[1])
    except (ValueError,TypeError):
        raise GitCipherArchiveError("ARCHIVE_RECEIPT_NOT_JSON") from None
    fields = {
            "schema","race_id","cipher_sha256","original_sealed_at",
            "producer_run_id","producer_commit","previous_archive_commit",
            "branch","cipher_only_not_source_or_cutoff_attestation"
    }
    need(type(receipt) is dict and
         set(receipt) in (fields, fields | {"cohort_sha256"}) and
         receipt["schema"]==SCHEMA and
         receipt["race_id"]==race_id and receipt["branch"]==BRANCH and
         receipt["cipher_sha256"]==expected_sha and
         receipt["cipher_only_not_source_or_cutoff_attestation"] is True,
         "ARCHIVE_RECEIPT_OR_SHA_MISMATCH")
    if "cohort_sha256" in receipt:
        need(type(receipt["cohort_sha256"]) is str and
             SHA.fullmatch(receipt["cohort_sha256"]), "REGISTRY_COHORT_SHA_REQUIRED")
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
                producer_run_id,producer_commit,synthetic_local=False,
                cohort_sha256=None):
    """Strict fast-forward-only append; never create/reset state branch."""
    repo=_remote(repo,synthetic_local=synthetic_local)
    doc=_cipher(raw_cipher,expected_cipher_sha256)
    rid=doc["race_id"]
    cipher_path, receipt_path=_refs(rid)
    # Ensure parent does not get invented: a missing or force-lost branch holds.
    for attempt in range(3):
        head=_refresh(repo)
        prior_cipher=read_blob_bytes(repo,head,cipher_path)
        prior_receipt=_show(repo,head,receipt_path)
        need((prior_cipher is None)==(prior_receipt is None),
             "EXISTING_ARCHIVE_PAIR_INCOMPLETE")
        if prior_cipher is not None:
            if sha256(prior_cipher).hexdigest() != expected_cipher_sha256:
                raise GitCipherArchiveError("FORECAST_ORIGINAL_ALREADY_EXISTS_DIFFERENT_CIPHER")
            prior = _read_at(repo,head,rid,expected_cipher_sha256)
            if cohort_sha256 is not None:
                need(prior.get("cohort_sha256") == cohort_sha256,
                     "EXISTING_ORIGINAL_COHORT_MISMATCH")
            return {"state":"IDENTICAL_ORIGINAL_ALREADY_FROZEN_NO_NEW_WRITE",
                    "race_id":rid,"cipher_sha256":expected_cipher_sha256,
                    "readback_head":head}
        receipt=_receipt(doc,expected_cipher_sha256,producer_run_id,
                         producer_commit,head,cohort_sha256)
        receipt_raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":"))
                       + "\n").encode("utf-8")
        status, newhead = _push_archive_files(
            repo, head, {cipher_path: raw_cipher, receipt_path: receipt_raw},
            f"archive(keirin): sealed A/B {rid} original SHA")
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


def _form_refs(race_id):
    cipher, receipt = _refs(race_id)
    return (cipher.removesuffix(".sealed.json") + ".form.sealed.json",
            receipt.removesuffix(".receipt.json") + ".form.receipt.json")


def _form_cipher(raw, digest, race_id, parent_sha):
    need(type(raw) is bytes and 0 < len(raw) < MAX_BYTES and
         type(digest) is str and SHA.fullmatch(digest) and
         sha256(raw).hexdigest() == digest and
         type(parent_sha) is str and SHA.fullmatch(parent_sha),
         "CONDITIONED_CIPHER_OR_PARENT_SHA_INVALID")
    _form_refs(race_id)
    # Reuse the existing envelope validator; the temporary file is ciphertext
    # only and never contains a key, source page or unencrypted prediction.
    with TemporaryDirectory(prefix="keirin-conditioned-cipher-check-") as folder:
        path = Path(folder) / (race_id + ".form.sealed.json")
        path.write_bytes(raw)
        path.chmod(0o600)
        try:
            condition.readback_shadow(path, expected_sha=digest,
                expected_baseline_sha=parent_sha, expected_race=race_id)
            return json.loads(raw)
        except (ValueError, TypeError, KeyError):
            raise GitCipherArchiveError("CONDITIONED_CIPHER_ENVELOPE_INVALID") from None


def _paired_baseline(repo, head, doc, baseline_sha, cohort_sha,
                     producer_run_id=None, producer_commit=None):
    need(type(cohort_sha) is str and SHA.fullmatch(cohort_sha),
         "REGISTRY_COHORT_SHA_REQUIRED")
    rid = doc["race_id"]
    receipt = _read_at(repo, head, rid, baseline_sha)
    need(receipt is not None and receipt.get("cohort_sha256") == cohort_sha,
         "CONDITIONED_BASELINE_OR_COHORT_NOT_FROZEN")
    if producer_run_id is not None:
        need(receipt["producer_run_id"] == producer_run_id and
             receipt["producer_commit"] == producer_commit,
             "CONDITIONED_PRODUCER_DIFFERS_FROM_BASELINE")
    base = _cipher(read_blob_bytes(repo, head, _refs(rid)[0]), baseline_sha)
    need(base["generated_at"] == doc["generated_at"] and
         base["published_cutoff_at"] == doc["cutoff_at"],
         "CONDITIONED_BASELINE_INPUT_CLOCK_MISMATCH")
    return receipt


def _read_conditioned_at(repo, head, race_id, expected_sha, baseline_sha,
                         parent_sha, cohort_sha):
    cipher_path, receipt_path = _form_refs(race_id)
    raw = read_blob_bytes(repo, head, cipher_path)
    metadata = _show(repo, head, receipt_path)
    need((raw is None) == (metadata is None),
         "CONDITIONED_ARCHIVE_PAIR_INCOMPLETE")
    if raw is None:
        return None
    doc = _form_cipher(raw, expected_sha, race_id, parent_sha)
    try:
        receipt = json.loads(metadata[1])
    except (ValueError, TypeError):
        raise GitCipherArchiveError("CONDITIONED_RECEIPT_NOT_JSON") from None
    need(type(receipt) is dict and set(receipt) == {
        "schema", "race_id", "cipher_sha256", "original_sealed_at",
        "producer_run_id", "producer_commit", "previous_archive_commit",
        "branch", "cipher_only_not_source_or_cutoff_attestation",
        "cohort_sha256", "baseline_cipher_sha256", "baseline_prediction_sha256"} and
        receipt["schema"] == FORM_SCHEMA and receipt["race_id"] == race_id and
        receipt["branch"] == BRANCH and receipt["cipher_sha256"] == expected_sha and
        receipt["baseline_cipher_sha256"] == baseline_sha and
        receipt["baseline_prediction_sha256"] == parent_sha and
        receipt["cohort_sha256"] == cohort_sha and
        receipt["original_sealed_at"] == doc["sealed_at"] and
        receipt["cipher_only_not_source_or_cutoff_attestation"] is True,
        "CONDITIONED_RECEIPT_OR_SHA_MISMATCH")
    _paired_baseline(repo, head, doc, baseline_sha, cohort_sha,
                     receipt["producer_run_id"], receipt["producer_commit"])
    previous = receipt["previous_archive_commit"]
    need(type(previous) is str and COMMIT.fullmatch(previous) and
         _cmd(repo, "merge-base", "--is-ancestor", previous, head, okay=True)[0] == 0,
         "CONDITIONED_ARCHIVE_PARENT_NOT_ANCESTOR")
    return receipt


def read_conditioned_original(*, repo, race_id, expected_cipher_sha256,
                              expected_baseline_cipher_sha256,
                              expected_baseline_prediction_sha256,
                              cohort_sha256, synthetic_local=False):
    """Verify a paired original from Git; plaintext parent linkage stays unproven."""
    repo = _remote(repo, synthetic_local=synthetic_local)
    head = _refresh(repo)
    receipt = _read_conditioned_at(repo, head, race_id, expected_cipher_sha256,
        expected_baseline_cipher_sha256, expected_baseline_prediction_sha256,
        cohort_sha256)
    need(receipt is not None, "CONDITIONED_ARCHIVED_RACE_NOT_FOUND")
    return {
        "state":"ENCRYPTED_GIT_CONDITIONED_SHA_READBACK_OK", "race_id":race_id,
        "cipher_sha256":expected_cipher_sha256, "observed_branch_head":head,
        "baseline_cipher_sha256":expected_baseline_cipher_sha256,
        "baseline_prediction_sha256":expected_baseline_prediction_sha256,
        "cohort_sha256":cohort_sha256,
        "producer_run_id":receipt["producer_run_id"],
        "RSA_decryption_verified":False, "official_cutoff_verified":False,
        "plaintext_parent_linkage_verified":False}


def append_conditioned_once(*, repo, raw_cipher, expected_cipher_sha256,
                            expected_baseline_cipher_sha256,
                            expected_baseline_prediction_sha256, cohort_sha256,
                            producer_run_id, producer_commit, synthetic_local=False):
    """Append the same-run conditioned ciphertext without changing its baseline."""
    repo = _remote(repo, synthetic_local=synthetic_local)
    try:
        rid = json.loads(raw_cipher)["race_id"]
    except (ValueError, TypeError, KeyError):
        raise GitCipherArchiveError("CONDITIONED_CIPHER_JSON_INVALID") from None
    doc = _form_cipher(raw_cipher, expected_cipher_sha256, rid,
                       expected_baseline_prediction_sha256)
    cipher_path, receipt_path = _form_refs(rid)
    for attempt in range(3):
        head = _refresh(repo)
        _paired_baseline(repo, head, doc, expected_baseline_cipher_sha256,
                         cohort_sha256, producer_run_id, producer_commit)
        prior = read_blob_bytes(repo, head, cipher_path)
        prior_receipt = _show(repo, head, receipt_path)
        need((prior is None) == (prior_receipt is None),
             "CONDITIONED_ARCHIVE_PAIR_INCOMPLETE")
        if prior is not None:
            need(sha256(prior).hexdigest() == expected_cipher_sha256,
                 "CONDITIONED_ORIGINAL_ALREADY_EXISTS_DIFFERENT_CIPHER")
            _read_conditioned_at(repo, head, rid, expected_cipher_sha256,
                expected_baseline_cipher_sha256, expected_baseline_prediction_sha256,
                cohort_sha256)
            return {"state":"IDENTICAL_CONDITIONED_ORIGINAL_ALREADY_FROZEN",
                    "race_id":rid, "cipher_sha256":expected_cipher_sha256,
                    "readback_head":head}
        receipt = _receipt(doc, expected_cipher_sha256, producer_run_id,
                           producer_commit, head, cohort_sha256)
        receipt.update(schema=FORM_SCHEMA,
                       baseline_cipher_sha256=expected_baseline_cipher_sha256,
                       baseline_prediction_sha256=expected_baseline_prediction_sha256)
        receipt_raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":"))
                       + "\n").encode("utf-8")
        status, newhead = _push_archive_files(
            repo, head, {cipher_path: raw_cipher, receipt_path: receipt_raw},
            f"archive(keirin): conditioned A/B {rid} original SHA")
        if status == 0:
            restored = read_conditioned_original(repo=repo, race_id=rid,
                expected_cipher_sha256=expected_cipher_sha256,
                expected_baseline_cipher_sha256=expected_baseline_cipher_sha256,
                expected_baseline_prediction_sha256=expected_baseline_prediction_sha256,
                cohort_sha256=cohort_sha256, synthetic_local=synthetic_local)
            need(_cmd(repo, "merge-base", "--is-ancestor", newhead,
                      restored["observed_branch_head"], okay=True)[0] == 0,
                 "CONDITIONED_NEW_COMMIT_NOT_ANCESTOR_OF_READBACK")
            return {"state":"GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED",
                    "race_id":rid, "cipher_sha256":expected_cipher_sha256,
                    "write_commit":newhead,
                    "readback_head":restored["observed_branch_head"]}
    raise GitCipherArchiveError("CONDITIONED_GIT_FAST_FORWARD_RETRY_EXHAUSTED")
