"""Connect existing pairwise models to freshly captured official P1 inputs.

Source locators are query-free for the unchanged model contract. Exact request
URLs, race identity, byte hashes and individual capture times are kept beside
that snapshot. This adapter grants no new source rights or timestamp proof.
"""
from copy import deepcopy
import hashlib
from urllib.parse import urlsplit, parse_qs
from .actions_contract import digest
from .boat_ab_shadow import _valid, _time
from .boat_observed_pairwise_models import predict_pair, FEATURE_TRANSFORMS, MODEL_IDS

RIGHTS = 'OWNER_PERSONAL_OFFICIAL_HTML_ANALYSIS_20261104'
SCHEMA = 'RACE_AI_OBSERVED_P1_CONNECTION_V1'

def need(ok, reason):
    if not ok: raise ValueError(reason)

def locator(url, kind, rid):
    day, venue, number = rid.split('-')
    p = urlsplit(url)
    need(p.scheme == 'https' and p.netloc == 'www.boatrace.jp' and not p.fragment and
         p.path == '/owpc/pc/race/' + kind and
         parse_qs(p.query, keep_blank_values=True) == {'hd':[day], 'jcd':[venue], 'rno':[str(int(number))]},
         'P1 exact official request identity mismatch')
    return p.scheme + '://' + p.netloc + p.path

def build_bundle(base, extra, generated_at, *, program_url, preview_url,
                 program_captured_at, preview_captured_at, owner_reviewed=False):
    """No fetching, imputation, coefficient changes or actual purchases."""
    need(owner_reviewed is True, 'owner source scope required')
    boats = _valid(base, generated_at)
    rid = base['race_id']; day, venue, number = rid.split('-')
    day_iso = day[:4]+'-'+day[4:6]+'-'+day[6:]
    need(_time(program_captured_at) <= _time(preview_captured_at) <= _time(generated_at), 'P1 capture chronology mismatch')
    need(_time(base['captured_at']) == _time(preview_captured_at) and
         extra['race_id'] == rid and _time(extra['observed_at']) == _time(preview_captured_at), 'P1 extra source binding mismatch')
    need(extra['source_sha256'] == hashlib.sha256((base['program_source_sha256']+base['beforeinfo_source_sha256']).encode()).hexdigest(), 'P1 extra source SHA mismatch')
    sources=[]; http=[]
    for kind,url,sha,at in (
        ('racelist',program_url,base['program_source_sha256'],program_captured_at),
        ('beforeinfo',preview_url,base['beforeinfo_source_sha256'],preview_captured_at)):
        sid=kind+'-'+rid
        sources.append(dict(source_id=sid,source_url=locator(url,kind,rid),source_sha256=sha,
            source_rights_ref=RIGHTS,published_at=None,captured_at=at,evidence_basis='CAPTURED_BY_CLAIM'))
        http.append(dict(source_id=sid,request_url=url,source_sha256=sha,captured_at=at))
    need(len(extra['participants']) == 6, 'P1 six ST observations required')
    by_lane={x['lane']:x for x in extra['participants']}
    need(set(by_lane)==set(range(1,7)), 'P1 duplicate or missing lane')
    participants=[]
    for row in boats:
        item=by_lane[row['lane']]
        need(item['racer_id']==row['racer_id'], 'P1 program/exhibition racer mismatch')
        values={'national_win_rate':row['national_win_rate'], 'motor_top2_rate':row['motor_two_place_rate_percent'],
                'exhibition_time_seconds':row['exhibition_time_seconds']}
        missing={k:'NO_PRIOR_SAMPLES' for k in ('recent_mean_finish','course_mean_finish','recent_mean_st','course_mean_st')}
        status=item['exhibition_st_status']; st=item['exhibition_st']
        need(status in ('OK','F','L','PENDING') and (status=='OK') == (st is not None), 'P1 inconsistent ST disposition')
        if status=='OK': values['exhibition_start_seconds']=st
        else: missing['exhibition_start_seconds']=status if status in ('F','L') else 'NOT_YET_PUBLISHED'
        features={}
        for name,value in values.items():
            if value is None: missing[name]='MISSING'; continue
            source=sources[1] if name.startswith('exhibition_') else sources[0]
            features[name]=dict(value=value,sample_n=None,source_id=source['source_id'],transform_id=FEATURE_TRANSFORMS[name])
        participants.append(dict(lane=row['lane'],registration_no=row['racer_id'],features=features,missing=missing))
    snapshot=dict(schema='RACE_AI_BOAT_OBSERVED_PAIRWISE_V1',scope='OPERATOR_SUPPLIED_RESEARCH',
        race_id=f'boat:{day_iso}:boatrace-jcd-{venue}:{int(number)}',event_date_jst=day_iso,
        venue='boatrace-jcd-'+venue,race_revision=1,sales_cutoff_at=base['cutoff_at'],as_of=generated_at,
        stage='P1',race_source_id=sources[0]['source_id'],sources=sources,participants=participants)
    admitted={s['source_url'] for s in sources}
    suite=predict_pair(snapshot,allow_source=lambda url,ref,purpose: url in admitted and ref==RIGHTS and purpose=='analysis')
    out=dict(schema=SCHEMA,race_id=rid,base_source_sha256=digest(base),snapshot=snapshot,suite=suite,
             http_provenance=http,source_locator_semantics='QUERY_FREE_LOCATOR_WITH_EXACT_REQUEST_BESIDE_IT',
             actual_purchases=False,new_model=False)
    out['bundle_sha256']=digest(out)
    return out

