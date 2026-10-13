"""Compare a B-extracted sample against separately read official race-card facts."""
import argparse
import json
from pathlib import Path
from .core import SourceError


def spotcheck(report:dict,ref:dict)->dict:
    if report.get('sample_race_id')!=ref.get('race_id'):
        raise SourceError('reference race does not match B sample')
    expected=ref.get('boats')
    seen=report.get('sample_source_boats')
    if (not isinstance(expected,list) or len(expected)!=6
        or not isinstance(seen,list) or len(seen)!=6):
        raise SourceError('reference/parsed race needs six boats')
    table={x['lane']:x for x in seen}
    reference={x['lane']:x for x in expected}
    if set(table)!=set(range(1,7)) or set(reference)!=set(range(1,7)):
        raise SourceError('duplicate/missing boat in sample/reference')
    mismatch=[]
    for lane in range(1,7):
        for field in ('motor_no','boat_no','motor_top2_rate'):
            if table[lane].get(field)!=reference[lane].get(field):
                mismatch.append({'lane':lane,'field':field})
    if mismatch:
        raise SourceError('official race card/B allocation mismatch: '+str(mismatch))
    return {'status':'B_MOTOR_RACE_CARD_SPOTCHECK_PASS',
       'race_id':report['sample_race_id'],'compared_boats':6,
       'motor_number_matches':6,'motor_top2_rate_matches':6,'boat_number_matches':6,
       'independent_official_page':ref.get('source'),
       'no_whole_day_official_webpage_comparison_claim':True}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--metadata-json',required=True)
    p.add_argument('--official-reference-json',required=True)
    a=p.parse_args()
    result=spotcheck(json.loads(Path(a.metadata_json).read_text()),
                     json.loads(Path(a.official_reference_json).read_text()))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
