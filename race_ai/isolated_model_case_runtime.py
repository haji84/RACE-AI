"""One fixed V2 producer child; no caller program, network or source authority.

preflight() -> True validates the fixed public bundle before target creation.
produce(request, request_sha256, raw_feed, source_verdicts, *, started_at,
admit_private_input) -> (original_wire, delivery_sha256, actual_UTC_start).
The no-argument admission callback runs only after verified READY and returns a
fresh aware timestamp. It is parent authority, not independent time/execution
proof. A blocking caller callback cannot safely be forcibly interrupted; an
independent watchdog still kills/reaps the child before private analysis expiry.
"""
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from . import isolated_model_case_worker as worker

TOTAL_SECONDS = 30.0


class IsolatedModelError(ValueError):
    """Sanitized fixed-runtime, protocol or private-send rejection."""


def _fail():
    raise IsolatedModelError("ISOLATED_MODEL_REJECTED") from None


def preflight():
    try:
        worker._bundle()
        return True
    except Exception:
        _fail()


class _Session:
    def __init__(self, process, deadline):
        self.process, self.deadline = process, deadline
        self.stopped, self.failed = threading.Event(), threading.Event()
        self.messages, self.threads = queue.Queue(2), []

    def start(self):
        self._start(self._read, "reader")
        self._start(self._watch, "watchdog")

    def _start(self, function, name):
        thread = threading.Thread(target=function, name="race32-" + name, daemon=True)
        self.threads.append(thread)
        thread.start()

    def _remaining(self):
        # Reserve a bounded part of the SINGLE lifecycle budget for cleanup.
        return self.deadline - time.monotonic() - min(.2, TOTAL_SECONDS / 4)

    def _kill(self):
        self.failed.set()
        try:
            if self.process.poll() is None:
                self.process.kill()
        except Exception:
            pass

    def _watch(self):
        while not self.stopped.is_set():
            remaining = self._remaining()
            if remaining <= 0:
                self._kill()
                # Reap proactively even if the caller's admission is still running.
                try:
                    self.process.wait(timeout=max(.001, self.deadline - time.monotonic()))
                except Exception:
                    pass
                return
            self.stopped.wait(min(.02, remaining))

    def _read(self):
        try:
            ready = worker._frame(self.process.stdout, worker.HEADER_LIMIT)
            self.messages.put_nowait(("READY", ready))
            header = worker._frame(self.process.stdout, worker.HEADER_LIMIT)
            wire = worker._frame(self.process.stdout, worker.WIRE_LIMIT)
            if self.process.stdout.read(1):
                worker._reject()
            self.messages.put_nowait(("RESULT", header, wire))
        except Exception:
            self._kill()

    def receive(self, phase):
        while self._remaining() > 0 and not self.failed.is_set():
            try:
                value = self.messages.get(timeout=min(.02, self._remaining()))
            except queue.Empty:
                continue
            if value[0] != phase:
                _fail()
            return value[1:]
        _fail()

    def send(self, control, raw):
        if self.failed.is_set() or self._remaining() <= 0:
            _fail()
        def write():
            try:
                if self.failed.is_set() or self._remaining() <= 0:
                    _fail()
                worker._write_frame(self.process.stdin, control)
                if self.failed.is_set() or self._remaining() <= 0:
                    _fail()
                worker._write_frame(self.process.stdin, raw)
                self.process.stdin.close()
            except Exception:
                self._kill()
        self._start(write, "writer")

    def close(self):
        self.stopped.set()
        if self.process.poll() is None:
            self._kill()
        try:
            self.process.wait(timeout=max(.001, self.deadline - time.monotonic()))
        except Exception:
            self._kill()
        for thread in self.threads:
            if thread.ident is not None:
                thread.join(timeout=max(.001, self.deadline - time.monotonic()))
        for stream in (self.process.stdin, self.process.stdout):
            try:
                stream.close()
            except Exception:
                pass
        if any(thread.is_alive() for thread in self.threads) or self.process.poll() is None:
            _fail()


def produce(request, request_sha256, raw_feed, source_verdicts, *, started_at, admit_private_input):
    session, process = None, None
    try:
        entered = time.monotonic()
        request_raw = worker._dump(request, worker.CONTROL_LIMIT)
        decisions_raw = worker._dump(source_verdicts, worker.CONTROL_LIMIT)
        owned = worker._json(request_raw, worker.CONTROL_LIMIT)
        decisions = worker._json(decisions_raw, worker.CONTROL_LIMIT)
        worker._request(owned, request_sha256, raw_feed, decisions)
        initial, cutoff = worker._stamp(started_at), worker._stamp(owned["sales_cutoff_at"])
        if not callable(admit_private_input) or not worker._stamp(owned["as_of"]) <= initial < cutoff:
            _fail()
        deadline = entered + min(TOTAL_SECONDS, (cutoff - initial).total_seconds())
        preflight()
        if time.monotonic() >= deadline:
            _fail()
        environment = {}
        if os.name == "nt":
            environment["SystemRoot"] = os.environ["SystemRoot"]
        process = subprocess.Popen([sys.executable, "-I", "-S", "-B", "-u", str(Path(worker.__file__).absolute())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            cwd=str(worker.PROJECT), env=environment, close_fds=True, bufsize=0)
        session = _Session(process, deadline)
        session.start()
        ready, = session.receive("READY")
        if worker._json(ready, worker.HEADER_LIMIT) != worker._identity(worker.READY):
            _fail()
        actual = worker._stamp(admit_private_input())
        if (not initial <= actual < cutoff or session.failed.is_set() or session._remaining() <= 0
                or worker._dump(request, worker.CONTROL_LIMIT) != request_raw
                or worker._dump(source_verdicts, worker.CONTROL_LIMIT) != decisions_raw):
            _fail()
        session.deadline = min(deadline, time.monotonic() + (cutoff - actual).total_seconds())
        if session._remaining() <= 0:
            _fail()
        control = {**worker._identity(worker.CONTROL), "request": owned, "request_sha256": request_sha256,
            "started_at": actual.isoformat(), "policy_record_sha256": owned["policy_record_sha256"],
            "source_verdicts": decisions}
        session.send(worker._dump(control, worker.CONTROL_LIMIT), raw_feed)
        header, wire = session.receive("RESULT")
        header = worker._json(header, worker.HEADER_LIMIT)
        if (type(header) is not dict or set(header) != {"schema", "profile", "pin", "manifest_sha256", "request_sha256",
                "delivery_sha256", "wire_sha256", "wire_bytes"}
                or any(header.get(key) != value for key, value in worker._identity(worker.RESULT).items())
                or header["request_sha256"] != request_sha256 or not worker._hex(header["delivery_sha256"])
                or not worker._hex(header["wire_sha256"]) or type(header["wire_bytes"]) is not int
                or header["wire_bytes"] != len(wire) or header["wire_sha256"] != worker._sha(wire)):
            _fail()
        process.wait(timeout=max(.001, session._remaining()))
        if process.returncode != 0 or session.failed.is_set() or session._remaining() <= 0:
            _fail()
        return wire, header["delivery_sha256"], actual.isoformat()
    except Exception:
        _fail()
    finally:
        try:
            if session is not None:
                session.close()
            elif process is not None:
                # Even construction/allocation failure releases the started child.
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=max(.001, deadline - time.monotonic()))
                for stream in (process.stdin, process.stdout):
                    stream.close()
        except Exception:
            _fail()
