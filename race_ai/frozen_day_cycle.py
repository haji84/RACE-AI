"""Read-only first-receipt forecast verification, settlement and PDCA.

No predictions are generated here. Source authentication is performed by the
caller using the pinned official parser. Original research flags are untouched.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib, io, itertools, json, math, re, zipfile
from .actions_contract import digest
from .repeated_cycle import matches as artifact_matches

UNIVERSE=set(itertools.permutations(range(1,7),3))
def need(ok,reason):
    if not ok:raise ValueError(reason)
def ts(value):
    v=datetime.fromisoformat(value.replace('Z','+00:00'))
    need(v.utcoffset() is not None,'aware time required');return v
def sealed(item,key):
    need(item.get(key)==digest({k:v for k,v in item.items() if k!=key}),'original hash changed: '+key)
def official_id(value):
    m=re.fullmatch(r'boat:(\d{4}-\d\d-\d\d):boatrace-jcd-(\d\d):([1-9]|1[0-2])',value)
    need(m is not None,'original race ID invalid')
    return m[1].replace('-','')+'-'+m[2]+'-'+m[3].zfill(2)
def archive_json(raw,receipt,member,expected_name):
    need(isinstance(raw,bytes) and len(raw)<=32*1024*1024,'bounded archive required')
    need(receipt.get('expired') is False and artifact_matches(receipt.get('name'),expected_name),'foreign or expired archive')
    need(receipt.get('workflow_run',{}).get('head_repository_id')==1416489937,'foreign repository')
    need(receipt.get('digest')=='sha256:'+hashlib.sha256(raw).hexdigest(),'archive digest mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        need(z.namelist()==[member] and z.getinfo(member).file_size<=32*1024*1024,'archive layout rejected')
        body=z.read(member)
    def unique(pairs):
        result={}
        for k,v in pairs:
            need(k not in result,'duplicate JSON key');result[k]=v
        return result
    return json.loads(body,object_pairs_hook=unique),hashlib.sha256(body).hexdigest()
def check_clock(generated,cutoff,server):
    g,c,s=ts(generated),ts(cutoff),ts(server)
    need(g<c and s<c and (g<=s or s.microsecond==0 and s<=g<s+timedelta(seconds=1)),
         'forecast not independently stored before cutoff')
def rank_check(ranked,top):
    combos=[tuple(r) for r in ranked]
    need(len(combos)==120 and set(combos)==UNIVERSE,'incomplete ranked universe')
    need([list(t) for t in combos[:8]]==top,'original top8 does not match rank')

def read_p0(raw,receipt,*,expected_day):
    run=receipt['workflow_run']['id']
    doc,body_sha=archive_json(raw,receipt,'forecasts.json',f'boat-p0-existing-{run}')
    need(doc.get('schema')=='RACE_AI_EXISTING_P0_DAY_V1' and doc.get('day_jst')==expected_day,'wrong forecast day/schema')
    need(doc.get('actual_purchases') is False,'not a research forecast')
    need(doc.get('race_count')==len(doc.get('predictions',[])),'forecast count mismatch')
    output=[];seen=set()
    for suite in doc['predictions']:
        sealed(suite,'suite_sha256');rid=official_id(suite['race_id'])
        need(rid not in seen and suite['event_date_jst']==expected_day and suite['stage']=='P0','duplicate or wrong-day suite')
        seen.add(rid);check_clock(suite['as_of'],suite['sales_cutoff_at'],receipt['created_at'])
        roster={str(x['lane']):x['registration_no'] for x in suite['observations']}
        need(set(roster)==set(map(str,range(1,7))) and len(set(roster.values()))==6,'original roster invalid')
        for mid,model in suite['models'].items():
            sealed(model,'prediction_sha256')
            need(mid==model['model_id'] and model['race_id']==suite['race_id'] and model['as_of']==suite['as_of']
                and model['sales_cutoff_at']==suite['sales_cutoff_at'] and model['snapshot_sha256']==suite['snapshot_sha256'],
                'cross-race/model binding rejected')
            ranked=[x['combination'] for x in model['candidates']];rank_check(ranked,model['ordered_top8'])
            output.append(dict(race_id=rid,sport='boat',stage='P0',model_id=mid,as_of=suite['as_of'],
                cutoff_at=suite['sales_cutoff_at'],server_saved_at=receipt['created_at'],artifact_id=receipt['id'],
                original_json_sha256=body_sha,model_sha256=model['prediction_sha256'],
                roster=roster,top8=model['ordered_top8'],ranked=ranked,calibrated=False))
    need(len(output)==doc.get('model_forecast_count'),'model count mismatch')
    return doc,output

def read_p1(raw,receipt):
    run=receipt['workflow_run']['id']
    doc,body_sha=archive_json(raw,receipt,'national.json',f'boat-national-cutoff-{run}')
    need(doc.get('schema')=='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1','P1 schema mismatch')
    shadows={r['race_id']:r for r in doc.get('additional_official_feature_shadows',[]) if 'bundle_sha256' in r}
    rows=[]
    for pair in doc.get('paired_forecasts',[]):
        sealed(pair,'bundle_sha256');check_clock(pair['generated_at'],pair['cutoff_at'],receipt['created_at'])
        rid=pair['race_id'];shadow=shadows.get(rid)
        # A/B omit roster in their output; use the same saved C-lite provenance.
        if shadow is None:continue
        sealed(shadow,'bundle_sha256')
        need(shadow['source_snapshot_sha256']==pair['source_sha256'],'P1 original inputs differ')
        roster={str(x['lane']):x['racer_id'] for x in shadow['features']}
        need(set(roster)==set(map(str,range(1,7))) and len(set(roster.values()))==6,'P1 original roster invalid')
        for model in [*pair['models'],shadow]:
            key='model_sha256' if 'model_sha256' in model else 'bundle_sha256';sealed(model,key)
            ranked=[list(map(int,x['ticket'].split('-'))) for x in model['full_120']]
            top=[list(map(int,x['ticket'].split('-'))) for x in model['top8']];rank_check(ranked,top)
            asof=model.get('as_of',pair['generated_at']);check_clock(asof,pair['cutoff_at'],receipt['created_at'])
            rows.append(dict(race_id=rid,sport='boat',stage='P1',model_id=model['model_id'],as_of=asof,
                cutoff_at=pair['cutoff_at'],server_saved_at=receipt['created_at'],artifact_id=receipt['id'],
                original_json_sha256=body_sha,model_sha256=model[key],roster=roster,top8=top,ranked=ranked,calibrated=False))
    from .observed_p1_connection import verified_rows
    pairs_by_id={p['race_id']:p for p in doc.get('paired_forecasts',[])}
    for bundle in doc.get('observed_pairwise_p1_bundles',[]):
        parent=pairs_by_id.get(bundle['race_id'])
        if parent is not None:
            need(bundle['base_source_sha256']==parent['source_sha256'] and
                 bundle['snapshot']['as_of']==parent['generated_at'], 'P1 observed and AB source/time mismatch')
        rows.extend(verified_rows(bundle,receipt,body_sha))
    keys=[(x['race_id'],x['stage'],x['model_id']) for x in rows]
    need(len(keys)==len(set(keys)), 'duplicate P1 race/phase/model in one original')
    return doc,rows

def settle(row,observation):
    base={k:v for k,v in row.items() if k not in ('ranked','roster')}
    if observation is None:return dict(base,state='RESULT_PENDING')
    need(observation.get('race_id')==row['race_id'],'foreign result')
    need(observation.get('body_identity_verified') is True,'unverified official identity')
    need(ts(observation['closed_at'])==ts(row['cutoff_at']) and ts(observation['captured_at'])>=ts(row['cutoff_at']),
         'result/cutoff chronology mismatch')
    base.update(result_captured_at=observation['captured_at'],result_sha256=observation['source_sha256'])
    data=observation.get('data')
    if observation.get('status')!='AVAILABLE' or not isinstance(data,dict):return dict(base,state='RESULT_PENDING')
    if data.get('status') in ('cancelled','no_contest') and data.get('confirmed') is True:
        return dict(base,state='FULL_REFUND',stake_yen=800,received_yen=800,net_yen=0)
    if data.get('finish_confirmed') is not True:return dict(base,state='RESULT_PENDING')
    roster={str(x['lane']):x['racer_registration_id'] for x in data.get('results',[])}
    need(len(data.get('results',[]))==6 and roster==row['roster'],'official/frozen racer identity mismatch')
    if data.get('refund_boats'):return dict(base,state='REFUND_REVIEW_REQUIRED')
    if any(x.get('finish_status')!='FINISHED' for x in data['results']):return dict(base,state='ABNORMAL_FINISH_REVIEW_REQUIRED')
    if data.get('status')!='settled' or data.get('confirmed') is not True:return dict(base,state='SETTLEMENT_PENDING')
    payouts=[x for x in data.get('payouts',[]) if x.get('bet_type')=='trifecta']
    if len(payouts)!=1:return dict(base,state='SPECIAL_SETTLEMENT_REVIEW_REQUIRED')
    winner=payouts[0]['combination'];yen=payouts[0]['payout_per_100_yen']
    need(tuple(winner) in UNIVERSE and data.get('top3')==winner and type(yen) is int and yen>=0,'payout/result mismatch')
    rank=row['ranked'].index(winner)+1;hit=rank<=8;top=row['top8']
    miss=('HIT' if hit else 'WINNER_NOT_COVERED' if not any(t[0]==winner[0] for t in top) else
          'FIRST_SECOND_PAIR_NOT_COVERED' if not any(t[:2]==winner[:2] for t in top) else 'THIRD_PLACE_MISMATCH')
    return dict(base,state='HIT' if hit else 'MISS',winning_combination=winner,payout_per_100_yen=yen,
        hit_rank=rank,stake_yen=800,received_yen=yen if hit else 0,net_yen=(yen if hit else 0)-800,
        pdca=miss,manshu_opportunity=yen>=10000,manshu_hit=hit and yen>=10000)

def evaluate(rows,observations):
    from .boat_cutoff_revision import cutoff_views, retain_frozen_cutoff
    keys=[(x['race_id'],x['stage'],x['model_id']) for x in rows]
    need(len(keys)==len(set(keys)),'duplicate forecast key')
    ids=[x['race_id'] for x in observations];need(len(ids)==len(set(ids)),'duplicate result observation')
    by_id={x['race_id']:x for x in observations};verdicts=[]
    evaluation_rows,revisions,blocked=cutoff_views(rows)
    for row in evaluation_rows:
        try:
            need(row['race_id'] not in blocked,blocked.get(row['race_id']))
            check_clock(row['as_of'],row['cutoff_at'],row['server_saved_at'])
            check_clock(row['as_of'],row.get('frozen_cutoff_at',row['cutoff_at']),row['server_saved_at'])
            verdicts.append(retain_frozen_cutoff(settle(row,by_id.get(row['race_id'])),row))
        except (ValueError,KeyError,TypeError) as e:
            # An invalid result must not erase an independently frozen forecast's receipt or tickets.
            # Keep original provenance for review, but never score this observation.
            base={k:v for k,v in row.items() if k not in ('ranked','roster')}
            verdicts.append(retain_frozen_cutoff(dict(base,state='RESULT_REJECTED',reason=str(e)[:160]),row))
    groups=defaultdict(list)
    for row in verdicts:groups[(row['stage'],row['model_id'])].append(row)
    scoreboard=[];proposals=[]
    for (phase,model),items in sorted(groups.items()):
        valid=[x for x in items if x['state'] in ('HIT','MISS')];hits=sum(x['state']=='HIT' for x in valid)
        stake=sum(x['stake_yen'] for x in valid);received=sum(x['received_yen'] for x in valid)
        failures=dict(Counter(x['pdca'] for x in valid if x['state']=='MISS'))
        scoreboard.append(dict(stage=phase,model_id=model,forecast_count=len(items),scored=len(valid),hits=hits,
            hit_rate=hits/len(valid) if valid else None,stake_yen=stake,received_yen=received,net_yen=received-stake,
            roi=received/stake if stake else None,pending=len(items)-len(valid),
            manshu_opportunities=sum(x['manshu_opportunity'] for x in valid),manshu_hits=sum(x['manshu_hit'] for x in valid),
            failure_categories=failures))
        if failures:proposals.append(dict(model_id=model,stage=phase,state='DIAGNOSTIC_ONLY_NEEDS_FUTURE_VALIDATION',
            failure_categories=failures,source_result_sha256=sorted({x['result_sha256'] for x in valid}),
            coefficients_changed=False,automatic_adoption=False))
    n=sum(x['state'] in ('HIT','MISS') for x in verdicts)
    return dict(schema='RACE_AI_EXISTING_MODEL_CYCLE_REPORT_V1',forecast_count=len(rows),
        distinct_races=len({x['race_id'] for x in rows}),scored_forecasts=n,pending_forecasts=len(rows)-n,
        per_forecast=verdicts,scoreboard=scoreboard,improvement_candidates=proposals,
        cutoff_revisions=revisions,cutoff_revision_conflicts=blocked,
        actual_purchases=False,past_forecasts_changed=False,auto_promoted=False,formal_model_superiority=False)
