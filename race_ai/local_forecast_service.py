"""Current-clock native inference and owner-private storage for the local app.

The trusted provider owns sources and their exact personal-use references.
No browser grants, historical clock, synthetic fallback or model promotion.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import stat
import threading

from . import existing_model_dispatch as native
from .dispatch_product_projection import project_dispatch
from .private_cycle_capture import _parent_handle
from .private_dispatch_operation import PrivateDispatchJournal, run_saved_inputs, _unwire


class LocalForecastService:
    automatic_supported = True

    def __init__(self, private_root, *, provider=None, clock=None, workflow_projection_root=None):
        self.root = Path(private_root)
        self.journal = PrivateDispatchJournal(self.root / "forecast.sqlite")
        self.clock = clock or (lambda: datetime.now(native.timezone.utc))
        self.workflow_projection_root = Path(workflow_projection_root) if workflow_projection_root is not None else None
        self.automatic_supported = self.workflow_projection_root is None
        if provider is None and self.workflow_projection_root is None:
            from .current_boat_inputs import CurrentBoatInputs
            provider = CurrentBoatInputs(self.root, clock=self.clock)
        self.provider = provider
        self.lock = threading.RLock()
        self._latest_cache = {}
        self._last_collection = {}
        self._receipt_evidence = {}
        self._automatic_schedules = {}
        self.capabilities = getattr(provider, "capabilities", {
            sport: {"P0": sport == "boat", "P1": sport == "boat"}
            for sport in sorted(native.SPORTS)})

    def _now(self):
        return native._time(self.clock())

    def status(self):
        with self.lock:
            automation = getattr(self, "automation", None)
            auto = automation.status() if automation is not None else {"enabled": False, "state": "DISABLED"}
            revisions = {}
            delivery = {}
            # Read native saved operations only. Status never calls a provider
            # or creates an operation, including while automatic work is stopped.
            for sport, stages in self.capabilities.items():
                revisions[sport] = {}
                delivery[sport] = {}
                for stage, supported in stages.items():
                    if not supported: continue
                    latest = self.latest(sport, stage)
                    revisions[sport][stage] = latest.get("revision")
                    delivery[sport][stage] = self._delivery(latest, sport, stage, auto)
            with self.journal.connect() as db:
                count = db.execute("SELECT COUNT(*) FROM dispatch_originals").fetchone()[0]
            if self.workflow_projection_root is not None:
                count = sum(self.latest(s, stage).get("summary", {}).get("reused", 0)
                    for s, stages in self.capabilities.items() for stage, supported in stages.items() if supported)
            return dict(day_jst=self._now().astimezone(native.JST).date().isoformat(),
                capabilities=self.capabilities,
                saved_prediction_count=count, auto=auto, latest_revisions=revisions, delivery=delivery,
                source_status="CURRENT_DAY_OFFICIAL_INPUT_REQUIRED",
                unavailable_reasons={sport: "適格な実入力が未接続です。保存済み予想は引き続き読み込めます。"
                    for sport in native.SPORTS if not any(self.capabilities.get(sport, {}).values())},
                independent_freeze_verified=False, actual_purchase=False)

    def automatic_source_status(self, day_jst=None):
        status = getattr(self.provider, "status", None)
        if not callable(status):
            raise ValueError("SOURCE_BUDGET_STATUS_UNAVAILABLE")
        value = status(day_jst=day_jst) if day_jst is not None else status()
        if (type(value) is not dict or type(value.get("requests_used")) is not int or
                value["requests_used"] < 0 or value.get("day_jst") != (day_jst or self._now().astimezone(native.JST).date().isoformat())):
            raise ValueError("SOURCE_BUDGET_STATUS_UNAVAILABLE")
        return value

    def generate_auto(self, sport, stage):
        return self.generate(sport, stage, _automatic=True)

    def _reuse_automatic_operation(self, sport, stage, rows, inputs, source):
        """Avoid another journal batch only when supplied models are frozen.

        A newly connected model or an explicit version pin still reaches the
        native dispatcher. Missing inputs remain visible in the saved matrix.
        """
        previous = self._automatic_schedules.get((sport, stage))
        if previous is None or previous["schedule"] != rows:
            return None
        saved = {}
        for original in self.journal.originals():
            key = original["race_id"], original["stage"], original["model_id"]
            saved.setdefault(key, set()).add(original.get("model_version"))
        groups = dict(native.GROUPS)
        applicable = {item["model_id"] for item in native.catalog() if sport in item["applicable_sports"]}
        for row in rows:
            supplied = inputs.get(row["race_id"], {}).get(stage, {})
            if not isinstance(supplied, dict) or set(supplied)-set(groups):
                return None
            # The learned family consumes the shared payload through a native
            # alias. Let its dispatcher recheck every supplied artifact.
            shared = supplied.get("shared")
            if isinstance(shared, dict) and "learned_model" in shared:
                return None
            pins = row.get("model_versions", {})
            for group in supplied:
                for model in set(groups[group]) & applicable:
                    versions = saved.get((row["race_id"], stage, model), set())
                    if not versions or model in pins and pins[model] not in versions:
                        return None
        latest = self.latest(sport, stage)
        if not latest.get("available") or latest.get("revision") != previous["revision"]:
            return None
        count = sum(1 for row in latest["view"]["records"] for prediction in
                    [row["prediction"], *row["comparison_predictions"]] if prediction is not None)
        latest["summary"].update(generated=0, reused=count, source=source, operation_reused=True)
        states = latest["summary"].get("status_counts", {})
        states.pop("GENERATED_UNATTESTED", None)
        states["ORIGINAL_REUSED"] = count
        return latest

    def _automatic_clock(self):
        now = self._now()
        automation = getattr(self, "automation", None)
        if automation is not None:
            state = automation.status()
            if state.get("state") in ("STOPPING", "STOPPED", "REVIEW_WAIT", "PAUSED"):
                raise ValueError("AUTOMATIC_SESSION_END")
            stop_at = state.get("stop_at")
            if stop_at is not None and now >= native._time(stop_at):
                raise ValueError("AUTOMATIC_SESSION_END")
            if state.get("day_jst") is not None and state["day_jst"] != now.astimezone(native.JST).date().isoformat():
                raise ValueError("DAY_HANDOFF")
        return now

    def _delivery(self, latest, sport, stage, auto):
        from .saved_delivery import assess_delivery
        now = self._now()
        rows = (latest.get("view") or {}).get("records", [])
        future = [r for r in rows if r.get("cutoff_at") and native._time(r["cutoff_at"]) > now]
        selected = min(future, key=lambda r:native._time(r["cutoff_at"])) if future else None
        prediction = selected.get("prediction") if selected else None
        key = ((selected or {}).get("race_id"), stage, (prediction or {}).get("model_id"),
               (prediction or {}).get("prediction_sha256"), (prediction or {}).get("output_sha256"))
        measured = self._receipt_evidence.get(key, {})
        value = assess_delivery(selected.get("cutoff_at") if selected else None,
            source_captured_at=measured.get("source_captured_at") or (prediction or {}).get("source_captured_at"),
            generated_at=measured.get("generation_finished_at") or (prediction or {}).get("generated_at"),
            saved_at=(prediction or {}).get("persisted_at"), assessed_at=now.isoformat())
        value["assessed_at"] = now.isoformat()
        if prediction is None:
            if auto.get("state") in ("SOURCE_WAIT", "REVIEW_WAIT"):
                value.update(state="SOURCE_WAIT", reason=auto.get("waiting_reason") or "SOURCE_CONFIRMATION_PENDING")
            elif selected is None:
                value.update(state="SCHEDULE_WAIT", reason="CURRENT_SCHEDULE_PENDING")
            elif now < native._time(value["target_open_at"]):
                value.update(state="WAITING_TARGET", reason="TARGET_WINDOW_NOT_OPEN")
            elif now > native._time(value["target_due_at"]):
                value.update(state="LATE_INPUT", reason="INPUT_PENDING_AFTER_TARGET")
            else:
                value.update(state="RUNNING", reason="TARGET_WINDOW_OPEN")
        return value

    def _workflow_latest(self, sport, stage, day):
        from .workflow_live_projection import read_projection
        try:
            snapshot = read_projection(self.workflow_projection_root, day=day)
        except (FileNotFoundError, ValueError):
            return dict(available=False, revision=None, day_jst=day,reason="SAVED_WORKFLOW_VIEW_PENDING")
        if not snapshot or snapshot["status"]["day_jst"] != day:
            return dict(available=False, revision=None, day_jst=day)
        view = deepcopy(snapshot["view"])
        records = []
        for row in view["records"]:
            if row["sport"] != sport: continue
            predictions = [p for p in [row.get("prediction"), *row.get("comparison_predictions", [])]
                           if p and p["stage"] == stage]
            row["prediction"] = predictions[0] if predictions else None
            row["comparison_predictions"] = predictions[1:]
            records.append(row)
        view["records"] = records
        count = sum((1 if r["prediction"] else 0)+len(r["comparison_predictions"]) for r in records)
        revision_inputs = dict(source=snapshot["status"]["revision"], sport=sport, stage=stage)
        if count and sport == "boat":
            from .boat_context_store import read_contexts, merge_contexts, attach_contexts
            contexts = []
            for root in dict.fromkeys((self.root, self.workflow_projection_root)):
                try:
                    contexts.append(read_contexts(root, day=day))
                except (OSError, ValueError):
                    # Optional observations never prevent saved originals from
                    # loading, and a damaged sidecar never becomes model input.
                    continue
            context_revision = attach_contexts(view, merge_contexts(*contexts))
            if context_revision is not None:
                revision_inputs["boat_observation_context"] = context_revision
        return dict(available=count>0, revision=native.digest(revision_inputs) if count else None,
            day_jst=day, view=view if count else None, source_kind="GITHUB_AUTHENTICATED_ORIGINALS",
            summary=dict(generated=0,reused=count,missing=None,coverage_known=False,races=len(records)))

    def _write(self, name, value):
        raw = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode()
        with _parent_handle(self.root) as parent:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(parent)

    def _saved_times(self):
        result = {}
        evidence = {}
        with _parent_handle(self.root) as parent:
            for name in os.listdir(parent):
                if not re.fullmatch(r"operation-[1-9][0-9]*-receipt\.json", name):
                    continue
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                            info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 4*1024*1024):
                        raise ValueError("PRIVATE_RECEIPT_REJECTED")
                    receipt = json.load(stream)
                completed = native._time(receipt["local_commit_completed_at"])
                if receipt.get("independent_freeze_verified") is not False or completed < native._time(receipt["local_save_checked_at"]):
                    raise ValueError("PRIVATE_RECEIPT_REJECTED")
                for item in receipt["new_originals"]:
                    key = (item["race_id"], item["stage"], item["model_id"], item["prediction_sha256"], item["output_sha256"])
                    if completed >= native._time(item["cutoff_at"]):
                        continue
                    if key not in result or completed < native._time(result[key]):
                        result[key] = completed.isoformat()
                        evidence[key] = dict(source_captured_at=item.get("source_captured_at"),
                            generation_finished_at=receipt.get("local_generation_finished_at"))
        self._receipt_evidence = evidence
        return result

    def _project_saved(self, operation):
        view = project_dispatch(operation, dataset_status="REAL_REPORTED")
        times = self._saved_times()
        for row in view["records"]:
            for prediction in [row["prediction"], *row["comparison_predictions"]]:
                if prediction is None: continue
                key = (row["race_id"], prediction["stage"], prediction["model_id"],
                       prediction["prediction_sha256"], prediction["output_sha256"])
                if key not in times:
                    raise ValueError("SAVED_ORIGINAL_TIME_UNVERIFIED")
                prediction["persisted_at"] = times[key]
        return view

    @staticmethod
    def _revision(view):
        stable = []
        for row in view["records"]:
            predictions = [{k:v for k,v in p.items() if k not in ("dispatch_status", "dispatch_reason")}
                for p in [row["prediction"], *row["comparison_predictions"]] if p is not None]
            stable.append(dict(race_id=row["race_id"], cutoff_at=row["cutoff_at"],
                               stages=row["scheduled_stages"], predictions=predictions))
        return native.digest(dict(day=view["event_date_jst"], records=stable))

    def latest(self, sport, stage):
        """Return checked current-day native originals; perform no inference/I/O to sources.

        Derived operation-*-view.json files are never trusted as an index or
        source of forecasts. Empty P1 updates remain separate from P0.
        """
        with self.lock:
            if sport not in native.SPORTS or stage not in ("P0", "P1"):
                raise ValueError("SAVED_VIEW_SELECTOR_REJECTED")
            day = self._now().astimezone(native.JST).date().isoformat()
            if self.workflow_projection_root is not None:
                return self._workflow_latest(sport, stage, day)
            empty = dict(available=False, revision=None, day_jst=day)
            with _parent_handle(self.root) as parent:
                names = [self.journal.path.name] + sorted(name for name in os.listdir(parent)
                    if re.fullmatch(r"operation-[1-9][0-9]*-receipt\.json", name))
                signature = []
                for name in names:
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                            info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600):
                        raise ValueError("PRIVATE_SAVED_VIEW_REJECTED")
                    signature.append((name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns))
            key = sport, stage, day
            signature = tuple(signature)
            cached = self._latest_cache.get(key)
            if cached is not None and cached[0] == signature:
                return deepcopy(cached[1])
            def keep(value):
                self._latest_cache[key] = signature, deepcopy(value)
                return value
            with self.journal.connect() as db:
                metadata = list(db.execute("SELECT operation_id,wire FROM dispatch_operations ORDER BY operation_id DESC LIMIT 20000"))
            for operation_id, raw_metadata in metadata:
                rows = _unwire(raw_metadata)["dispatch"]["schedule"]
                if not rows or not all(r["sport"] == sport and r["stage"] == stage and
                        native._time(r["cutoff_at"]).astimezone(native.JST).date().isoformat() == day for r in rows):
                    continue
                operation = self.journal.read_operation(operation_id)
                try:
                    view = self._project_saved(operation)
                except ValueError:
                    return keep({**empty, "reason": "SAVED_ORIGINAL_TIME_UNVERIFIED"})
                counts = Counter(s["status"] for s in operation["dispatch"]["slots"])
                has_predictions = any(r["prediction"] is not None for r in view["records"])
                return keep(dict(available=has_predictions, revision=self._revision(view) if has_predictions else None,
                    day_jst=day, view=view if has_predictions else None,
                    summary=dict(generated=counts["GENERATED_UNATTESTED"], reused=counts["ORIGINAL_REUSED"],
                        missing=sum(n for k,n in counts.items() if k not in ("GENERATED_UNATTESTED", "ORIGINAL_REUSED", "NOT_APPLICABLE")),
                        races=len(rows), status_counts=dict(counts), independent_freeze_verified=False)))
            return keep(empty)

    def generate(self, sport, stage, *, _automatic=False):
        with self.lock:
            if self.workflow_projection_root is not None:
                raise ValueError("EXTERNAL_WORKFLOW_MANAGED")
            if sport not in native.SPORTS or stage not in ("P0", "P1") or not self.capabilities.get(sport, {}).get(stage):
                raise ValueError("GENERATION_INPUT_UNAVAILABLE")
            options = dict(stage=stage, sport=sport)
            if _automatic:
                self._automatic_clock()
                options["due_only"] = True
                options.update(refresh_discovery=True, preferred_window=True,
                               automatic_guard=self._automatic_clock)
                automation = getattr(self, "automation", None)
                if automation is not None:
                    options["automatic_stop_at"] = automation.status()["stop_at"]
            collected = self.provider.collect(**options)
            at = self._automatic_clock() if _automatic else self._now()
            day = at.astimezone(native.JST).date().isoformat()
            rows, inputs = collected["schedule"], collected["inputs"]
            self._last_collection[(sport, stage)] = dict(source=collected.get("source_report", {}))
            if not rows and _automatic:
                return dict(day_jst=day, view=None, revision=None,
                    summary=dict(generated=0,reused=0,missing=0,races=0,
                                 source=collected.get("source_report", {}),waiting_reason="SCHEDULE_NOT_AVAILABLE"))
            if not rows or any(row["sport"] != sport or row["stage"] != stage or
                    native._time(row["cutoff_at"]).astimezone(native.JST).date().isoformat() != day for row in rows):
                raise ValueError("CURRENT_DAY_INPUT_REQUIRED")
            if _automatic:
                reused = self._reuse_automatic_operation(sport, stage, rows, inputs,
                    collected.get("source_report", {}))
                if reused is not None:
                    self._automatic_clock()
                    return reused
            admitted = {(r["source_ref"], r["source_rights_ref"])
                        for r in collected["source_references"]}
            def authorize(ref, rights, purpose):
                return (ref, rights) in admitted and purpose in ("analysis", "private_storage", "private_derived")
            operation = run_saved_inputs(self.journal, rows, inputs, at=at,
                allow_source=authorize, commit_clock=self._automatic_clock if _automatic else self._now,
                cutoff_buffer_seconds=210)
            completed = self._now()
            captures = {}
            def capture_times(value):
                found=[]
                if isinstance(value, dict):
                    for key,item in value.items():
                        if key in ("captured_at", "observed_at") and isinstance(item,str):
                            try: found.append(native._time(item))
                            except ValueError: pass
                        else: found.extend(capture_times(item))
                elif isinstance(value,list):
                    for item in value:found.extend(capture_times(item))
                return found
            for row in rows:
                times=capture_times(inputs.get(row["race_id"], {}))
                if times: captures[row["race_id"]]=max(times).isoformat()
            new = [slot for slot in operation["dispatch"]["slots"] if slot["status"] == "GENERATED_UNATTESTED"]
            receipt = dict(operation_id=operation["operation_id"],
                local_save_checked_at=operation["local_save_checked_at"],
                local_generation_finished_at=operation["local_save_checked_at"],
                local_commit_completed_at=completed.isoformat(), independent_freeze_verified=False,
                new_originals=[dict({key: s.get(key) for key in
                    ("race_id", "stage", "model_id", "prediction_sha256", "output_sha256", "cutoff_at")}
                    , source_captured_at=captures.get(s["race_id"])) for s in new])
            self._write(f"operation-{operation['operation_id']}-receipt.json", receipt)
            # Actual post-commit time is local evidence only; never backdate it.
            if completed < native._time(operation["local_save_checked_at"]) or any(completed >= native._time(s["cutoff_at"]) for s in new):
                raise ValueError("LOCAL_COMMIT_TIME_REJECTED")
            saved = self.journal.read_operation(operation["operation_id"])
            view = self._project_saved(saved)
            self._last_collection[(sport,stage)]["evidence"] = {rid:dict(source_captured_at=stamp,
                generation_finished_at=operation["local_save_checked_at"]) for rid,stamp in captures.items()}
            counts = Counter(s["status"] for s in saved["dispatch"]["slots"])
            summary = dict(generated=counts["GENERATED_UNATTESTED"], reused=counts["ORIGINAL_REUSED"],
                missing=sum(n for k,n in counts.items() if k not in ("GENERATED_UNATTESTED", "ORIGINAL_REUSED", "NOT_APPLICABLE")),
                races=len(rows), status_counts=dict(counts),
                source=collected.get("source_report", {}),
                local_commit_completed_at=completed.isoformat(), independent_freeze_verified=False)
            result = dict(day_jst=day, view=view, summary=summary, revision=self._revision(view))
            self._write(f"operation-{operation['operation_id']}-view.json", result)
            if _automatic:
                self._automatic_schedules[(sport, stage)] = dict(schedule=deepcopy(rows), revision=result["revision"])
            return result
