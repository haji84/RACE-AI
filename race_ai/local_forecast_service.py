"""Current-clock native inference and owner-private storage for the local app.

The trusted provider owns sources and their exact personal-use references.
No browser grants, historical clock, synthetic fallback or model promotion.
"""
from collections import Counter
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
from .private_dispatch_operation import PrivateDispatchJournal, run_saved_inputs


class LocalForecastService:
    def __init__(self, private_root, *, provider=None, clock=None):
        self.root = Path(private_root)
        self.journal = PrivateDispatchJournal(self.root / "forecast.sqlite")
        self.clock = clock or (lambda: datetime.now(native.timezone.utc))
        if provider is None:
            from .current_boat_inputs import CurrentBoatInputs
            provider = CurrentBoatInputs(self.root, clock=self.clock)
        self.provider = provider
        self.lock = threading.RLock()
        self.capabilities = getattr(provider, "capabilities", {
            sport: {"P0": sport == "boat", "P1": sport == "boat"}
            for sport in sorted(native.SPORTS)})

    def _now(self):
        return native._time(self.clock())

    def status(self):
        with self.lock:
            return dict(day_jst=self._now().astimezone(native.JST).date().isoformat(),
                capabilities=self.capabilities,
                saved_prediction_count=len(self.journal.originals()),
                source_status="CURRENT_DAY_OFFICIAL_INPUT_REQUIRED",
                unavailable_reasons={sport: "適格な実入力が未接続です。保存済み予想は引き続き読み込めます。"
                    for sport in native.SPORTS if not any(self.capabilities.get(sport, {}).values())},
                independent_freeze_verified=False, actual_purchase=False)

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
        return result

    def generate(self, sport, stage):
        with self.lock:
            if sport not in native.SPORTS or stage not in ("P0", "P1") or not self.capabilities.get(sport, {}).get(stage):
                raise ValueError("GENERATION_INPUT_UNAVAILABLE")
            collected = self.provider.collect(stage=stage, sport=sport)
            at = self._now()
            day = at.astimezone(native.JST).date().isoformat()
            rows, inputs = collected["schedule"], collected["inputs"]
            if not rows or any(row["sport"] != sport or row["stage"] != stage or
                    native._time(row["cutoff_at"]).astimezone(native.JST).date().isoformat() != day for row in rows):
                raise ValueError("CURRENT_DAY_INPUT_REQUIRED")
            admitted = {(r["source_ref"], r["source_rights_ref"])
                        for r in collected["source_references"]}
            def authorize(ref, rights, purpose):
                return (ref, rights) in admitted and purpose in ("analysis", "private_storage", "private_derived")
            operation = run_saved_inputs(self.journal, rows, inputs, at=at,
                allow_source=authorize, commit_clock=self._now, cutoff_buffer_seconds=210)
            completed = self._now()
            new = [slot for slot in operation["dispatch"]["slots"] if slot["status"] == "GENERATED_UNATTESTED"]
            receipt = dict(operation_id=operation["operation_id"],
                local_save_checked_at=operation["local_save_checked_at"],
                local_commit_completed_at=completed.isoformat(), independent_freeze_verified=False,
                new_originals=[{key: s.get(key) for key in
                    ("race_id", "stage", "model_id", "prediction_sha256", "output_sha256", "cutoff_at")}
                    for s in new])
            self._write(f"operation-{operation['operation_id']}-receipt.json", receipt)
            # Actual post-commit time is local evidence only; never backdate it.
            if completed < native._time(operation["local_save_checked_at"]) or any(completed >= native._time(s["cutoff_at"]) for s in new):
                raise ValueError("LOCAL_COMMIT_TIME_REJECTED")
            saved = self.journal.read_operation(operation["operation_id"])
            view = project_dispatch(saved, dataset_status="REAL_REPORTED")
            times = self._saved_times()
            for row in view["records"]:
                for prediction in [row["prediction"], *row["comparison_predictions"]]:
                    if prediction is None: continue
                    key = (row["race_id"], prediction["stage"], prediction["model_id"],
                           prediction["prediction_sha256"], prediction["output_sha256"])
                    if key not in times:
                        # A crash or late commit must not become an accepted
                        # on-time original merely by retrying. Preserve it in
                        # the immutable journal; never issue it again.
                        raise ValueError("SAVED_ORIGINAL_TIME_UNVERIFIED")
                    prediction["persisted_at"] = times[key]
            counts = Counter(s["status"] for s in saved["dispatch"]["slots"])
            summary = dict(generated=counts["GENERATED_UNATTESTED"], reused=counts["ORIGINAL_REUSED"],
                missing=sum(n for k,n in counts.items() if k not in ("GENERATED_UNATTESTED", "ORIGINAL_REUSED", "NOT_APPLICABLE")),
                races=len(rows), status_counts=dict(counts),
                source=collected.get("source_report", {}),
                local_commit_completed_at=completed.isoformat(), independent_freeze_verified=False)
            result = dict(day_jst=day, view=view, summary=summary)
            self._write(f"operation-{operation['operation_id']}-view.json", result)
            return result
