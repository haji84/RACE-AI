"""One-race MANUAL 71 result bridge for the existing encrypted KEIRIN Actions state.

Consumes only already-permission-admitted V3 result rows and privately staged
SHA-pinned owner-authored forecasts. No web I/O, plaintext public HTML, betting,
official result certification or retroactive forecast generation.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import sqlite3

PILOT_RACE = "75-07"
PINNED_V3_SHA256 = "4cd7e88d9ab7880702180bcbab248ebda2a8078a721fab5a08fe47323de21d68"
TABLE = "keirin_owner_manual_71_audits"
SHA = re.compile(r"^[a-f0-9]{64}$")

class PilotError(ValueError):
    pass

def _need(ok, code):
    if not ok:
        raise PilotError(code)

def _sha(value):
    return sha256(value).hexdigest()

def _has_table(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                      (TABLE,)).fetchone() is not None

def _private_root(path, repo):
    if not path:
        return None
    p = Path(path)
    _need(p.is_absolute() and p.is_dir() and not p.is_symlink(),
          "MANUAL71_PRIVATE_SOURCE_NOT_STAGED")
    root, target = Path(repo).resolve(), p.resolve()
    _need(root != target and root not in target.parents,
          "PUBLIC_REPOSITORY_PRIVATE_INPUT_REFUSED")
    for name in ("forecast_v3.json", "baseline_v2.json",
                 "categories.html", "template.html"):
        f = p / name
        _need(f.is_file() and not f.is_symlink() and f.resolve().parent == target,
              "MANUAL71_SOURCE_FILE_MISSING_OR_SYMLINK")
    return p

def _load_existing(repo):
    file = Path(repo) / "race_ai" / "keirin_manual_result_sync.py"
    _need(file.is_file() and not file.is_symlink(),
          "EXISTING_MANUAL_SYNC_MODULE_UNAVAILABLE")
    spec = importlib.util.spec_from_file_location("_keirin_manual_71_main", file)
    _need(spec is not None and spec.loader is not None,
          "INVALID_MANUAL_SYNC_MODULE")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def _ensure_table(db):
    db.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        race_id TEXT NOT NULL, source_revision_sha256 TEXT NOT NULL,
        forecast_sha256 TEXT NOT NULL, report_sha256 TEXT NOT NULL,
        html_sha256 TEXT NOT NULL, report_json BLOB NOT NULL,
        private_html BLOB NOT NULL, written_at TEXT NOT NULL,
        PRIMARY KEY (race_id, source_revision_sha256)
    )""")

def verify_private_archive(db):
    """Must also be called on a FRESH runner after AES/SQLite restore."""
    if not _has_table(db):
        return {"state":"NO_MANUAL71_AUDIT_IN_ARCHIVE",
                "verified_rows":0}
    count = 0
    for row in db.execute(f"""SELECT race_id,source_revision_sha256,
            forecast_sha256,report_sha256,html_sha256,report_json,private_html
            FROM {TABLE} ORDER BY race_id,source_revision_sha256"""):
        rid, revision, original, report_sha, html_sha, payload, html = row
        _need(rid == PILOT_RACE and SHA.fullmatch(revision) is not None and
              original == PINNED_V3_SHA256,
              "WRONG_PILOT_PROVENANCE")
        _need(_sha(payload) == report_sha and _sha(html) == html_sha,
              "ENCRYPTED_MANUAL71_AUDIT_TAMPERED")
        doc = json.loads(payload)
        _need(doc.get("schema") == "RACE_AI_KEIRIN_MANUAL_71_RESULT_AUDIT_V1" and
              doc.get("official_results_authenticated") is False and
              doc.get("official_cutoffs_verified") is False and
              doc.get("event_date_jst") == "2026-11-17" and
              len(doc.get("rows", [])) == 71 and
              any(r.get("race_id") == PILOT_RACE and
                  r.get("source_revision_sha256") == revision
                  for r in doc["rows"]) and
              html.count(b'class="keirin-auto-result"') == 71,
              "INVALID_MANUAL71_PRIVATE_HTML_OR_RESULT")
        count += 1
    return {"state":"PRIVATE_MANUAL71_AUDIT_SHA_READBACK_VERIFIED",
            "verified_rows":count,
            "official_results_authenticated":False}

