"""Bridge PR103 variable research tickets to the existing OWNER-PRIVATE SQLite.

Uses the same SQLite file as the original eight-pick freeze and result history,
but never writes to forecasts, result_revisions, or existing audit rows.
No source download, official certification, model fitting, public persistence,
or wagering. All real data must stay on an owner-controlled private volume.
"""
from __future__ import annotations

from hashlib import sha256
from datetime import timedelta
import json
import sqlite3

from .keirin_owner_sqlite import PrivateKeirinStore, _checked_clock
from .keirin_result_delivery import canonical, utc
from .keirin_variable_selection import (
    SCHEMA, AUDIT_SCHEMA, VariableSelectionError, aggregate_latest_audits,
    evaluate_settled_result, instant, seal
)

class PrivateVariableBridgeError(ValueError):
    pass


def _require(yes, code):
    if not yes:
        raise PrivateVariableBridgeError(code)


def _verify(document, schema):
    _require(type(document) is dict and document.get("schema") == schema,
             "INVALID_VARIABLE_DOCUMENT")
    key = document.get("document_sha256")
    _require(type(key) is str and len(key) == 64 and
             key == seal({k: v for k, v in document.items()
                          if k != "document_sha256"}),
             "VARIABLE_DOCUMENT_HASH_MISMATCH")
    return canonical(document)


