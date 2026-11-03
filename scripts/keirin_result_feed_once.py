"""One-shot owner-private KEIRIN result intake (offline research, never a crawler).

Invoke only from an owner-controlled environment with a genuinely reviewed
provider source-use permission and authenticated source bytes. An operator-made
'admission.json' alone does NOT prove legal authority or provider provenance.
No forecast is generated, no main branch is changed, and no wagers are placed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from race_ai.keirin_result_delivery import build_research_batch, research_hit8, KeirinDeliveryError
from race_ai.evaluation_result_revision_bridge import link_result_revisions


def _load_json(path):
    data = Path(path).read_bytes()
    if not data or len(data) > 4*1024*1024:
        raise KeirinDeliveryError('INPUT_BOUNDS')
    return json.loads(data)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bridge',required=True)
    p.add_argument('--feed',required=True,help='owner-protected licensed normalized bytes (no GET)')
    p.add_argument('--admission',required=True,help='trusted external rights/provenance review receipt')
    p.add_argument('--previous-batch',action='append',default=[])
    p.add_argument('--reference-forecasts',help='optional research-only reference; never formal')
    p.add_argument('--output',required=True,help='new owner-private JSON, create-only')
    args=p.parse_args(argv)
    try:
        bridge=_load_json(args.bridge)
        admission=_load_json(args.admission)
        prior=[_load_json(path) for path in args.previous_batch]
        raw=Path(args.feed).read_bytes()
        batch=build_research_batch(bridge,raw,admission=admission,
                  reviewed_at=datetime.now(timezone.utc).isoformat(),previous_batches=prior)
        report=link_result_revisions(bridge, [*prior,batch])
        reference=(research_hit8(batch,_load_json(args.reference_forecasts))
                   if args.reference_forecasts else None)
        result={
            'schema':'RACE_AI_KEIRIN_RESULT_OFFLINE_RESEARCH_EXPORT_V1',
            'mode':'RESEARCH_ONLY_NOT_OFFICIAL',
            'batch':batch,
            'revision_link':report,
            'reference_hit8':reference,
            'formal_hit_at_8_all':None,
            'official_results_authenticated':False,
            'provider_automated_collection_approved_by_cli':False,
            'model_autopromoted':False,
            'next_forecast_dispatched':False,
        }
        content=json.dumps(result,ensure_ascii=False,sort_keys=True,
                           separators=(',',':'),allow_nan=False).encode('utf-8')+b'\n'
        target=Path(args.output)
        if target.is_symlink():
            raise KeirinDeliveryError('SYMLINK_OUTPUT_REJECTED')
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_NOFOLLOW',0),0o600)
        with os.fdopen(fd,'wb') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        print(json.dumps({'mode':result['mode'],
              'new_revisions':len(batch['observations']),
              'listed_races':report['listed_races'],
              'formal_hit_at_8_all':None},sort_keys=True))
        return 2  # research-only, never 0=verified official ingestion
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print('KEIRIN_RESULT_INTAKE_REJECTED: '+str(exc),file=sys.stderr)
        return 3


if __name__=='__main__':
    raise SystemExit(main())
