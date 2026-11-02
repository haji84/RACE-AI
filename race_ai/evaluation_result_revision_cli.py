"""Private offline CLI for operator-supplied result revisions. No HTTP or model calls."""
import argparse
import json
import os
from pathlib import Path
import sys

from .discovery_audit_cli import _read_json
from .evaluation_result_revision_bridge import (
    ResultLinkError, link_result_revisions, research_score_existing_seal,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bridge', required=True)
    parser.add_argument('--observation-batch', action='append', required=True)
    parser.add_argument('--research-seal', help='original local research-only seal')
    parser.add_argument('--output', required=True, help='new private report; no overwrite')
    args = parser.parse_args(argv)
    try:
        bridge = _read_json(args.bridge)
        batches = [_read_json(p) for p in args.observation_batch]
        report = link_result_revisions(bridge, batches)
        scores = (research_score_existing_seal(bridge, batches, _read_json(args.research_seal))
                  if args.research_seal else None)
        result = {'schema':'RACE_AI_RESULT_REVISION_PRIVATE_EXPORT_V1',
                  'research_result_link':report, 'research_scores':scores,
                  'formal_result_authority':False,'formal_hit_at_8_all':None}
        raw = json.dumps(result, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')+b'\n'
        target = Path(args.output)
        if target.is_symlink():
            raise ResultLinkError('SYMLINK_OUTPUT_REJECTED')
        with target.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({'status':'RESEARCH_ONLY_NOT_FORMAL',
                          'listed_races':report['listed_races'],
                          'observations':report['result_observations'],
                          'formal_hit_at_8_all':None},sort_keys=True))
        return 2
    except (ResultLinkError, ValueError, KeyError, TypeError, OSError) as error:
        print('RESULT_REVISION_LINK_REJECTED: '+str(error),file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