class PrivateVariableLedger:
    """Append-only selection plus revision-keyed audit on the original DB."""

    def __init__(self, original_store):
        _require(isinstance(original_store, PrivateKeirinStore),
                 "PRIVATE_OWNER_SQLITE_REQUIRED")
        self.store = original_store
        self.db = original_store.db
        # Independent table names: existing eight-pick forecasts are untouched.
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS variable_selections (
                race_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                selection_sha256 TEXT NOT NULL,
                original_forecast_sha256 TEXT NOT NULL,
                payload BLOB NOT NULL,
                persisted_at TEXT NOT NULL,
                PRIMARY KEY (race_id,model_id)
            );
            CREATE TABLE IF NOT EXISTS variable_selection_audits (
                race_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                result_revision INTEGER NOT NULL,
                selection_sha256 TEXT NOT NULL,
                result_payload_sha256 TEXT NOT NULL,
                audit_sha256 TEXT NOT NULL,
                payload BLOB NOT NULL,
                PRIMARY KEY (race_id,model_id,result_revision)
            );
        """)

    def selection(self, race_id, model_id):
        row = self.db.execute(
            "SELECT payload,selection_sha256,original_forecast_sha256,"
            "persisted_at FROM variable_selections "
            "WHERE race_id=? AND model_id=?", (race_id,model_id)
        ).fetchone()
        if not row:
            return None
        obj = json.loads(row["payload"])
        _require(row["selection_sha256"] == obj.get("document_sha256"),
                 "PERSISTED_VARIABLE_HASH_MISMATCH")
        _verify(obj,SCHEMA)
        return {"selection":obj,"selection_sha256":row["selection_sha256"],
                "original_forecast_sha256":row["original_forecast_sha256"],
                "persisted_at":row["persisted_at"]}

    def freeze_once(self, selection, *, original_forecast_sha256):
        """Bind 0..12 selection to an already saved original, never overwrite.

        The upstream caller must separately verify the full model suite and
        unchanged original top8 against the same source snapshot.
        """
        body = _verify(selection, SCHEMA)
        rid,mid = selection["race_id"],selection["model_id"]
        old = self.store.get_persisted_forecast(rid)
        _require(old is not None and old["sha256"]==original_forecast_sha256,
                 "ORIGINAL_FORECAST_NOT_BOUND")
        original = old["forecast"]
        cutoff = utc(original["official_cutoff_at"])
        decision = instant(selection["selection_at"])
        asof = instant(selection["forecast_as_of"])
        _require(mid==original["model_id"]
                 and selection["model_version"]==original["model_version"]
                 and instant(selection["official_cutoff_at"])==cutoff
                 and asof<=decision<cutoff
                 and utc(original["generated_at"])<=decision,
                 "ORIGINAL_FORECAST_SELECTION_MISMATCH")
        _require(type(selection["pick_count"]) is int
                 and 0<=selection["pick_count"]<=12
                 and len(selection["tickets"])==selection["pick_count"]
                 and selection["reference_investment_yen"]==
                    100*selection["pick_count"]
                 and selection["real_money_recommendation"]=="NO_BET_UNVERIFIED"
                 and selection["official_pre_cutoff_witness_verified"] is False,
                 "UNSAFE_VARIABLE_SELECTION")
        at = _checked_clock(self.store.clock)
        _require(decision<=at and at+timedelta(seconds=60)<cutoff,
                 "VARIABLE_CUTOFF_MARGIN_FAILED")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute(
                "SELECT forecast_sha256 FROM forecasts WHERE race_id=?",(rid,)
            ).fetchone()
            _require(row is not None and
                     row["forecast_sha256"]==original_forecast_sha256,
                     "ORIGINAL_CHANGED_DURING_VARIABLE_WRITE")
            prior=self.db.execute(
                "SELECT selection_sha256,original_forecast_sha256 FROM "
                "variable_selections WHERE race_id=? AND model_id=?",
                (rid,mid)
            ).fetchone()
            if prior:
                _require(prior["selection_sha256"]==selection["document_sha256"]
                         and prior["original_forecast_sha256"]==
                            original_forecast_sha256,
                         "IMMUTABLE_VARIABLE_CONFLICT")
                self.db.execute("COMMIT")
                _require(self.selection(rid,mid)["selection"]==selection,
                         "VARIABLE_READBACK_MISMATCH")
                return "ALREADY_PRESENT_IDENTICAL"
            # Revalidate deadline under the transaction lock.
            at = _checked_clock(self.store.clock)
            _require(decision<=at and at+timedelta(seconds=60)<cutoff,
                     "VARIABLE_CUTOFF_DURING_WRITE")
            self.db.execute(
                "INSERT INTO variable_selections VALUES (?,?,?,?,?,?)",
                (rid,mid,selection["document_sha256"],
                 original_forecast_sha256,body,at.isoformat())
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        _require(self.selection(rid,mid)["selection"]==selection,
                 "VARIABLE_READBACK_MISMATCH")
        return "CREATED_ONCE"

    def audit_latest(self, race_id, model_id):
        """Append new result revision audit, not touching the source result."""
        saved=self.selection(race_id,model_id)
        if saved is None:
            return None
        row=self.db.execute(
            "SELECT revision,payload,payload_sha256 FROM result_revisions "
            "WHERE race_id=? ORDER BY revision DESC LIMIT 1",
            (race_id,)
        ).fetchone()
        if row is None:
            return None
        _require(sha256(row["payload"]).hexdigest()==row["payload_sha256"],
                 "PERSISTED_RESULT_HASH_MISMATCH")
        result=json.loads(row["payload"])
        audit=evaluate_settled_result(saved["selection"],result,
                                      revision=row["revision"])
        body=_verify(audit,AUDIT_SCHEMA)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous=self.db.execute(
                "SELECT payload,selection_sha256,result_payload_sha256 "
                "FROM variable_selection_audits "
                "WHERE race_id=? AND model_id=? AND result_revision=?",
                (race_id,model_id,row["revision"])
            ).fetchone()
            if previous:
                _require(previous["payload"]==body and
                         previous["selection_sha256"]==
                            saved["selection_sha256"] and
                         previous["result_payload_sha256"]==
                            row["payload_sha256"],
                         "IMMUTABLE_VARIABLE_AUDIT_CONFLICT")
            else:
                self.db.execute(
                    "INSERT INTO variable_selection_audits "
                    "VALUES (?,?,?,?,?,?,?)",
                    (race_id,model_id,row["revision"],
                     saved["selection_sha256"],row["payload_sha256"],
                     audit["document_sha256"],body)
                )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return audit

    def aggregate(self):
        """One latest-revision score per race/model; no post-hoc double count."""
        rows=self.db.execute(
            "SELECT a.payload FROM variable_selection_audits a "
            "JOIN (SELECT race_id,MAX(revision) AS rev "
            "FROM result_revisions GROUP BY race_id) latest "
            "ON a.race_id=latest.race_id "
            "AND a.result_revision=latest.rev"
        ).fetchall()
        report=aggregate_latest_audits([json.loads(row["payload"]) for row in rows])
        missing=self.db.execute(
            "SELECT COUNT(*) FROM variable_selections s "
            "LEFT JOIN (SELECT race_id,MAX(revision) AS rev "
            "FROM result_revisions GROUP BY race_id) r ON s.race_id=r.race_id "
            "LEFT JOIN variable_selection_audits a ON "
            "a.race_id=s.race_id AND a.model_id=s.model_id "
            "AND a.result_revision=r.rev "
            "WHERE r.rev IS NOT NULL AND a.audit_sha256 IS NULL"
        ).fetchone()[0]
        report["latest_result_not_yet_audited"]=missing
        report["latest_revision_reconciled"]=missing==0
        return report
