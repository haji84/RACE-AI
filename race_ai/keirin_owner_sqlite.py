"""Concrete private SQLite persistence for the existing KEIRIN owner workflow.

This is a REAL filesystem-backed, cross-process state store. It implements the
PR72 outbox/forecast callback contracts using transactional SQLite, not mock
dictionaries. It does NOT provide a source licence, prediction model, trusted
external timestamp witness, a GitHub-hosted persistent volume or a live feed.

Use only on an owner-controlled private disk. Never place the DB or its WAL/SHM
in the public repository, Actions logs, public artifacts, or GitHub cache.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Callable

from .keirin_result_delivery import canonical, utc

SHA = re.compile(r"^[0-9a-f]{64}$")


class OwnerStoreError(ValueError):
    pass


def _ensure(condition, code):
    if not condition:
        raise OwnerStoreError(code)


def _json(data):
    return canonical(data).decode("utf-8")


def _now():
    return datetime.now(timezone.utc)


def _checked_clock(clock):
    value = clock()
    if isinstance(value, datetime):
        _ensure(value.utcoffset() is not None, "AWARE_CLOCK_REQUIRED")
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        return utc(value)
    raise OwnerStoreError("AWARE_CLOCK_REQUIRED")


class PrivateKeirinStore:
    """Owner-local append-only records with SQLite IMMEDIATE transactions.

    Each method opens its own transaction and commits before it returns, so
    readback after the process restarts is an actual disk-level test. This
    does not magically persist a GitHub-hosted runner's ephemeral filesystem.
    """

    def __init__(self, path, *, clock: Callable = _now):
        _ensure(callable(clock), "CLOCK_REQUIRED")
        location = Path(path).expanduser()
        _ensure(str(location) not in ("", ":memory:") and
                location.suffix in (".db", ".sqlite3"),
                "PERSISTENT_SQLITE_PATH_REQUIRED")
        if location.is_symlink():
            raise OwnerStoreError("SYMLINKED_DB_FORBIDDEN")
        location.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(location.parent, 0o700) if location.parent.name == ".race-ai-private" else None
        self.path = location
        self.clock = clock
        self.db = sqlite3.connect(str(location), timeout=4,
                                  isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=4000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS race_index (
                race_id TEXT PRIMARY KEY,
                cutoff_at TEXT,
                status TEXT NOT NULL,
                discovered_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_sha256 TEXT PRIMARY KEY,
                race_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                payload BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                idempotency_key TEXT PRIMARY KEY,
                race_id TEXT NOT NULL,
                payload BLOB NOT NULL,
                inserted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forecasts (
                race_id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                forecast_sha256 TEXT NOT NULL,
                payload BLOB NOT NULL,
                persisted_at TEXT NOT NULL,
                independent_witness_at TEXT,
                independent_witness_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS result_revisions (
                race_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                source_sha256 TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload BLOB NOT NULL,
                observed_at TEXT NOT NULL,
                provider_auth_verified INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (race_id, revision)
            );
            CREATE TABLE IF NOT EXISTS audits (
                race_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                result_revision INTEGER NOT NULL,
                payload_sha256 TEXT NOT NULL,
                payload BLOB NOT NULL,
                PRIMARY KEY (race_id, model_id, result_revision)
            );
        """)
        if os.name == "posix":
            os.chmod(location, 0o600)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _insert_once(self, table, keyfield, key, race, document):
        body = canonical(document)
        _ensure(0 < len(body) <= 2_000_000, "PRIVATE_RECORD_SIZE_INVALID")
        at = _checked_clock(self.clock).isoformat()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                f"SELECT payload FROM {table} WHERE {keyfield}=?", (key,)
            ).fetchone()
            if prior is not None:
                identical = prior["payload"] == body
                self.db.execute("COMMIT")
                return identical
            self.db.execute(
                f"INSERT INTO {table} ({keyfield},race_id,payload,inserted_at)"
                " VALUES (?,?,?,?)", (key, race, body, at))
            self.db.execute("COMMIT")
            return True
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def enqueue_once(self, intent):
        """Adapter for reactor enqueue_once. Duplicate same key is idempotent."""
        if type(intent) is not dict:
            return None
        key, race = intent.get("idempotency_key"), intent.get("race_id")
        if not (type(key) is str and SHA.fullmatch(key) and type(race) is str):
            return None
        try:
            ok = self._insert_once("outbox", "idempotency_key",
                                   key, race, intent)
        except (sqlite3.Error, OwnerStoreError):
            return None
        return ({"idempotency_key": key, "state": "CREATED_OR_EXISTS"}
                if ok else None)

    def read_queued_intent(self, key):
        if type(key) is not str or not SHA.fullmatch(key):
            return None
        row = self.db.execute(
            "SELECT payload FROM outbox WHERE idempotency_key=?", (key,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def enqueue_readback(self, key):
        return self.read_queued_intent(key)

    def save_source_snapshot_once(self, snapshot):
        """Caller must independently attest real origin and captured time."""
        if type(snapshot) is not dict:
            raise OwnerStoreError("SNAPSHOT_DICT_REQUIRED")
        rid = snapshot.get("race_id")
        captured = snapshot.get("as_of")
        _ensure(type(rid) is str and type(captured) is str,
                "SNAPSHOT_RACE_OR_TIME_REQUIRED")
        _ensure(utc(captured) <= _checked_clock(self.clock),
                "FUTURE_SOURCE_SNAPSHOT_REFUSED")
        body = canonical(snapshot)
        _ensure(len(body) <= 2_000_000, "SNAPSHOT_TOO_LARGE")
        digest = sha256(body).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT payload FROM snapshots WHERE snapshot_sha256=?",
                (digest,)
            ).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO snapshots VALUES (?,?,?,?)",
                    (digest, rid, captured, body)
                )
            elif row["payload"] != body:
                raise OwnerStoreError("SNAPSHOT_HASH_COLLISION")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return digest

    def read_snapshot(self, intent):
        if type(intent) is not dict:
            return None
        sha = intent.get("pre_race_snapshot_sha256")
        if type(sha) is not str or not SHA.fullmatch(sha):
            return None
        row = self.db.execute(
            "SELECT payload FROM snapshots WHERE snapshot_sha256=?",
            (sha,)
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["payload"])
        return data if data.get("race_id") == intent.get("race_id") else None

    def frozen_status(self, race_id):
        row = self.db.execute(
            "SELECT forecast_sha256 FROM forecasts WHERE race_id=?",
            (race_id,)
        ).fetchone()
        if not row:
            return {"race_id": race_id,
                    "state": "ABSENT_VERIFIED_BY_OWNER"}
        return {"race_id": race_id, "state": "EXISTS",
                "forecast_sha256": row["forecast_sha256"]}

    def atomic_freeze(self, forecast, digest):
        """Never replace an original, including after a worker crash/retry."""
        if type(forecast) is not dict or type(digest) is not str:
            return None
        rid = forecast.get("race_id")
        cutoff = forecast.get("official_cutoff_at")
        generated = forecast.get("generated_at")
        if type(rid) is not str or not SHA.fullmatch(digest):
            return None
        body = canonical(forecast)
        if sha256(body).hexdigest() != digest or len(body) > 2_000_000:
            return None
        at = _checked_clock(self.clock)
        try:
            if not (utc(generated) <= at < utc(cutoff)):
                return None
        except (ValueError, TypeError):
            return None
        try:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute(
                "SELECT 1 FROM forecasts WHERE race_id=?", (rid,)
            ).fetchone()
            if prior is not None:
                self.db.execute("COMMIT")
                return None
            # Re-read clock under the write lock. A slow queue must not
            # freeze a model after sales have closed.
            at = _checked_clock(self.clock)
            if not (utc(generated) <= at < utc(cutoff)):
                self.db.execute("ROLLBACK")
                return None
            self.db.execute(
                "INSERT INTO forecasts "
                "(race_id,model_id,forecast_sha256,payload,persisted_at)"
                " VALUES (?,?,?,?,?)",
                (rid, forecast.get("model_id"), digest, body, at.isoformat())
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"race_id": rid, "forecast_sha256": digest,
                "state": "CREATED_ONCE"}

    def freeze_readback(self, race_id, digest):
        if type(digest) is not str or not SHA.fullmatch(digest):
            return None
        row = self.db.execute(
            "SELECT payload FROM forecasts WHERE race_id=? AND forecast_sha256=?",
            (race_id, digest)
        ).fetchone()
        if not row:
            return None
        if sha256(row["payload"]).hexdigest() != digest:
            return None
        return json.loads(row["payload"])

    def get_persisted_forecast(self, race_id):
        row = self.db.execute(
            "SELECT payload,forecast_sha256,persisted_at FROM forecasts "
            "WHERE race_id=?", (race_id,)
        ).fetchone()
        if not row:
            return None
        return {"forecast": json.loads(row["payload"]),
                "sha256": row["forecast_sha256"],
                "persisted_at": row["persisted_at"],
                "external_receipt_verified": False}

    def add_result_observation(self, observation, *, independently_authenticated=False):
        """Persist ordered provider revisions without promoting unauthenticated rows.

        A caller's boolean is only a claimed trust boundary. A real runner
        must authenticate provider bytes and rights BEFORE invoking it.
        """
        if type(observation) is not dict:
            raise OwnerStoreError("RESULT_OBSERVATION_REQUIRED")
        rid = observation.get("race_id")
        source_sha = observation.get("source_sha256")
        if not (type(rid) is str and type(source_sha) is str and
                SHA.fullmatch(source_sha)):
            raise OwnerStoreError("RESULT_IDENTITY_SOURCE_REQUIRED")
        at = _checked_clock(self.clock)
        _ensure(utc(observation["observed_at"]) <= at,
                "FUTURE_OBSERVATION_REFUSED")
        body = canonical(observation)
        digest = sha256(body).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                "SELECT revision,payload_sha256 FROM result_revisions "
                "WHERE race_id=? ORDER BY revision DESC LIMIT 1", (rid,)
            ).fetchone()
            if prior is not None and prior["payload_sha256"] == digest:
                self.db.execute("COMMIT")
                return {"race_id": rid, "revision": prior["revision"],
                        "state": "ALREADY_PRESENT"}
            rev = 1 if prior is None else prior["revision"] + 1
            self.db.execute(
                "INSERT INTO result_revisions VALUES (?,?,?,?,?,?,?)",
                (rid, rev, source_sha, digest, body, at.isoformat(),
                 1 if independently_authenticated else 0)
            )
            self.db.execute("COMMIT")
            return {"race_id": rid, "revision": rev,
                    "state": "RESULT_REVISION_APPENDED",
                    "official_result_authenticated": False}
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def research_audit(self, race_id):
        """Score the ORIGINAL saved 8 tickets, never alter previous reports."""
        original = self.get_persisted_forecast(race_id)
        result = self.db.execute(
            "SELECT revision,payload,provider_auth_verified FROM result_revisions "
            "WHERE race_id=? ORDER BY revision DESC LIMIT 1", (race_id,)
        ).fetchone()
        if result is None or original is None:
            return {"race_id": race_id, "research_hit8": None,
                    "reason": "FORECAST_OR_RESULT_MISSING"}
        row = json.loads(result["payload"])
        if row.get("status") != "FINAL_NORMAL" or (
                row.get("refund_status") != "NONE"):
            return {"race_id": race_id, "research_hit8": None,
                    "reason": "RESULT_NOT_SETTLED"}
        picks = original["forecast"].get("top8", [])
        wins = row.get("winning_triples", [])
        _ensure(type(picks) is list and type(wins) is list,
                "INVALID_RESEARCH_TOP8_OR_OUTCOME")
        if not picks or len(picks) > 8 or any(
                type(p) is not list or len(p) != 3 or
                len(set(p)) != 3 for p in picks):
            raise OwnerStoreError("INVALID_FORECAST_TOP8")
        hit = bool({tuple(p) for p in picks} & {tuple(p) for p in wins})
        report = {"schema": "RACE_AI_PRIVATE_RESEARCH_AUDIT_V1",
                  "race_id": race_id,
                  "model_id": original["forecast"]["model_id"],
                  "forecast_sha256": original["sha256"],
                  "result_revision": result["revision"],
                  "research_hit8": hit, "formal_hit_at_8_all": None,
                  "independent_forecast_time_verified": False,
                  "official_result_authenticated": False}
        body = canonical(report)
        fingerprint = sha256(body).hexdigest()
        key = (race_id, report["model_id"], result["revision"])
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                "SELECT payload FROM audits WHERE race_id=? AND model_id=? "
                "AND result_revision=?", key
            ).fetchone()
            if prior is None:
                self.db.execute(
                    "INSERT INTO audits VALUES (?,?,?,?,?)",
                    (*key, fingerprint, body)
                )
            elif prior["payload"] != body:
                raise OwnerStoreError("AUDIT_IMMUTABILITY_CONFLICT")
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return report
