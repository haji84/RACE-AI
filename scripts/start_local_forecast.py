"""Start the existing forecast UI on Linux/WSL without public deployment.

An optional bundled private-seed is installed once, with exact byte validation,
into a new owner-only directory. Existing stores are never reseeded. --check
reads readiness and the existing journal only; it does not collect or predict.
"""
import argparse
import ctypes
import ctypes.util
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) in sys.path:
    sys.path.remove(str(ROOT))
sys.path.insert(0, str(ROOT))

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
MAX_FILE = 256 * 1024 * 1024
MAX_SEED = 512 * 1024 * 1024
PINNED_FILES = (
    "pr64-reference/race_ai/core.py",
    "pr64-reference/race_ai/official_archive_probe.py",
    "pr64-reference/race_ai/official_lzh_extract.py",
    "pr72-reference/race_ai/boat_observed_program_bridge.py",
)


class LaunchError(ValueError):
    """A fixed local readiness error; never include a private path or payload."""


def _need(value, code):
    if not value:
        raise LaunchError(code)


def _no_git(fd):
    try:
        os.stat(".git", dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise LaunchError("PRIVATE_DIRECTORY_MUST_BE_OUTSIDE_GIT")


def _open_dir(path, *, create=False, outside_git=False):
    path = Path(path)
    _need(path.is_absolute() and ".." not in path.parts, "ABSOLUTE_PRIVATE_DIRECTORY_REQUIRED")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            if outside_git:
                _no_git(fd)
            try:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = following
        if outside_git:
            _no_git(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private_store(parent, name):
    folder = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        info = os.fstat(folder)
        _need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
              "PRIVATE_DIRECTORY_MODE_REQUIRED")
        _no_git(folder)
        try:
            source = os.open("forecast.sqlite", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
        except FileNotFoundError:
            raise LaunchError("EXISTING_PRIVATE_DIRECTORY_INCOMPLETE") from None
        try:
            info = os.fstat(source)
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                  info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600,
                  "PRIVATE_DATABASE_REQUIRED")
        finally:
            os.close(source)
    finally:
        os.close(folder)


def _read_seed_file(root, name, limit):
    folder = os.dup(root)
    try:
        parts = name.split("/")
        for part in parts[:-1]:
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = following
        source = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            os.close(source)
            raise LaunchError("PRIVATE_SEED_FILE_REJECTED")
        return source, info
    finally:
        os.close(folder)


def _scan_seed(root, prefix=""):
    found = set()
    for name in os.listdir(root):
        _need(NAME.fullmatch(name) is not None, "PRIVATE_SEED_NAME_REJECTED")
        info = os.stat(name, dir_fd=root, follow_symlinks=False)
        relative = prefix + name
        if stat.S_ISDIR(info.st_mode):
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            try:
                found.update(_scan_seed(child, relative + "/"))
            finally:
                os.close(child)
        else:
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "PRIVATE_SEED_LINK_REJECTED")
            found.add(relative)
    return found


def _manifest(seed):
    source, _ = _read_seed_file(seed, "manifest.json", 1024 * 1024)
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "PRIVATE_SEED_MANIFEST_REJECTED")
            result[key] = value
        return result
    with os.fdopen(source, "rb") as stream:
        value = json.load(stream, object_pairs_hook=pairs)
    _need(type(value) is dict and type(value.get("files")) is list and
          1 <= len(value["files"]) <= 4096, "PRIVATE_SEED_MANIFEST_REJECTED")
    names = set()
    total = 0
    for row in value["files"]:
        _need(type(row) is dict and set(row) == {"file", "sha256", "bytes"}, "PRIVATE_SEED_MANIFEST_REJECTED")
        name = row["file"]
        _need(type(name) is str and 0 < len(name) <= 1024 and name != "manifest.json" and
              all(NAME.fullmatch(part) for part in name.split("/")), "PRIVATE_SEED_NAME_REJECTED")
        _need(name not in names and type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_FILE and
              type(row["sha256"]) is str and SHA.fullmatch(row["sha256"]) is not None,
              "PRIVATE_SEED_MANIFEST_REJECTED")
        names.add(name)
        total += row["bytes"]
    _need("forecast.sqlite" in names and total <= MAX_SEED, "PRIVATE_SEED_DATABASE_REQUIRED")
    _need(_scan_seed(seed) == names | {"manifest.json"}, "PRIVATE_SEED_CONTENTS_REJECTED")
    return value["files"]


