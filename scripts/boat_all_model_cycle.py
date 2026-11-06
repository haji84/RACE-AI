"""Actions-only encrypted all-model preparation, inference and strict readback.

Uses the existing GitHub credential context and pure model engine. No official
source GETs, root-key export, fitting, workflow controls or plaintext uploads.
"""
import argparse
import base64
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from race_ai import boat_all_model_cycle as engine
from race_ai import boat_model_runtime as runtime
from race_ai import boat_all_model_store as store
from race_ai import saved_view_feed as feed
from race_ai.actions_contract import digest
from race_ai.boat_history_store import wire
from race_ai.boat_pdca_recipient import _json
from race_ai.boat_pdca_state import state_key
from race_ai.boat_private_original_archive import open_original_zip
from race_ai.existing_model_coverage import catalog
from race_ai.frozen_day_cycle import official_id
from race_ai.repeated_cycle import artifact_name as baseline_name, matches
from scripts.boat_history_collect import private_root, save
from scripts.boat_saved_view_feed import git_auth

REPO = "haji84/RACE-AI"
REPO_ID = "1416489937"
READY_SCHEMA = "RACE_AI_BOAT_ALL_MODEL_RUNTIME_READY_V1"
READBACK_SCHEMA = "RACE_AI_BOAT_ALL_MODEL_READBACK_V1"
KNOWN = {s["model_id"] for s in catalog()}
SHA = re.compile(r"[a-f0-9]{64}\Z")
HEAD = re.compile(r"[a-f0-9]{40}\Z")


class CycleError(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise CycleError("ALL_MODEL_CLI_"+reason)


def utc_now():
    return datetime.now(timezone.utc)


def _time(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    need(parsed.utcoffset() is not None, "AWARE_CLOCK_REQUIRED")
    return parsed


def _wire(value):
    return (wire(value)+"\n").encode()


def _environment():
    need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == REPO
         and os.environ.get("GITHUB_REPOSITORY_ID") == REPO_ID, "EXISTING_ACTIONS_REPOSITORY_REQUIRED")
    head = os.environ.get("GITHUB_SHA", ""); run = os.environ.get("GITHUB_RUN_ID", "")
    need(HEAD.fullmatch(head) and re.fullmatch(r"[1-9][0-9]{0,19}", run), "CURRENT_RUN_HEAD_REQUIRED")
    temp = Path(os.environ.get("RUNNER_TEMP", ""))
    need(temp.is_absolute() and temp.is_dir() and not any(p.is_symlink() for p in (temp, *temp.parents))
         and not temp.resolve().is_relative_to(ROOT.resolve()) and not any((p/".git").exists() for p in (temp, *temp.parents)),
         "PRIVATE_RUNNER_TEMP_REQUIRED")
    return dict(head=head, run_id=run, temp=temp)


def _owner():
    _environment()
    return state_key("production")


def _read(path, limit, *, private=False):
    path = Path(path)
    need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
         and 0 < path.stat().st_size <= limit and (not private or not path.stat().st_mode & 0o077), "FILE_BOUND_OR_PERMISSION_INVALID")
    with path.open("rb") as stream:
        raw = stream.read(limit+1)
    need(len(raw) <= limit, "FILE_BOUND_OR_PERMISSION_INVALID")
    return raw


def _file_hash(path, limit):
    path = Path(path)
    need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
         and not path.stat().st_mode & 0o077 and 0 < path.stat().st_size <= limit, "PRIVATE_FILE_INVALID")
    digestor = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024*1024):
            digestor.update(block)
    return digestor.hexdigest(), path.stat().st_size


def gh(path):
    need(re.fullmatch(r"actions/(?:artifacts/[1-9][0-9]*(?:/zip)?|runs/[1-9][0-9]*)", path), "GITHUB_ROUTE_INVALID")
    result = subprocess.run(["gh", "api", "repos/"+REPO+"/"+path], capture_output=True, timeout=90)
    need(result.returncode == 0 and len(result.stdout) <= 40*1024*1024, "GITHUB_READ_FAILED")
    return result.stdout


def artifact_name(run_id, round_no):
    return f"boat-all-model-forecasts-{run_id}-r{round_no}"


def _round(value):
    need(type(value) is int and 0 <= value <= 999999, "ROUND_INVALID")
    return value


def _pointer():
    raw = _read(ROOT/runtime.INPUT_PATH, 64*1024)
    pointer = _json(raw, 64*1024)
    runtime._validate_pointer(pointer)
    return pointer, sha256(raw).hexdigest()


