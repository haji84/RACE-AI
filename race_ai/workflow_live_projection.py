"""Cache exact saved Actions originals and publish a private, read-only view.

Only the supervisor calls refresh_projection. HTTP readers call read_projection,
which has no GitHub, race-source, inference or training side effects. Artifact
claims are discovery hints; every forecast still passes the existing strict
capture, restore and projection readers with its original bytes and receipt.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
import fcntl
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import zipfile

from .actions_contract import digest
from .cycle_recovery import (BRANCH, WORKFLOW, JST, _result_day, _wait,
                             artifact_pages)
from .first_receipt_continuity import first_receipt_rows, latest_result_observations
from .frozen_day_cycle import archive_json, read_p1, ts
from .private_cycle_capture import (MAX_METADATA, MAX_ZIP, _parent_handle,
                                     _read as remote_read, _write_at,
                                     capture_artifacts)
from .private_cycle_projection import project_state
from .private_cycle_restore import _json, _read, restore_manifest
from .repeated_cycle import matches
from .saved_delivery import assess_delivery

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_REPOSITORY_ID = 1416489937


def _need(condition):
    if not condition:
        raise ValueError("WORKFLOW_SAVED_PROJECTION_REJECTED")


def _wire(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def _directory(parent, name, *, create=True):
    with _parent_handle(parent) as fd:
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
        try:
            info = os.fstat(child)
            _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700)
        finally:
            os.close(child)
    return Path(parent) / name


def _base(private_root, *, create):
    root = Path(private_root).expanduser()
    _need(root.is_absolute() and ".." not in root.parts)
    with _parent_handle(root):
        pass
    return _directory(root, "workflow-projection", create=create)


def _local(root, name, limit=MAX_ZIP):
    parts = name.split("/")
    _need(all(part not in ("", ".", "..") for part in parts))
    parent = Path(root)
    for part in parts[:-1]:
        parent = _directory(parent, part, create=False)
    with _parent_handle(parent) as fd:
        info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
        _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
              and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)
    return _read(root, name, limit, [0])


def _atomic(parent, name, raw):
    with _parent_handle(parent) as fd:
        try:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                  and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)
        temporary = ".publish-" + secrets.token_hex(12)
        _write_at(fd, temporary, raw)
        try:
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass


@contextmanager
def _writer(base):
    with _parent_handle(base) as parent:
        fd = os.open("projection.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        try:
            info = os.fstat(fd)
            _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                  and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


def _kind(meta):
    run = meta.get("workflow_run", {}).get("id")
    _need(type(run) is int and run > 0)
    choices = [kind for kind, prefix in (("p0", "boat-p0-existing"),
               ("p1", "boat-national-cutoff"), ("result", "race-existing-cycle"))
               if matches(meta.get("name"), f"{prefix}-{run}")]
    _need(len(choices) == 1)
    return choices[0]


def _day(meta, raw, kind):
    run = meta["workflow_run"]["id"]
    if kind == "result":
        return _result_day(raw, meta)
    if kind == "p0":
        document, _ = archive_json(raw, meta, "forecasts.json", f"boat-p0-existing-{run}")
        value = document.get("day_jst")
    else:
        document, rows = read_p1(raw, meta)
        days = {row["race_id"][:4] + "-" + row["race_id"][4:6] + "-" + row["race_id"][6:8]
                for row in rows}
        _need(len(days) <= 1)
        value = next(iter(days), document.get("day_jst") or
                     ts(document.get("observed_at", meta["created_at"])).astimezone(JST).date().isoformat())
    _need(type(value) is str and date.fromisoformat(value).isoformat() == value)
    return value


def _receipt_matches(meta, expected):
    if expected is None:
        return
    _need(type(expected) is dict and meta["id"] == expected.get("id"))
    for key in ("digest", "created_at", "name"):
        if key in expected:
            _need(meta.get(key) == expected[key])
    if "workflow_run" in expected:
        _need(meta["workflow_run"]["id"] == expected["workflow_run"].get("id"))


def _artifact(get, base, ident, expected=None):
    _need(type(ident) is int and 0 < ident < 10**16)
    artifacts = _directory(base, "artifacts")
    folder = artifacts / str(ident)
    if os.path.lexists(folder):
        _directory(artifacts, str(ident), create=False)
        manifest = _json(_local(folder, "manifest.json", MAX_METADATA))
        _need(len(manifest.get("artifacts", [])) == 1 and
              manifest["artifacts"][0]["artifact_id"] == ident)
        # Validate cached bytes on every use; corruption never triggers a fresh
        # download that would silently hide the damaged original.
        restore_manifest(manifest, folder)
        entry = manifest["artifacts"][0]
        meta = _json(_local(folder, entry["metadata_file"], MAX_METADATA))
        raw = _local(folder, entry["zip_file"])
    else:
        meta_wire = remote_read(get, f"actions/artifacts/{ident}", MAX_METADATA)
        meta = _json(meta_wire)
        _receipt_matches(meta, expected)
        raw = remote_read(get, f"actions/artifacts/{ident}/zip", MAX_ZIP)
        day = _day(meta, raw, _kind(meta))
        responses = {f"actions/artifacts/{ident}": meta_wire,
                     f"actions/artifacts/{ident}/zip": raw}
        manifest = capture_artifacts(day, [ident], folder,
                                     github_get=lambda endpoint: responses[endpoint])
    _receipt_matches(meta, expected)
    return manifest, meta, raw


def _report(raw, meta, day):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        _need(archive.getinfo("status.json").file_size <= 16 * 1024 * 1024)
        report = _json(archive.read("status.json"))
    _need(type(report) is dict and report.get("day_jst") == day and
          str(report.get("run_id")) == str(meta["workflow_run"]["id"]) and
          report.get("report_sha256") == digest({k: v for k, v in report.items()
                                                   if k != "report_sha256"}))
    return report

def _has_saved_forecasts(wrapper):
    doc=wrapper["document"]
    if wrapper["member_name"]=="forecasts.json":
        return bool(doc.get("predictions"))
    if wrapper["member_name"]=="national.json":
        return (bool(doc.get("paired_forecasts")) or bool(doc.get("learned_pairwise_shadows")) or
                any("bundle_sha256" in row for row in doc.get("additional_official_feature_shadows",[])) or
                any("suite" in row for row in doc.get("observed_pairwise_p1_bundles",[])))
    return False


def _merged(base, day, identifiers):
    entries = []
    for ident in sorted(identifiers):
        folder = base / "artifacts" / str(ident)
        manifest = _json(_local(folder, "manifest.json", MAX_METADATA))
        _need(manifest["day_jst"] == day)
        for original in manifest["artifacts"]:
            entry = deepcopy(original)
            for key in ("metadata_file", "zip_file"):
                entry[key] = f"artifacts/{ident}/" + entry[key]
            entries.append(entry)
    states = []
    for start in range(0, len(entries), 100):
        manifest = dict(repo="haji84/RACE-AI", repository_id=_REPOSITORY_ID,
                        day_jst=day, artifacts=entries[start:start+100])
        states.append(restore_manifest(manifest, base))
    _need(bool(states))
    state = deepcopy(states[0])
    rows, observations = [], []
    state["unresolved_learned_dependencies"] = [item for part in states
                                               for item in part["unresolved_learned_dependencies"]]
    receipts, documents = {}, {}
    references=[]
    for part in states:
        for receipt in part["receipts"]:
            ident=receipt["id"]
            _need(ident not in receipts or receipts[ident]==receipt)
            receipts[ident]=receipt
        for document in part["original_documents"]:
            key=(document["artifact_id"],document["member_name"])
            _need(key not in documents or documents[key]==document)
            if key in documents:continue
            documents[key]=document
            references.append({field:deepcopy(document[field])
                               for field in ("artifact_id","member_name","member_sha256")})
    state["receipts"]=list(receipts.values())
    # All bytes above already passed strict restore against the retained ZIP
    # and its metadata. The pure view reader ignores these ancillary bodies;
    # carrying every round's cumulative result/report again exceeds its JSON
    # input bound. Keep the full distinct observation journal and exact member
    # SHA references, while native forecast documents remain byte-for-byte.
    state["original_documents"]=[value for value in documents.values()
                                 if _has_saved_forecasts(value)]
    state["original_document_references"]=references
    for part in states:
        rows.extend(part["rows"])
        observations.extend(part["observations"])
    state["rows"], state["excluded_repeats"] = first_receipt_rows(rows)
    _, state["observations"] = latest_result_observations(observations)
    state["state_sha256"] = digest({k: v for k, v in state.items() if k != "state_sha256"})
    return state


def _delivery(view, assessed_at):
    stages = {}
    for stage in ("P0", "P1"):
        predictions = [p for row in view["records"] for p in
                       [row["prediction"], *row["comparison_predictions"]]
                       if p and p["stage"] == stage]
        # Show an actual saved race, never a claimed report target/count.
        selected = max(predictions, key=lambda p: ts(p["persisted_at"]), default=None)
        stages[stage] = assess_delivery(selected["cutoff_at"] if selected else None,
            source_captured_at=selected.get("source_captured_at") if selected else None,
            generated_at=selected.get("generated_at") if selected else None,
            saved_at=selected["persisted_at"] if selected else None,
            assessed_at=assessed_at)
    return {"boat": stages}


def _pointer(base, *, day=None):
    parent = base if day is None else _directory(_directory(base, "days", create=False), day, create=False)
    pointer = _json(_local(parent, "current.json", MAX_METADATA))
    _need(type(pointer) is dict and set(pointer) ==
          {"day_jst", "revision", "view_sha256", "status_sha256", "manifest_sha256"})
    _need(type(pointer["day_jst"]) is str and
          date.fromisoformat(pointer["day_jst"]).isoformat() == pointer["day_jst"] and
          (day is None or pointer["day_jst"] == day))
    _need(all(type(pointer[key]) is str and _SHA.fullmatch(pointer[key])
              for key in ("revision", "view_sha256", "status_sha256", "manifest_sha256")))
    return pointer


def _snapshot(base, pointer):
    prefix = "days/" + pointer["day_jst"] + "/snapshots/" + pointer["revision"] + "/"
    parsed = {}
    for filename, field in (("view", "view_sha256"), ("status", "status_sha256"),
                            ("manifest", "manifest_sha256")):
        raw = _local(base, prefix + filename + ".json")
        _need(sha256(raw).hexdigest() == pointer[field])
        parsed[filename] = _json(raw)
    _need(parsed["status"]["revision"] == pointer["revision"] and
          parsed["status"]["day_jst"] == pointer["day_jst"] and
          parsed["view"]["event_date_jst"] == pointer["day_jst"])
    return parsed


def read_projection(private_root, *, day=None):
    """Read a pinned published snapshot only; no API or source calls occur."""
    if day is not None:
        _need(type(day) is str and date.fromisoformat(day).isoformat() == day)
    base = _base(private_root, create=False)
    parsed = _snapshot(base, _pointer(base, day=day))
    return {"status": parsed["status"], "view": parsed["view"]}


def refresh_projection(github_api, private_root, run_id, *, dataset_status="REAL_REPORTED"):
    """Capture newly saved originals once, validate, then atomically publish.

