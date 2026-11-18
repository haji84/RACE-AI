"""Open a complete encrypted owner-view snapshot locally, without network I/O.

The existing owner PEM stays local. A DELTA is not a complete view and is
rejected; this command never fetches state, runs settlement, or writes Git.
Only a new 0600 HTML file inside an existing private 0700 directory is created.
"""
from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import stat

from race_ai import keirin_official_run_history as history
from race_ai import keirin_official_owner_report as report_view

FULL_SNAPSHOT_SCHEMA = "RACE_AI_KEIRIN_OFFICIAL_PRIVATE_DAY_V1"
MAX_KEY_BYTES = 20_000
MAX_HTML_BYTES = 16 * 1024 * 1024


class OwnerViewError(ValueError):
    pass


def _need(condition, code):
    if not condition:
        raise OwnerViewError(code)


def _path(value):
    path = Path(value)
    _need(path.is_absolute() and path == path.resolve() and
          not any(part.is_symlink() for part in (path, *path.parents)),
          "OWNER_VIEW_ABSOLUTE_PATH_WITHOUT_SYMLINKS_REQUIRED")
    return path


def _read_input(path, limit, *, private_key=False):
    path = _path(path)
    _need(path.is_file(), "OWNER_VIEW_EXISTING_LOCAL_FILE_REQUIRED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= limit,
              "OWNER_VIEW_INPUT_SIZE_OR_TYPE_INVALID")
        if private_key:
            mode = stat.S_IMODE(info.st_mode)
            _need(mode & 0o077 == 0 and mode & 0o400,
                  "OWNER_VIEW_KEY_PERMISSIONS_MUST_BE_OWNER_ONLY")
        raw = stream.read(limit + 1)
        _need(len(raw) == info.st_size and len(raw) <= limit,
              "OWNER_VIEW_INPUT_CHANGED_OR_TOO_LARGE")
    return raw


def _destination(value):
    path = _path(value)
    parent = path.parent
    _need(parent.is_dir() and stat.S_IMODE(parent.stat().st_mode) == 0o700,
          "OWNER_VIEW_PRIVATE_0700_OUTPUT_DIRECTORY_REQUIRED")
    _need(not path.exists() and not path.is_symlink(),
          "OWNER_VIEW_OUTPUT_MUST_BE_NEW")
    _need(not any((folder / ".git").exists() for folder in path.parents),
          "OWNER_VIEW_PLAINTEXT_OUTPUT_CANNOT_BE_IN_GIT")
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        public = Path(workspace).resolve()
        _need(path != public and public not in path.parents,
              "OWNER_VIEW_PLAINTEXT_OUTPUT_CANNOT_BE_IN_WORKSPACE")
    return path


def _write_new_private(path, raw):
    """Create relative to the opened private directory; read back exact bytes."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(path.parent, flags)
    created = False
    try:
        _need(stat.S_IMODE(os.fstat(parent_fd).st_mode) == 0o700,
              "OWNER_VIEW_OUTPUT_DIRECTORY_PERMISSIONS_CHANGED")
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent_fd)
        created = True
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        read_fd = os.open(path.name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                          dir_fd=parent_fd)
        with os.fdopen(read_fd, "rb") as stream:
            _need(stream.read(MAX_HTML_BYTES + 1) == raw,
                  "OWNER_VIEW_HTML_READBACK_MISMATCH")
    except Exception:
        if created:
            os.unlink(path.name, dir_fd=parent_fd)
        raise
    finally:
        os.close(parent_fd)


def render_snapshot(*, cipher_path, owner_private_pem_path, out_path):
    """Authenticate the supplied full snapshot and create one private HTML file."""
    out = _destination(out_path)
    raw = _read_input(cipher_path, history.MAX_CIPHER_BYTES)
    key = _read_input(owner_private_pem_path, MAX_KEY_BYTES, private_key=True)
    payload = history.decrypt_evidence(raw, key)
    _need(payload.get("schema") == FULL_SNAPSHOT_SCHEMA and
          type(payload.get("safe_report")) is dict and
          type(payload.get("owner_rows")) is list,
          "OWNER_VIEW_FULL_SNAPSHOT_REQUIRED_DELTA_UNSUPPORTED")
    report = payload["safe_report"]
    _need(payload.get("day_jst") == report.get("day_jst"),
          "OWNER_VIEW_SNAPSHOT_DAY_MISMATCH")
    html = report_view.render_private_report(report, payload["owner_rows"]).encode("utf-8")
    _need(0 < len(html) <= MAX_HTML_BYTES, "OWNER_VIEW_HTML_TOO_LARGE")
    _write_new_private(out, html)
    return {"state": "PRIVATE_OWNER_VIEW_CREATED", "day_jst": report["day_jst"],
            "registered_races": report["registered_races"],
            "paired_A_B_scored": report["paired_A_B_scored"]}


class _SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unrecognized arguments; they could contain
        # an accidentally pasted key. Only a fixed code may reach the log.
        raise OwnerViewError("OWNER_VIEW_ARGUMENTS_INVALID")


def main(argv=None):
    parser = _SafeParser(description=__doc__)
    parser.add_argument("--cipher", required=True, help="Absolute encrypted full snapshot path")
    parser.add_argument("--owner-private-pem", required=True, help="Absolute existing owner-only PEM path")
    parser.add_argument("--out", required=True, help="New absolute HTML path in a private 0700 folder")
    try:
        args = parser.parse_args(argv)
        result = render_snapshot(cipher_path=args.cipher,
                                 owner_private_pem_path=args.owner_private_pem,
                                 out_path=args.out)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OwnerViewError, history.OfficialRunHistoryError,
            report_view.OwnerReportError) as exc:
        print(json.dumps({"state": "HOLD_PRIVATE_OWNER_VIEW", "reason": str(exc)}, sort_keys=True))
        return 2
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        print('{"state":"HOLD_PRIVATE_OWNER_VIEW",'
              '"reason":"OWNER_VIEW_PRIVATE_INPUT_OR_OUTPUT_UNAVAILABLE"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