def _cache(pointer, pin, env, *, current=True):
    folder = env["temp"]/"boat-all-model-runtime"
    marker = _json(_read(folder/"runtime-ready.json", 128*1024, private=True), 128*1024)
    need(marker.get("schema") == READY_SCHEMA and marker.get("ready") is True
         and marker.get("pointer_sha256") == pin and marker.get("cipher_sha256") == pointer["cipher_sha256"]
         and all(marker.get(k) is True for k in ("verified_runtime", "history_identity_verified", "owner_reviewed")), "RUNTIME_CACHE_PIN_INVALID")
    if current:
        need(marker.get("run_id") == env["run_id"] and marker.get("source_code_commit") == env["head"], "RUNTIME_CACHE_RUN_HEAD_MISMATCH")
    need(set(marker.get("files", {})) == set(pointer["header"]["files"]), "RUNTIME_CACHE_FILES_MISMATCH")
    for name, expected in pointer["header"]["files"].items():
        need(name in runtime.FILE_LIMITS and marker["files"][name].get("path") == str(folder/name), "RUNTIME_CACHE_PATH_INVALID")
        actual_sha, actual_size = _file_hash(folder/name, runtime.FILE_LIMITS[name])
        need(actual_sha == expected["sha256"] and actual_size == expected["size"]
             and marker["files"][name] == dict(path=str(folder/name), **expected), "RUNTIME_CACHE_FILE_HASH_MISMATCH")
    need(marker["metadata_sha256"] == pointer["header"]["files"]["metadata.json"]["sha256"], "RUNTIME_METADATA_HASH_MISMATCH")
    if current:
        for name, field in (("issued-models.json", "issued_models_sha256"), ("issued-p0-models.json", "issued_p0_models_sha256")):
            need(sha256(_read(folder/name, 1024*1024, private=True)).hexdigest() == marker[field], "ISSUED_MATRIX_HASH_MISMATCH")
        expected_files = {name: str(folder/name) for name in pointer["header"]["files"]}
        expected_files.update(verified_runtime=True, history_identity_verified=True, owner_reviewed=True,
                              source_code_commit=env["head"], run_id=env["run_id"])
        need(marker.get("runtime_files") == expected_files, "RUNTIME_CACHE_PATH_INVALID")
    return marker


def restore_ready():
    """Return strictly checked current Actions runtime paths without transport."""
    env = _environment(); key = _owner(); pointer, pin = _pointer()
    public = runtime._private(key).public_key().public_bytes_raw()
    need(sha256(public).hexdigest() == pointer["header"]["recipient_key_id"], "OWNER_RECIPIENT_MISMATCH")
    return _cache(pointer, pin, env)


def _existing_view(key):
    config = _json(_read(ROOT/"audit/state/boat-saved-view-input.json", 8192), 8192)
    need(config.get("schema") == "RACE_AI_SAVED_VIEW_INPUT_V1", "SAVED_VIEW_CONFIG_INVALID")
    raw = base64.b64decode(config["bootstrap"], validate=True)
    need(sha256(raw).hexdigest() == config["bootstrap_sha256"], "SAVED_VIEW_BOOTSTRAP_HASH_INVALID")
    bootstrap = feed.open_bootstrap(raw, key=key)
    return feed.current_view(feed.FeedRepository(ROOT), bootstrap)[3]


def _inventory(view, result):
    if isinstance(view, list):
        for item in view: _inventory(item, result)
        return
    need(isinstance(view, dict) and isinstance(view.get("records"), list), "SAVED_VIEW_RECORDS_INVALID")
    for row in view["records"]:
        rid = row["race_id"]
        if isinstance(rid, str) and re.fullmatch(r"\d{8}-(?:0[1-9]|1\d|2[0-4])-(?:0[1-9]|1[0-2])", rid):
            datetime.strptime(rid[:8], "%Y%m%d")
        else:
            rid = official_id(rid)
        for prediction in [row.get("prediction"), *row.get("comparison_predictions", [])]:
            if prediction is None: continue
            stage = prediction.get("stage", row.get("stage")); mid = prediction.get("model_id")
            if stage in result and mid in KNOWN:
                result[stage].setdefault(rid, set()).add(mid)


