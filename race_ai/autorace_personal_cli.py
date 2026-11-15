"""One-shot personal AUTORACE A/B CLI with no HTTP, secrets or web scraping.

python -m race_ai.autorace_personal_cli predict --input PRIVATE/observed.json --output PRIVATE/A.json
python -m race_ai.autorace_personal_cli compare --input PRIVATE/A.json --result PRIVATE/result.json --output PRIVATE/score.json

Only explicitly observed pre-race measurements enter predictions. Output files
are create-only and local, *not* independently time-attested frozen forecasts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat

from .autorace_personal_baseline import predict_personal, preview_personal_result

MAX_BYTES = 1_000_000
REPO_ROOT = Path(__file__).resolve().parents[1]


def _check_outside_repo(path):
    resolved = Path(path).absolute()
    if resolved.is_relative_to(REPO_ROOT):
        raise ValueError("PRIVATE_FILES_MUST_NOT_BE_INSIDE_GIT_REPO")
    return resolved


def _read(path):
    p = _check_outside_repo(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_BYTES:
        raise ValueError("PRIVATE_INPUT_INVALID")
    data = p.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError("PRIVATE_INPUT_OVERSIZED")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("DUPLICATE_INPUT_JSON_KEY")
            out[key] = value
        return out
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ValueError("NONFINITE_INPUT_JSON")))
    except (UnicodeError, RecursionError):
        raise ValueError("PRIVATE_INPUT_NOT_JSON") from None


def _write_exclusive(path, value):
    path = _check_outside_repo(path)
    if os.name != "posix":
        raise ValueError("PRIVATE_FILE_ACL_NOT_VERIFIED")
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise ValueError("PRIVATE_OUTPUT_PATH_INVALID")
    if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise ValueError("OUTPUT_DIRECTORY_NOT_PRIVATE")
    try:
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)+"\n").encode("utf-8")
    except (ValueError, TypeError):
        raise ValueError("INVALID_FORECAST_JSON") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("PRIVATE_OUTPUT_OVERSIZED")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    if path.read_bytes() != raw:
        raise ValueError("PRIVATE_WRITE_READBACK_MISMATCH")
    return path


def run_predict(input_path, output_path, *, clock=None):
    stamp = (clock or (lambda: datetime.now(timezone.utc)))()
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise ValueError("OFFSET_AWARE_CLOCK_REQUIRED")
    prediction = predict_personal(_read(input_path), generated_at=stamp.isoformat())
    path = _write_exclusive(output_path, prediction)
    return {"mode": "PERSONAL_OBSERVED_PREDICTION", "stored_at": str(path),
            "phase": prediction["phase"], "race_id": prediction["race_id"],
            "forecast_sha256": prediction["prediction_sha256"],
            "official_prediction": False, "formal_hit_at_8_eligible": False}


def run_compare(input_path, result_path, output_path, *, clock=None):
    stamp = (clock or (lambda: datetime.now(timezone.utc)))()
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise ValueError("OFFSET_AWARE_CLOCK_REQUIRED")
    preview = preview_personal_result(_read(input_path), _read(result_path),
                                      observed_at=stamp.isoformat())
    path = _write_exclusive(output_path, preview)
    return {"mode": "PERSONAL_RESULT_PREVIEW", "stored_at": str(path),
            "race_id": preview["race_id"],
            "classification": preview["classification"],
            "formal_hit_at_8_eligible": False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    for action in ("predict","compare"):
        item=sub.add_parser(action)
        item.add_argument("--input",required=True)
        item.add_argument("--output",required=True)
        if action=="compare":
            item.add_argument("--result",required=True)
    args=parser.parse_args(argv)
    answer=(run_predict(args.input,args.output) if args.command=="predict" else
            run_compare(args.input,args.result,args.output))
    # Print metadata only. Never expose the entire private prediction JSON.
    print(json.dumps(answer,ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    main()
