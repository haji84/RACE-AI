"""Offline runner for a private, SHA-pinned owner-authored 71R audit.

Consumes ONLY previously obtained private licensed-result rows; makes zero
network calls. Intended to be invoked by the existing KEIRIN Actions producer
AFTER its separately authorized input and owner-private forecast restoration.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from race_ai.keirin_manual_result_sync import (
    ManualSyncError, evaluate, public_counters, read_categories,
    read_forecast, read_result_candidates, render_html,
)


def _private_path(value):
    p = Path(value).absolute()
    workspace = os.environ.get('GITHUB_WORKSPACE')
    if workspace:
        public = Path(workspace).resolve()
        resolved = p.resolve()
        if resolved == public or public in resolved.parents:
            raise ManualSyncError('PUBLIC_GITHUB_WORKSPACE_PRIVATE_PATH_REFUSED')
    return p


def _write_private(path, content):
    p = _private_path(path)
    if p.is_symlink():
        raise ManualSyncError('OUTPUT_SYMLINK_REFUSED')
    p.parent.mkdir(parents=True, exist_ok=True)
    # Create without overwriting old private evidence; no public artifacts.
    fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        p.unlink(missing_ok=True)
        raise
    return p


def run(*, forecast, baseline, forecast_sha256, categories, template,
        result_dir, out_report, out_html, now=None):
    paths = [forecast, baseline, categories, template, result_dir, out_report, out_html]
    for p in paths:
        if p is not None:
            _private_path(p)
    d = read_forecast(forecast, expected_file_sha256=forecast_sha256,
                      baseline_file=baseline)
    labels = read_categories(categories,d)
    at = now or datetime.now(timezone.utc).isoformat()
    candidates = read_result_candidates(result_dir,as_of=at)
    # Mismatched race observations cannot silently join the 71R cohort.
    ids = {r['id'] for r in d['races']}
    if not set(candidates).issubset(ids):
        raise ManualSyncError('RESULT_RACE_NOT_IN_FORECAST_COHORT')
    output = evaluate(d,candidates,categories=labels)
    if out_report:
        _write_private(out_report,
                       (json.dumps(output,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    if out_html:
        if template is None:
            raise ManualSyncError('HTML_TEMPLATE_REQUIRED')
        txt = _private_path(template).read_text(encoding='utf-8')
        _write_private(out_html,render_html(output,d,template_text=txt).encode('utf-8'))
    return public_counters(output)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forecast',required=True)
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--forecast-sha256',required=True)
    parser.add_argument('--categories')
    parser.add_argument('--template')
    parser.add_argument('--result-dir',required=True)
    parser.add_argument('--out-report')
    parser.add_argument('--out-html')
    args=parser.parse_args(argv)
    try:
        result=run(forecast=args.forecast,baseline=args.baseline,
                   forecast_sha256=args.forecast_sha256,
                   categories=args.categories,template=args.template,
                   result_dir=args.result_dir,out_report=args.out_report,
                   out_html=args.out_html)
        print(json.dumps(result,ensure_ascii=False,sort_keys=True))
        return 0
    except (ManualSyncError,OSError,TypeError,ValueError,UnicodeError):
        # Never echo private paths/source URLs/forecast tickets in Actions logs.
        print('{"state":"HOLD_MANUAL_RESULT_SYNC_INPUT_OR_AUTHORITY","official_result_authenticated":false}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
