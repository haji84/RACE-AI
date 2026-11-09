"""Immutable four-model variable picks for the existing cloud PR71 SQLite.

No new forecaster or scorer. Reuses PR103's selection algorithm and the
original FourModelRankLedger. All inputs stay private on the trusted runner;
only the existing AES snapshot may contain actual selections.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import json
import sqlite3

from race_ai.four_sport_model_suite import ALL_MODELS
from race_ai.keirin_owner_sqlite import PrivateKeirinStore, _checked_clock
from race_ai.keirin_pr71_four_model_rank import FourModelRankLedger
from race_ai.keirin_result_delivery import canonical, utc
from race_ai.keirin_variable_selection import (
    ODDS_SCHEMA, SCHEMA as VARIABLE_SCHEMA, seal, select_research_tickets,
)

CUTOFF_MARGIN_SECONDS = 65
MAX_RACES_PER_CYCLE = 150


class FourVariableError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise FourVariableError(code)


class FourModelVariableLedger:
    """Additive per-model sidecars. Never alters original suites or results."""

    def __init__(self, store):
        need(isinstance(store, PrivateKeirinStore), "PRIVATE_OWNER_STORE_REQUIRED")
        self.store = store
        self.db = store.db
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS keirin_pr71_four_model_variable_selections (
                race_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                suite_sha256 TEXT NOT NULL,
                odds_sha256 TEXT NOT NULL,
                selection_sha256 TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                persisted_at TEXT NOT NULL,
                payload BLOB NOT NULL,
                PRIMARY KEY(race_id, model_id)
            )
        """)

    def selection(self, race_id, model_id):
        row = self.db.execute(
            "SELECT * FROM keirin_pr71_four_model_variable_selections "
            "WHERE race_id=? AND model_id=?", (race_id, model_id)
        ).fetchone()
        if row is None:
            return None
        raw = row["payload"]
        need(sha256(raw).hexdigest() == row["payload_sha256"],
             "VARIABLE_PAYLOAD_CHANGED")
        document = json.loads(raw)
        need(type(document) is dict and
             document.get("schema") == VARIABLE_SCHEMA and
             document.get("race_id") == race_id and
             document.get("model_id") == model_id and
             document.get("suite_sha256") == row["suite_sha256"] and
             document.get("odds_snapshot_sha256") == row["odds_sha256"] and
             document.get("document_sha256") == row["selection_sha256"] and
             seal({k: v for k, v in document.items()
                   if k != "document_sha256"}) == row["selection_sha256"] and
             type(document.get("pick_count")) is int and
             0 <= document["pick_count"] <= 12 and
             len(document.get("tickets", [])) == document["pick_count"] and
             utc(row["persisted_at"]) < utc(document["official_cutoff_at"]),
             "VARIABLE_SELECTION_READBACK_INVALID")
        return {"selection": document, "persisted_at": row["persisted_at"]}

    def freeze_four_once(self, race_id, odds, *, source_admission=None):
        """Freeze exactly four independently calculated decisions atomically."""
        saved = FourModelRankLedger(self.store).read_suite(race_id)
        need(saved is not None, "ORIGINAL_FOUR_MODELS_NOT_FROZEN")
        suite = saved["suite"]
        need(tuple(suite["models"]) == tuple(ALL_MODELS) and
             len(ALL_MODELS) == 4, "MODEL_ROSTER_CHANGED")
        previous = [self.selection(race_id, m) for m in ALL_MODELS]
        need(not any(previous) or all(previous),
             "INCOMPLETE_FOUR_MODEL_VARIABLE_ORIGINAL")
        if all(previous):
            need(all(r["selection"]["suite_sha256"] == suite["suite_sha256"] and
                     r["selection"]["model_prediction_sha256"] ==
                     suite["models"][m]["prediction_sha256"]
                     for m, r in zip(ALL_MODELS, previous)),
                 "EXISTING_VARIABLE_NOT_BOUND_TO_FROZEN_SUITE")
            return 0
        now = _checked_clock(self.store.clock)
        cutoff = utc(suite["sales_cutoff_at"])
        need(now + timedelta(seconds=CUTOFF_MARGIN_SECONDS) < cutoff and
             utc(saved["persisted_at"]) <= now,
             "PRE_CUTOFF_DECISION_REQUIRED")
        need(type(odds) is dict and odds.get("schema") == ODDS_SCHEMA and
             odds.get("race_id") == race_id and
             type(odds.get("prices")) is list and
             len(odds["prices"]) == suite["models"][ALL_MODELS[0]]["candidate_count"] and
             utc(odds["captured_at"]) <= now and
             utc(odds["captured_at"]) >= utc(suite["as_of"]),
             "COMPLETE_PRE_CUTOFF_ODDS_REQUIRED")
        if suite.get("scope") != "SYNTHETIC_ONLY":
            need(callable(source_admission), "LICENSED_ODDS_REQUIRED")
            purposes = ("automated_fetch", "analysis", "pre_race",
                        "model_inference", "private_retention")
            def admit(url, rights, purpose):
                return (purpose == "private_odds_research" and
                        all(source_admission(url, rights, p) is True
                            for p in purposes))
            need(admit(odds["source_ref"], odds["source_rights_ref"],
                       "private_odds_research"),
                 "ODDS_RESEARCH_RIGHTS_REQUIRED")
        else:
            admit = None
        decisions = {
            mid: select_research_tickets(
                suite, mid, odds, decision_at=now.isoformat(),
                source_admission=admit
            ) for mid in ALL_MODELS
        }
        self.db.execute("BEGIN IMMEDIATE")
        try:
            at = _checked_clock(self.store.clock)
            need(at + timedelta(seconds=CUTOFF_MARGIN_SECONDS) < cutoff,
                 "VARIABLE_WRITE_CUTOFF_EXPIRED")
            need(self.db.execute(
                "SELECT suite_sha256 FROM keirin_pr71_four_model_suites "
                "WHERE race_id=?", (race_id,)
            ).fetchone()["suite_sha256"] == suite["suite_sha256"],
                 "ORIGINAL_CHANGED_DURING_WRITE")
            need(self.db.execute(
                "SELECT COUNT(*) FROM keirin_pr71_four_model_variable_selections "
                "WHERE race_id=?", (race_id,)
            ).fetchone()[0] == 0, "CONCURRENT_VARIABLE_FREEZE")
            for mid, selection in decisions.items():
                raw = canonical(selection)
                self.db.execute(
                    "INSERT INTO keirin_pr71_four_model_variable_selections "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (race_id, mid, suite["suite_sha256"],
                     selection["odds_snapshot_sha256"],
                     selection["document_sha256"], sha256(raw).hexdigest(),
                     at.isoformat(), raw)
                )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        for mid in ALL_MODELS:
            need(self.selection(race_id, mid)["selection"] == decisions[mid],
                 "FOUR_MODEL_VARIABLE_INDEPENDENT_READBACK_FAILED")
        return 4

    def inventory(self):
        rows = self.db.execute(
            "SELECT race_id,model_id,selection_sha256 "
            "FROM keirin_pr71_four_model_variable_selections "
            "ORDER BY race_id,model_id"
        ).fetchall()
        for row in rows:
            self.selection(row["race_id"], row["model_id"])
        return [tuple(row) for row in rows]


