"""Count-only national P1 model matrix from independently read owner evidence.

This pure calculator cannot authenticate official source bytes, source clocks,
AES decryptions or GH receipts. Call it ONLY after the existing immutable
owner reader has independently accepted those inputs. It never fetches or
generates a forecast, and never exposes race IDs or private model inputs.
"""
from collections import Counter
import re

SCHEMA='RACE_AI_BOAT_OWNER_NATIONAL_P1_MATRIX_V1'
MODEL=re.compile(r'[A-Za-z0-9_.-]{1,128}\Z')


def _need(ok):
    if not ok:raise ValueError('BOAT_OWNER_NATIONAL_P1_MATRIX_REJECTED')


def calculate(report,model_ids,*,independent_original_reader=False):
    _need(type(report) is dict and report.get('schema')==
          'RACE_AI_OWNER_ORIGINAL_EVIDENCE_AUDIT_V1')
    _need(type(model_ids) in (tuple,list) and 0<len(model_ids)<=128 and
          len(set(model_ids))==len(model_ids) and
          all(type(m) is str and MODEL.fullmatch(m) for m in model_ids))
    _need(type(independent_original_reader) is bool)
    valid=report.get('official_program_verified')
    _need(type(valid) is bool)
    scheduled=report.get('scheduled_races')
    retained=report.get('retained_schedule_rows')
    _need(type(retained) is int and 0<retained<=288)
    _need(scheduled is None or (type(scheduled) is int and 0<scheduled<=288))
    _need((valid and scheduled==retained) or (not valid and scheduled is None))
    p1=report.get('p1_models')
    _need(type(p1) is dict and all(type(k) is str and MODEL.fullmatch(k) and
          type(v) is int and 0<=v<=retained for k,v in p1.items()))
    p0=report.get('p0_models')
    _need(type(p0) is dict and all(type(k) is str and MODEL.fullmatch(k) and
          type(v) is int and 0<=v<=retained for k,v in p0.items()))
    _need(report.get('baseline_p1_unique_model_slots')==sum(p1.values()))
    _need(type(report.get('baseline_p1_races')) is int and
          0<=report['baseline_p1_races']<=retained)
    _need(type(report.get('baseline_p0_races')) is int and
          0<=report['baseline_p0_races']<=retained)
    _need(type(report.get('p1_schedule_cutoff_conflict_races')) is int and
          0<=report['p1_schedule_cutoff_conflict_races']<=retained)
    _need(type(report.get('verified_video_prediction_rows')) is int and
          report['verified_video_prediction_rows']>=0)
    _need(report.get('official_source_requests')==0 and
          report.get('originals_changed') is False and
          report.get('successor_dispatch_allowed') is False)
    _need(report.get('owner_conclusion') in ('success','failure'))
    control=report.get('source_control')
    _need(type(control) is dict and control.get('prepared_round') is None and
          type(control.get('completed_round')) is int and control['completed_round']>=0)
    _need(type(report.get('owner_run_id')) is int and report['owner_run_id']>0 and
          type(report.get('day_jst')) is str and
          re.fullmatch(r'20[0-9]{2}-[01][0-9]-[0-3][0-9]',report['day_jst']))
    expected=set(model_ids)
    expected_total=retained*len(expected)
    present=sum(p1.get(mid,0) for mid in expected)
    _need(present<=expected_total)
    extras={key:value for key,value in p1.items() if key not in expected}
    missing=expected_total-present
    by_model=[dict(model_id=mid,p1_saved_races=p1.get(mid,0),
                   missing_races=retained-p1.get(mid,0),
                   p1_saved_rate=round(p1.get(mid,0)/retained,6))
              for mid in sorted(expected)]
    full=(independent_original_reader and valid and
          report['owner_conclusion']=='success' and
          report['p1_schedule_cutoff_conflict_races']==0 and
          missing==0 and not extras and
          report['baseline_p1_races']==retained)
    state=('INDEPENDENT_P1_MODEL_MATRIX_PRESENT' if full else
           'HOLD_SOURCE_OR_INDEPENDENT_READBACK' if not (independent_original_reader and valid) else
           'HOLD_P1_INCOMPLETE_OR_CONFLICTED')
    return dict(schema=SCHEMA,status=state,day_jst=report['day_jst'],
        owner_run_id=report['owner_run_id'],official_schedule_authenticated=valid,
        owner_original_reader_independently_verified=independent_original_reader,
        source_owner_conclusion=report['owner_conclusion'],
        expected_active_model_count=len(expected),scheduled_races=scheduled,
        retained_schedule_races=retained,baseline_p0_races=report['baseline_p0_races'],
        baseline_p1_any_races=report['baseline_p1_races'],
        expected_p1_model_slots=expected_total,p1_saved_expected_slots=present,
        missing_p1_model_slots=missing,unrecognized_p1_model_count=len(extras),
        p1_source_cutoff_conflicts=report['p1_schedule_cutoff_conflict_races'],
        by_model=by_model,verified_video_prediction_rows=report['verified_video_prediction_rows'],
        all_expected_models_p1_readback_proven=full,
        public_video_usable=False,full_e2e_website_proven=False,
        original_forecasts_unchanged=True,racing_provider_gets=0,
        no_forecast_generation=True)
