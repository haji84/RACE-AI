"""Owner-private, restart-safe KEIRIN source-inbox cycle.

With a real *authorized* data feeder and an owner-controlled persistent disk,
this program handles every supplied race automatically, without an hourly
ChatGPT task: pre-race snapshot -> PR71 untrained model -> private SQLite
create-once freeze -> post-race result revisions -> PDCA -> next snapshot.

Not a source collector. Source admission, independent third-party timestamp,
official result attestation, and 24/7 host are external dependencies.
No provider network, odds input, public raw forecasts, or wagering.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time

from .keirin_result_delivery import canonical, utc
from .keirin_next_forecast_worker import consume_next_intent
from .keirin_owner_sqlite import PrivateKeirinStore
from .keirin_pr71_model_adapter import run_pr71_for_next_race

SOURCE_SCHEMA = "RACE_AI_KEIRIN_PRIVATE_PRE_RACE_V1"
RESULT_SCHEMA = "RACE_AI_PRIVATE_KEIRIN_RESULT_OBSERVATION_V1"
INTENT_SCHEMA = "RACE_AI_KEIRIN_NEXT_FORECAST_INTENT_V1"
MODEL = "multisport-scenario-ensemble-v1"
MAX_FILES_PER_KIND = 200
MAX_BYTES = 2_000_000


class InboxError(ValueError):
    pass


def _safe_json(path):
    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise InboxError("UNTRUSTED_INBOX_FILE")
    if not 0 < target.stat().st_size <= MAX_BYTES:
        raise InboxError("INBOX_FILE_SIZE_INVALID")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise InboxError("INVALID_JSON") from None


def _files(root, name):
    folder = Path(root) / name
    if folder.is_symlink():
        raise InboxError("SYMLINKED_INBOX_DIRECTORY")
    if not folder.exists():
        return []
    if not folder.is_dir():
        raise InboxError("INBOX_NOT_DIRECTORY")
    items = sorted(folder.glob("*.json"))
    if len(items) > MAX_FILES_PER_KIND:
        raise InboxError("INBOX_BATCH_LIMIT")
    return items


def _fingerprint(obj):
    return sha256(canonical(obj)).hexdigest()


class KeirinPrivateSpool:
    def __init__(self, store, *, clock=None,
                 model_suite=None, model_verifier=None,
                 source_attestor=None, source_observation_gate=None,
                 witness=None):
        if not isinstance(store, PrivateKeirinStore):
            raise InboxError("PERSISTENT_PRIVATE_OWNER_STORE_REQUIRED")
        self.store = store
        self.clock = clock if clock is not None else (
            lambda: datetime.now(timezone.utc))
        self.model_suite = model_suite
        self.model_verifier = model_verifier
        self.source_attestor = source_attestor
        self.source_observation_gate = source_observation_gate
        self.witness = witness

    def _time(self):
        stamp = self.clock()
        if type(stamp) is str:
            return utc(stamp)
        if isinstance(stamp, datetime) and stamp.utcoffset() is not None:
            return stamp.astimezone(timezone.utc)
        raise InboxError("CLOCK_WITH_TIMEZONE_REQUIRED")

    def _source_certificate(self, snapshot, intent):
        # A JSON flag must never grant rights or source authenticity.
        # Only a separately configured trusted owner callback may attest a
        # real source. Synthetic data is independently labeled as fictitious.
        evidence = snapshot.get("facts",{}).get("pr71_evidenced_snapshot",{})
        if evidence.get("scope") == "SYNTHETIC_ONLY":
            return {
                "race_id":intent["race_id"],
                "source_sha256":intent["pre_race_snapshot_sha256"],
                "permission_ref":intent["permission_ref"],
                "official_cutoff_at":intent["official_cutoff_at"],
                "verified_purposes":["schedule","pre_race",
                                     "private_retention","model_inference"],
                "valid_until":intent["official_cutoff_at"],
            }
        if not callable(self.source_attestor):
            return None
        try:
            return self.source_attestor(snapshot, intent)
        except Exception:
            return None

    def _model(self, snapshot):
        if not callable(self.model_suite) or not callable(self.model_verifier):
            return None
        evidence = snapshot.get("facts",{}).get("pr71_evidenced_snapshot",{})
        if evidence.get("scope") != "SYNTHETIC_ONLY" and not callable(
                self.source_observation_gate):
            return None
        return run_pr71_for_next_race(
            snapshot,
            run_suite=self.model_suite,
            verify_suite=self.model_verifier,
            source_admission=self.source_observation_gate,
            model_id=MODEL,
            issued_at=self._time().isoformat(),
        )

    def _run_forecast(self, snapshot):
        if not isinstance(snapshot, dict) or (
                snapshot.get("schema") != SOURCE_SCHEMA):
            return "REJECTED_SOURCE_SCHEMA"
        race_id=snapshot.get("race_id")
        if type(race_id) is not str:
            return "REJECTED_RACE_ID"
        if self.store.frozen_status(race_id).get("state") != (
                "ABSENT_VERIFIED_BY_OWNER"):
            return "ALREADY_PRIVATE_FROZEN"
        try:
            cutoff=utc(snapshot["official_cutoff_at"])
            observed=utc(snapshot["as_of"])
            now=self._time()
        except (KeyError,TypeError,ValueError):
            return "UNVERIFIED_SOURCE_OR_CUTOFF"
        if not observed <= now < cutoff:
            return "MISSED_OR_UNVERIFIED_CUTOFF"
        evidence=snapshot.get("facts",{}).get("pr71_evidenced_snapshot",{})
        if evidence.get("scope") != "SYNTHETIC_ONLY" and not callable(
                self.source_attestor):
            return "REAL_SOURCE_ATTESTOR_NOT_CONFIGURED"
        try:
            original_sha=self.store.save_source_snapshot_once(snapshot)
        except (ValueError,KeyError,TypeError):
            return "SOURCE_PRIVATE_SAVE_FAILED"
        key=sha256(canonical({
            "race_id":race_id,
            "official_cutoff_at":snapshot["official_cutoff_at"],
            "job_kind":"KEIRIN_NEXT_FORECAST_V1"
        })).hexdigest()
        intent={
            "schema":INTENT_SCHEMA,
            "idempotency_key":key,
            "trigger_source_event_sha256":
                sha256(("PRE_RACE_FIRST_SEED:"+original_sha).encode()).hexdigest(),
            "race_id":race_id,
            "official_cutoff_at":snapshot["official_cutoff_at"],
            "pre_race_snapshot_sha256":original_sha,
            "pre_race_snapshot_at":snapshot["as_of"],
            "permission_ref":snapshot.get("permission_ref"),
            "max_trifecta_picks":8,
            "prediction_generated":False,
        }
        ack=self.store.enqueue_once(intent)
        if not isinstance(ack,dict):
            return "OUTBOX_CONFLICT_NO_RETRY"
        result=consume_next_intent(
            intent,
            clock=lambda:self._time().isoformat(),
            read_queued_intent=self.store.read_queued_intent,
            read_snapshot=self.store.read_snapshot,
            attest_source=self._source_certificate,
            frozen_status=self.store.frozen_status,
            model_forecast=self._model,
            atomic_freeze=self.store.atomic_freeze,
            freeze_readback=self.store.freeze_readback,
            independent_receipt_check=self.witness,
            margin_seconds=60,
        )
        if result.get("forecast_durably_saved"):
            return "FORECAST_PRIVATE_DURABLY_SAVED"
        return result.get("state","UNKNOWN_WORKER_STATE")

    def _run_result(self, document):
        if not isinstance(document,dict) or (
                document.get("schema") != RESULT_SCHEMA):
            return "REJECTED_RESULT_SCHEMA"
        result=document.get("observation")
        if not isinstance(result,dict):
            return "REJECTED_RESULT_SHAPE"
        try:
            self.store.add_result_observation(result)
            scored=self.store.research_audit(result["race_id"])
        except (ValueError,TypeError,KeyError):
            return "RESULT_REJECTED_OR_NOT_ADMITTED"
        if scored.get("research_hit8") is True:
            return "REFERENCE_HIT8_RESEARCH"
        if scored.get("research_hit8") is False:
            return "REFERENCE_MISS_RESEARCH"
        return "RESULT_SAVED_FORECAST_OR_SETTLEMENT_MISSING"

    def tick(self, inbox):
        """Every supplied race is inventoried. Missing evidence is not a miss."""
        reports=[]
        for path in _files(inbox,"daily"):
            try:
                value=_safe_json(path)
                x=self.store.register_discovered_cohort(value)
                reports.append(("daily","IMPORTED" if x["total"] else "EMPTY"))
            except (InboxError,ValueError,TypeError,KeyError):
                reports.append(("daily","REJECTED_DAILY_INDEX"))
        for path in _files(inbox,"pre"):
            try:
                status=self._run_forecast(_safe_json(path))
            except (InboxError,ValueError,TypeError,KeyError):
                status="FORECAST_FAILED_CLOSED"
            reports.append(("pre",status))
        # Results are consumed only AFTER the pre-race pass; they never enter
        # model features. Corrected results append new immutable revisions.
        for path in _files(inbox,"results"):
            try:
                status=self._run_result(_safe_json(path))
            except (InboxError,ValueError,TypeError,KeyError):
                status="RESULT_FAILED_CLOSED"
            reports.append(("result",status))
        counts=dict(sorted(Counter(s for _,s in reports).items()))
        return {"schema":"RACE_AI_KEIRIN_OWNER_PRIVATE_TICK_V1",
                "processed_files":len(reports),
                "states":counts,
                "private_forecasts_saved_this_tick":
                    counts.get("FORECAST_PRIVATE_DURABLY_SAVED",0),
                "reference_hits_this_tick":
                    counts.get("REFERENCE_HIT8_RESEARCH",0),
                "reference_misses_this_tick":
                    counts.get("REFERENCE_MISS_RESEARCH",0),
                "official_hit_at_8_all":None,
                "private_witness_verified_by_this_module":False,
                "provider_network_requests":0,
                "auto_betting":False}
