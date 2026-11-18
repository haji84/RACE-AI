"""Post-race GitHub-only collector for secondary evidence, not official settlement.

Fetch after the pre-race sealed cutoff, corroborate Kdreams/netkeirin,
append revisions to the SAME already-existing Git encrypted history branch.
Never decrypt a forecast, declare official accuracy or retrofit predictions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json
import os
import re

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_github_provider_stop as provider_stop
from race_ai import keirin_nationwide_auto_storage as seal
from race_ai import keirin_nationwide_auto_generator as model
from scripts import keirin_github_only_ab_day as live
from scripts import keirin_register_public_day as registration
from scripts import keirin_secondary_result_poll as result_poll
from scripts import keirin_capture_public_two_sources as capture

JST = timezone(timedelta(hours=9))
SCHEMA = "RACE_AI_KEIRIN_GITHUB_ONLY_SECONDARY_RESULT_DAY_V1"
ROOT = "state/keirin/ab/secondary-results/v1"
MAX_RACES = 8


def _published_cutoff(repo, head, race_id, cipher_sha):
    cipher_path, _ = archive._refs(race_id)
    checked = archive._read_at(repo, head, race_id, cipher_sha)
    live.require(checked is not None, "RESULT_NO_FROZEN_CIPHER")
    original = archive._show(repo, head, cipher_path)
    live.require(original is not None, "RESULT_ORIGINAL_MISSING")
    try:
        envelope = json.loads(original[1])
        seal.validate_cipher(envelope)
        live.require(envelope["race_id"] == race_id,
                     "CIPHER_OTHER_RACE")
        return model.when(envelope["published_cutoff_at"])
    except (ValueError,KeyError,TypeError):
        raise live.GitHubOnlyDayError("RESULT_CIPHER_CUTOFF_UNVERIFIED") from None


def _prior_research(repo, head, race_id):
    prefix = f"{ROOT}/{race_id[:4]}-{race_id[4:6]}-{race_id[6:8]}/{race_id}/"
    _, files = archive._cmd(repo, "ls-tree", "-r", "--name-only",
                             head, "--", prefix)
    reports = []
    for p in files.splitlines():
        live.require(p.startswith(prefix) and
                     re.fullmatch(r"[0-9a-f]{64}\.json",p[len(prefix):]),
                     "UNKNOWN_SECONDARY_ARCHIVE_ENTRY")
        raw = archive._show(repo,head,p)
        live.require(raw is not None, "SECONDARY_ARCHIVE_MISSING")
        try:
            doc = json.loads(raw[1])
        except ValueError:
            raise live.GitHubOnlyDayError("SECONDARY_ARCHIVE_NOT_JSON") from None
        live.require(doc.get("race_id") == race_id and
                     doc.get("state") ==
                     "SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL" and
                     doc.get("qualifies_for_formal_settlement") is False,
                     "SECONDARY_ARCHIVE_AUTHORITY_MISMATCH")
        reports.append(doc)
    return reports


def _archive_result(repo, observed):
    """Create-only research revision with guarded fast-forward and recheck."""
    live.require(observed["state"] ==
                 "SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL" and
                 observed["qualifies_for_formal_settlement"] is False,
                 "UNVERIFIED_RESULT_CANNOT_BE_ARCHIVED_AS_MATCHED")
    repo = archive._remote(repo, synthetic_local=False)
    rid = observed["race_id"]
    payload = model.canonical(observed) + b"\n"
    digest = sha256(payload).hexdigest()
    path = f"{ROOT}/{rid[:4]}-{rid[4:6]}-{rid[6:8]}/{rid}/{digest}.json"
    for _ in range(3):
        head = archive._refresh(repo)
        previous = _prior_research(repo,head,rid)
        if any(item.get("winning_triple") == observed["winning_triple"] and
               item.get("payout_per_100yen") == observed["payout_per_100yen"]
               for item in previous):
            return "RESEARCH_MATCH_ALREADY_RECORDED"
        with TemporaryDirectory(prefix="keirin-result-safe-") as directory:
            tree = Path(directory)/"branch"
            archive._cmd(repo,"worktree","add","--detach",str(tree),head)
            try:
                dest = tree/path
                dest.parent.mkdir(parents=True,exist_ok=True)
                live.require(not dest.exists(),
                             "RESULT_REVISION_MUST_BE_CREATE_ONCE")
                dest.write_bytes(payload)
                archive._cmd(tree,"add","--",path)
                archive._cmd(tree,"-c","user.name=RACE-AI",
                             "-c","user.email=race-ai@users.noreply.github.com",
                             "commit","-m","research(keirin): append observed two-site result "+rid)
                status,_ = archive._cmd(tree,"push","origin",
                                        f"HEAD:refs/heads/{archive.BRANCH}",
                                        okay=True)
            finally:
                archive._cmd(repo,"worktree","remove","--force",str(tree),
                             okay=True)
        if status == 0:
            rechecked = archive._refresh(repo)
            raw = archive._show(repo,rechecked,path)
            live.require(raw is not None and
                         sha256((raw[1]+"\n").encode("utf-8")).hexdigest()
                         == digest, "SECONDARY_RESULT_GIT_READBACK_MISMATCH")
            return "RESEARCH_REVISION_GIT_CREATE_ONCE_READBACK"
    raise live.GitHubOnlyDayError("RESULT_GIT_FAST_FORWARD_CONFLICT")


def run_day(*, day, repo, private_raw_dir, max_races=MAX_RACES, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock()
    today = now.astimezone(JST).date()
    live.require(day in (today.isoformat(),
                 (today-timedelta(days=1)).isoformat()),
                 "RESULT_ONLY_CURRENT_OR_PREVIOUS_JST_DAY")
    live.require(type(max_races) is int and 1 <= max_races <= MAX_RACES,
                 "RESULT_POLL_BUDGET_INVALID")
    raw = capture.private_dir(private_raw_dir)
    repo = archive._remote(repo, synthetic_local=False)
    frozen = live.archived_day(repo,day)
    if not frozen:
        return {"schema":SCHEMA,"day_jst":day,"previous_forecasts":0,
                "result_candidates":0,"research_matches_persisted":0,
                "officially_scored":0,"states":{"NO_FROZEN_FORECAST":1}}
    def guarded_fetch(url):
        try:
            return capture.fetch_once(url)
        except capture.SourceCaptureError as exc:
            if str(exc) in provider_stop.CODES:
                provider_stop.append_once(
                    repo=repo, day=day, code=str(exc),
                    observed_at=clock().astimezone(timezone.utc).isoformat())
            raise

    registry, manifest, source_status = registration.register_day(
        day_jst=day,private_raw_dir=raw,clock=clock,
        fetch=guarded_fetch)
    linked = {r["race_id"] for r in manifest["races"]}
    head = archive._refresh(repo)
    eligible = []
    for rid,cipher_sha in sorted(frozen.items()):
        if rid not in linked:
            continue
        cutoff = _published_cutoff(repo,head,rid,cipher_sha)
        if now < cutoff + timedelta(minutes=10):
            continue
        previous = _prior_research(repo,head,rid)
        # Previously corroborated research can still be rechecked in a
        # separately scheduled audit for revisions, not every 10 minutes.
        if previous:
            continue
        eligible.append(rid)
    states={}
    new_matches=0
    attempted=0
    for rid in eligible[:max_races]:
        attempted+=1
        try:
            observed=result_poll.poll(manifest=manifest,race_id=rid,
                                      clock=clock,fetch=guarded_fetch)
            if observed["state"] == "SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL":
                state = _archive_result(repo,observed)
                new_matches += (state == "RESEARCH_REVISION_GIT_CREATE_ONCE_READBACK")
                states[rid]=state
            else:
                states[rid]="HOLD_TWO_SOURCES_DISAGREE"
        except (ValueError,TypeError,KeyError,OSError,
                capture.SourceCaptureError) as exc:
            reason=str(exc)
            if (not re.fullmatch(r"[A-Z0-9_]{1,100}",reason)):
                reason="UNVERIFIED_SOURCE_OR_RESULT"
            states[rid]="HOLD_"+reason
            if reason in ("PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                          "PUBLIC_PROVIDER_HTTP_ERROR_STOP",
                          "PUBLIC_PROVIDER_UNAVAILABLE_STOP"):
                break
    return {"schema":SCHEMA,"day_jst":day,
            "registered_linked_races":len(registry["races"]),
            "previous_forecasts":len(frozen),
            "eligible_post_cutoff_without_result":len(eligible),
            "result_candidates":attempted,
            "research_matches_persisted":new_matches,
            "officially_scored":0,
            "official_primary_result_authenticated":False,
            "pre_cutoff_originals_never_modified":True,
            "states":states}


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--day",required=True)
    p.add_argument("--repo",required=True)
    p.add_argument("--private-raw",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args(argv)
    try:
        data=run_day(day=a.day,repo=Path(a.repo),
                     private_raw_dir=Path(a.private_raw))
        out=Path(a.out)
        live.require(out.is_absolute() and not out.exists() and
                     os.environ.get("RUNNER_TEMP") and
                     Path(os.environ["RUNNER_TEMP"]).resolve() in out.resolve().parents,
                     "RESULT_SAFE_OUTPUT_TEMP_REQUIRED")
        capture._write_once(out,model.canonical(data)+b"\n")
        print(json.dumps({k:data[k] for k in (
            "day_jst","previous_forecasts","result_candidates",
            "research_matches_persisted","officially_scored")},
            sort_keys=True))
        return 0
    except (ValueError,KeyError,TypeError,OSError,
            archive.GitCipherArchiveError,
            provider_stop.ProviderStopError,
            capture.SourceCaptureError,
            registration.DayPublicRegistrationError):
        print('{"state":"HOLD_GITHUB_ONLY_RESULT_INTAKE_UNVERIFIED",'
              '"officially_scored":0}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
