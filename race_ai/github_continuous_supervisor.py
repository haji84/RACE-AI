"""Keep the existing workflow serialized using the configured cloud identity.

The supervisor never fetches racing sites or runs a model. A physical runner
may finish; a verified checkpoint permits one successor on the same workflow.
The host must remain available. No embedded token, cron, new workflow or paid
service is created, and a source denial is never treated as permission.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import ast
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import uuid
import zipfile

from .private_cycle_capture import _parent_handle
from .source_retry_policy import wait_active, plan_http_wait
from .saved_view_run import display_only_run

REPO = "haji84/RACE-AI"
REPO_ID = 1416489937
BRANCH = "feat/four-sport-forecast-audit-view-20261022"
WORKFLOW = 405276784
TRIGGER = "docs/evidence/boat-nationwide-pilot-trigger.txt"
WORKFLOW_FILE = ".github/workflows/boat-nationwide-ab-one-shot.yml"
SCHEMA = "RACE_AI_EXISTING_WORKFLOW_SUPERVISOR_V1"
NORMAL_HANDOFF = {None, "BOUNDED_SESSION_END", "DAY_CHANGED", "DAY_HANDOFF",
                  "MAX_ROUNDS_REACHED", "SESSION_SOURCE_BUDGET_EXHAUSTED",
                  "SOURCE_BUDGET_EXHAUSTED", "WORKER_HANDOFF"}
SHA = re.compile(r"[a-f0-9]{40,64}\Z")
OWNED_TRIGGER_LINE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\S+ RACE_AI_CONTINUOUS_[a-f0-9]{32}: "
    r"owner-authorized continuous successor after authenticated run [1-9][0-9]*; "
    r"same workflow/single writer, unlimited logical rounds/time, preferred T-15\.\.T-10, "
    r"preserve originals and upstream waits; no new service, model, bet or promotion\.\r?\n?\Z")


class WorkflowAPIWait(OSError):
    def __init__(self, wait):
        self.wait = wait
        super().__init__("WORKFLOW_API_UNAVAILABLE")


def moment(value):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("SUPERVISOR_AWARE_CLOCK_REQUIRED")
    return result


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


class GitHubCLI:
    """Use inherited CLI/proxy authentication; never inspect credential files."""
    def raw(self, endpoint, *, method="GET", data=None):
        if not isinstance(endpoint, str) or endpoint.startswith(("/", "http")) or ".." in endpoint:
            raise ValueError("SUPERVISOR_ENDPOINT_INVALID")
        command = ["gh", "api", "--include", "repos/" + REPO + "/" + endpoint]
        if method != "GET": command += ["--method", method]
        if data is not None: command += ["--input", "-"]
        try:
            result = subprocess.run(command, input=wire(data) if data is not None else None,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=50)
        except subprocess.SubprocessError:
            raise WorkflowAPIWait(plan_http_wait(None, {}, datetime.now(timezone.utc))) from None
        body, status, headers = result.stdout, None, {}
        while body.startswith(b"HTTP/"):
            # gh may use LF headers while the ZIP contains CRLF. Select the
            # first header separator, never one found later inside its body.
            boundary = re.search(br"\r?\n\r?\n", body)
            if boundary is None or boundary.start() > 65536:
                raise OSError("WORKFLOW_API_UNAVAILABLE")
            lines = body[:boundary.start()].decode("latin1").splitlines()
            if not re.fullmatch(r"HTTP/[0-9.]+ [0-9]{3}(?: .*)?", lines[0]):
                raise OSError("WORKFLOW_API_UNAVAILABLE")
            status = int(lines[0].split()[1])
            headers = {k.strip().lower():v.strip() for k,v in
                       (line.split(":",1) for line in lines[1:] if ":" in line)}
            body = body[boundary.end():]
            if not (100 <= status < 200 or 300 <= status < 400):
                break
        if result.returncode or status is not None and status >= 400:
            # stderr may contain private endpoint details; expose a fixed code.
            effective = 429 if status == 403 and (headers.get("retry-after") or headers.get("x-ratelimit-remaining") == "0") else status
            wait = plan_http_wait(effective, headers, datetime.now(timezone.utc))
            if effective == 429 and headers.get("x-ratelimit-reset") is not None:
                try:
                    reset = headers["x-ratelimit-reset"]
                    if not re.fullmatch(r"[0-9]{1,20}", reset): raise ValueError()
                    reset_at = datetime.fromtimestamp(int(reset), timezone.utc)
                    if wait["retry_at"] is not None:
                        wait["retry_at"] = max(moment(wait["retry_at"]), reset_at).isoformat()
                except (ValueError, OverflowError, OSError):
                    wait.update(state="SOURCE_REVIEW_WAIT", reason="SERVER_RETRY_TIME_UNREPRESENTABLE", retry_at=None)
            wait["http_status"] = status
            raise WorkflowAPIWait(wait)
        return body

    def api(self, endpoint, **kwargs):
        return json.loads(self.raw(endpoint, **kwargs))

    def verify_authorization(self):
        """Explicitly verify the current inherited connection, without writes.

        This confirms current access; it does not diagnose the old 401, refresh
        credentials, switch identities, or claim to reproduce an unknown failed
        endpoint. Ordinary ticks never call this operator recovery probe.
        """
        try:
            result = subprocess.run(["gh", "auth", "status", "--hostname", "github.com"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=50)
        except (OSError, subprocess.SubprocessError):
            raise ValueError("GITHUB_AUTHORIZATION_NOT_CONFIRMED") from None
        if result.returncode:
            raise ValueError("GITHUB_AUTHORIZATION_NOT_CONFIRMED")
        workflow = self.api(f"actions/workflows/{WORKFLOW}")
        if (not isinstance(workflow, dict) or type(workflow.get("id")) is not int or
                workflow["id"] != WORKFLOW or workflow.get("path") != WORKFLOW_FILE or
                workflow.get("state") != "active"):
            raise ValueError("WORKFLOW_AUTHORIZATION_IDENTITY_INVALID")
        active = self.active_runs()
        latest = self.latest_run()
        if not isinstance(active, list):
            raise ValueError("WORKFLOW_RUN_IDENTITY_INVALID")
        for run in active + [latest]:
            if (not isinstance(run, dict) or type(run.get("id")) is not int or run["id"] < 1 or
                    type(run.get("workflow_id")) is not int or run["workflow_id"] != WORKFLOW or
                    run.get("head_branch") != BRANCH or
                    not isinstance(run.get("head_sha"), str) or
                    re.fullmatch(r"[a-f0-9]{40}", run["head_sha"]) is None):
                raise ValueError("WORKFLOW_RUN_IDENTITY_INVALID")
            for field in ("repository", "head_repository"):
                repository = run.get(field)
                if (not isinstance(repository, dict) or repository.get("full_name") != REPO or
                        type(repository.get("id")) is not int or repository["id"] != REPO_ID):
                    raise ValueError("WORKFLOW_RUN_IDENTITY_INVALID")
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ValueError("WORKFLOW_AUTHORIZATION_CHECKPOINT_UNAVAILABLE")
        control = self.final_control(latest)
        if (not isinstance(control, dict) or
                type(control.get("previous_run_id", control.get("run_id"))) is not int or
                control.get("previous_run_id", control.get("run_id")) != latest["id"]):
            raise ValueError("WORKFLOW_COUNTER_IDENTITY_INVALID")
        return dict(repo=REPO, workflow_id=WORKFLOW, run_id=latest["id"],
                    active_run_ids=sorted(run["id"] for run in active),
                    source_control_sha256=hashlib.sha256(wire(control)).hexdigest(),
                    verification="GH_AUTH_STATUS_AND_AUTHENTICATED_WORKFLOW_READS")

    def active_runs(self):
        found = {}
        for status in ("in_progress", "queued", "pending", "waiting"):
            page = 1
            while True:
                data = self.api(f"actions/workflows/{WORKFLOW}/runs?status={status}&per_page=100&page={page}")
                rows = data["workflow_runs"]
                if not isinstance(rows, list): raise ValueError("WORKFLOW_RUN_PAGE_INVALID")
                for row in rows:
                    if row.get("head_branch") != BRANCH or row.get("workflow_id") != WORKFLOW:
                        raise ValueError("WORKFLOW_RUN_IDENTITY_INVALID")
                    if display_only_run(row):continue
                    found[row["id"]] = row
                if len(rows) < 100: break
                page += 1
        return list(found.values())

    def latest_run(self):
        for page in range(1,101):
            data=self.api(f"actions/workflows/{WORKFLOW}/runs?branch={BRANCH}&per_page=100&page={page}")
            rows=data['workflow_runs']
            if not isinstance(rows,list):raise ValueError('WORKFLOW_RUN_PAGE_INVALID')
            for row in rows:
                if not display_only_run(row):return row
            if len(rows)<100:return None
        raise ValueError('WORKFLOW_RUN_PAGE_BOUND')

    def final_control(self, run):
        from .cycle_recovery import artifact_pages, authenticated_source_control
        rows = artifact_pages(self.raw, run["id"])
        selected = [a for a in rows if a.get("name") == f"race-cycle-continuity-{run['id']}"]
        if len(selected) != 1: raise ValueError("WORKFLOW_CHECKPOINT_NOT_AVAILABLE")
        meta = self.api(f"actions/artifacts/{selected[0]['id']}")
        raw = self.raw(f"actions/artifacts/{meta['id']}/zip")
        value = authenticated_source_control(raw, meta, expected_run=run["id"])
        if value is None: raise ValueError("WORKFLOW_CHECKPOINT_NOT_AVAILABLE")
        return value

    def read_trigger(self):
        pr = self.api("pulls/71")
        if pr.get("state") != "open" or pr["head"]["ref"] != BRANCH:
            raise ValueError("EXISTING_PR_NOT_AVAILABLE")
        head = pr["head"]["sha"]
        if not SHA.fullmatch(head): raise ValueError("WORKFLOW_HEAD_INVALID")
        commit = self.api("git/commits/" + head)
        source = self._file("race_ai/repeated_cycle.py",head).decode()
        constants = {}
        for node in ast.parse(source).body:
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
                if node.targets[0].id in ("MAX_ROUNDS","MAX_SECONDS"):
                    constants[node.targets[0].id] = ast.literal_eval(node.value)
        if constants != {"MAX_ROUNDS":None,"MAX_SECONDS":None}:
            raise ValueError("CONTINUOUS_WORKFLOW_NOT_APPLIED")
        deployed=(Path(__file__).resolve().parents[1]/WORKFLOW_FILE).read_bytes()
        if self._file(WORKFLOW_FILE,head)!=deployed:
            raise ValueError("CONTINUOUS_WORKFLOW_NOT_APPLIED")
        body = self._file(TRIGGER,head)
        return dict(head=head, tree=commit["tree"]["sha"], content=body.decode("utf-8"))

    def _file(self, path, head):
        entry=self.api("contents/"+path+"?ref="+head)
        # Large Contents API responses can omit their bytes. They must never
        # be mistaken for an empty trigger and overwrite the owner's history.
        if entry.get("type")!="file" or entry.get("encoding")!="base64" or not isinstance(entry.get("content"),str):
            raise ValueError("WORKFLOW_FILE_CONTENT_UNAVAILABLE")
        body=base64.b64decode(entry["content"].replace("\n",""),validate=True)
        if len(body)>1024*1024:raise ValueError("WORKFLOW_FILE_SIZE_INVALID")
        return body

    def append_trigger(self, previous, line):
        # A concurrent forward branch update rejects this commit parent. No
        # force reset is performed, and original commits remain in Git history.
        content=previous["content"]
        if len((content+line).encode())>512*1024:
            lines=content.splitlines(keepends=True)
            owned=[index for index,text in enumerate(lines) if OWNED_TRIGGER_LINE.fullmatch(text)]
            obsolete=set(owned[:-128])
            content="".join(text for index,text in enumerate(lines) if index not in obsolete)
        body = (content + line).encode()
        if len(body)>1024*1024:
            raise ValueError("WORKFLOW_OWNER_TRIGGER_CONTENT_TOO_LARGE")
        blob = self.api("git/blobs", method="POST", data={"content": base64.b64encode(body).decode(), "encoding": "base64"})
        tree = self.api("git/trees", method="POST", data={"base_tree": previous["tree"],
            "tree": [{"path": TRIGGER, "mode": "100644", "type": "blob", "sha": blob["sha"]}]})
        commit = self.api("git/commits", method="POST", data={"message": "chore: continue existing verified deadline automation",
            "parents": [previous["head"]], "tree": tree["sha"]})
        self.api("git/refs/heads/" + BRANCH, method="PATCH", data={"sha": commit["sha"], "force": False})
        return commit["sha"]


class GitHubSupervisor:
    def __init__(self, private_root, *, client=None, clock=None, projection_refresh=None):
        self.root = Path(private_root)
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.client = client or GitHubCLI()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.projection_refresh = projection_refresh
        self._mutex = threading.Lock(); self._status_lock = threading.Lock()
        self._stop = threading.Event(); self._thread = None; self._lock_fd = None
        self._state = None
        self._state_digest = None
        self._root_identity = None
        self._snapshot = dict(enabled=True, continuous=True, runtime_plane="EXISTING_GITHUB_WORKFLOW",
            state="NOT_STARTED", round_no=None, max_rounds=None, source_limit=None, stop_at=None,
            interval_seconds=180, requests_used=None, lifetime_requests=None,
            lifetime_completed_rounds=None, counter_run_id=None, counter_as_of=None,
            counter_scope="UNKNOWN", next_run_at=None, halted_reason=None,
            supervisor_available=True)

    def status(self):
        with self._status_lock: return deepcopy(self._snapshot)

    def _publish(self, state, **fields):
        with self._status_lock:
            self._snapshot.update(state=state, waiting_state=None, waiting_reason=None,
                                  retry_at=None, next_run_at=None)
            self._snapshot.update(**fields)
        return self.status()

    @staticmethod
    def _private(info):
        if not (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600):
            raise ValueError("PRIVATE_SUPERVISOR_FILE_REQUIRED")

    def _acquire(self):
        if self._lock_fd is not None:
            self._verify_files()
            return True
        with _parent_handle(self.root) as directory:
            info = os.fstat(directory)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError("PRIVATE_SUPERVISOR_ROOT_REQUIRED")
            self._root_identity = info.st_dev, info.st_ino
            fd = os.open("supervisor.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            self._private(os.fstat(fd))
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd); return False
            self._lock_fd = fd
            try:
                source = os.open("supervisor.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            except FileNotFoundError:
                if os.fstat(fd).st_size:
                    raise ValueError("SUPERVISOR_CHECKPOINT_MISSING")
                self._state = dict(schema=SCHEMA, last_observed_at=moment(self.clock()).isoformat(), intent=None)
                return True
            with os.fdopen(source, "rb") as stream:
                self._private(os.fstat(stream.fileno()))
                data = stream.read(1024*1024+1)
            if len(data) > 1024*1024: raise ValueError("SUPERVISOR_STATE_SIZE")
            value = json.loads(data); claimed = value.pop("state_sha256")
            if value.get("schema") != SCHEMA or hashlib.sha256(wire(value)).hexdigest() != claimed:
                raise ValueError("SUPERVISOR_STATE_INVALID")
            self._state = value
            self._state_digest = hashlib.sha256(data).hexdigest()
            return True

    def _verify_files(self, directory=None):
        if self._lock_fd is None:
            raise ValueError("SUPERVISOR_LOCK_NOT_HELD")
        if directory is not None:
            return self._verify_at(directory)
        with _parent_handle(self.root) as directory:
            self._verify_at(directory)

    def _verify_at(self, directory):
        root=os.fstat(directory)
        if (root.st_dev,root.st_ino)!=self._root_identity or root.st_uid!=os.getuid() or stat.S_IMODE(root.st_mode)!=0o700:
            raise ValueError("PRIVATE_SUPERVISOR_ROOT_REQUIRED")
        try:
            held=os.fstat(self._lock_fd);actual=os.stat("supervisor.lock",dir_fd=directory,follow_symlinks=False)
        except (OSError,TypeError):
            raise ValueError("SUPERVISOR_LOCK_CHANGED") from None
        self._private(held);self._private(actual)
        if (held.st_dev,held.st_ino)!=(actual.st_dev,actual.st_ino):
            raise ValueError("SUPERVISOR_LOCK_CHANGED")
        try:source=os.open("supervisor.json",os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
        except FileNotFoundError:
            if self._state_digest is not None or held.st_size:
                raise ValueError("SUPERVISOR_CHECKPOINT_MISSING") from None
            return
        with os.fdopen(source,"rb") as stream:
            self._private(os.fstat(stream.fileno()));body=stream.read(1024*1024+1)
        if self._state_digest is None or hashlib.sha256(body).hexdigest()!=self._state_digest:
            raise ValueError("SUPERVISOR_CHECKPOINT_CHANGED")

    def _save(self):
        value = deepcopy(self._state)
        value["state_sha256"] = hashlib.sha256(wire(value)).hexdigest()
        body = wire(value)+b"\n"
        with _parent_handle(self.root) as directory:
            self._verify_files(directory)
            name = "supervisor-tmp-" + uuid.uuid4().hex + ".json"
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body); stream.flush(); os.fsync(stream.fileno())
            try:
                self._verify_files(directory)
                os.replace(name, "supervisor.json", src_dir_fd=directory, dst_dir_fd=directory)
                os.fsync(directory)
            finally:
                try:os.unlink(name,dir_fd=directory)
                except FileNotFoundError:pass
        self._state_digest = hashlib.sha256(body).hexdigest()
        os.lseek(self._lock_fd,0,os.SEEK_SET);os.write(self._lock_fd,(SCHEMA+"\n").encode());os.fsync(self._lock_fd)

    def _refresh(self, run):
        if self.projection_refresh is None: return
        try:
            data = self.projection_refresh(self.client.raw, self.root, run["id"])
            with self._status_lock:
                self._snapshot.update(projection_status=data,projection_waiting=False)
        except WorkflowAPIWait:
            raise
        except (OSError, ValueError, KeyError, TypeError):
            with self._status_lock: self._snapshot["projection_waiting"] = True

    def _completed_counters(self, run, control):
        source_run=control.get("previous_run_id",control.get("run_id"))
        if source_run!=run["id"]:raise ValueError("WORKFLOW_COUNTER_IDENTITY_INVALID")
        counts={"requests_used":control.get("previous_session_requests",control.get("requests_used")),
                "round_no":control.get("completed_round"),
                "lifetime_requests":control.get("lifetime_requests"),
                "lifetime_completed_rounds":control.get("lifetime_completed_rounds")}
        if any(value is not None and (type(value) is not int or value<0) for value in counts.values()):
            raise ValueError("WORKFLOW_COUNTER_INVALID")
        with self._status_lock:
            self._snapshot.update(**counts,counter_run_id=run["id"],
                counter_as_of=control.get("receipt",{}).get("created_at"),
                counter_scope="AUTHENTICATED_COMPLETED_RUN")

    def reconnect_authorization(self, expected_checkpoint_sha256):
        """Recover one reviewed 401 latch after current provider verification.

        The trusted operator supplies only the exact original checkpoint hash.
        This method never triggers a run or clears a racing-source wait. All
        normal handoff checks still run on the next ordinary tick.
        """
        with self._mutex:
            if (not isinstance(expected_checkpoint_sha256, str) or
                    re.fullmatch(r"[a-f0-9]{64}", expected_checkpoint_sha256) is None):
                raise ValueError("SUPERVISOR_RECONNECT_CHECKPOINT_REQUIRED")
            if not self._acquire():
                raise ValueError("ANOTHER_SUPERVISOR_ACTIVE")
            if self._state_digest != expected_checkpoint_sha256:
                raise ValueError("SUPERVISOR_RECONNECT_CHECKPOINT_CHANGED")
            wait = self._state.get("api_wait")
            if (not isinstance(wait, dict) or type(wait.get("http_status")) is not int or
                    wait["http_status"] != 401 or wait.get("state") != "AUTHORIZATION_WAIT" or
                    wait.get("reason") != "SOURCE_AUTHORIZATION_REQUIRED" or wait.get("retry_at") is not None):
                raise ValueError("SUPERVISOR_RECONNECT_401_WAIT_REQUIRED")
            now = moment(self.clock())
            if now < moment(self._state["last_observed_at"]):
                raise ValueError("CLOCK_REVERSED")
            verification = self.client.verify_authorization()
            self._verify_files()
            if verification["run_id"] < self._state.get("last_adopted_run_id", 0):
                raise ValueError("WORKFLOW_METADATA_PENDING")
            checked_at = moment(self.clock())
            if checked_at < now:
                raise ValueError("CLOCK_REVERSED")
            candidate = deepcopy(self._state)
            history = candidate.setdefault("authorization_recoveries", [])
            if not isinstance(history, list):
                raise ValueError("SUPERVISOR_RECONNECT_HISTORY_INVALID")
            history.append(dict(previous_checkpoint_sha256=expected_checkpoint_sha256,
                                previous_api_wait=deepcopy(wait), checked_at=checked_at.isoformat(),
                                verification=verification))
            candidate["api_wait"] = None
            if len(wire(candidate)) > 1024 * 1024 - 128:
                raise ValueError("SUPERVISOR_STATE_SIZE")
            original_state = self._state
            self._state = candidate
            try:
                self._save()
            except BaseException:
                # Even a late filesystem failure must not permit this process
                # to continue with an unacknowledged in-memory authorization.
                self._state = original_state
                raise
            return dict(state="AUTHORIZATION_RECONNECTED", checkpoint_sha256=self._state_digest,
                        checked_at=checked_at.isoformat(), workflow_id=WORKFLOW,
                        run_id=verification["run_id"])

    def tick(self):
        with self._mutex:
            try:
                if not self._acquire():
                    return self._publish("REVIEW_WAIT", halted_reason="ANOTHER_SUPERVISOR_ACTIVE")
                now = moment(self.clock())
                if now < moment(self._state["last_observed_at"]):
                    return self._publish("REVIEW_WAIT", halted_reason="CLOCK_REVERSED")
                self._state["last_observed_at"] = now.isoformat()
                api_wait = self._state.get("api_wait")
                if api_wait is not None and wait_active(api_wait,now):
                    return self._publish("SOURCE_WAIT",waiting_reason="WORKFLOW_API_UNAVAILABLE",
                        waiting_state=api_wait.get("state"),
                        next_run_at=api_wait.get("retry_at"),retry_at=api_wait.get("retry_at"))
                if api_wait is not None:
                    self._state["api_wait"]=None;self._save()
                active = self.client.active_runs()
                running = [r for r in active if r["status"] == "in_progress"]
                if len(running) > 1 or len(active) > 2:
                    return self._publish("REVIEW_WAIT", halted_reason="OVERLAPPING_WORKFLOW_WRITERS")
                if active:
                    run = running[0] if running else active[0]
                    intent = self._state.get("intent")
                    if intent and (intent.get("commit_sha") == run.get("head_sha") or run["id"] > intent["predecessor"]):
                        self._state["intent"] = None
                    self._state["last_adopted_run_id"] = max(run["id"],self._state.get("last_adopted_run_id",0))
                    self._state["active_run_id"] = run["id"]; self._save()
                    self._publish("RUNNING" if running else "WAITING", active_run_id=run["id"],halted_reason=None,
                        round_no=None,requests_used=None,lifetime_requests=None,lifetime_completed_rounds=None,
                        counter_run_id=run["id"],counter_as_of=None,counter_scope="ACTIVE_RUN_UNVERIFIED")
                    self._refresh(run)
                    return self._publish("RUNNING" if running else "WAITING", active_run_id=run["id"],
                        halted_reason=None, next_run_at=(now+timedelta(seconds=30)).isoformat())
                latest = self.client.latest_run()
                if latest is None or latest.get("status") != "completed" or latest.get("conclusion") != "success":
                    return self._publish("REVIEW_WAIT", halted_reason="PREDECESSOR_REVIEW_REQUIRED")
                if latest["id"] < self._state.get("last_adopted_run_id",0):
                    return self._publish("WAITING",waiting_reason="WORKFLOW_METADATA_PENDING")
                if self._state.get("intent") and latest["id"] > self._state["intent"]["predecessor"]:
                    self._state["intent"]=None;self._save()
                control = self.client.final_control(latest)
                self._state["source_control"] = control
                self._completed_counters(latest,control)
                self._refresh(latest)
                if control.get("prepared_round") is not None:
                    self._save()
                    return self._publish("REVIEW_WAIT",halted_reason="PREDECESSOR_TRANSACTION_INCOMPLETE")
                wait = control.get("source_wait")
                if wait is not None and wait_active(wait, now):
                    self._save()
                    return self._publish("SOURCE_WAIT", waiting_state=wait["state"], waiting_reason=wait["reason"],
                        retry_at=wait.get("retry_at"), next_run_at=wait.get("retry_at"), halted_reason=None)
                reason = control.get("halted_reason") or control.get("previous_halted_reason")
                if reason not in NORMAL_HANDOFF:
                    self._save()
                    return self._publish("REVIEW_WAIT", halted_reason="PREDECESSOR_SOURCE_REVIEW_REQUIRED")
                trigger = self.client.read_trigger()
                intent = self._state.get("intent")
                if intent and intent["marker"] in trigger["content"]:
                    intent["commit_sha"] = intent.get("commit_sha") or trigger["head"]
                    self._save()
                    return self._publish("HANDOFF_WAIT", next_run_at=(now+timedelta(seconds=30)).isoformat(), halted_reason=None)
                if intent is None:
                    intent = dict(marker="RACE_AI_CONTINUOUS_"+uuid.uuid4().hex,
                                  predecessor=latest["id"], created_at=now.isoformat(), commit_sha=None)
                    self._state["intent"] = intent; self._save()
                if self._stop.is_set(): return self._publish("PAUSED")
                line = ("\n" + now.isoformat() + " " + intent["marker"] +
                        f": owner-authorized continuous successor after authenticated run {latest['id']}; "
                        "same workflow/single writer, unlimited logical rounds/time, preferred T-15..T-10, "
                        "preserve originals and upstream waits; no new service, model, bet or promotion.\n")
                self._verify_files()
                intent["commit_sha"] = self.client.append_trigger(trigger, line)
                self._save()
                return self._publish("HANDOFF_WAIT", next_run_at=(now+timedelta(seconds=30)).isoformat(), halted_reason=None)
            except OSError as error:
                wait = error.wait if isinstance(error,WorkflowAPIWait) else plan_http_wait(None,{},moment(self.clock()))
                if self._state is not None and self._lock_fd is not None:
                    self._state["api_wait"]=wait
                    try:self._save()
                    except ValueError:
                        return self._publish("REVIEW_WAIT",halted_reason="SUPERVISOR_STATE_OR_CHECKPOINT_UNAVAILABLE")
                    except OSError:pass
                return self._publish("SOURCE_WAIT", waiting_reason="WORKFLOW_API_UNAVAILABLE",
                                     waiting_state=wait.get("state"), next_run_at=wait.get("retry_at"),retry_at=wait.get("retry_at"))
            except (ValueError, KeyError, TypeError, zipfile.BadZipFile, SyntaxError):
                return self._publish("REVIEW_WAIT", halted_reason="SUPERVISOR_STATE_OR_CHECKPOINT_UNAVAILABLE")

    def start(self):
        if self._thread is not None and self._thread.is_alive(): return True
        self._stop.clear()
        def work():
            while not self._stop.is_set():
                try:self.tick()
                except Exception:
                    self._publish("REVIEW_WAIT",halted_reason="SUPERVISOR_UNEXPECTED_ERROR")
                self._stop.wait(30)
        self._thread = threading.Thread(target=work, name="race-ai-existing-workflow-supervisor", daemon=True)
        self._thread.start(); return True

    def stop(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=60)
            if self._thread.is_alive(): raise ValueError("SUPERVISOR_SHUTDOWN_INCOMPLETE")
        with self._mutex:
            if self._lock_fd is not None:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN); os.close(self._lock_fd); self._lock_fd=None
            self._publish("PAUSED")
