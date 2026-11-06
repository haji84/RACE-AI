"""Admit existing-model history trials using the existing GitHub clock verifier.

No forecast mutation, inference, source permission grant or production switch.
The caller supplies an official observation authenticated by the existing
result parser. Summaries accept only reports from this admission boundary.
"""
from copy import deepcopy
import json

from .actions_contract import digest
from .boat_history_comparison import load_pair,read_freeze_receipt,score_pair,need
from .boat_history_store import instant
from .frozen_day_cycle import sealed
from .github_freeze_receipt import verify_github_freeze,verify_github_pair_manifest


def admit_pair_result(pair_path,observation,github_receipt,now,*,manifest=False,_fetch=None):
    pair=load_pair(pair_path);local=read_freeze_receipt(pair_path,pair)
    need(all(pair[variant]['snapshot']['scope']=='OPERATOR_SUPPLIED_RESEARCH'
             for variant in ('baseline','history')),'PROSPECTIVE_REAL_RESEARCH_SCOPE_REQUIRED')
    if manifest:
        entry=dict(pair_sha256=pair['pair_sha256'],file_sha256=local['file_sha256'],
            local_freeze_receipt_sha256=local['receipt_sha256'],race_id=pair['race_id'],
            stage=pair['baseline']['snapshot']['stage'],write_completed_at=local['write_completed_at'],cutoff_at=pair['cutoff_at'])
        verify_github_pair_manifest(github_receipt,entry,_fetch=_fetch)
    else:
        verify_github_freeze(github_receipt,pair['pair_sha256'],local['write_completed_at'],
                            pair['cutoff_at'],_fetch=_fetch)
    report=score_pair(pair,observation,now)
    report.update(schema='RACE_AI_AUTHENTICATED_HISTORY_TRIAL_RESULT_V1',
        result_captured_at=observation['captured_at'],freeze_receipt=deepcopy(github_receipt),
        freeze_receipt_kind='PAIR_MANIFEST_V2' if manifest else 'SINGLE_ANCHOR_V1',
        independent_pre_cutoff_receipt_verified=True,
        prospective_metric_eligible=all(row['paired'] for row in report['models']),
        scoring_scope='AUTHENTICATED_PROSPECTIVE_RESEARCH_HISTORY_INPUT_COMPARISON',
        comparison_axis='HISTORY_INPUT_ADDITION_AT_SHARED_ASOF',
        actual_purchases=False,production_promoted=False)
    report['report_sha256']=digest(report)
    return report


def summarize_trials(reports):
    """Count each admitted pair once at its latest shared result revision.

    Caller owns report authentication/storage, just as for frozen_day_cycle.
    The hash detects corruption; it is not an independent source receipt.
    """
    latest={};revisions=set()
    for report in reports:
        sealed(report,'report_sha256')
        need(report.get('schema')=='RACE_AI_AUTHENTICATED_HISTORY_TRIAL_RESULT_V1' and
             report.get('independent_pre_cutoff_receipt_verified') is True,'PROSPECTIVE_ADMISSION_REQUIRED')
        key=report['pair_sha256'];at=instant(report['result_captured_at']);old=latest.get(key)
        revisions.add((key,report['result_sha256'],at))
        if old and instant(old['result_captured_at'])==at:
            need(old==report,'PROSPECTIVE_EQUAL_CLOCK_RESULT_CONFLICT')
        if old is None or instant(old['result_captured_at'])<at:latest[key]=report
    rows={}
    for report in latest.values():
        if not report['prospective_metric_eligible']:continue
        for value in report['models']:
            mid=value['model_id'];row=rows.setdefault(mid,dict(model_id=mid,scored=0,
                baseline_hits=0,history_hits=0,baseline_stake_yen=0,history_stake_yen=0,
                baseline_received_yen=0,history_received_yen=0))
            row['scored']+=1
            for variant in ('baseline','history'):
                row[variant+'_hits']+=value[variant+'_hit']
                row[variant+'_stake_yen']+=value['stake_yen_per_variant']
                row[variant+'_received_yen']+=value[variant+'_received_yen']
    for row in rows.values():
        for variant in ('baseline','history'):
            row[variant+'_hit_rate']=row[variant+'_hits']/row['scored']
            row[variant+'_roi']=row[variant+'_received_yen']/row[variant+'_stake_yen']
    return dict(schema='RACE_AI_AUTHENTICATED_HISTORY_TRIAL_SUMMARY_V1',unique_races=len(latest),
        result_revisions=len(revisions),normal_races=sum(r['prospective_metric_eligible'] for r in latest.values()),
        excluded_special_or_pending_races=sum(not r['prospective_metric_eligible'] for r in latest.values()),
        models=[rows[k] for k in sorted(rows)],accuracy_improvement_proven=False,
        actual_purchases=False,production_promoted=False)


def verify_retained_trials(state,root,now):
    """Replay owner-authenticated admitted results without changing originals.

    This checks stored admission/model/result bindings. External GitHub clocks
    were verified at admission; this offline replay does not re-query GitHub.
    """
    reports=[]
    for name,ident in state.db.execute("SELECT name,sha FROM heads WHERE name LIKE 'prospective-admissions/%.json'"):
        report=json.loads(state._get(ident));sealed(report,'report_sha256')
        need(report.get('schema')=='RACE_AI_AUTHENTICATED_HISTORY_TRIAL_RESULT_V1' and
             report.get('independent_pre_cutoff_receipt_verified') is True,'PROSPECTIVE_ADMISSION_REQUIRED')
        pair=load_pair(root/'pairs'/f"{report['pair_sha256']}.json")
        observations=[json.loads(row[0]) for row in state.db.execute('SELECT body FROM results WHERE race_id=?',(pair['race_id'],))]
        matches=[o for o in observations if o['captured_at']==report['result_captured_at'] and o['source_sha256']==report['result_sha256']]
        need(len(matches)==1,'PROSPECTIVE_RETAINED_RESULT_MISSING')
        replay=score_pair(pair,matches[0],now)
        need(replay['models']==report['models'] and report['race_id']==pair['race_id'] and
             report['prospective_metric_eligible']==all(r['paired'] for r in replay['models']) and
             report['actual_purchases'] is False and report['production_promoted'] is False,
             'PROSPECTIVE_RETAINED_SCORING_CONFLICT')
        reports.append(report)
    return dict(admitted_prospective_races=len(reports),admitted_summary=summarize_trials(reports),
                external_receipts_rechecked_live=False)
