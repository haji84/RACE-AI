"""File-based private evaluation journal CLI; no fetching, fitting or prediction.

JSON inputs may use ordinary formatting; duplicate keys/nonfinite numbers are
rejected. Expected digests use canonical JSON without a trailing newline.
Only metadata is printed. Full reports require an explicit create-only file.
Reveal/append defer all label-file I/O to the journal's reserved reader callback.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from .evaluation_experiment import EvaluationError, moment
from .evaluation_journal import EvaluationJournal

MAX_JSON_BYTES = 100_000_000


class CliError(ValueError):
    """Contains only a fixed public error code, never source content."""


def canonical_bytes(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise CliError('INPUT_JSON_INVALID') from None


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path):
    """This function must only be called inside the reader for label files."""
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise CliError('INPUT_NOT_REGULAR_FILE')
    if path.stat().st_size > MAX_JSON_BYTES:
        raise CliError('INPUT_TOO_LARGE')
    with path.open('rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise CliError('INPUT_NOT_REGULAR_FILE')
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise CliError('INPUT_TOO_LARGE')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise CliError('INPUT_DUPLICATE_KEY')
            result[key] = value
        return result

    def nonfinite(_value):
        raise CliError('INPUT_JSON_INVALID')

    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=nonfinite)
        canonical_bytes(value)  # Also rejects overflow such as 1e999.
        return value
    except CliError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise CliError('INPUT_JSON_INVALID') from None


def export_report(path, report):
    raw = canonical_bytes(report) + b'\n'
    if len(raw) > MAX_JSON_BYTES:
        raise CliError('OUTPUT_TOO_LARGE')
    path = Path(path)
    if path.is_symlink():
        raise CliError('OUTPUT_LINK_REJECTED')
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise CliError('OUTPUT_READBACK_MISMATCH')


class SafeParser(argparse.ArgumentParser):
    def error(self, _message):
        raise CliError('INVALID_ARGUMENTS')


def sha_argument(value):
    if not re.fullmatch('[0-9a-f]{64}', value):
        raise argparse.ArgumentTypeError('canonical SHA256 required')
    return value


def parser():
    root = SafeParser(description=__doc__)
    commands = root.add_subparsers(dest='command', required=True, parser_class=SafeParser)
    for command in ('register', 'seal', 'reveal', 'append', 'report'):
        sub = commands.add_parser(command)
        sub.add_argument('--root', required=True, type=Path, help='trusted private shared registry')
        sub.add_argument('--experiment', required=True)
        if command == 'register':
            sub.add_argument('--plan', required=True, type=Path)
        if command in ('register', 'seal'):
            sub.add_argument('--expected-plan-sha', required=True, type=sha_argument)
        if command == 'seal':
            sub.add_argument('--contexts', required=True, type=Path)
            sub.add_argument('--outputs', required=True, type=Path)
        if command in ('reveal', 'append'):
            sub.add_argument('--labels', required=True, type=Path)
        if command in ('reveal', 'append', 'report'):
            sub.add_argument('--expected-seal-sha', required=True, type=sha_argument)
        if command in ('append', 'report'):
            sub.add_argument('--expected-report-sha', required=command == 'append', type=sha_argument)
        if command == 'append':
            sub.add_argument('--batch-number', required=True, type=int)
        if command == 'report':
            sub.add_argument('--through-batch', type=int, help='explicit completed batch: 0 is initial; omitted means latest')
            sub.add_argument('--output', type=Path, help='exclusive private report export')
    return root


def report_summary(report):
    return {'report_sha256': digest(report), 'seal_sha256': report['seal_sha256'],
            'model_rows': len(report['models']), 'cohort_races': sum(report['split_counts'].values()),
            'split_counts': report['split_counts'], 'mode': report['mode']}


def execute(args):
    journal = EvaluationJournal(args.root, args.experiment)
    now = lambda: datetime.now(timezone.utc).isoformat()
    if args.command == 'register':
        plan = read_json(args.plan)
        if digest(plan) != args.expected_plan_sha:
            raise CliError('EXPECTED_DIGEST_MISMATCH')
        if type(plan) is not dict or 'declared_at' not in plan or moment(plan['declared_at']) > moment(now()):
            raise CliError('PLAN_DECLARED_IN_FUTURE')
        result = {'plan_sha256': journal.register(plan), 'cohort_races': len(plan['races']),
                  'models': len(plan['models']), 'stages': len(plan['stages'])}
    elif args.command == 'seal':
        contexts, outputs = read_json(args.contexts), read_json(args.outputs)
        sealed = journal.seal(contexts, outputs, sealed_at=now(), expected_plan_sha256=args.expected_plan_sha)
        result = {'seal_sha256': sealed['seal_sha256'], 'plan_sha256': sealed['plan_sha256'],
                  'contexts': len(sealed['contexts']), 'outputs': len(sealed['outputs']), 'sealed_at': sealed['sealed_at']}
    elif args.command == 'reveal':
        report = journal.reveal(lambda: read_json(args.labels), expected_seal_sha256=args.expected_seal_sha, now=now())
        result = report_summary(report)
    elif args.command == 'append':
        report = journal.append_results(lambda: read_json(args.labels), batch_number=args.batch_number,
            expected_report_sha256=args.expected_report_sha, expected_seal_sha256=args.expected_seal_sha, now=now())
        result = {**report_summary(report), 'batch_number': args.batch_number}
    else:
        report = journal.read_report(expected_seal_sha256=args.expected_seal_sha, through_batch=args.through_batch)
        if args.expected_report_sha is not None and digest(report) != args.expected_report_sha:
            raise CliError('EXPECTED_DIGEST_MISMATCH')
        if args.output is not None:
            export_report(args.output, report)
        result = {**report_summary(report), 'through_batch': args.through_batch,
                  'selection': 'LATEST' if args.through_batch is None else 'EXPLICIT_COMPLETED_BATCH',
                  'report_exported': args.output is not None}
    return {'status': 'OK', 'operation': args.command, **result}


def main(argv=None):
    try:
        result = execute(parser().parse_args(argv))
    except CliError as exc:
        error = exc.args[0]
    except FileExistsError:
        error = 'FILE_ALREADY_EXISTS'
    except FileNotFoundError:
        error = 'FILE_NOT_FOUND'
    except OSError:
        error = 'FILE_ACCESS_ERROR'
    except (EvaluationError, ValueError, TypeError, KeyError, RecursionError):
        error = 'JOURNAL_REJECTED'
    else:
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    print(json.dumps({'status': 'ERROR', 'error': error}, sort_keys=True), file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
