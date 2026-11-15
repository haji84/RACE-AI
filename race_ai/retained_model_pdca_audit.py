"""Read-only model-specific PDCA from authenticated, immutable saved BOAT views.

The caller must first authenticate the AES saved-history day and the result
revision. This never calls a provider, rewrites a forecast, trains coefficients,
or calls money actual purchases. An unknown clock, payout or reference-only
result remains in HOLD, never in the miss denominator.
"""
from collections import defaultdict,Counter
from datetime import datetime
import re
from . import saved_view_feed as F, result_due_ledger as D
from .actions_contract import digest

SCHEMA='RACE_AI_RETAINED_MODEL_PDCA_AUDIT_V1'
SHA=re.compile('[a-f0-9]{64}\\Z')


def need(ok,reason):
    if not ok: raise ValueError('RETAINED_MODEL_PDCA_'+reason)


def _clock(text):
    need(type(text) is str,'CLOCK_INVALID')
    try: value=datetime.fromisoformat(text.replace('Z','+00:00'))
    except ValueError: raise ValueError('RETAINED_MODEL_PDCA_CLOCK_INVALID') from None
    need(value.utcoffset() is not None,'CLOCK_INVALID')
    return value


def _ticket(t):
    return type(t) is list and len(t)==3 and all(type(n) is int and 1<=n<=6 for n in t) and len(set(t))==3


def _saved_clock(prediction,row):
    cutoff=_clock(prediction.get('cutoff_at') or row.get('cutoff_at'))
    persisted=prediction.get('persisted_at') or prediction.get('server_saved_at')
    need(persisted and _clock(persisted)<cutoff,'PRE_CUTOFF_RECEIPT_MISSING')
    for key in ('generated_at','as_of','source_captured_at','server_saved_at'):
        if prediction.get(key) is not None:need(_clock(prediction[key])<cutoff,'FORECAST_AFTER_CUTOFF')
    return cutoff


def _result_context(row):
    result=row.get('result') or {}
    state=D.reconciled_status(row)
    if state in ('missing','pending'):
        return ('PENDING_OFFICIAL_RESULT',None,None)
    if state not in ('final','void'):
        return ('HOLD_NO_FORMAL_RESULT',None,None)
    if row.get('saved_observation_cutoff_variants') or not row.get('cutoff_at'):
        return ('HOLD_CUTOFF_IDENTITY',None,None)
    observations=row.get('result_observations') or []
    if not observations: return ('HOLD_NO_SOURCE_OBSERVATION',None,None)
    need(all(type(o) is dict and o.get('race_id')==row['race_id'] for o in observations),'RESULT_RACE_IDENTITY')
    latest=max(observations,key=lambda o:_clock(o.get('captured_at')))
    if latest.get('source_sha256')!=result.get('source_sha256') or \
       latest.get('captured_at')!=result.get('observed_at') or \
       latest.get('body_identity_verified') is not True or \
       latest.get('status')!='AVAILABLE' or \
       type(latest.get('source_sha256')) is not str or not SHA.fullmatch(latest['source_sha256']):
        return ('HOLD_SOURCE_RECEIPT_UNVERIFIED',None,None)
    data=latest.get('data')
    if type(data) is not dict or data.get('confirmed') is not True:
        return ('HOLD_RESULT_BODY_UNVERIFIED',None,None)
    if result['status']=='void':
        if data.get('status') not in ('cancelled','no_contest'):
            return ('HOLD_VOID_SOURCE_DISAGREEMENT',None,None)
        return ('VOID',{},set())
    if data.get('status')!='settled' or data.get('finish_confirmed') is not True:
        return ('HOLD_RESULT_BODY_UNVERIFIED',None,None)
    payouts=[p for p in data.get('payouts',[]) if type(p) is dict and p.get('bet_type')=='trifecta']
    if not payouts: return ('HOLD_PAYOUT_UNAVAILABLE',None,None)
    mapped={}
    for p in payouts:
        combo=p.get('combination');money=p.get('payout_per_100_yen')
        need(_ticket(combo) and type(money) is int and money>=0,'PAYOUT_INVALID')
        key=tuple(combo);need(key not in mapped,'PAYOUT_DUPLICATE');mapped[key]=money
    if set(mapped)!={tuple(t) for t in result.get('winning_combinations',[]) if _ticket(t)}:
        return ('HOLD_WINNER_REVISION_CONFLICT',None,None)
    if len(mapped)==1 and result.get('payout_yen_per_100')!=next(iter(mapped.values())):
        return ('HOLD_PAYOUT_REVISION_CONFLICT',None,None)
    if len(mapped)>1 and (type(result.get('payouts')) is not list or
                          {(tuple(p.get('combination',[])),p.get('payout_per_100_yen')) for p in result['payouts']} != set(mapped.items())):
        return ('HOLD_PAYOUT_REVISION_CONFLICT',None,None)
    refunds=data.get('refund_boats',[])
    need(type(refunds) is list and all(type(n) is int and 1<=n<=6 for n in refunds) and len(set(refunds))==len(refunds),'REFUND_INVALID')
    need(not any(set(combination)&set(refunds) for combination in mapped),'REFUND_WINNER_CONFLICT')
    return ('FINAL',mapped,set(refunds))


