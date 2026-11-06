"""Read retained pairs into the existing private UI; no fetch, prediction or scoring."""
from copy import deepcopy
import json

from .boat_history_comparison import verify_pair,verify_freeze_receipt
from .boat_pdca_state import need
from .boat_history_store import instant
from .private_cycle_projection import _observation,_ResultObservationRejection


def project_pdca(state):
    state.verify_files();need(state.mode=='production','PDCA_VIEW_PRODUCTION_STATE_REQUIRED')
    observations={}
    for rid,body in state.db.execute('SELECT race_id,body FROM results ORDER BY captured_at,sha'):
        observations.setdefault(rid,[]).append(json.loads(body))
    records=[];seen=set()
    for pair_sha,json_sha,receipt_sha in state.db.execute('SELECT sha,json_sha,receipt_sha FROM pairs ORDER BY sha'):
        raw=state._get(json_sha);pair=verify_pair(json.loads(raw));receipt=json.loads(state._get(receipt_sha))
        verify_freeze_receipt(pair,receipt,json_sha)
        rid=pair['race_id'];need(rid not in seen,'PDCA_VIEW_MULTIPLE_PAIR_VERSIONS_REQUIRE_SELECTION');seen.add(rid)
        snapshot=pair['baseline']['snapshot'];predictions=[]
        for variant,label in (('baseline','HISTORY_BASELINE'),('history','HISTORY_ADDED')):
            version=pair[variant];snap=version['snapshot']
            for mid,model in sorted(version['suite']['models'].items()):
                predictions.append(dict(model_id=mid,model_version=model['model_version'],stage=model['stage'],variant=label,
                    ordered_top8=deepcopy(model['ordered_top8']),ordered_candidates=[deepcopy(c['combination']) for c in model['candidates']],
                    prediction_sha256=model['prediction_sha256'],input_sha256=model['snapshot_sha256'],
                    source_sha256=snap['sources'][0].get('source_sha256') if snap['sources'] else None,
                    as_of=model['as_of'],generated_at=pair['generated_at'],persisted_at=receipt['write_completed_at'],
                    server_saved_at=receipt['write_completed_at'],cutoff_at=pair['cutoff_at'],odds_independent=model.get('odds_independent'),
                    original_json_sha256=json_sha,physical_receipt_sha256=receipt_sha,pair_sha256=pair_sha,
                    source_provenance='OWNER_SAVED_PDCA_PAIR',external_receipt_verified=False,missing_reasons=[]))
        row=dict(race_id=rid,sport='boat',venue=snapshot['venue'],race_no=int(rid[-2:]),
            event_date_jst=snapshot['event_date_jst'],cutoff_at=pair['cutoff_at'],saved_cutoff_variants=[pair['cutoff_at']],
            offering_status='UNKNOWN',race_status='UNKNOWN',observed_at=pair['generated_at'],
            participants=[dict(number=p['lane'],registration_no=p['registration_no'],name=None) for p in snapshot['participants']],
            prediction=predictions[0],comparison_predictions=predictions[1:],result=None,result_revisions=[],
            result_observations=deepcopy(observations.get(rid,[])),missing_reasons=[],source_provenance='OWNER_SAVED_PDCA_PAIR')
        if row['result_observations']:
            latest=max(row['result_observations'],key=lambda o:instant(o['captured_at']))
            try:row['result']=_observation(latest,row)
            except (KeyError,TypeError,ValueError,_ResultObservationRejection):
                row['missing_reasons'].append('LATEST_RESULT_OBSERVATION_REJECTED')
        records.append(row)
    need(records,'PDCA_VIEW_NO_SAVED_PAIRS')
    days={r['event_date_jst'] for r in records}
    return dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status='REAL_REPORTED',
        event_date_jst=next(iter(days)) if len(days)==1 else None,records=sorted(records,key=lambda r:r['race_id']),
        source_provenance='OWNER_SAVED_PDCA_PAIR',accuracy_improvement_proven=False,
        independent_pre_cutoff_receipt_verified=False,formal_backtest_eligible=False)
