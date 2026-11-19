"""Create-once Git-only provider stops, across ephemeral runners and days.

Public branch contains *only* day, a generic provider failure code and time.
No source HTML, racecard, wager, secret, provider response or person data.
An unresolved 403/429 never expires at midnight. Other transport failures
retain their observation-day scope. No marker is overwritten or cleared.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import re

from . import keirin_nationwide_cipher_history as archive

ROOT = "state/keirin/ab/provider-stop/v1"
DENIED_ROOT = ROOT + "/denied"
DENIED = "PROVIDER_DENIED_OR_RATE_LIMITED_STOP"
SCHEMA = "RACE_AI_KEIRIN_GITHUB_PROVIDER_DAY_STOP_V1"
JST = timezone(timedelta(hours=9))
CODES = frozenset({
    "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
    "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
    "PUBLIC_PROVIDER_UNAVAILABLE_STOP",
})


class ProviderStopError(ValueError):
    pass


class ProviderStopPersistenceError(RuntimeError):
    """Fatal: parser handlers for ValueError/OSError must not resume GETs."""


def must(ok, reason):
    if not ok:
        raise ProviderStopError(reason)


def _path(day):
    must(type(day) is str, "STOP_DAY_INVALID")
    try:
        must(date.fromisoformat(day).isoformat() == day,
             "STOP_DAY_INVALID")
    except ValueError:
        raise ProviderStopError("STOP_DAY_INVALID") from None
    return f"{ROOT}/{day}.json"


def _denied_path(day):
    _path(day)
    return f"{DENIED_ROOT}/{day}.json"


def _check(value, day):
    must(type(value) is dict and
         set(value) == {"schema", "day_jst", "code", "observed_at"} and
         value["schema"] == SCHEMA and value["day_jst"] == day and
         type(value["code"]) is str and value["code"] in CODES and
         type(value["observed_at"]) is str,
         "STOP_MARKER_UNTRUSTED")
    _observed_day(value["observed_at"])
    return value


def _observed_day(observed_at):
    must(type(observed_at) is str, "STOP_MARKER_CLOCK_INVALID")
    try:
        at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        must(at.utcoffset() is not None, "STOP_MARKER_CLOCK_UNVERIFIED")
    except ValueError:
        raise ProviderStopError("STOP_MARKER_CLOCK_INVALID") from None
    return at.astimezone(JST).date().isoformat()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        must(key not in value, "STOP_MARKER_DUPLICATE_JSON_FIELD")
        value[key] = item
    return value


def _decode_marker(raw, day):
    try:
        doc = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, RecursionError):
        raise ProviderStopError("STOP_MARKER_JSON_INVALID") from None
    return _check(doc, day)


def read(*, repo, day, head=None):
    repo = archive._remote(repo, synthetic_local=False)
    ref = head or archive._refresh(repo)
    record = archive._show(repo, ref, _path(day))
    if record is None:
        return None
    return _decode_marker(record[1], day)


def _read_immutable_marker(repo, ref, path, day):
    raw = archive.read_blob_bytes(repo, ref, path, max_bytes=8192)
    if raw is None:
        return None
    return _decode_marker(raw, day)


def _marker_entries(repo, ref):
    """Validate the entire marker subtree; unknown entries cannot hide a stop."""
    components = ROOT.split("/")
    parents = {"/".join(components[:n]) for n in range(1, len(components) + 1)}
    for count in range(1, len(components)):
        parent = "/".join(components[:count])
        _, entry = archive._cmd(repo, "--no-replace-objects", "ls-tree", "-z",
                                "--full-tree", ref, "--", parent)
        if not entry:
            return []  # An absent ancestor is a legitimate empty history.
        # Git silently returns an empty subtree if an ancestor is a blob or
        # symlink. That must not be interpreted as "no denial recorded".
        must(re.fullmatch(r"040000 tree [0-9a-f]{40}\t" + re.escape(parent) + r"\x00", entry),
             "STOP_MARKER_ANCESTOR_NOT_TREE")
    _, tree = archive._cmd(repo, "--no-replace-objects", "ls-tree", "-r", "-t", "-z",
                           "--full-tree", ref, "--", ROOT)
    if not tree:
        return []
    must(tree.endswith("\0"), "STOP_MARKER_TREE_INVALID")
    parents.add(DENIED_ROOT)
    entries, seen = [], set()
    for item in tree[:-1].split("\0"):
        fields = item.split("\t", 1)
        must(len(fields) == 2, "STOP_MARKER_TREE_ENTRY_INVALID")
        metadata, path = fields
        parts = metadata.split(" ")
        must(len(parts) == 3 and re.fullmatch(r"[0-9a-f]{40}", parts[2]) and
             path not in seen, "STOP_MARKER_TREE_ENTRY_INVALID")
        seen.add(path)
        mode, kind, _ = parts
        if path in parents:
            must(mode == "040000" and kind == "tree", "STOP_MARKER_TREE_ENTRY_INVALID")
            continue
        match = re.fullmatch(re.escape(ROOT) + r"/(denied/)?(\d{4}-\d{2}-\d{2})\.json", path)
        must(mode == "100644" and kind == "blob" and match is not None,
             "STOP_MARKER_TREE_ENTRY_INVALID")
        stored_day = match[2]
        _path(stored_day)
        entries.append((path, stored_day, bool(match[1])))
    return entries


def read_for_observed_day(*, repo, day, head=None):
    """Retain every unresolved denial; expire only daily transport failures.

    The earlier result job wrote yesterday's result denial under yesterday
    even when it happened today. Read old keys without changing their bytes.
    All persisted markers are validated before choosing a stop. A 403/429
    takes priority over a current-day transient failure; there is no implicit
    release date or release API. Future observation dates fail closed.
    """
    _path(day)
    repo = archive._remote(repo, synthetic_local=False)
    ref = head or archive._refresh(repo)
    previous = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    records = {}
    for stored_day in (day, previous):
        record = read(repo=repo, day=stored_day, head=ref)
        if record is not None:
            records[_path(stored_day)] = record
    for path, stored_day, denied_only in _marker_entries(repo, ref):
        record = _read_immutable_marker(repo, ref, path, stored_day)
        must(record is not None, "STOP_MARKER_LISTED_BUT_UNREADABLE")
        must(not denied_only or record["code"] == DENIED,
             "STOP_DENIAL_MARKER_CODE_INVALID")
        records[path] = record
    active = None
    denied = None
    for record in records.values():
        observed_day = _observed_day(record["observed_at"])
        must(record["day_jst"] <= day and observed_day <= day,
             "STOP_MARKER_FUTURE_DATE_UNTRUSTED")
        if record["code"] == DENIED:
            denied = denied or record
        elif observed_day == day:
            active = active or record
    return denied or active


def record_denial(*, repo, code, observed_at):
    """Record the real JST observation day; failure must terminate intake."""
    try:
        return append_once(repo=repo, day=_observed_day(observed_at),
                           code=code, observed_at=observed_at)
    except (ValueError, TypeError, KeyError, OSError):
        raise ProviderStopPersistenceError(
            "PROVIDER_STOP_PERSISTENCE_FAILED_NO_RETRY") from None


def append_once(*, repo, day, code, observed_at):
    doc = _check({"schema":SCHEMA, "day_jst":day,"code":code,
                  "observed_at":observed_at},day)
    must(_observed_day(observed_at) == day,
         "STOP_MARKER_OBSERVED_DAY_MISMATCH")
    repo = archive._remote(repo, synthetic_local=False)
    payload = json.dumps(
        doc, sort_keys=True, ensure_ascii=False,
        separators=(",",":")) + "\n"
    for _ in range(3):
        head = archive._refresh(repo)
        path = _path(day)
        existing = read(repo=repo, day=day, head=head)
        if existing is not None:
            if code != DENIED or existing["code"] == DENIED:
                return "PROVIDER_DAY_ALREADY_STOPPED"
            # A concurrent/earlier transient failure must not swallow a later
            # 403/429. Preserve the original daily marker and append a separate
            # create-once denial with the same four-field public schema.
            path = _denied_path(day)
            prior_denial = _read_immutable_marker(repo, head, path, day)
            if prior_denial is not None:
                must(prior_denial["code"] == DENIED, "STOP_DENIAL_MARKER_CODE_INVALID")
                return "PROVIDER_DAY_ALREADY_STOPPED"
        with TemporaryDirectory(prefix="keirin-provider-stop-") as d:
            tree = Path(d)/"branch"
            archive._cmd(repo, "worktree", "add", "--detach", str(tree), head)
            try:
                target=tree/path
                target.parent.mkdir(parents=True,exist_ok=True)
                must(not target.exists(), "PROVIDER_STOP_CREATE_ONCE_REQUIRED")
                target.write_text(payload,encoding="utf-8")
                archive._cmd(tree,"add","--",path)
                archive._cmd(
                    tree,"-c","user.name=RACE-AI",
                    "-c","user.email=race-ai@users.noreply.github.com",
                    "commit","-m","safety(keirin): stop denied day source GET")
                status,_=archive._cmd(
                    tree,"push","origin",f"HEAD:refs/heads/{archive.BRANCH}",
                    okay=True)
            finally:
                archive._cmd(repo,"worktree","remove","--force",str(tree),
                             okay=True)
        if status==0:
            checked_head = archive._refresh(repo)
            must(_read_immutable_marker(repo, checked_head, path, day) == doc,
                 "PROVIDER_STOP_POST_WRITE_READBACK_NOT_MATCHED")
            return "PROVIDER_DAY_STOP_RECORDED"
    raise ProviderStopError("PROVIDER_STOP_CONCURRENT_GIT_RETRY_EXHAUSTED")