def _score_using_existing_bulk_engine(row,prediction,tickets,winners,refunds,state,identity):
    """Adapt an already AES-authenticated, pre-cutoff BOAT view to the ORIGINAL bulk scorer.

    Only _saved_clock and _result_context verify receipt, race, clock,
    official revision and refunds. The old bulk scorer does NOT verify them.
    Its result is strictly private and only numeric/status fields may escape.
    """
    from . import verified_bulk_backtest as B
    need(state in ('FINAL','VOID'),'FORMAL_RESULT_REQUIRED')
    rid=row['race_id']
    physical='ボート:'+row['event_date_jst']+':'+rid[9:11]+':'+str(int(rid[-2:]))
    frozen=dict(race_id=physical,forecast_id=identity,
                model_id=prediction['model_id'],
                picks=['-'.join(map(str,t)) for t in tickets],
                frozen_at=prediction.get('persisted_at') or prediction.get('server_saved_at'),
                cutoff_at=prediction.get('cutoff_at') or row.get('cutoff_at'))
    observed=dict(race_id=physical,
                  status='CANCELLED' if state=='VOID' else 'SETTLED',
                  payouts={'-'.join(map(str,t)):money for t,money in sorted(winners.items())},
                  refunded_numbers=sorted(refunds),
                  source_grade='official_observed',revision=1)
    try:
        scored=B.settle(frozen,B.validate_result(observed))
    except B.BadRecord:
        raise ValueError('RETAINED_MODEL_PDCA_EXISTING_SETTLEMENT_REJECTED') from None
    need(scored['status'] in ('HIT','HIT_PLUS_REFUND','MISS','MISS_PLUS_REFUND','FULL_REFUND'),
         'EXISTING_SETTLEMENT_STATUS_INVALID')
    need(all(type(scored[k]) is int for k in ('gross_yen','win_yen','refund_yen','received_yen','net_yen')),
         'EXISTING_SETTLEMENT_MONEY_INVALID')
    need(scored['gross_yen']==100*len(tickets) and
         scored['received_yen']==scored['win_yen']+scored['refund_yen'] and
         scored['net_yen']==scored['received_yen']-scored['gross_yen'],
         'EXISTING_SETTLEMENT_ACCOUNTING_MISMATCH')
    return scored


def _miss_reason(tickets,winners):
    # A diagnostic partition based on saved Top8 only. This is NOT a causal
    # claim about driver ability, equipment, weather, odds, or model weights.
    first={t[0] for t in tickets}
    for winner in winners:
        if winner[0] in first:
            seconds={t[1] for t in tickets if t[0]==winner[0]}
            if winner[1] in seconds:
                return 'THIRD_OR_COMBINATION_EXCLUDED'
    if any(w[0] in first for w in winners):return 'SECOND_PLACE_COMBINATION_EXCLUDED'
    return 'FIRST_PLACE_NOT_SELECTED'


