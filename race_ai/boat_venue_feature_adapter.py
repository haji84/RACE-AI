"""Authenticated venue/course aggregates -> existing native research inputs.

No new model/weights, current-entry inference, recent-history substitution or
retrospective availability claim. The course condition is today's FRAME applied
to past ACTUAL courses. Unknown historical courses and source gaps withhold it.
"""
from copy import deepcopy
from datetime import date
import re

from .actions_contract import digest,stamp
from .boat_observed_pairwise_models import _validate,FEATURE_TRANSFORMS
from .boat_venue_dataset import _manifest,_sha,lookup,INPUT,PREFIX
from .teiai_history import need

RIGHTS='OWNER_PERSONAL_OFFICIAL_VENUE_HISTORY_ANALYSIS_20261106'
FIELDS=('course_mean_finish','course_mean_st')

def enrich_venue_snapshot(snapshot,folder,pointer,*,verified_at,allow_source=None):
    """Return a copied snapshot and private evidence; caller admits source use.

    Source-period membership comes from the owner-authenticated dataset and its
    pinned encrypted originals. A key/hash is not a permission grant. Both
    existing models must receive this same returned snapshot.
    """
    _validate(snapshot);need(snapshot['scope']=='OPERATOR_SUPPLIED_RESEARCH','VENUE_FEATURE_RESEARCH_ONLY')
    need(callable(allow_source),'VENUE_FEATURE_SOURCE_USE_REVIEW_REQUIRED')
    raw,state=_manifest(folder);now=stamp(snapshot['as_of']);verified=stamp(verified_at)
    need(stamp(state['available_at'])<=verified<=now<stamp(snapshot['sales_cutoff_at']),'VENUE_FEATURE_AVAILABILITY_OR_CUTOFF')
    need(date.fromisoformat(state['requested_end'])<date.fromisoformat(snapshot['event_date_jst']),'VENUE_FEATURE_CURRENT_OR_FUTURE_RESULTS')
    sha=_sha(raw)
    need(type(pointer) is dict and pointer.get('schema')==INPUT and pointer.get('status')=='READY' and
         pointer.get('repository_id')=='1416489937' and pointer.get('dataset_sha256')==sha and
         type(pointer.get('source_commit')) is str and re.fullmatch('[a-f0-9]{40}',pointer['source_commit']) and
         pointer.get('dataset_path')==PREFIX+'datasets/'+sha+'/dataset.json','VENUE_FEATURE_PIN_REQUIRED')
    url='https://raw.githubusercontent.com/haji84/RACE-AI/'+pointer['source_commit']+'/'+pointer['dataset_path']
    need(allow_source(url,RIGHTS,'analysis') is True,'VENUE_FEATURE_ANALYSIS_NOT_ADMITTED')
    source_id='official-venue-grid-'+sha[:16]
    source=dict(source_id=source_id,source_url=url,source_sha256=sha,source_rights_ref=RIGHTS,
                published_at=None,captured_at=verified_at,evidence_basis='CAPTURED_BY_CLAIM')
    out=deepcopy(snapshot);old=[s for s in out['sources'] if s['source_id']==source_id]
    need(not old or old==[source],'VENUE_FEATURE_CONFLICTING_SOURCE')
    if not old:out['sources'].append(source)
    venue=snapshot['venue'].removeprefix('boatrace-jcd-');evidence={};st_participants=0
    for participant in out['participants']:
        pid=participant['registration_no'];profile=lookup(folder,pid,venue,as_of=snapshot['as_of'])
        for name in FIELDS:
            participant['features'].pop(name,None);participant['missing'][name]='NO_PRIOR_SAMPLES'
        evidence[pid]=dict(profile=profile,condition='HISTORICAL_ACTUAL_COURSE_EQUALS_CURRENT_FRAME_NOT_CURRENT_ENTRY',
            current_frame=participant['lane'],period_start=state['requested_start'],period_end=state['requested_end'])
        if not profile['history_completeness']:
            participant['missing'].update({name:'SOURCE_UNAVAILABLE' for name in FIELDS});continue
        if profile['stats']['unknown_course_n']:
            participant['missing'].update({name:'NO_VERIFIED_COURSE' for name in FIELDS});continue
        b=profile['by_actual_course'][str(participant['lane'])];n=b['opportunities']
        if not n:continue
        window='official-venue-course-all-available-'+digest(evidence[pid])
        def add(name,value,ok,f=0,l=0,missing=0):
            need(ok>0 and ok+f+l+missing==n and missing>=0,'VENUE_FEATURE_INCONSISTENT_COUNTS')
            participant['features'][name]=dict(value=value,sample_n=ok,source_id=source_id,transform_id=FEATURE_TRANSFORMS[name],
                history=dict(window_id=window,total_n=n,ok_n=ok,f_n=f,l_n=l,missing_n=missing,unresolved_n=0))
            participant['missing'].pop(name,None)
        if b['numeric_finish_n']==n and not b['special_result_n']:
            add('course_mean_finish',sum((i+1)*count for i,count in enumerate(b['finish_counts']))/n,n)
        else:participant['missing']['course_mean_finish']='UNRESOLVED_DISPOSITION'
        if b['st_n']:
            f=sum(v for code,v in b['dispositions'].items() if code.startswith('F'))
            l=sum(v for code,v in b['dispositions'].items() if code.startswith('L'))
            add('course_mean_st',b['mean_st'],b['st_n'],f,l,n-b['st_n']-f-l);st_participants+=1
        else:participant['missing']['course_mean_st']='UNRESOLVED_DISPOSITION'
    _validate(out)
    return dict(snapshot=out,venue_evidence=evidence,dataset_sha256=sha,course_st_participants=st_participants,
        actual_entry_course_inferred=False,recent_history_replaced=False,model_coefficients_changed=False,
        formal_backtest_eligible=False,production_promoted=False,actual_purchases=False)
