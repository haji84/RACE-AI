"""Synthetic acceptance views for existing native models and private readback."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from race_ai import existing_model_dispatch as native
from race_ai.dispatch_product_projection import project_dispatch
from race_ai.private_dispatch_operation import PrivateDispatchJournal, run_saved_inputs
from tests.test_dispatch_product_projection import all_native_reports
from tests.test_private_dispatch_operation import fixture, AT


def build_fixture(output_file):
    out=Path(output_file)
    if not out.is_absolute() or not out.parent.is_dir() or out.exists() or out.is_symlink():
        raise ValueError('fresh synthetic fixture output required')
    views=[project_dispatch(report,dataset_status='SYNTHETIC_ONLY') for report in all_native_reports()]
    schedule=[];inputs={}
    for sport in ('boat','keirin','autorace','horse'):
        rows,supplied=fixture(sport);schedule.extend(rows);inputs.update(supplied)
    with tempfile.TemporaryDirectory(prefix='dispatch-ui-',dir=out.parent) as temporary:
        db_path=Path(temporary)/'private.sqlite'
        journal=PrivateDispatchJournal(db_path)
        first=run_saved_inputs(journal,schedule,inputs,at=AT)
        originals=deepcopy(journal.originals())
        assert len(originals)==16
        reopened=PrivateDispatchJournal(db_path)
        with patch.object(native,'run_suite',side_effect=AssertionError('readback model replay')):
            second=run_saved_inputs(reopened,schedule,{},at='2030-01-15T12:00:00+09:00')
        assert reopened.originals()==originals
        assert reopened.read_operation(first['operation_id'])==first
        assert reopened.read_operation(second['operation_id'])==second
        assert all(slot['status']=='ORIGINAL_REUSED' for slot in second['dispatch']['slots'] if slot['prediction'])
        views.extend(project_dispatch(reopened.read_operation(item['operation_id']),dataset_status='SYNTHETIC_ONLY') for item in (first,second))
    opaque=native.dispatch([{'race_id':'actual-schedule-opaque-fixture','sport':'boat','stage':'P0','cutoff_at':'2030-01-15T11:00:00+09:00'}],{},now=AT)
    views.append(project_dispatch(opaque,dataset_status='SYNTHETIC_ONLY'))
    models={p['model_id'] for view in views for row in view['records'] for p in [row['prediction'],*row['comparison_predictions']] if p}
    assert len(models)==16
    document={'schema':'RACE_AI_SYNTHETIC_DISPATCH_UI_FIXTURES_V1','scope':'SYNTHETIC_ONLY','views':views,
              'local_readback_proof':{'retained_originals':len(originals),'operations':2,'native_hashes_preserved':True,
                                     'source_requests':0,'real_readbacks':0,'physical_safari_acceptance':False}}
    fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(document,stream,ensure_ascii=False);stream.write('\n')
    return {'scope':'SYNTHETIC_ONLY','views':len(views),'existing_model_families':len(models),
            'local_retained_originals':len(originals),'source_requests':0}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True)
    args=parser.parse_args(argv);print(json.dumps(build_fixture(args.out)));return 0


if __name__=='__main__':raise SystemExit(main())
