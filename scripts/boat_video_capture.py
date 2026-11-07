"""Collect an explicitly authorized HLS source into private local windows.

No new service is installed. ``--follow`` has no acquisition-count or runtime
ceiling. Upstream denial/wait state is owned by Collector and survives restart.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("CAPTURE_ARGUMENTS_REJECTED")


def _private_json(path):
    from race_ai.boat_video_intake import _path, _parent_handle, _private, _regular
    import os
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("CAPTURE_JSON_REJECTED")
            value[key] = child
        return value
    def invalid_constant(value):
        raise ValueError("CAPTURE_JSON_REJECTED")
    target = _path(path)
    with _parent_handle(target.parent) as parent:
        _private(os.fstat(parent), directory=True)
        with _regular(parent, target.name, limit=2 * 1024 * 1024) as stream:
            value = json.loads(stream.read(), object_pairs_hook=unique, parse_constant=invalid_constant)
    if type(value) is not dict:
        raise ValueError("CAPTURE_JSON_REJECTED")
    return value


def export_closed(collector, cursor, *, job_template=None, intake_root=None,
                  should_stop=lambda: False):
    """Page closed windows; resume existing exports if a prior enqueue crashed.

    The caller advances its cursor only after this returns successfully.
    Existing intake content addressing makes replay of an accepted job safe.
    A fresh process starts at zero, including windows exported before a crash.
    """
    results = []
    # A DB page is a scheduling unit, not a source acquisition ceiling. Return
    # to tick between pages, keeping memory bounded and honoring termination.
    rows = collector.list_windows(after_id=cursor, limit=100)
    for row in rows:
        if not row["closed"] or should_stop():
            break
        if row.get("analysis_exportable", True) is False:
            results.append({"status": "ARCHIVED_ANALYSIS_INELIGIBLE",
                            "window_id": row["window_id"]})
            cursor = row["window_id"]
            continue
        record = collector.export_window(row["window_id"])
        if job_template is None:
            result = {"status": "CAPTURE_ONLY", "window_id": record["window_id"],
                      "media_sha256": record["media_sha256"],
                      "receipt_sha256": record["receipt_sha256"]}
        else:
            from race_ai.boat_video_capture_bridge import enqueue_export
            result = enqueue_export(intake_root, record, job_template)
        results.append(result)
        cursor = row["window_id"]
    return cursor, results


def _delay(summary):
    stamp = summary.get("next_poll_at")
    wait = summary.get("source_wait")
    if wait:
        stamp = wait.get("retry_at")
        if stamp is None:
            return 60.0
    if stamp:
        instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return max(0.1, (instant - datetime.now(timezone.utc)).total_seconds())
    return 1.0


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument("--private-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--job-template")
    parser.add_argument("--intake-root")
    parser.add_argument("--window-id", type=int)
    stop = False
    previous = {}
    collector = None

    def stopping(signum, frame):
        nonlocal stop
        stop = True

    try:
        args = parser.parse_args(argv)
        if bool(args.job_template) != bool(args.intake_root) or (args.follow and args.window_id is not None):
            raise ValueError("CAPTURE_ARGUMENTS_REJECTED")
        manifest = _private_json(args.manifest)
        template = _private_json(args.job_template) if args.job_template else None
        from race_ai.boat_video_capture import Collector
        collector = Collector(args.private_root, manifest)
        if args.window_id is not None:
            record = collector.export_window(args.window_id)
            if template is not None:
                from race_ai.boat_video_capture_bridge import enqueue_export
                result = enqueue_export(args.intake_root, record, template)
            else:
                result = {"status": "CAPTURE_ONLY", "window_id": record["window_id"],
                          "media_sha256": record["media_sha256"],
                          "receipt_sha256": record["receipt_sha256"]}
            print(json.dumps(result), flush=True)
            return 0
        for name in (signal.SIGINT, signal.SIGTERM):
            previous[name] = signal.signal(name, stopping)
        cursor = 0
        while not stop:
            summary = collector.tick()
            try:
                cursor, exports = export_closed(collector, cursor, job_template=template,
                                                 intake_root=args.intake_root,
                                                 should_stop=lambda: stop)
            except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
                # Preserve cursor so a subsequent tick/restart retries the saved
                # local export/binding; source collection continues independently.
                exports = [{"status": "LOCAL_EXPORT_OR_BINDING_REQUIRES_REVIEW"}]
            print(json.dumps({"capture": summary, "exports": exports}, allow_nan=False), flush=True)
            if not args.follow:
                return 0 if all(row["status"] != "LOCAL_EXPORT_OR_BINDING_REQUIRES_REVIEW"
                                for row in exports) else 1
            until = time.monotonic() + _delay(summary)
            while not stop and time.monotonic() < until:
                time.sleep(min(0.5, max(0, until - time.monotonic())))
        return 0
    except KeyboardInterrupt:
        return 0
    except (ValueError, OSError, KeyError, TypeError, OverflowError, RuntimeError, sqlite3.Error):
        print("CAPTURE_ARGUMENTS_REJECTED_OR_STORAGE_UNAVAILABLE", file=sys.stderr)
        return 2
    finally:
        for name, handler in previous.items():
            signal.signal(name, handler)
        if collector is not None:
            collector.close()


if __name__ == "__main__":
    raise SystemExit(main())
