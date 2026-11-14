"""Publish only whitelisted operational counters beside encrypted continuity."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from race_ai import boat_source_control as safe
from scripts.boat_history_collect import private_root, save


def pack(*, cipher_path, output_dir):
    safe.need(os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == safe.REPO
        and os.environ.get("GITHUB_REPOSITORY_ID") == str(safe.REPO_ID), "EXISTING_ACTIONS_REQUIRED")
    run = os.environ.get("GITHUB_RUN_ID", ""); head = os.environ.get("GITHUB_SHA", "")
    safe.need(re.fullmatch(r"[1-9][0-9]{0,19}", run) and re.fullmatch(r"[a-f0-9]{40}", head), "CURRENT_RUN_HEAD_REQUIRED")
    runner = Path(os.environ.get("RUNNER_TEMP", "")); output = Path(output_dir).absolute(); path = Path(cipher_path).absolute()
    safe.need(runner.is_absolute() and runner.is_dir() and not any(p.is_symlink()
        for p in (path, output, runner, *path.parents, *output.parents, *runner.parents)), "PRIVATE_RUNNER_PATH_REQUIRED")
    runner, output, path = runner.resolve(), output.resolve(), path.resolve()
    safe.need(not runner.is_relative_to(ROOT.resolve()) and output.is_relative_to(runner) and output != runner
        and path.is_relative_to(runner) and output != path.parent
        and not any((p/".git").exists() for p in (runner, *runner.parents)), "PRIVATE_RUNNER_PATH_REQUIRED")
    info = path.stat()
    safe.need(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o077 and info.st_nlink == 1
              and 0 < info.st_size <= safe.MAX_CONTINUITY_ZIP, "PRIVATE_CIPHER_REQUIRED")
    with path.open("rb") as stream: cipher = stream.read(safe.MAX_CONTINUITY_ZIP+1)
    safe.need(len(cipher) == info.st_size, "CIPHER_CHANGED")
    summary = safe.build_summary(cipher, run_id=int(run), head_sha=head)
    raw = (json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)+"\n").encode()
    safe.need(len(raw) <= safe.MAX_SUMMARY, "SUMMARY_BOUND_INVALID")
    private_root(output)
    safe.need({p.name for p in output.iterdir()} <= {safe.MEMBER}, "SOLE_SUMMARY_OUTPUT_REQUIRED")
    save(output/safe.MEMBER, raw)
    return dict(ready=True, artifact_name=f"race-source-control-{run}", path=str(output/safe.MEMBER),
                run_id=int(run), requests_used=summary["control"]["requests_used"],
                completed_round=summary["control"]["completed_round"], summary_sha256=sha256(raw).hexdigest())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("pack")
    command.add_argument("--cipher", required=True, dest="cipher_path", type=Path)
    command.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try: result = pack(cipher_path=args.cipher_path, output_dir=args.output_dir)
    except (ValueError, OSError, KeyError, TypeError):
        result = dict(ready=False)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            for field in ("ready", "artifact_name", "path"):
                if field in result:
                    value = str(result[field]).lower() if type(result[field]) is bool else str(result[field])
                    safe.need("\n" not in value and "\r" not in value, "OUTPUT_INVALID")
                    output.write(field+"="+value+"\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("path", "artifact_name")}, sort_keys=True))
    return 0 if result["ready"] else 2


if __name__ == "__main__": raise SystemExit(main())
