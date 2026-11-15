"""Pack exact native outputs into the existing Actions owner's encrypted ZIP."""
import argparse
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import stat
import sys
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from race_ai import boat_private_original_archive as archive


def _need(ok, reason):
    archive._need(ok, reason)


def _no_links(path):
    _need(not any(part.is_symlink() for part in (path, *path.parents)), 'PATH_SYMLINK_INVALID')


def _outside_git(path):
    _no_links(path)
    _need(not path.is_relative_to(ROOT.resolve())
          and not any((part/'.git').exists() for part in (path, *path.parents)), 'OUTPUT_OUTSIDE_GIT_REQUIRED')


class _BoundedZipBuffer(io.BytesIO):
    def write(self, value):
        _need(self.tell()+len(value) <= archive.MAX_PLAIN_ZIP, 'ZIP_BOUND_INVALID')
        return super().write(value)


def _files(path):
    _no_links(path)
    _need(path.exists(), 'EXISTING_INPUT_REQUIRED')
    pending = [(path, path.name)] if path.is_file() else [(path, '')]
    found = []
    total = 0
    visited = 0
    while pending:
        current, name = pending.pop()
        visited += 1
        _need(visited <= archive.MAX_ENTRIES+1, 'INPUT_ENTRIES_BOUND_INVALID')
        _no_links(current)
        info = current.lstat()
        if stat.S_ISDIR(info.st_mode):
            _need(len(pending)+len(found) < archive.MAX_ENTRIES, 'INPUT_ENTRIES_BOUND_INVALID')
            for child in sorted(current.iterdir(), key=lambda p: p.name, reverse=True):
                child_name = name+'/'+child.name if name else child.name
                archive._name(child_name)
                pending.append((child, child_name))
                _need(len(pending)+len(found) <= archive.MAX_ENTRIES, 'INPUT_ENTRIES_BOUND_INVALID')
        else:
            _need(stat.S_ISREG(info.st_mode), 'REGULAR_INPUT_REQUIRED')
            archive._name(name)
            total += info.st_size
            _need(0 <= info.st_size <= archive.MAX_EXPANDED and total <= archive.MAX_EXPANDED,
                  'ZIP_EXPANDED_BOUND_INVALID')
            found.append((name, current, info))
            _need(len(found) <= archive.MAX_ENTRIES, 'INPUT_ENTRIES_BOUND_INVALID')
    _need(found, 'NONEMPTY_INPUT_REQUIRED')
    return sorted(found), total


def _canonical_zip(path):
    files, total = _files(path)
    target = _BoundedZipBuffer()
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=False) as zipped:
        for name, current, original in files:
            _no_links(current)
            fd = os.open(current, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(fd, 'rb') as source:
                before = os.fstat(source.fileno())
                _need(stat.S_ISREG(before.st_mode) and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                      == (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns), 'INPUT_CHANGED')
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = (stat.S_IFREG | 0o600) << 16
                size = 0
                with zipped.open(entry, 'w') as member:
                    while block := source.read(min(1024*1024, original.st_size-size+1)):
                        size += len(block)
                        _need(size <= original.st_size, 'INPUT_CHANGED')
                        member.write(block)
                after = os.fstat(source.fileno())
                _need(size == original.st_size and (after.st_size, after.st_mtime_ns)
                      == (before.st_size, before.st_mtime_ns), 'INPUT_CHANGED')
    raw = target.getvalue()
    _need(len(raw) <= archive.MAX_PLAIN_ZIP, 'ZIP_BOUND_INVALID')
    return raw, len(files), total


def _existing(path, plain, *, run_id, head_sha, kind):
    _no_links(path)
    info = path.stat()
    _need(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077
          and info.st_nlink == 1 and 0 < info.st_size <= archive.MAX_WIRE, 'PRIVATE_CIPHER_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as source:
        raw = source.read(archive.MAX_WIRE+1)
    _need(len(raw) <= archive.MAX_WIRE, 'ENVELOPE_BOUND_INVALID')
    restored, header = archive._open_envelope(raw)
    _need(header['run_id'] == run_id and header['head_sha'] == head_sha and header['kind'] == kind
          and restored == plain, 'EXISTING_CIPHER_OVERWRITE_REJECTED')
    return raw


def _write(path, cipher):
    temporary = path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'wb') as target:
            target.write(cipher)
            target.flush()
            os.fsync(target.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def pack(*, kind, input_path, output_dir):
    """Return safe counts/hashes; publishable directory holds only ciphertext."""
    _need(type(kind) is str and kind in archive.KINDS, 'KIND_INVALID')
    run_id = archive._run(os.environ.get('GITHUB_RUN_ID'))
    head_sha = os.environ.get('GITHUB_SHA')
    _need(type(head_sha) is str and archive._HEAD.fullmatch(head_sha), 'HEAD_INVALID')
    runner = Path(os.environ.get('RUNNER_TEMP', ''))
    _need(runner.is_absolute() and runner.is_dir(), 'RUNNER_TEMP_REQUIRED')
    _outside_git(runner)
    runner = runner.resolve()
    out = Path(output_dir).absolute()
    _outside_git(out)
    out = out.resolve()
    _need(out.is_relative_to(runner) and out != runner, 'RUNNER_TEMP_OUTPUT_REQUIRED')
    source = Path(input_path).absolute()
    _no_links(source)
    source = source.resolve()
    _need(not (source.is_dir() and out.is_relative_to(source))
          and source != out/archive.CIPHER_MEMBER, 'INPUT_OUTPUT_OVERLAP_REJECTED')
    plain, file_count, expanded = _canonical_zip(source)
    # Build parents with private permissions; never relax an existing directory.
    missing = []
    parent = out
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o700)
    _no_links(out)
    _need(out.is_dir() and not out.stat().st_mode & 0o077, 'PRIVATE_OUTPUT_REQUIRED')
    _need({path.name for path in out.iterdir()} <= {archive.CIPHER_MEMBER}, 'SOLE_CIPHER_OUTPUT_REQUIRED')
    path = out/archive.CIPHER_MEMBER
    reused = path.exists()
    if reused:
        cipher = _existing(path, plain, run_id=run_id, head_sha=head_sha, kind=kind)
    else:
        cipher = archive.seal_original_zip(plain, run_id=run_id, head_sha=head_sha, kind=kind)
        try:
            _write(path, cipher)
        except FileExistsError:
            cipher = _existing(path, plain, run_id=run_id, head_sha=head_sha, kind=kind)
            reused = True
    return dict(status='PRIVATE_ORIGINAL_ARCHIVE_PACKED', file_count=file_count,
                uncompressed_bytes=expanded, inner_zip_bytes=len(plain),
                inner_zip_sha256=sha256(plain).hexdigest(), cipher_bytes=len(cipher),
                cipher_sha256=sha256(cipher).hexdigest(), reused=reused, plaintext_published=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('pack')
    command.add_argument('--kind', required=True, choices=sorted(archive.KINDS))
    command.add_argument('--input', required=True, dest='input_path', type=Path)
    command.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = pack(kind=args.kind, input_path=args.input_path, output_dir=args.output_dir)
    except (ValueError, OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
        print(json.dumps(dict(status='PRIVATE_ORIGINAL_ARCHIVE_REJECTED'), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