def verified_rows(bundle, receipt, body_sha):
    """Read saved original only; external archive authentication is caller-owned."""
    from .frozen_day_cycle import sealed, check_clock, official_id, rank_check
    sealed(bundle,'bundle_sha256')
    need(bundle.get('schema')==SCHEMA and bundle.get('actual_purchases') is False and bundle.get('new_model') is False, 'observed P1 bundle schema')
    snap=bundle['snapshot']; suite=bundle['suite']; sealed(suite,'suite_sha256')
    rid=official_id(snap['race_id'])
    need(rid==bundle['race_id'] and snap['stage']=='P1' and suite['stage']=='P1', 'observed P1 identity/phase mismatch')
    need(suite['snapshot_sha256']==digest(snap) and suite['observations']==snap['participants'] and
         suite['source_evidence']==snap['sources'] and tuple(suite['models'])==MODEL_IDS, 'observed P1 snapshot/model binding mismatch')
    need(len(bundle['http_provenance'])==len(snap['sources'])==2,'P1 exact provenance required')
    for kind,source,http in zip(('racelist','beforeinfo'),snap['sources'],bundle['http_provenance']):
        need(source['source_url']==locator(http['request_url'],kind,rid) and
             all(source[k]==http[k] for k in ('source_id','source_sha256','captured_at')) and
             _time(http['captured_at'])<=_time(snap['as_of']), 'P1 source provenance mismatch')
    check_clock(snap['as_of'],snap['sales_cutoff_at'],receipt['created_at'])
    roster={str(x['lane']):x['registration_no'] for x in snap['participants']}
    need(len(snap['participants'])==6 and set(roster)==set(map(str,range(1,7))) and len(set(roster.values()))==6,'P1 observed roster invalid')
    output=[]
    for mid,model in suite['models'].items():
        sealed(model,'prediction_sha256')
        need(model['model_id']==mid and model['race_id']==snap['race_id'] and model['as_of']==snap['as_of'] and
             model['sales_cutoff_at']==snap['sales_cutoff_at'] and model['snapshot_sha256']==digest(snap) and
             model['stage']=='P1' and model['official_prediction'] is False,'P1 observed model binding mismatch')
        ranked=[x['combination'] for x in model['candidates']];rank_check(ranked,model['ordered_top8'])
        output.append(dict(race_id=rid,sport='boat',stage='P1',model_id=mid,as_of=snap['as_of'],
            cutoff_at=snap['sales_cutoff_at'],server_saved_at=receipt['created_at'],artifact_id=receipt['id'],
            original_json_sha256=body_sha,model_sha256=model['prediction_sha256'],roster=roster,
            top8=deepcopy(model['ordered_top8']),ranked=ranked,calibrated=False))
    return output
