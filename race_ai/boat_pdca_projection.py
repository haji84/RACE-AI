"""Read retained pairs into the existing private UI; no fetch, prediction or scoring."""
from copy import deepcopy
import json
import re

from .boat_history_comparison import verify_pair_original,verify_freeze_receipt
from .boat_pdca_state import need
from .actions_contract import digest
from .boat_history_store import instant
from .private_cycle_projection import _observation,_ResultObservationRejection
from .teiai_history import VENUES

VENUE_NAMES={code:name for name,code in VENUES.items()}


def project_pdca(state):
    from .saved_result_sync import read_batch,project_observation,_merge
    state.verify_files();need(state.mode=='production','PDCA_VIEW_PRODUCTION_STATE_REQUIRED')
    observations={}
    extra,raw_sources,synced_at=read_batch(state)
    existing=[json.loads(body) for body, in state.db.execute('SELECT body FROM results ORDER BY captured_at,sha')]
    for observation in _merge([*existing,*extra]):
        observations.setdefault(observation['race_id'],[]).append(observation)
    records=[];seen=set()
    for pair_sha,json_sha,receipt_sha in state.db.execute('SELECT sha,json_sha,receipt_sha FROM pairs ORDER BY sha'):
        raw=state._get(json_sha);pair=verify_pair_original(json.loads(raw));receipt=json.loads(state._get(receipt_sha))
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
        venue=snapshot['venue']
        label=VENUE_NAMES.get(venue.removeprefix('boatrace-jcd-'),venue) if venue.startswith('boatrace-jcd-') else venue
        row=dict(race_id=rid,sport='boat',venue=label,race_no=int(rid[-2:]),
            event_date_jst=snapshot['event_date_jst'],cutoff_at=pair['cutoff_at'],saved_cutoff_variants=[pair['cutoff_at']],
            offering_status='UNKNOWN',race_status='UNKNOWN',observed_at=pair['generated_at'],
            participants=[dict(number=p['lane'],registration_no=p['registration_no'],name=None) for p in snapshot['participants']],
            prediction=predictions[0],comparison_predictions=predictions[1:],result=None,result_revisions=[],
            result_observations=deepcopy(observations.get(rid,[])),result_observation_rejections=[],missing_reasons=[],source_provenance='OWNER_SAVED_PDCA_PAIR')
        if row['result_observations']:
            latest=max(row['result_observations'],key=lambda o:instant(o['captured_at']))
            try:row['result']=project_observation(latest,row,freeze_at=receipt['write_completed_at'],raw_bound=digest(latest) in raw_sources)
            except (KeyError,TypeError,ValueError,_ResultObservationRejection) as error:
                reason=str(error) if re.fullmatch('[A-Z][A-Z0-9_]{1,199}',str(error)) else 'RESULT_OBSERVATION_INVALID'
                row['result']=dict(status='unsupported',winning_combinations=[],confirmed_at=None,observed_at=latest['captured_at'],official=False,source_sha256=latest.get('source_sha256'))
                row['result_observation_rejections'].append(dict(captured_at=latest['captured_at'],source_sha256=latest.get('source_sha256'),reason=reason))
                row['missing_reasons'].append('LATEST_RESULT_OBSERVATION_REJECTED')
        records.append(row)
    need(records,'PDCA_VIEW_NO_SAVED_PAIRS')
    days={r['event_date_jst'] for r in records}
    return dict(schema='RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status='REAL_REPORTED',
        event_date_jst=next(iter(days)) if len(days)==1 else None,records=sorted(records,key=lambda r:r['race_id']),
        source_provenance='OWNER_SAVED_PDCA_PAIR',accuracy_improvement_proven=False,
        independent_pre_cutoff_receipt_verified=False,formal_backtest_eligible=False,results_synced_at=synced_at)
