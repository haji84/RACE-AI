"""Read a pinned official-SP archive day and emit only an aggregate scorecard."""
import argparse
from functools import partial
import json
import os
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_public_forecasts as public
from race_ai.keirin_official_paired_measurement import SCHEMA, measure_day
from scripts import keirin_official_nationwide_continuation as continuation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--owner-public-pem', required=True)
    parser.add_argument('--day', required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    try:
        repo, root, day, _, code_commit = continuation._runtime(
            repo=args.repo, private_root=args.private_root, owner_public_pem=args.owner_public_pem,
            owner_private_pem=private, day=args.day, clock=continuation.now_utc, mode='measure')
        checked_at = continuation.now_utc()
        with TemporaryDirectory(prefix='measurement-archive-', dir=root) as folder:
            reader = Path(folder)
            archive._cmd(reader, 'init', '--quiet', '--template=')
            archive._cmd(reader, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
            archive._cmd(reader, 'config', '--local', 'remote.origin.promisor', 'true')
            archive._cmd(reader, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
            store = records.RecordStore(reader, day, partial_read=True)
            admit_pair = partial(records.admit_saved_pair, history_cache={})
            report = measure_day(store, private, admit_condition_pair=admit_pair)
            index_sha = model.digest(store.index)
        report.update(scoring_code_commit=code_commit, scoring_action_run_id=os.environ['GITHUB_RUN_ID'])
        if args.publish:
            from race_ai import keirin_measurement_publication as publication

            report['publication'] = publication.publish_day(public.PublicForecastGit(repo), report,
                                        index_sha256=index_sha, checked_at=checked_at)
    except (ValueError, KeyError, TypeError, OSError, TimeoutExpired):
        print(json.dumps(dict(schema=SCHEMA, state='HOLD_OFFICIAL_MEASUREMENT_RUNTIME_OR_EVIDENCE_UNAVAILABLE')))
        return 2
    finally:
        private = b''
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
