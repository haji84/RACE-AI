"""Small public scheduling counters in the existing encrypted-history branch.

Only this day's metadata file is replaced by an ordinary fast-forward commit.
Forecast originals and official evidence revisions remain unchanged. This is
scheduling state, not source evidence, an immutable receipt or a timestamp proof.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from . import keirin_nationwide_cipher_history as archive


ROOT = "state/keirin/ab/poll-progress/v1"
SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_POLL_PROGRESS_V1"
MAX_BYTES = 4096
MAX_CURSOR = (1 << 53) - 1
FIELDS = frozenset({"schema", "day_jst", "result_poll_cursor", "origin_poll_cursor",
                    "last_operation_id", "observed_at"})


class OfficialPollProgressError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise OfficialPollProgressError(code)


def _path(day):
    _need(type(day) is str and re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", day),
          "POLL_PROGRESS_DAY_INVALID")
    try:
        _need(date.fromisoformat(day).isoformat() == day, "POLL_PROGRESS_DAY_INVALID")
    except ValueError:
        raise OfficialPollProgressError("POLL_PROGRESS_DAY_INVALID") from None
    return f"{ROOT}/{day}.json"


def _time(value):
    _need(type(value) is str and 0 < len(value) <= 64 and "T" in value,
          "POLL_PROGRESS_OBSERVATION_CLOCK_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        _need(parsed.utcoffset() is not None, "POLL_PROGRESS_OBSERVATION_CLOCK_INVALID")
    except ValueError:
        raise OfficialPollProgressError("POLL_PROGRESS_OBSERVATION_CLOCK_INVALID") from None


def _check(document, day):
    _need(type(document) is dict and set(document) == FIELDS and
          document["schema"] == SCHEMA and document["day_jst"] == day,
          "POLL_PROGRESS_SCHEMA_OR_DAY_INVALID")
    for field in ("result_poll_cursor", "origin_poll_cursor"):
        _need(type(document[field]) is int and 0 <= document[field] <= MAX_CURSOR,
              "POLL_PROGRESS_CURSOR_INVALID_OR_EXHAUSTED")
    _need(type(document["last_operation_id"]) is str and
          archive.SHA.fullmatch(document["last_operation_id"]),
          "POLL_PROGRESS_OPERATION_ID_INVALID")
    _time(document["observed_at"])
    return document


def _canonical(document):
    return (json.dumps(document, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        _need(key not in result, "POLL_PROGRESS_DUPLICATE_JSON_FIELD")
        result[key] = value
    return result


def _read_at(repo, head, day):
    path = _path(day)
    raw = archive.read_blob_bytes(repo, head, path, max_bytes=MAX_BYTES)
    if raw is None:
        return None
    mode = archive._cmd(repo, "--no-replace-objects", "ls-tree",
                        "--format=%(objectmode)", head, "--", path)[1]
    _need(mode == "100644", "POLL_PROGRESS_REGULAR_METADATA_FILE_REQUIRED")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        _check(document, day)
        _need(_canonical(document) == raw, "POLL_PROGRESS_CANONICAL_BYTES_REQUIRED")
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise OfficialPollProgressError("POLL_PROGRESS_JSON_INVALID") from None
    return document


def read_day(*, repo, day, synthetic_local=False):
    """Return intact canonical day metadata, or None on an existing empty day."""
    _path(day)
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    return _read_at(repo, archive._refresh(repo), day)


def _parent(tree, path):
    parent = tree
    for component in Path(path).parts[:-1]:
        parent /= component
        _need(not parent.is_symlink(), "POLL_PROGRESS_SYMLINK_PATH_PROHIBITED")
        parent.mkdir(exist_ok=True)


def advance_day(*, repo, day, result_delta, origin_delta, operation_id,
                observed_at, synthetic_local=False):
    """Add 0/1 deltas after each fresh read; retry only normal Git conflicts.

    Repeating the current last_operation_id is a no-op. This bounded record
    intentionally promises no deduplication of arbitrary older operation IDs.
    A successful return may include another writer's later increments.
    """
    path = _path(day)
    _need(type(result_delta) is int and result_delta in (0, 1) and
          type(origin_delta) is int and origin_delta in (0, 1),
          "POLL_PROGRESS_DELTA_MUST_BE_ZERO_OR_ONE")
    proposed = _check({"schema": SCHEMA, "day_jst": day,
        "result_poll_cursor": result_delta, "origin_poll_cursor": origin_delta,
        "last_operation_id": operation_id, "observed_at": observed_at}, day)
    repo = archive._remote(repo, synthetic_local=synthetic_local)
    for _ in range(3):
        head = archive._refresh(repo)
        prior = _read_at(repo, head, day)
        if prior is not None and prior["last_operation_id"] == operation_id:
            return prior
        updated = dict(proposed)
        if prior is not None:
            for field in ("result_poll_cursor", "origin_poll_cursor"):
                updated[field] += prior[field]
        _check(updated, day)
        raw = _canonical(updated)
        with TemporaryDirectory(prefix="keirin-poll-progress-") as directory:
            tree = Path(directory) / "tree"
            archive._cmd(repo, "worktree", "add", "--detach", str(tree), head)
            try:
                _parent(tree, path)
                target = tree / path
                _need(not target.is_symlink() and
                      (not target.exists() or target.is_file()),
                      "POLL_PROGRESS_REGULAR_METADATA_FILE_REQUIRED")
                target.write_bytes(raw)
                target.chmod(0o644)
                archive._cmd(tree, "add", "--", path)
                changed = archive._cmd(tree, "diff", "--cached", "--name-only")[1]
                _need(changed == path, "POLL_PROGRESS_ONLY_DAY_METADATA_MAY_CHANGE")
                archive._cmd(tree, "-c", "user.name=RACE-AI", "-c",
                    "user.email=race-ai@users.noreply.github.com", "commit", "-m",
                    f"state(keirin): advance official polling {day}")
                written = archive._cmd(tree, "rev-parse", "HEAD")[1]
                status, _ = archive._cmd(tree, "push", "origin",
                    f"HEAD:refs/heads/{archive.BRANCH}", okay=True)
            finally:
                archive._cmd(repo, "worktree", "remove", "--force", str(tree), okay=True)
        if status == 0:
            observed_head = archive._refresh(repo)
            ancestor, _ = archive._cmd(repo, "merge-base", "--is-ancestor",
                                       written, observed_head, okay=True)
            current = _read_at(repo, observed_head, day)
            _need(ancestor == 0 and _read_at(repo, written, day) == updated and
                  current is not None and all(current[field] >= updated[field]
                  for field in ("result_poll_cursor", "origin_poll_cursor")),
                  "POLL_PROGRESS_POST_WRITE_READBACK_MISMATCH")
            return current
    raise OfficialPollProgressError("POLL_PROGRESS_CONCURRENT_GIT_RETRY_EXHAUSTED")
