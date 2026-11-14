"""External GitHub server-time anchor for pre-cutoff forecast hashes.

No forecasts are generated, pushed or changed. GitHub Actions run.created_at
and a file pinned to that run's head_sha establish a witnessed hash before
cutoff. This is NOT RFC3161 notarization or a source permission grant.
"""
import base64
import binascii
from datetime import datetime
import json
import os
import re
from urllib.parse import quote
from urllib.request import Request, build_opener
from .permissioned_source_delivery import NoRedirect

REPO = "haji84/RACE-AI"
BASE = "https://api.github.com/repos/" + REPO
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SAFE_PATH = re.compile(r"audit/freezes/\d{4}-\d{2}-\d{2}/[a-zA-Z0-9_.-]+\.json\Z")
ANCHOR_SCHEMA = "RACE_AI_GITHUB_FREEZE_ANCHOR_V1"


class ReceiptVerificationError(ValueError):
    """Fail closed: external pre-cutoff hash presence unverified."""


def _date(value):
    if not isinstance(value, str):
        raise ReceiptVerificationError("complete external timestamp required")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptVerificationError("invalid external timestamp") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ReceiptVerificationError("external timestamp must include timezone")
    return d


def _github_json(url):
    if not url.startswith(BASE + "/"):
        raise ReceiptVerificationError("untrusted GitHub API endpoint")
    headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "RACE-AI-freeze-audit/1",
    }
    token=os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:headers['Authorization']='Bearer '+token
    req = Request(url,headers=headers)
    with build_opener(NoRedirect()).open(req, timeout=8) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ReceiptVerificationError("GitHub response too large")
    return json.loads(data)


def _read_freeze_document(receipt,persisted_at,cutoff_at,*,_fetch=None):
    if not isinstance(receipt, dict) or set(receipt) != {"run_id", "path"}:
        raise ReceiptVerificationError("receipt requires run_id and path")
    run_id, path = receipt["run_id"], receipt["path"]
    if type(run_id) is not int or run_id < 1 or run_id > 10**15:
        raise ReceiptVerificationError("run_id invalid")
    if not isinstance(path, str) or not SAFE_PATH.fullmatch(path):
        raise ReceiptVerificationError("anchor must be in audit/freezes")
    deadline, claimed = _date(cutoff_at), _date(persisted_at)
    if not claimed < deadline:
        raise ReceiptVerificationError("local persisted_at is not before cutoff")

    get = _github_json if _fetch is None else _fetch
    run = get(f"{BASE}/actions/runs/{run_id}")
    if not isinstance(run, dict):
        raise ReceiptVerificationError("GitHub run unavailable")
    commit_sha = run.get("head_sha")
    server_time = _date(run.get("created_at"))
    if (run.get("id") != run_id or run.get("event") not in {"push", "pull_request"}
        or not isinstance(run.get("repository"), dict)
        or run["repository"].get("full_name") != REPO
        or (run.get("event") == "pull_request" and
            (not isinstance(run.get("head_repository"), dict) or
             run["head_repository"].get("full_name") != REPO))
        or not isinstance(commit_sha, str) or not HEX40.fullmatch(commit_sha)
        or not server_time < deadline):
        raise ReceiptVerificationError("GitHub run not independently before cutoff")

    blob = get(f"{BASE}/contents/{quote(path, safe='/')}?ref={commit_sha}")
    if not isinstance(blob, dict) or blob.get("type") != "file" or blob.get("encoding") != "base64":
        raise ReceiptVerificationError("pinned anchor missing")
    payload = blob.get("content")
    if not isinstance(payload, str) or len(payload) > 100_000:
        raise ReceiptVerificationError("invalid anchor size")
    try:
        raw = base64.b64decode("".join(payload.split()), validate=True)
        anchor = json.loads(raw)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ReceiptVerificationError("corrupt anchor") from exc
    return anchor


def verify_github_freeze(receipt,content_hash,persisted_at,cutoff_at,*,_fetch=None):
    """Verify a single hash at an exact server-witnessed pre-cutoff commit.

    Local clocks are consistency checks, not independent timestamp evidence.
    _fetch is reserved for invented offline responses in tests.
    """
    if not isinstance(content_hash,str) or not HEX64.fullmatch(content_hash):
        raise ReceiptVerificationError('forecast hash invalid')
    anchor=_read_freeze_document(receipt,persisted_at,cutoff_at,_fetch=_fetch)
    if (not isinstance(anchor, dict) or anchor.get("schema") != ANCHOR_SCHEMA
        or anchor.get("prediction_sha256") != content_hash
        or anchor.get("cutoff_at") != cutoff_at
        or not isinstance(anchor.get("race_id"), str) or not anchor["race_id"]):
        raise ReceiptVerificationError("anchor hash/identity/cutoff mismatch")
    return True


def verify_github_pair_manifest(receipt,expected_entry,*,_fetch=None):
    """Verify exact membership of unchanged V2 pair/body/physical-receipt hashes.

    The same server clock, same-repository event and immutable content checks
    used for single anchors apply. Producer admission flags grant no trust.
    """
    fields={'pair_sha256','file_sha256','local_freeze_receipt_sha256','race_id','stage','write_completed_at','cutoff_at'}
    def valid(entry):
        return (type(entry) is dict and set(entry)==fields and
            all(type(entry[k]) is str and HEX64.fullmatch(entry[k]) for k in ('pair_sha256','file_sha256','local_freeze_receipt_sha256')) and
            type(entry['race_id']) is str and re.fullmatch(r'[0-9]{8}-(?:0[1-9]|1[0-9]|2[0-4])-(?:0[1-9]|1[0-2])',entry['race_id']) and
            entry['stage'] in ('P0','P1') and _date(entry['write_completed_at'])<_date(entry['cutoff_at']))
    if not valid(expected_entry):raise ReceiptVerificationError('pair manifest entry invalid')
    doc=_read_freeze_document(receipt,expected_entry['write_completed_at'],expected_entry['cutoff_at'],_fetch=_fetch)
    if (type(doc) is not dict or doc.get('schema')!='RACE_AI_RESEARCH_PAIRS_SHA_ONLY_V2' or
        doc.get('research_only') is not True or doc.get('actual_purchases') is not False or doc.get('auto_promoted') is not False):
        raise ReceiptVerificationError('pair manifest schema/scope invalid')
    entries=doc.get('entries');prepared=doc.get('prepared_races');scheduled=doc.get('scheduled_races')
    if (type(entries) is not list or type(prepared) is not int or type(scheduled) is not int or
        not 1<=prepared<=scheduled<=288 or len(entries)!=prepared or not all(valid(e) for e in entries) or
        len({e['pair_sha256'] for e in entries})!=len(entries)):
        raise ReceiptVerificationError('pair manifest duplicate/count invalid')
    matches=[e for e in entries if e['pair_sha256']==expected_entry['pair_sha256']]
    if matches!=[expected_entry]:raise ReceiptVerificationError('pair manifest membership mismatch')
    return True