The API callback receives repository-relative actions/... paths and returns
bytes. Every day has isolated immutable snapshots; current.json is only a
pointer. Failed capture/validation leaves the previous published view intact.
"""
    _need(callable(github_api) and type(run_id) is int and run_id > 0 and
          dataset_status in ("REAL_REPORTED", "SYNTHETIC_ONLY"))
    base = _base(private_root, create=True)
    with _writer(base):
        run = _json(remote_read(github_api, f"actions/runs/{run_id}", MAX_METADATA))
        _need(run.get("id") == run_id and run.get("workflow_id") == WORKFLOW and
              run.get("head_branch") == BRANCH)
        listed = artifact_pages(github_api, run_id)
        relevant = [row for row in listed if any(matches(row.get("name"), f"{prefix}-{run_id}")
                    for prefix in ("boat-p0-existing", "boat-national-cutoff", "race-existing-cycle"))]
        captured = {}
        for row in relevant:
            item = _artifact(github_api, base, row["id"], row)
            _need(item[1]["workflow_run"]["id"] == run_id)
            captured[row["id"]] = item
        results = [item for item in captured.values() if _kind(item[1]) == "result"]
        _need(bool(results))
        _, result_meta, result_raw = max(results, key=lambda item: (ts(item[1]["created_at"]), item[1]["id"]))
        day = _result_day(result_raw, result_meta)
        report = _report(result_raw, result_meta, day)
        dependencies = report.get("first_forecast_artifacts", [])
        _need(type(dependencies) is list and len(dependencies) <= 2000)
        for receipt in dependencies:
            _need(type(receipt) is dict and type(receipt.get("id")) is int and
                  _kind(receipt) in ("p0", "p1"))
            captured[receipt["id"]] = _artifact(github_api, base, receipt["id"], receipt)
        identifiers = {ident for ident, item in captured.items() if item[0]["day_jst"] == day}
        try:
            prior = _snapshot(base, _pointer(base, day=day))
        except FileNotFoundError:
            pass
        else:
            _need(prior["manifest"]["day_jst"] == day and
                  type(prior["manifest"]["artifact_ids"]) is list)
            identifiers.update(prior["manifest"]["artifact_ids"])
            for ident in prior["manifest"]["artifact_ids"]:
                _need(type(ident) is int and ident > 0 and
                      os.path.lexists(base / "artifacts" / str(ident)))
                if ident not in captured:
                    captured[ident] = _artifact(github_api, base, ident)
            # Delayed polls of an older run cannot roll source waits or their
            # assessment timestamps back after a newer independent result.
            latest = max((item for item in captured.values()
                          if item[0]["day_jst"] == day and _kind(item[1]) == "result"),
                         key=lambda item: (ts(item[1]["created_at"]), item[1]["id"]))
            result_meta, result_raw = latest[1:]
            report = _report(result_raw, result_meta, day)
        state = _merged(base, day, identifiers)
        view = project_state(state, dataset_status=dataset_status)
        view["original_document_references"]=deepcopy(state["original_document_references"])
        forecasts = [p for row in view["records"] for p in
                     [row["prediction"], *row["comparison_predictions"]] if p]
        session = report.get("bounded_repeat_session", {})
        _need(type(session) is dict)
        status = dict(day_jst=day, counts=dict(races=len(view["records"]), forecasts=len(forecasts),
            p0_forecasts=sum(p["stage"] == "P0" for p in forecasts),
            p1_forecasts=sum(p["stage"] == "P1" for p in forecasts),
            result_observations=sum(len(row["result_observations"]) for row in view["records"]),
            result_races=sum(row["result"] is not None for row in view["records"])),
            source_wait=_wait(session.get("source_wait")),
            delivery=_delivery(view, result_meta["created_at"]))
        manifest = dict(day_jst=day, artifact_ids=sorted(identifiers))
        revision = digest(dict(view=view, status=status, manifest=manifest))
        status["revision"] = revision
        days = _directory(base, "days")
        day_root = _directory(days, day)
        snapshots = _directory(day_root, "snapshots")
        snapshot = snapshots / revision
        wires = {"view": _wire(view), "status": _wire(status), "manifest": _wire(manifest)}
        if os.path.lexists(snapshot):
            _directory(snapshots, revision, create=False)
            _need(all(_local(snapshot, name + ".json") == raw for name, raw in wires.items()))
        else:
            _directory(snapshots, revision)
            with _parent_handle(snapshot) as fd:
                for name, raw in wires.items():
                    _write_at(fd, name + ".json", raw)
                os.fsync(fd)
        pointer = dict(day_jst=day, revision=revision,
                       **{name + "_sha256": sha256(raw).hexdigest() for name, raw in wires.items()})
        _atomic(day_root, "current.json", _wire(pointer))
        try:
            current_day = _pointer(base)["day_jst"]
        except FileNotFoundError:
            current_day = day
        if current_day <= day:
            _atomic(base, "current.json", _wire(pointer))
        return status