def prepare_runtime(*, round_no=0):
    """Restore/recheck immutable inputs and refresh stage-specific issued maps."""
    _round(round_no); env = _environment(); key = _owner(); pointer, pin = _pointer()
    folder = env["temp"]/"boat-all-model-runtime"
    git_auth()
    if (folder/"runtime-ready.json").exists():
        _cache(pointer, pin, env, current=False)
        public = runtime._private(key).public_key().public_bytes_raw()
        need(sha256(public).hexdigest() == pointer["header"]["recipient_key_id"], "OWNER_RECIPIENT_MISMATCH")
    else:
        runtime.restore_runtime(pointer, ROOT, folder, key=key)
    maps = {"P0": {}, "P1": {}}
    _inventory(_existing_view(key), maps)
    if (folder/"native-view.json").exists():
        _inventory(_json(_read(folder/"native-view.json", runtime.FILE_LIMITS["native-view.json"], private=True), runtime.FILE_LIMITS["native-view.json"]), maps)
    pending = env["temp"]/"boat-all-model-readback.json"
    if pending.exists():
        ref = _json(_read(pending, 128*1024, private=True), 128*1024)
        if ref.get("schema") == READBACK_SCHEMA and ref.get("receipt", {}).get("independently_verified") is True:
            path = Path(ref["private_view_path"])
            need(path.parent == env["temp"]/"boat-all-model-views", "PRIVATE_VIEW_PATH_INVALID")
            raw = _read(path, store.MAX_PLAIN, private=True)
            need(sha256(raw).hexdigest() == ref["view_sha256"], "PRIVATE_VIEW_HASH_MISMATCH")
            _inventory(_json(raw, store.MAX_PLAIN), maps)
    hashes = {}
    for stage, name in (("P1", "issued-models.json"), ("P0", "issued-p0-models.json")):
        raw = _wire({rid: sorted(mids) for rid, mids in sorted(maps[stage].items())})
        save(folder/name, raw, replace=True); hashes[stage] = sha256(raw).hexdigest()
    files = {name: str(folder/name) for name in pointer["header"]["files"]}
    files.update(verified_runtime=True, history_identity_verified=True, owner_reviewed=True,
                 source_code_commit=env["head"], run_id=env["run_id"])
    marker = dict(schema=READY_SCHEMA, ready=True, round_no=round_no, run_id=env["run_id"], source_code_commit=env["head"],
        verified_runtime=True, history_identity_verified=True, owner_reviewed=True, pointer_sha256=pin,
        cipher_sha256=pointer["cipher_sha256"], metadata_sha256=pointer["header"]["files"]["metadata.json"]["sha256"],
        files={name: dict(path=str(folder/name), **entry) for name, entry in pointer["header"]["files"].items()}, runtime_files=files,
        issued_models_path=str(folder/"issued-models.json"), issued_p0_models_path=str(folder/"issued-p0-models.json"),
        issued_models_sha256=hashes["P1"], issued_p0_models_sha256=hashes["P0"])
    save(folder/"runtime-ready.json", _wire(marker), replace=True)
    return marker


def _artifact(ident, *, member, expected_name, expected_run, expected_head):
    need(type(ident) is int and ident > 0, "ARTIFACT_ID_INVALID")
    meta = _json(gh(f"actions/artifacts/{ident}"), 128*1024); run = meta.get("workflow_run", {})
    need(meta.get("id") == ident and meta.get("expired") is False and matches(meta.get("name"), expected_name)
         and run.get("repository_id") == int(REPO_ID) and run.get("head_repository_id") == int(REPO_ID)
         and str(run.get("id")) == str(expected_run) and run.get("head_sha") == expected_head
         and HEAD.fullmatch(expected_head), "ARTIFACT_IDENTITY_MISMATCH")
    now = utc_now()
    need(_time(meta["created_at"]) <= now < _time(meta["expires_at"]), "ARTIFACT_CLOCK_INVALID")
    info = _json(gh(f"actions/runs/{run['id']}"), 256*1024)
    need(info.get("id") == run["id"] and info.get("head_sha") == expected_head
         and info.get("repository", {}).get("id") == int(REPO_ID) and info["repository"].get("full_name") == REPO
         and info.get("head_repository", {}).get("id") == int(REPO_ID)
         and info["head_repository"].get("full_name") == REPO, "ARTIFACT_RUN_MISMATCH")
    archive = gh(f"actions/artifacts/{ident}/zip")
    need(len(archive) <= 40*1024*1024 and meta.get("size_in_bytes") == len(archive)
         and meta.get("digest") == "sha256:"+sha256(archive).hexdigest(), "ARTIFACT_ARCHIVE_HASH_MISMATCH")
    opened=(open_original_zip(archive,meta,expected_kind='P1' if member=='national.json' else 'P0',
                              max_plain_zip_bytes=32*1024*1024)
            if member in ('national.json','forecasts.json') else zipfile.ZipFile(io.BytesIO(archive)))
    with opened as source:
        infos = source.infolist()
        need(len(infos) == 1 and infos[0].filename == member and infos[0].orig_filename == member
             and not infos[0].is_dir() and stat.S_IFMT(infos[0].external_attr >> 16) in (0, stat.S_IFREG)
             and not infos[0].flag_bits & 1 and infos[0].file_size <= store.MAX_WIRE
             and infos[0].compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "ARTIFACT_MEMBERS_INVALID")
        body = source.read(member)
    return body, meta


