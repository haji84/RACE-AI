"""Create-once Git-only daily provider-denial stop, across ephemeral runners.

Public branch contains *only* day, a generic provider failure code and time.
No source HTML, racecard, wager, secret, provider response or person data.
Never clear a marker or retry a denied provider the same JST day.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from . import keirin_nationwide_cipher_history as archive

ROOT = "state/keirin/ab/provider-stop/v1"
SCHEMA = "RACE_AI_KEIRIN_GITHUB_PROVIDER_DAY_STOP_V1"
CODES = frozenset({
    "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
    "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
    "PUBLIC_PROVIDER_UNAVAILABLE_STOP",
})


class ProviderStopError(ValueError):
    pass


def must(ok, reason):
    if not ok:
        raise ProviderStopError(reason)


def _path(day):
    must(type(day) is str and date.fromisoformat(day).isoformat() == day,
         "STOP_DAY_INVALID")
    return f"{ROOT}/{day}.json"


def _check(value, day):
    must(type(value) is dict and
         set(value) == {"schema", "day_jst", "code", "observed_at"} and
         value["schema"] == SCHEMA and value["day_jst"] == day and
         value["code"] in CODES and type(value["observed_at"]) is str,
         "STOP_MARKER_UNTRUSTED")
    try:
        at = datetime.fromisoformat(
            value["observed_at"].replace("Z", "+00:00"))
        must(at.utcoffset() is not None, "STOP_MARKER_CLOCK_UNVERIFIED")
    except ValueError:
        raise ProviderStopError("STOP_MARKER_CLOCK_INVALID") from None
    return value


def read(*, repo, day, head=None):
    repo = archive._remote(repo, synthetic_local=False)
    ref = head or archive._refresh(repo)
    record = archive._show(repo, ref, _path(day))
    if record is None:
        return None
    try:
        doc = json.loads(record[1])
    except ValueError:
        raise ProviderStopError("STOP_MARKER_JSON_INVALID") from None
    return _check(doc, day)


def append_once(*, repo, day, code, observed_at):
    repo = archive._remote(repo, synthetic_local=False)
    doc = _check({"schema":SCHEMA, "day_jst":day,"code":code,
                  "observed_at":observed_at},day)
    path = _path(day)
    payload = json.dumps(
        doc, sort_keys=True, ensure_ascii=False,
        separators=(",",":")) + "\n"
    for _ in range(3):
        head = archive._refresh(repo)
        if read(repo=repo,day=day,head=head) is not None:
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
            must(read(repo=repo,day=day) == doc,
                 "PROVIDER_STOP_POST_WRITE_READBACK_NOT_MATCHED")
            return "PROVIDER_DAY_STOP_RECORDED"
    raise ProviderStopError("PROVIDER_STOP_CONCURRENT_GIT_RETRY_EXHAUSTED")
