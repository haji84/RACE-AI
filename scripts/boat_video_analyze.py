"""Analyze explicitly identified local boat media into a private sealed report.

This command performs experimental image measurements, with no network access,
model updates, or accuracy claims. Supply the complete job manifest; identity,
roster, source metadata and capture timestamps are never invented. Optional
view enrichment writes a new private file and preserves the supplied original.
OpenCV and NumPy are required only when real extraction starts.
"""
from contextlib import ExitStack, contextmanager
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_ERROR = "BOAT_VIDEO_ANALYSIS_REJECTED"
_MAX_JOB = 2 * 1024 * 1024
_MAX_VIEW = 32 * 1024 * 1024


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default includes rejected argument values, possibly secrets.
        self.exit(2, _ERROR + ": invalid command arguments\n")


def _local_path(value):
    if (not isinstance(value, str) or not value or "\x00" in value
            or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value)
            or value.startswith("//") or ".." in Path(value).parts):
        raise ValueError(_ERROR)
    return Path(value).absolute()


@contextmanager
def _input_file(path):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError(_ERROR)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(_ERROR)
        yield source
        after = os.fstat(source.fileno())
        current = path.stat(follow_symlinks=False)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
                or current.st_nlink != 1):
            raise ValueError(_ERROR)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_ERROR)
        result[key] = value
    return result


def _constant(value):
    raise ValueError(_ERROR)


def _read_json(source, limit):
    if not 0 < os.fstat(source.fileno()).st_size <= limit:
        raise ValueError(_ERROR)
    raw = source.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError(_ERROR)
    value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
    if type(value) is not dict:
        raise ValueError(_ERROR)
    return value


def _require_new(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise ValueError(_ERROR)


def _write_new(parent, name, raw):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
    created = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            actual = os.fstat(stream.fileno())
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if actual.st_nlink != 1 or (current.st_dev, current.st_ino) != (created.st_dev, created.st_ino):
                raise ValueError(_ERROR)
        os.fsync(parent)
    except BaseException:
        try:
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                os.unlink(name, dir_fd=parent)
        except OSError:
            pass
        raise


def main(argv=None, *, extractor=None):
    """Run the local command; extractor injection supports isolated integration tests."""
    parser = _Parser(description=__doc__)
    parser.add_argument("--video", required=True, help="existing local regular video file")
    parser.add_argument("--job", required=True, help="complete explicit JSON job manifest")
    parser.add_argument("--private-root", required=True, help="existing owner-only 0700 directory outside Git")
    parser.add_argument("--view-in", help="original local JSON view to copy and enrich")
    parser.add_argument("--view-out", help="new output file in an existing directory outside Git")
    args = parser.parse_args(argv)
    if bool(args.view_in) != bool(args.view_out):
        parser.error("--view-in and --view-out must be supplied together")
    try:
        from race_ai.boat_video_evaluation import analyze_video, enrich_view, save_evaluation
        from race_ai.private_cycle_capture import _parent_handle

        media = _local_path(args.video)
        manifest = _local_path(args.job)
        private = _local_path(args.private_root)
        with ExitStack() as stack:
            private_fd = stack.enter_context(_parent_handle(private))
            private_info = os.fstat(private_fd)
            if private_info.st_uid != os.getuid() or stat.S_IMODE(private_info.st_mode) != 0o700:
                raise ValueError(_ERROR)
            stack.enter_context(_input_file(media))
            job_source = stack.enter_context(_input_file(manifest))
            job = _read_json(job_source, _MAX_JOB)
            original = destination = output_parent = None
            if args.view_in:
                original_path = _local_path(args.view_in)
                view_source = stack.enter_context(_input_file(original_path))
                original = _read_json(view_source, _MAX_VIEW)
                destination = _local_path(args.view_out)
                output_parent = stack.enter_context(_parent_handle(destination.parent))
                _require_new(output_parent, destination.name)

            # The default path uses the real clock and the lazy local extractor.
            report = (analyze_video(media, job) if extractor is None else
                      analyze_video(media, job, extractor=extractor))
            enriched = enrich_view(original, [report]) if original is not None else None
            raw_view = ((json.dumps(enriched, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
                        if enriched is not None else None)
            digest = save_evaluation(private, report)
            summary = {"report_sha256": digest,
                "report_path": str(private / "video-evaluations" / (digest + ".json")),
                "lane_count": len(report["measurements"]["lanes"]),
                "measured_phase_count": sum(phase["status"] == "MEASURED"
                    for lane in report["measurements"]["lanes"] for phase in lane["phases"].values())}
            if enriched is not None:
                summary.update(view_out=str(destination), attached_report_count=sum(
                    evaluation.get("report_sha256") == digest
                    for row in enriched.get("records", []) if type(row) is dict
                    and type(row.get("boat_video_evaluations")) is list
                    for evaluation in row.get("boat_video_evaluations", []) if type(evaluation) is dict))
                _write_new(output_parent, destination.name, raw_view)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, ImportError, RuntimeError):
        print(_ERROR, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