def _receipt(meta, payload):
    return dict(repository_id=REPO_ID, repository=REPO, run_id=str(meta["workflow_run"]["id"]),
                head_sha=meta["workflow_run"]["head_sha"], artifact_id=meta["id"], created_at=meta["created_at"],
                payload_sha256=digest(payload), independently_verified=True)


def _paths(env, round_no):
    parent = env["temp"]/"boat-all-model-forecasts"
    return parent/f"cycle-{round_no}"/"forecasts.enc", parent/f"cycle-{round_no}.json"


def _sealed(operation, round_no, inputs, baseline_artifact, build):
    env = _environment(); key = _owner(); path, manifest_path = _paths(env, round_no)
    binding = dict(operation=operation, round_no=round_no, run_id=env["run_id"], head_sha=env["head"],
                   inputs_sha256=digest(inputs), baseline_artifact=baseline_artifact)
    if path.exists() or manifest_path.exists():
        manifest = _json(_read(manifest_path, 8192, private=True), 8192)
        need(all(manifest.get(k) == v for k, v in binding.items()), "SEALED_ROUND_INPUT_CHANGED")
        cipher = _read(path, store.MAX_WIRE, private=True)
        need(sha256(cipher).hexdigest() == manifest["cipher_sha256"], "SEALED_ROUND_CIPHER_CHANGED")
        payload = store.open_forecasts(cipher, key=key)
        need(digest(payload) == manifest["payload_sha256"], "SEALED_ROUND_PAYLOAD_CHANGED")
    else:
        payload = build()
        cipher = store.seal_forecasts(payload, run_id=env["run_id"], round_no=round_no, key=key)
        private_root(path.parent); save(path, cipher)
        save(manifest_path, _wire(dict(binding, cipher_sha256=sha256(cipher).hexdigest(), payload_sha256=digest(payload))))
    return dict(ready=True, cipher_path=str(path), artifact_name=artifact_name(env["run_id"], round_no),
                **payload["summary"])


def generate(round_no, baseline_artifact=None):
    _round(round_no); marker = restore_ready(); env = _environment()
    need(marker["round_no"] == round_no, "PREPARED_ROUND_MISMATCH")
    folder = env["temp"]/"boat-all-model-inputs"/f"cycle-{round_no}"
    contexts = []
    if folder.exists():
        for path in sorted(folder.iterdir()):
            need(re.fullmatch(r"\d{8}-\d\d-\d\d\.json", path.name), "RETAINED_INPUT_NAME_INVALID")
            item = _json(_read(path, 2*1024*1024, private=True), 2*1024*1024)
            need(item.get("schema") == engine.INPUT_SCHEMA, "RETAINED_INPUT_SCHEMA_INVALID")
            contexts.append(item)
    need(len(contexts) <= 288, "CONTEXT_COUNT_INVALID")
    if not contexts: return dict(ready=False, contexts=0, generated_forecasts=0)
    issued = _json(_read(marker["issued_models_path"], 1024*1024, private=True), 1024*1024)
    def build():
        document = receipt = None
        if baseline_artifact is not None:
            raw, meta = _artifact(baseline_artifact, member="national.json", expected_name=baseline_name("boat-national-cutoff", int(env["run_id"]), round_no),
                                  expected_run=env["run_id"], expected_head=env["head"])
            document = _json(raw, store.MAX_PLAIN); receipt = _receipt(meta, document)
        return engine.forecast_round(contexts, marker["runtime_files"], now=utc_now(), baseline_document=document,
                                     baseline_receipt=receipt, issued_models=issued)
    return _sealed("generate", round_no, contexts, baseline_artifact, build)