def _copy_verified(seed, stage, row):
    source, before = _read_seed_file(seed, row["file"], MAX_FILE)
    folder = os.dup(stage)
    try:
        _need(before.st_size == row["bytes"], "PRIVATE_SEED_SIZE_MISMATCH")
        parts = row["file"].split("/")
        for part in parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=folder)
            except FileExistsError:
                pass
            following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = following
        target = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=folder)
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(target, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            while True:
                chunk = os.read(source, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                _need(size <= row["bytes"], "PRIVATE_SEED_SIZE_MISMATCH")
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(source)
        _need(size == row["bytes"] and digest.hexdigest() == row["sha256"] and
              (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns, before.st_size) ==
              (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_size) and
              after.st_nlink == 1, "PRIVATE_SEED_SHA_MISMATCH")
        os.fsync(folder)
    finally:
        os.close(source)
        os.close(folder)


def _rename_noreplace(parent, old, new):
    """Linux atomic publication; unlike rename(), never replace an empty target."""
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    _need(rename is not None, "ATOMIC_PRIVATE_INSTALL_UNAVAILABLE")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(parent, os.fsencode(old), parent, os.fsencode(new), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, "PRIVATE_INSTALL_NOT_PUBLISHED")


def prepare_private_root(private_root, seed_root=None):
    target = Path(private_root)
    _need(os.name == "posix" and target.is_absolute() and ".." not in target.parts and
          NAME.fullmatch(target.name), "ABSOLUTE_PRIVATE_DIRECTORY_REQUIRED")
    parent = _open_dir(target.parent, create=True, outside_git=True)
    stage_name = None
    try:
        info = os.fstat(parent)
        sticky = bool(info.st_mode & stat.S_ISVTX)
        _need((info.st_uid == os.getuid() or sticky) and (not info.st_mode & 0o022 or sticky),
              "PRIVATE_PARENT_REJECTED")
        try:
            os.stat(target.name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            _private_store(parent, target.name)
            return target
        if seed_root is None or not os.path.lexists(seed_root):
            os.mkdir(target.name, 0o700, dir_fd=parent)
            os.fsync(parent)
            return target
        seed = _open_dir(Path(seed_root))
        try:
            rows = _manifest(seed)
            stage_name = "race-ai-seed-" + secrets.token_hex(12)
            os.mkdir(stage_name, 0o700, dir_fd=parent)
            stage = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                for row in rows:
                    _copy_verified(seed, stage, row)
                os.fsync(stage)
            finally:
                os.close(stage)
            _rename_noreplace(parent, stage_name, target.name)
            stage_name = None
            os.fsync(parent)
            return target
        finally:
            os.close(seed)
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise LaunchError("PRIVATE_INITIALIZATION_REJECTED") from None
    finally:
        if stage_name is not None:
            # /proc binds cleanup to the open parent even if an ancestor moves.
            shutil.rmtree(f"/proc/self/fd/{parent}/{stage_name}", ignore_errors=True)
        os.close(parent)


def check_runtime(root):
    _need(sys.platform == "linux" and os.name == "posix" and
          Path("/proc/self/fd").is_dir() and sys.version_info >= (3, 10), "LINUX_OR_WSL_RUNTIME_REQUIRED")
    _need(all((Path(root) / name).is_file() for name in PINNED_FILES), "PINNED_REFERENCE_FILES_REQUIRED")
    library = ctypes.util.find_library("archive")
    if library:
        try:
            archive = ctypes.CDLL(library)
            _need(all(hasattr(archive, symbol) for symbol in
                ("archive_read_new", "archive_read_support_format_lha", "archive_read_open_memory",
                 "archive_read_next_header", "archive_entry_pathname", "archive_read_data", "archive_read_free")),
                "LZH_RUNTIME_REQUIRED")
            return
        except OSError:
            pass
    _need(importlib.util.find_spec("lhafile") is not None, "LZH_RUNTIME_REQUIRED")


def main(argv=None):
    parser = argparse.ArgumentParser(description="RACE-AI: owner-only local forecast launcher (Linux/WSL)")
    parser.add_argument("--private-dir", type=Path, default=Path.home()/".local/share/race-ai-owner")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check", action="store_true", help="check local readiness without fetching or predicting")
    args = parser.parse_args(argv)
    try:
        _need(type(args.port) is int and 0 <= args.port <= 65535, "LOCAL_PORT_REQUIRED")
        check_runtime(ROOT)
        private = prepare_private_root(args.private_dir, ROOT/"private-seed")
        from race_ai.local_forecast_service import LocalForecastService
        service = LocalForecastService(private)
        if args.check:
            status = service.status()
            print("LOCAL_FORECAST_READY: saved_predictions=" + str(status["saved_prediction_count"]))
            return 0
        from race_ai.local_forecast_server import make_server
        with make_server(service, port=args.port) as server:
            print("RACE-AI local forecast: " + server.origin, flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return 0
    except (LaunchError, OSError, ValueError, ImportError):
        print("LOCAL_FORECAST_START_FAILED: Linux/WSL・固定参照ファイル・LZH実行環境・私有保存先を確認してください。既存原本は上書きしません。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
