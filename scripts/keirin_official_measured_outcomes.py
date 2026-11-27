"""Read a pinned official-SP archive day and emit a source-free aggregate scorecard."""
import argparse
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
from subprocess import TimeoutExpired
from tempfile import TemporaryDirectory

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_official_combined_study as study
from race_ai import keirin_official_learned_replay as learned_replay
from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_run_history as history
from race_ai import keirin_public_forecasts as public
from race_ai.keirin_official_paired_measurement import SCHEMA, measure_day
from scripts import keirin_capture_official_form_history as capture_files
from scripts import keirin_official_nationwide_continuation as continuation


def _freeze(output, public_pem, stage, payload, *, prefix='combined-study'):
    at, day = payload['observed_at'], payload['day_jst']
    name = f'{prefix}-{stage}.sealed.json'
    path = output / name
    sealed = history.seal_evidence(payload, public_pem, day, at)
    capture_files._save_once(path, sealed)
    readback = path.read_bytes()
    records.need(readback == sealed, 'STUDY_FREEZE_READBACK')
    return dict(file=name, frozen_at=at, sealed_sha256=sha256(readback).hexdigest(),
                plaintext_sha256=history._checked_cipher(readback)['evidence_plaintext_sha256'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--owner-public-pem', required=True)
    parser.add_argument('--day', required=True)
    parser.add_argument('--race-ids', help='Comma-separated race IDs for a private replay and aggregate report')
    study_mode = parser.add_mutually_exclusive_group()
    study_mode.add_argument('--combined-holdout-from', help='First evaluation cutoff (ISO-8601 with timezone)')
    study_mode.add_argument('--official-learned-replay', action='store_true',
                            help='Compare official saved A/B and the frozen learned research candidate')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    combined_study = args.combined_holdout_from is not None
    is_study = combined_study or args.official_learned_replay
    if (args.race_ids is not None or is_study) and args.publish:
        parser.error('A selected cohort cannot replace the published day report')
    requested = args.race_ids.split(',') if args.race_ids is not None else None
    if combined_study and not requested:
        parser.error('A combined study requires a selected cohort')
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    try:
        repo, root, day, owner_public_pem, code_commit = continuation._runtime(
            repo=args.repo, private_root=args.private_root, owner_public_pem=args.owner_public_pem,
            owner_private_pem=private, day=args.day, clock=continuation.now_utc,
            mode='study' if is_study else 'measure')
        checked_at = continuation.now_utc()
        with TemporaryDirectory(prefix='measurement-archive-', dir=root) as folder:
            reader = Path(folder)
            archive._cmd(reader, 'init', '--quiet', '--template=')
            archive._cmd(reader, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
            archive._cmd(reader, 'config', '--local', 'remote.origin.promisor', 'true')
            archive._cmd(reader, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
            # Conditional originals prove lineage against an earlier archive
            # commit. Retain its ancestry without downloading unrelated blobs.
            head = records.fetch_partial_head(reader, with_ancestry=True)
            store = records.RecordStore(reader, day, index_commit=head)
            if args.official_learned_replay:
                candidate = learned_replay.load_candidate(repo, private, day)
                output = capture_files._private_directory(root.parent / 'safe')
                report = learned_replay.run(store, private, candidate, clock=continuation.now_utc,
                    requested_race_ids=requested, freeze=partial(_freeze, output, owner_public_pem,
                                                                 prefix='official-learned-replay'))
            elif combined_study:
                output = capture_files._private_directory(root.parent / 'safe')
                report = study.run(store, private, requested, holdout_from=model.when(args.combined_holdout_from),
                                   clock=continuation.now_utc, freeze=partial(_freeze, output, owner_public_pem))
            else:
                admit_pair = partial(records.admit_saved_pair, history_cache={})
                report = measure_day(store, private, admit_condition_pair=admit_pair,
                                     requested_race_ids=requested,
                                     combined_replay_at=checked_at.isoformat() if requested is not None else None)
            index_sha = model.digest(store.index)
        report.update(scoring_code_commit=code_commit, scoring_action_run_id=os.environ['GITHUB_RUN_ID'])
        if args.publish:
            from race_ai import keirin_measurement_publication as publication

            report['publication'] = publication.publish_day(public.PublicForecastGit(repo), report,
                                        index_sha256=index_sha, checked_at=checked_at)
    except (ValueError, KeyError, TypeError, OSError, TimeoutExpired, ImportError):
        schema = learned_replay.SCHEMA if args.official_learned_replay else study.SCHEMA if combined_study else SCHEMA
        print(json.dumps(dict(schema=schema,
                              state='HOLD_OFFICIAL_MEASUREMENT_RUNTIME_OR_EVIDENCE_UNAVAILABLE')))
        return 2
    finally:
        private = b''
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return int(is_study and report['state'] not in ('HISTORICAL_STUDY_MEASURED', 'OFFICIAL_LEARNED_REPLAY_MEASURED'))


if __name__ == '__main__':
    raise SystemExit(main())
