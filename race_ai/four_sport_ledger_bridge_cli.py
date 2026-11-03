"""Offline read-only daily coverage-to-archive join; no provider requests or model calls."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from .discovery_audit_cli import _read_json
from .discovery_reconcile import CoverageError
from .four_sport_ledger_bridge import link_day


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', required=True)
    p.add_argument('--ledger', required=True)
    p.add_argument('--secondary-reference')
    p.add_argument('--seal', action='append', default=[], help='existing local evaluation seal JSON (read-only)')
    p.add_argument('--horse-authorities', help='explicit archive race_id to horse_jra/horse_local map')
    p.add_argument('--retained-root', help='existing private CapturedHistoryAuditJournal root')
    p.add_argument('--retained-audit', help='existing private audit name')
    p.add_argument('--retained-import-sha', help='existing immutable import digest')
    p.add_argument('--retained-report-sha', help='existing latest report digest')
    p.add_argument('--retained-through-batch', type=int)
    p.add_argument('--output', required=True, help='new private report path; overwrite forbidden')
    args = p.parse_args(argv)
    try:
        retained = []
        bound = (args.retained_root, args.retained_audit, args.retained_import_sha,
                 args.retained_report_sha)
        if any(v is not None for v in bound) != all(v is not None for v in bound):
            raise CoverageError('ALL_RETAINED_JOURNAL_BINDINGS_REQUIRED')
        if all(v is None for v in bound) and args.retained_through_batch is not None:
            raise CoverageError('RETAINED_BATCH_WITHOUT_JOURNAL')
        if all(v is not None for v in bound):
            if not all(re.fullmatch('[0-9a-f]{64}', v or '') for v in
                       (args.retained_import_sha, args.retained_report_sha)):
                raise CoverageError('EXPECTED_PRIVATE_HASH_REQUIRED')
            # The private journal revalidates the immutable origin, all batches,
            # exposure registry and row hashes. No raw source download or rerun.
            from .retained_captured_journal import CapturedHistoryAuditJournal
            from .retained_prediction_audit import digest
            journal = CapturedHistoryAuditJournal(args.retained_root, args.retained_audit)
            original = journal.read_report(expected_import_sha256=args.retained_import_sha,
                                           through_batch=args.retained_through_batch)
            if original is None or digest(original) != args.retained_report_sha:
                raise CoverageError('PRIVATE_REPORT_CHAIN_HASH_MISMATCH')
            retained.append(original)
        result = link_day(_read_json(args.reference), _read_json(args.ledger),
                          secondary_reference=(_read_json(args.secondary_reference)
                                               if args.secondary_reference else None),
                          sealed_bundles=[_read_json(x) for x in args.seal],
                          retained_reports=retained,
                          horse_authorities=(_read_json(args.horse_authorities)
                                             if args.horse_authorities else None))
        # Never print the private report or archived prediction details to logs.
        raw = json.dumps(result, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8') + b'\n'
        out = Path(args.output)
        if out.is_symlink():
            raise CoverageError('SYMLINK_OUTPUT_REJECTED')
        with out.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({'status':'RESEARCH_BRIDGE_NOT_FORMAL',
                          'report_path':str(out),
                          'reported_race_identities':result['reported_race_identities'],
                          'archive_slots':sum(result['local_archived_slot_counts'].values()),
                          'formal_hit_at_8_all':None},sort_keys=True))
        return 2  # Explicitly never an official success gate.
    except (CoverageError, OSError, ValueError, KeyError, TypeError) as exc:
        print('FOUR_SPORT_BRIDGE_REJECTED: ' + str(exc), file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