def stage_four_model_variable_selections(inbox, store, *,
                                         source_admission=None):
    """Use only already licensed, staged full odds; no network or backfills."""
    folder = Path(inbox) / "odds"
    if not folder.exists():
        return {"four_model_variable_saved": 0,
                "four_model_variable_held": 0,
                "odds_files_inspected": 0}
    need(folder.is_dir() and not folder.is_symlink(),
         "ODDS_FOLDER_UNSAFE")
    ledger = FourModelVariableLedger(store)
    rows = sorted(folder.glob("*.json"))
    need(len(rows) <= MAX_RACES_PER_CYCLE, "ODDS_BATCH_TOO_LARGE")
    saved = held = 0
    for path in rows:
        try:
            need(path.is_file() and not path.is_symlink() and
                 0 < path.stat().st_size <= 2_000_000, "ODDS_FILE_UNSAFE")
            odds = json.loads(path.read_bytes())
            race_id = odds["race_id"]
            need(path.name == sha256(race_id.encode("utf-8")).hexdigest() + ".json",
                 "ODDS_FILE_RACE_BINDING_INVALID")
            saved += ledger.freeze_four_once(
                race_id, odds, source_admission=source_admission)
        except (ValueError, TypeError, KeyError, OSError, sqlite3.Error):
            held += 1
    return {"four_model_variable_saved": saved,
            "four_model_variable_held": held,
            "odds_files_inspected": len(rows)}
