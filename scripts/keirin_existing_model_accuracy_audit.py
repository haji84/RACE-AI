"""Read-only audit of frozen existing-A shadows; no fitting, fetch, or promotion.

Caller supplies a trusted published candidate digest and publication observation.
This audit checks their consistency; it does not issue a server witness.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path

from race_ai import keirin_existing_model_accuracy as learning
from race_ai import keirin_nationwide_auto_generator as original
from race_ai.keirin_form_fall_blind_pdca import _tickets,_score
from race_ai.keirin_note_view import _private_root,_create
from scripts.keirin_note_collect_results import checked_observation,MATCHED

SHADOW_FIELDS=frozenset(('schema model_id candidate_sha256 race_id source_facts_sha256 source_as_of '
    'generated_at published_cutoff_at ranked_tickets baseline_ranked_tickets ticket_count scope '
    'calibrated forward_improvement_proven production_promoted wagers_placed forecast_sha256').split())


def need(ok,code):
    if not ok:raise ValueError('KEIRIN_ACCURACY_AUDIT_'+code)


def compare_locked(*,artifact,forecasts,latest_results,expected_candidate_sha256,
                   expected_forecast_sha256,git_observed_at,clock=None):
    artifact=learning._artifact(artifact)
    need(artifact['artifact_sha256']==expected_candidate_sha256,'LOCKED_DIGEST')
    saved=original.when(git_observed_at);now=learning._clock(clock)
    need(saved<=now and original.when(artifact['created_at'])<=saved,'PUBLICATION_CLOCK')
    need(type(forecasts) is list and forecasts and type(latest_results) is list,'INPUT_LISTS')
    need(type(expected_forecast_sha256) is str and original.digest(forecasts)==expected_forecast_sha256,
        'LOCKED_FORECAST_COHORT_CHANGED')
    labels={}
    for result in latest_results:
        checked_observation(result);rid=result['race_id']
        need(rid not in labels,'RESULT_REVISIONS_NOT_RESOLVED');labels[rid]=result
    report=dict(expected=len(forecasts),matched=0,pending=0,held=0,baseline_hits8=0,candidate_hits8=0,
        both_hits=0,both_misses=0,baseline_only_hits=0,candidate_only_hits=0)
    seen=set()
    for row in forecasts:
        need(type(row) is dict and {'input','forecast'}<=set(row),'FORECAST_ROW')
        snapshot,out=row['input'],row['forecast'];rid=snapshot['race_id'];cutoff=original.when(snapshot['published_cutoff_at'])
        need(type(out) is dict and set(out)==SHADOW_FIELDS and out['schema']==learning.SHADOW and
            out['scope']==learning.SCOPE and out['source_as_of']==snapshot['as_of'] and
            out['published_cutoff_at']==snapshot['published_cutoff_at'],'SHADOW_SCHEMA_OR_SOURCE')
        original.validate_snapshot(snapshot,computed_at=out['generated_at'])
        need(original.when(artifact['training_boundary'])<original.when(snapshot['as_of']),'INPUT_PRECEDES_TRAINING')
        need(rid not in seen and out['race_id']==rid,'DUPLICATE_OR_CHANGED_RACE');seen.add(rid)
        need(rid[:8]==cutoff.astimezone(learning.JST).strftime('%Y%m%d') and
            rid not in set(artifact['train_race_ids'])|set(artifact['validation_race_ids']),'FITTING_RACE_OR_DAY')
        need(out['forecast_sha256']==original.digest({k:v for k,v in out.items() if k!='forecast_sha256'}) and
            out['candidate_sha256']==expected_candidate_sha256 and out['model_id']==original.MODEL_A and
            out['source_facts_sha256']==original.digest(snapshot),'FORECAST_IDENTITY')
        need(all(out.get(k) is False for k in ('calibrated','forward_improvement_proven','production_promoted','wagers_placed')),
            'RESEARCH_SCOPE')
        generated=original.when(out['generated_at'])
        need(original.when(artifact['created_at'])<=generated<=saved<cutoff,'FORECAST_NOT_SAVED_PRE_CUTOFF')
        cars={r['car'] for r in snapshot['riders']}
        baseline=_tickets(dict(ranked_tickets=out['baseline_ranked_tickets']),cars)
        candidate=_tickets(dict(ranked_tickets=out['ranked_tickets']),cars)
        need(len(baseline)==len(candidate)==out['ticket_count']==8,'EQUAL_EIGHT_POINT_BUDGET')
        need(out['baseline_ranked_tickets']==learning.rank_tickets(snapshot,generated_at=out['generated_at']) and
            out['ranked_tickets']==learning.rank_tickets(snapshot,weights=artifact['weights'],generated_at=out['generated_at']),
            'FROZEN_TICKETS_NOT_REPLAYED')
        result=labels.get(rid)
        if result is None:report['pending']+=1;continue
        need(original.when(result['captured_at'])<=now,'FUTURE_RESULT')
        if result['state']!=MATCHED:
            report['pending' if result['state'].startswith('PENDING_') else 'held']+=1;continue
        need(cutoff<original.when(result['captured_at']) and
            all(cutoff<original.when(r['observed_at']) for r in result['provider_receipts']) and
            set(result['winning_triple'])<=cars,'RESULT_BEFORE_CUTOFF_OR_WRONG_ROSTER')
        paid={tuple(result['winning_triple']):result['payout_per_100yen']}
        a=_score(baseline,paid)['all_hit'];b=_score(candidate,paid)['all_hit']
        report['matched']+=1;report['baseline_hits8']+=a;report['candidate_hits8']+=b
        report['both_hits' if a and b else 'baseline_only_hits' if a else 'candidate_only_hits' if b else 'both_misses']+=1
    n=report['matched']
    report.update(schema='RACE_AI_FROZEN_EXISTING_A_COMPARISON_V1',candidate_sha256=expected_candidate_sha256,
        forecast_manifest_sha256=expected_forecast_sha256,
        observed_at_utc=now.isoformat(),git_observed_at=saved.isoformat(),ticket_count=8,
        baseline_hit_at_8=report['baseline_hits8']/n if n else None,
        candidate_hit_at_8=report['candidate_hits8']/n if n else None,
        hit_delta=report['candidate_hits8']-report['baseline_hits8'] if n else None,
        statistical_improvement_supported=None,formal_model_admission=False,production_promoted=False,
        result_scope='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL',source_requests=0,
        publication_proof_from_caller_not_independently_verified=True,registered_BOAT_study_changed=False)
    return report


def _private_json(path):
    p=Path(path)
    need(p.is_absolute() and not p.is_symlink() and p.is_file() and
        p.stat().st_mode&0o077==0 and p.stat().st_size<=50*1024*1024,'PRIVATE_INPUT')
    return json.loads(p.read_bytes())


def main(argv=None,*,clock=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('artifact','forecasts','results','expected-candidate-sha256','expected-forecast-sha256','git-observed-at','private-root'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args(argv)
    try:
        report=compare_locked(artifact=_private_json(args.artifact),forecasts=_private_json(args.forecasts),
            latest_results=_private_json(args.results),expected_candidate_sha256=args.expected_candidate_sha256,
            expected_forecast_sha256=args.expected_forecast_sha256,
            git_observed_at=args.git_observed_at,clock=clock)
        root=_private_root(args.private_root)
        _create(root/'report.json',original.canonical(report)+b'\n')
        print(json.dumps(report,sort_keys=True));return 0
    except (ValueError,TypeError,KeyError,OSError):
        print(json.dumps(dict(state='HOLD_INVALID_PRIVATE_INPUT')));return 2


if __name__=='__main__':raise SystemExit(main())
