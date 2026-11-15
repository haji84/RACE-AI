"""Stage the exact pre-outcome registered JS policy, never current mutable rules.

The registered three-file digest and git commit remain unchanged. Temporary
staging is private to the Actions runner. The existing settlement script then
uses the archived JS modules through ordinary relative require(), preserving
the frozen plan and every saved original. No provider requests are made.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

POLICY_PATHS = (
    "web/product-data.js",
    "web/saved-performance.js",
    "scripts/boat_budget_plan.cjs",
)
SUPPORT_PATHS = ("web/forecast-audit-model.js",)
SETTLEMENT = "scripts/boat_frozen_plan_settlement.cjs"


def _check(condition, code):
    if not condition:
        raise ValueError("REGISTERED_POLICY_" + code)


def _data(path):
    _check(path.is_file() and not path.is_symlink(), "REGULAR_FILE_REQUIRED")
    data = path.read_bytes()
    _check(0 < len(data) <= 2 * 1024 * 1024, "SOURCE_SIZE_INVALID")
    return data


def _head(path):
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, check=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        raise ValueError("REGISTERED_POLICY_COMMIT_UNAVAILABLE") from None
    return result.stdout.strip()


@contextmanager
def staged_registered_policy(registration, *, repository, temporary):
    """Provide a private module root only when git HEAD and all 3 hashes match."""
    _check(type(registration) is dict, "REGISTRATION_REQUIRED")
    commit = registration.get("policy_commit")
    mapping = registration.get("policy_files_sha256")
    _check(type(commit) is str and re.fullmatch(r"[a-f0-9]{40}", commit), "COMMIT_INVALID")
    _check(type(mapping) is dict and set(mapping) == set(POLICY_PATHS), "DIGEST_SCOPE_INVALID")
    _check(all(type(v) is str and re.fullmatch(r"[a-f0-9]{64}", v) for v in mapping.values()), "DIGEST_INVALID")
    repository = Path(repository).resolve(strict=True)
    reference = repository / "registered-policy-reference"
    _check(reference.is_dir() and not reference.is_symlink() and _head(reference) == commit,
           "COMMIT_MISMATCH")
    temporary = Path(temporary).resolve(strict=True)
    _check(temporary.is_dir() and not temporary.is_symlink(), "PRIVATE_TEMP_REQUIRED")
    for name in POLICY_PATHS:
        _check(hashlib.sha256(_data(reference / name)).hexdigest() == mapping[name],
               "REGISTERED_DIGEST_MISMATCH")
    for name in SUPPORT_PATHS:
        _data(reference / name)
    settlement = _data(repository / SETTLEMENT)
    with tempfile.TemporaryDirectory(prefix="race-registered-policy-", dir=temporary) as folder:
        staged = Path(folder)
        os.chmod(staged, 0o700)
        for name in (*POLICY_PATHS, *SUPPORT_PATHS, SETTLEMENT):
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            contents = settlement if name == SETTLEMENT else _data(reference / name)
            with target.open("xb") as stream:
                stream.write(contents)
            os.chmod(target, 0o600)
            if name in mapping:
                _check(hashlib.sha256(_data(target)).hexdigest() == mapping[name],
                       "STAGED_DIGEST_MISMATCH")
        yield staged