def attempt_one_race(*, db, repo, source_dir, result_dir, observed_at=None):
    """The caller must independently admit real V3 grants BEFORE invoking."""
    _need(isinstance(db, sqlite3.Connection), "PRIVATE_SQLITE_REQUIRED")
    if not source_dir:
        return {"state":"HOLD_MANUAL71_PRIVATE_ORIGINAL_NOT_PROVISIONED",
                "new_audits":0, "official_results_authenticated":False}
    private = _private_root(source_dir, repo)
    folder = Path(result_dir)
    _need(folder.is_absolute() and folder.is_dir() and not folder.is_symlink(),
          "AUTHORIZED_RESULT_STAGE_NOT_AVAILABLE")
    _need(Path(repo).resolve() not in folder.resolve().parents,
          "PUBLIC_WORKSPACE_RESULT_STAGE_FORBIDDEN")
    mod = _load_existing(repo)
    original = mod.read_forecast(private/"forecast_v3.json",
               expected_file_sha256=PINNED_V3_SHA256,
               baseline_file=private/"baseline_v2.json")
    categories = mod.read_categories(private/"categories.html", original)
    at = observed_at or datetime.now(timezone.utc).isoformat()
    staged = mod.read_result_candidates(folder, as_of=at)
    candidate = staged.get(PILOT_RACE)
    if candidate is None:
        return {"state":"HOLD_NO_ADMITTED_PILOT_RESULT", "new_audits":0,
                "official_results_authenticated":False}
    report = mod.evaluate(original, {PILOT_RACE:candidate}, categories=categories)
    pilot = next(r for r in report["rows"] if r["race_id"] == PILOT_RACE)
    if (pilot["result_state"] != "PROVISIONAL_RESULT_CANDIDATE" or
            not pilot["reference_comparison"]):
        return {"state":"HOLD_PILOT_NOT_SETTLED_OR_PREDICTION_LATE",
                "new_audits":0, "official_results_authenticated":False}
    page = mod.render_html(report, original,
               template_text=(private/"template.html").read_text(encoding="utf-8"))
    payload, html = mod.canonical(report), page.encode("utf-8")
    revision = pilot["source_revision_sha256"]
    _need(SHA.fullmatch(revision) is not None and len(payload) <= 1_000_000 and
          len(html) <= 2_000_000,
          "INVALID_MANUAL71_PRIVATE_ARCHIVE_SIZE")
    with db:
        _ensure_table(db)
        old = db.execute(f"""SELECT report_sha256,html_sha256 FROM {TABLE}
                      WHERE race_id=? AND source_revision_sha256=?""",
                      (PILOT_RACE,revision)).fetchone()
        if old is not None:
            _need(tuple(old) == (_sha(payload),_sha(html)),
                  "MANUAL71_REVISION_CONFLICT_NOT_OVERWRITTEN")
            inserted = 0
        else:
            db.execute(f"""INSERT INTO {TABLE} (race_id,source_revision_sha256,
                 forecast_sha256,report_sha256,html_sha256,report_json,
                 private_html,written_at) VALUES (?,?,?,?,?,?,?,?)""",
                 (PILOT_RACE,revision,PINNED_V3_SHA256,
                  _sha(payload),_sha(html),payload,html,at))
            inserted = 1
    result = verify_private_archive(db)
    _need(result["verified_rows"] > 0, "PRIVATE_SQLITE_READBACK_FAILED")
    # Public Actions logs must not disclose the private forecast tickets,
    # race-specific hit flags or payouts. Those remain in sealed SQLite.
    return {"state":"PRIVATE_MANUAL71_PILOT_RESEARCH_STORED",
            "new_audits":inserted, "verified_rows":result["verified_rows"],
            "official_results_authenticated":False,
            "official_cutoffs_verified":False,
            "public_html_published":False}
