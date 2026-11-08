"""Owner-private, restart-safe KEIRIN source-inbox cycle.

With a real *authorized* data feeder and an owner-controlled persistent disk,
this program handles every supplied race automatically, without an hourly
ChatGPT task: pre-race snapshot -> PR71 untrained model -> original eight-pick private freeze
-> PR103 optional separately supplied pre-cutoff odds -> variable selection
-> post-race result revisions -> both immutable audits -> next snapshot.

Not a source collector. Source admission, independent third-party timestamp,
official result attestation, and 24/7 host are external dependencies.
No provider network, automatic odds retrieval, public raw forecasts, or wagering.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from pathlib import Path
import time

from .keirin_result_delivery import canonical, utc
from .keirin_next_forecast_worker import consume_next_intent
from .keirin_owner_sqlite import PrivateKeirinStore
from .keirin_pr71_model_adapter import run_pr71_for_next_race
from .keirin_variable_selection import (
    select_research_tickets, ODDS_SCHEMA, VariableSelectionError
)
from .keirin_variable_integration import (
    PrivateVariableLedger, PrivateVariableBridgeError
)
from .comprehensive_four_sport_models import digest as model_digest

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
                 source_odds_gate=None, witness=None):
        if not isinstance(store, PrivateKeirinStore):
            raise InboxError("PERSISTENT_PRIVATE_OWNER_STORE_REQUIRED")
        self.store = store
        self.clock = clock if clock is not None else (
            lambda: datetime.now(timezone.utc))
        self.model_suite = model_suite
        self.model_verifier = model_verifier
        self.source_attestor = source_attestor
        self.source_observation_gate = source_observation_gate
        self.source_odds_gate = source_odds_gate
        self.witness = witness
        self.variable_store = PrivateVariableLedger(store)

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


    def _run_odds(self, odds):
        """After original freeze, generate a separately immutable 0..12-pick record.

        For real evidence, both observation and odds callbacks are required.
        Neither a URL nor a self-declared label is an official rights grant.
        """
        if type(odds) is not dict or odds.get("schema") != ODDS_SCHEMA:
            return "REJECTED_ODDS_SCHEMA"
        race_id=odds.get("race_id")
        if type(race_id) is not str:
            return "REJECTED_ODDS_RACE"
        old=self.store.get_persisted_forecast(race_id)
        if old is None:
            return "VARIABLE_ORIGINAL_FORECAST_MISSING"
        prior=self.variable_store.selection(race_id,MODEL)
        if prior is not None:
            try:
                same=(model_digest(odds)==
                      prior["selection"]["odds_snapshot_sha256"])
            except (TypeError,ValueError):
                same=False
            return ("VARIABLE_ALREADY_PRIVATE_FROZEN" if same
                    else "VARIABLE_POST_FREEZE_ODDS_CONFLICT")
        try:
            now=self._time()
            cutoff=utc(old["forecast"]["official_cutoff_at"])
            if now+timedelta(seconds=60)>=cutoff:
                return "VARIABLE_ODDS_TOO_LATE"
            snapshot=self.store.read_snapshot({
                "race_id":race_id,
                "pre_race_snapshot_sha256":
                    old["forecast"]["snapshot_sha256"]
            })
            if type(snapshot) is not dict:
                return "VARIABLE_ORIGINAL_SOURCE_MISSING"
            evidence=snapshot["facts"]["pr71_evidenced_snapshot"]
            if not callable(self.model_suite) or not callable(self.model_verifier):
                return "VARIABLE_VERIFIED_MODEL_MISSING"
            if evidence.get("scope") != "SYNTHETIC_ONLY" and (
                    not callable(self.source_observation_gate)
                    or not callable(self.source_odds_gate)):
                return "VARIABLE_SOURCE_GATES_MISSING"
            suite=self.model_suite(
                evidence,allow_source=self.source_observation_gate)
            if self.model_verifier(suite) is not True or (
                    suite.get("race_id")!=race_id or
                    suite.get("input_sha256")!=model_digest(evidence) or
                    suite.get("sales_cutoff_at")!=
                       old["forecast"]["official_cutoff_at"] or
                    suite.get("as_of")!=snapshot["as_of"]):
                return "VARIABLE_SOURCE_MODEL_MISMATCH"
            m=suite["models"][MODEL]
            if (m["ordered_top8"]!=old["forecast"]["top8"] or
                    m["model_version"]!=old["forecast"]["model_version"] or
                    m["model_id"]!=old["forecast"]["model_id"]):
                return "VARIABLE_ORIGINAL_MODEL_MISMATCH"
            if len(odds.get("prices",[])) != m["candidate_count"]:
                return "VARIABLE_INCOMPLETE_ODDS"
            selection=select_research_tickets(
                suite,MODEL,odds,decision_at=now.isoformat(),
                source_admission=self.source_odds_gate)
            outcome=self.variable_store.freeze_once(
                selection,original_forecast_sha256=old["sha256"],
                odds_snapshot=odds)
            return ("VARIABLE_PRIVATE_SELECTION_SAVED" if
                    outcome=="CREATED_ONCE" else "VARIABLE_ALREADY_PRIVATE_FROZEN")
        except (ValueError,TypeError,KeyError,AttributeError,IndexError,
                VariableSelectionError,PrivateVariableBridgeError):
            return "VARIABLE_ODDS_OR_BINDING_REJECTED"

    def _run_result(self, document):
        if not isinstance(document,dict) or (
                document.get("schema") != RESULT_SCHEMA):
            return "REJECTED_RESULT_SCHEMA"
        result=document.get("observation")
        if not isinstance(result,dict):
            return "REJECTED_RESULT_SHAPE"
        try:
            insertion=self.store.add_result_observation(result)
            scored=self.store.research_audit(result["race_id"])
        except (ValueError,TypeError,KeyError):
            return "RESULT_REJECTED_OR_NOT_ADMITTED"
        try:
            # Separate audit of latest revision, never a rewrite of old results.
            self.variable_store.audit_latest(result["race_id"],MODEL)
        except (ValueError,TypeError,KeyError):
            return "RESULT_SAVED_VARIABLE_AUDIT_NEEDS_RETRY"
        if insertion.get("state")=="ALREADY_PRESENT":
            return "RESULT_ALREADY_SEEN_NO_RECOUNT"
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
        # Finalized prior-race results are audited BEFORE new forecasts.
        # The actual PR71 prediction still receives only strictly timestamped
        # pre-race source fields, never the result file as a model feature.
        for path in _files(inbox,"results"):
            try:
                status=self._run_result(_safe_json(path))
            except (InboxError,ValueError,TypeError,KeyError):
                status="RESULT_FAILED_CLOSED"
            reports.append(("result",status))
        for path in _files(inbox,"pre"):
            try:
                status=self._run_forecast(_safe_json(path))
            except (InboxError,ValueError,TypeError,KeyError):
                status="FORECAST_FAILED_CLOSED"
            reports.append(("pre",status))
        # Same-tick odds are processed only AFTER the original forecast freeze.
        # Missing odds never block the existing forecast/result pipeline.
        for path in _files(inbox,"odds"):
            try:
                status=self._run_odds(_safe_json(path))
            except (InboxError,ValueError,TypeError,KeyError):
                status="VARIABLE_ODDS_FAILED_CLOSED"
            reports.append(("odds",status))
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
                "variable_selections_saved_this_tick":
                    counts.get("VARIABLE_PRIVATE_SELECTION_SAVED",0),
                "official_hit_at_8_all":None,
                "private_witness_verified_by_this_module":False,
                "provider_network_requests":0,
                "auto_betting":False}