def score_view(view,*,authenticated,include_private_due=False):
    """Return only count-only model-stage-version summaries, no tickets or URLs."""
    need(authenticated is True,'AUTHENTICATED_INPUT_REQUIRED')
    need(view.get('dataset_status')=='REAL_REPORTED','REAL_DATASET_REQUIRED')
    F.originals_sha(view)
    inventory_hash=F.inventory_sha(view)  # immutable original identities and digest guard
    anchor=F.forecast_anchor(view)
    summary={}
    seen=set()
    private_due_ids=set()
    for row in view['records']:
        if row.get('sport')!='boat':continue
        need(row.get('scope')=='research','REAL_RACE_SCOPE_REQUIRED')
        rid=row.get('race_id')
        need(type(rid) is str and D._rid_day(rid)==row.get('event_date_jst'),'RACE_DATE_MISMATCH')
        state,winners,refunds=_result_context(row)
        predictions=([row['prediction']] if row.get('prediction') is not None else [])+list(row.get('comparison_predictions') or [])
        for prediction in predictions:
            need(type(prediction) is dict,'FORECAST_INVALID')
            tickets=prediction.get('ordered_top8')
            need(type(tickets) is list and 1<=len(tickets)<=8 and all(_ticket(t) for t in tickets) and len({tuple(t) for t in tickets})==len(tickets),'TOP8_INVALID')
            ident=digest([rid,anchor,inventory_hash,prediction])
            if ident in seen:continue
            seen.add(ident)
            model=prediction.get('model_id');stage=prediction.get('stage');version=prediction.get('model_version');variant=prediction.get('variant')
            need(type(model) is str and 0<len(model)<=256 and type(stage) is str and 0<len(stage)<=32,'MODEL_ID_INVALID')
            key=(model,stage,version or '',variant or '')
            a=summary.setdefault(key,dict(model_id=model,stage=stage,version=version,variant=variant,
               forecasts=0,eligible=0,hits=0,misses=0,void=0,pending=0,held=0,
               stake_yen=0,returned_yen=0,refund_yen=0,net_yen=0,unresolved_reasons=Counter(),miss_reasons=Counter()))
            a['forecasts']+=1
            try: cutoff=_saved_clock(prediction,row)
            except ValueError as exc:
                a['held']+=1;a['unresolved_reasons']['PRE_CUTOFF_PROOF_MISSING']+=1;private_due_ids.add(rid);continue
            if state=='PENDING_OFFICIAL_RESULT':
                a['pending']+=1;private_due_ids.add(rid);continue
            if state.startswith('HOLD_'):
                a['held']+=1;a['unresolved_reasons'][state]+=1;private_due_ids.add(rid);continue
            if _clock(row['result']['observed_at'])<cutoff:
                a['held']+=1;a['unresolved_reasons']['RESULT_BEFORE_CUTOFF']+=1;private_due_ids.add(rid);continue
            # Reuse verified_bulk_backtest.settle instead of independently
            # recomputing payout, refund and hit logic here. Strict AES source
            # authentication and pre-cutoff validation have ALREADY passed.
            ticket_set=[tuple(t) for t in tickets]
            settled=_score_using_existing_bulk_engine(
                row,prediction,ticket_set,winners,refunds,state,ident)
            a['stake_yen']+=settled['gross_yen']
            a['returned_yen']+=settled['received_yen']
            a['refund_yen']+=settled['refund_yen']
            a['net_yen']+=settled['net_yen']
            if settled['status']=='FULL_REFUND':
                # Fully refunded tickets, whether due to cancellation or all
                # selections refunded, never enter the miss denominator.
                a['void']+=1
            elif settled['status'] in ('HIT','HIT_PLUS_REFUND'):
                a['eligible']+=1;a['hits']+=1
            else:
                a['eligible']+=1;a['misses']+=1
                a['miss_reasons'][_miss_reason(ticket_set,winners)]+=1
    groups=[]
    for key,a in sorted(summary.items()):
        b=dict(a,unresolved_reasons=dict(sorted(a['unresolved_reasons'].items())),miss_reasons=dict(sorted(a['miss_reasons'].items())))
        need(b['eligible']==b['hits']+b['misses'],'SCORE_ACCOUNTING_MISMATCH')
        need(b['forecasts']==b['eligible']+b['void']+b['held']+b['pending'],'FORECAST_COVERAGE_MISMATCH')
        b['hit_rate']=b['hits']/b['eligible'] if b['eligible'] else None
        b['roi']=b['returned_yen']/b['stake_yen'] if b['stake_yen'] else None
        b['actual_purchases']=False
        groups.append(b)
    report=dict(schema=SCHEMA,source='AES_AUTHENTICATED_SAVED_VIEW_ONLY',model_groups=groups,
        model_group_count=len(groups),total_forecasts=sum(a['forecasts'] for a in groups),
        total_scored=sum(a['eligible'] for a in groups),unresolved=sum(a['held']+a['pending'] for a in groups),
        actual_purchases=False,accuracy_improvement_proven=False,
        no_provider_requests=True,rewrote_predictions=False)
    # Race IDs never belong in the count-only audit or public output. A trusted
    # encrypted-only caller may explicitly request them to retain PDCA HOLDs.
    if include_private_due is True:
        report['_private_due_race_ids']=sorted(private_due_ids)
    return report