def bootstrap_current(round_no=0):
    marker = prepare_runtime(round_no=round_no); env = _environment()
    local = ROOT/"boat_all_day_output/forecasts.json"; local_receipt = ROOT/"boat_all_day_output/first-receipt.json"
    if local.exists() or local_receipt.exists():
        old = _json(_read(local_receipt, 128*1024), 128*1024)
        run = old["workflow_run"]
        raw, meta = _artifact(old["id"], member="forecasts.json", expected_name=f"boat-p0-existing-{run['id']}",
                              expected_run=run["id"], expected_head=run["head_sha"])
        need(raw == _read(local, runtime.FILE_LIMITS["p0-source.json"])
             and all(old.get(k) == meta.get(k) for k in ("id", "digest", "created_at", "name", "workflow_run")), "LOCAL_P0_SOURCE_BYTES_MISMATCH")
        document = _json(raw, runtime.FILE_LIMITS["p0-source.json"]); receipt = _receipt(meta, document)
    elif marker["runtime_files"].get("p0-source.json"):
        packet = _json(_read(marker["runtime_files"]["p0-source.json"], runtime.FILE_LIMITS["p0-source.json"], private=True), runtime.FILE_LIMITS["p0-source.json"])
        need(set(packet) == {"document", "receipt"}, "P0_PACKET_SCHEMA_INVALID")
        document, receipt = packet["document"], packet["receipt"]
    else:
        return dict(ready=False, contexts=0, generated_forecasts=0)
    issued = _json(_read(marker["issued_p0_models_path"], 1024*1024, private=True), 1024*1024)
    return _sealed("bootstrap-current", round_no, dict(document=document, receipt=receipt), None,
        lambda: engine.forecast_saved_p0(document, receipt, marker["runtime_files"], now=utc_now(), issued_models=issued))


def readback(round_no, ident):
    _round(round_no); env = _environment(); key = _owner(); path, _ = _paths(env, round_no)
    raw, meta = _artifact(ident, member="forecasts.enc", expected_name=artifact_name(env["run_id"], round_no),
                          expected_run=env["run_id"], expected_head=env["head"])
    need(raw == _read(path, store.MAX_WIRE, private=True), "UPLOADED_CIPHER_BYTES_MISMATCH")
    header = store.forecast_header(raw); payload = store.open_forecasts(raw, key=key)
    need(header["run_id"] == env["run_id"] and header["round_no"] == round_no
         and payload.get("source_code_commit") == env["head"] and str(payload.get("run_id")) == env["run_id"], "CIPHER_RUN_ROUND_HEAD_MISMATCH")
    receipt = _receipt(meta, payload); view = engine.project_round(payload, receipt)
    git_auth(); git = store.GitForecastRepository(ROOT)
    pointer = store.publish_forecasts(raw, ROOT, expected_parent=git.head(), transport=git)
    folder = private_root(env["temp"]/"boat-all-model-views"); view_path = folder/f"cycle-{round_no}.json"
    encoded = _wire(view); save(view_path, encoded)
    ref = dict(schema=READBACK_SCHEMA, pointer=pointer, receipt=receipt, private_view_path=str(view_path),
               view_sha256=sha256(encoded).hexdigest(), round_no=round_no, run_id=env["run_id"])
    save(env["temp"]/"boat-all-model-readback.json", _wire(ref), replace=True)
    return dict(ready=True, contexts=payload["summary"]["contexts"], generated_forecasts=payload["summary"]["generated_forecasts"],
                artifact_id=ident, independently_verified=True)


def _outputs(values):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as stream:
            for key in ("ready", "cipher_path", "artifact_name"):
                if key in values:
                    value = str(values[key]).lower() if type(values[key]) is bool else str(values[key])
                    need("\n" not in value and "\r" not in value, "OUTPUT_INVALID")
                    stream.write(key+"="+value+"\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "generate", "bootstrap-current", "readback"):
        p = subs.add_parser(command); p.add_argument("--round", dest="round_no", type=int, default=0, required=command != "bootstrap-current")
        if command == "generate": p.add_argument("--baseline-artifact", type=int)
        if command == "readback": p.add_argument("--artifact", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            prepare_runtime(round_no=args.round_no); result = dict(ready=True)
        elif args.command == "generate": result = generate(args.round_no, args.baseline_artifact)
        elif args.command == "bootstrap-current": result = bootstrap_current(args.round_no)
        else: result = readback(args.round_no, args.artifact)
        _outputs(result)
        print(wire(dict(status="ALL_MODEL_"+args.command.upper().replace("-", "_")+"_COMPLETE",
                        **{k:v for k,v in result.items() if k not in ("cipher_path", "artifact_name")})))
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, CycleError) else "ALL_MODEL_CLI_OPERATION_FAILED"
        _outputs(dict(ready=False)); print(wire(dict(status="ALL_MODEL_PATH_REJECTED", reason=reason)))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
