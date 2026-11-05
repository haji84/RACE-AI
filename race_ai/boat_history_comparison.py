"""Frozen, equal-as-of reference/history pairs of existing BOAT models.

This isolates measured recent-history inputs. Course is not inferred from a
lane, motor epochs are not invented, and a local seal is not an external clock.
"""
from collections import Counter
from copy import deepcopy
from datetime import date,datetime,timezone
import json
from pathlib import Path
import re

from .actions_contract import digest
from .boat_history_store import instant,wire
from .boat_observed_pairwise_models import predict_pair,FEATURE_TRANSFORMS
from .frozen_day_cycle import sealed,official_id,settle,check_clock

RECENT=('recent_mean_finish','recent_mean_st')
RIGHTS='OWNER_PERSONAL_OFFICIAL_HISTORY_ANALYSIS_20261106'


def need(ok,reason):
    if not ok:raise ValueError(reason)


def run(snapshot):
    allowed={(s['source_url'],s['source_rights_ref']) for s in snapshot['sources']}
    return predict_pair(snapshot,allow_source=lambda url,ref,purpose:(url,ref) in allowed and purpose=='analysis')


class EvidenceHistory:
    """Replay a frozen selected window, without claiming career completeness."""
    def __init__(self,evidence):self.evidence=evidence

    def history_rows(self,regs,as_of):
        windows=self.evidence['windows'];proofs=self.evidence['source_proofs'];clock=instant(as_of)
        need(set(windows)==set(regs),'HISTORY_EVIDENCE_ROSTER_MISMATCH')
        output=[];seen=set()
        from .official_archive_probe import official_url
        for reg,window in windows.items():
            need(isinstance(window,list) and len(window)<=10,'HISTORY_EVIDENCE_WINDOW_LIMIT')
            for row in window:
                day=date.fromisoformat(row['day']);proof=proofs[row['day']]
                need(row['racer_id']==reg and row['race_id'].startswith(day.strftime('%Y%m%d')+'-') and type(row['lane']) is int and row['lane'] in range(1,7),
                    'HISTORY_EVIDENCE_MEMBER_IDENTITY')
                need(row['st_status'] in ('OK','F','L','MISSING') and
                     (row['st_status']=='OK')==(row['st'] is not None),'HISTORY_EVIDENCE_START_STATUS')
                need(row['st'] is None or type(row['st']) in (float,int) and 0<=row['st']<=1,'HISTORY_EVIDENCE_START_VALUE')
                for kind in ('B','K'):
                    src=proof[kind]
                    need(src['source_url']==official_url(day,kind) and re.fullmatch(r'[a-f0-9]{64}',src['source_sha256']) is not None,
                        'HISTORY_EVIDENCE_SOURCE_IDENTITY')
                    need(instant(src['captured_at'])<clock,'HISTORY_EVIDENCE_FUTURE_CAPTURE')
                need(row['source_sha256']==proof['K']['source_sha256'] and instant(row['cutoff_at'])<instant(proof['K']['captured_at']) and
                     instant(row['available_at'])==max(instant(p['captured_at']) for p in proof.values()),'HISTORY_EVIDENCE_SOURCE_BINDING')
                identity=(row['race_id'],row['lane'])
                need(identity not in seen,'HISTORY_EVIDENCE_DUPLICATE_START');seen.add(identity);output.append(deepcopy(row))
            need(window==sorted(window,key=lambda r:(instant(r['cutoff_at']),r['race_id'],r['lane'])),'HISTORY_EVIDENCE_WINDOW_ORDER')
        return output

    def source_proofs(self,as_of,days):
        return deepcopy({d:v for d,v in self.evidence['source_proofs'].items() if d in days})


def prepare_pair(snapshot,history_store,now):
    clock=instant(now);cutoff=instant(snapshot['sales_cutoff_at'])
    need(clock<cutoff and instant(snapshot['as_of'])<=clock,'PROSPECTIVE_CURRENT_CLOCK_REQUIRED')
    baseline=deepcopy(snapshot);baseline['as_of']=clock.isoformat()
    a=run(baseline)
    candidate=deepcopy(baseline)
    regs=[p['registration_no'] for p in baseline['participants']]
    rows=history_store.history_rows(regs,clock)
    windows={reg:[r for r in rows if r['racer_id']==reg and r['st_status']!='ABSENT'][-10:] for reg in regs}
    days={r['day'] for w in windows.values() for r in w}
    proofs=history_store.source_proofs(clock,days)
    source_ids={}
    for day,proof in sorted(proofs.items()):
        for kind,source in sorted(proof.items()):
            sid=f'history-{kind}-{day}-{source["source_sha256"][:12]}'
            candidate['sources'].append(dict(source_id=sid,source_url=source['source_url'],source_sha256=source['source_sha256'],
                source_rights_ref=RIGHTS,published_at=None,captured_at=source['captured_at'],evidence_basis='CAPTURED_BY_CLAIM'))
            source_ids[(day,kind)]=sid
    coverage=Counter()
    for participant in candidate['participants']:
        reg=participant['registration_no'];window=windows[reg]
        counts=Counter(r['st_status'] for r in window)
        for name in RECENT:
            participant['features'].pop(name,None)
            participant['missing'][name]='NO_PRIOR_SAMPLES'
        if not window:continue
        source_id=source_ids[(window[-1]['day'],'K')]
        # The primary source pointer is a provenance pivot. The window seal and
        # evidence retain EVERY contributing B/K source and each selected row.
        window_id='captured-last10-'+digest(dict(racer_id=reg,rows=window))
        finish_ok=all(r['normal_result'] and type(r['finish']) is int and 1<=r['finish']<=6 for r in window)
        if finish_ok:
            values=[r['finish'] for r in window]
            participant['features']['recent_mean_finish']=dict(value=sum(values)/len(values),sample_n=len(values),source_id=source_id,
                transform_id=FEATURE_TRANSFORMS['recent_mean_finish'],history=dict(window_id=window_id,total_n=len(window),ok_n=len(values),f_n=0,l_n=0,missing_n=0,unresolved_n=0))
            participant['missing'].pop('recent_mean_finish',None);coverage['participants_with_recent_finish']+=1
        else:participant['missing']['recent_mean_finish']='UNRESOLVED_DISPOSITION'
        values=[r['st'] for r in window if r['st_status']=='OK' and r['st'] is not None]
        unresolved=sum(v for k,v in counts.items() if k not in ('OK','F','L','MISSING'))
        if values and not unresolved:
            participant['features']['recent_mean_st']=dict(value=sum(values)/len(values),sample_n=len(values),source_id=source_id,
                transform_id=FEATURE_TRANSFORMS['recent_mean_st'],history=dict(window_id=window_id,total_n=len(window),ok_n=len(values),f_n=counts['F'],l_n=counts['L'],missing_n=counts['MISSING'],unresolved_n=0))
            participant['missing'].pop('recent_mean_st',None);coverage['participants_with_recent_st']+=1
    b=run(candidate)
    pair=dict(schema='RACE_AI_RECENT_HISTORY_PROSPECTIVE_PAIR_V1',race_id=official_id(baseline['race_id']),
        stage=baseline['stage'],generated_at=clock.isoformat(),cutoff_at=baseline['sales_cutoff_at'],
        protocol='SAME_ASOF_FIXED8_RECENT_HISTORY_ONLY_EXISTING_WEIGHTS',
        baseline=dict(snapshot=baseline,suite=a),history=dict(snapshot=candidate,suite=b),
        history_evidence=dict(windows=windows,source_proofs=proofs,primary_source_pointer_semantics='PIVOT_WITH_ALL_CONTRIBUTING_SOURCES_IN_WINDOW'),
        history_coverage={name:coverage[name] for name in ('participants_with_recent_finish','participants_with_recent_st')},
        independent_pre_cutoff_receipt_verified=False,actual_purchases=False,auto_promoted=False)
    pair=json.loads(wire(pair))  # JSON-native contract also survives freeze/readback.
    pair['pair_sha256']=digest(pair)
    return pair


def verify_pair(pair):
    sealed(pair,'pair_sha256')
    need(pair.get('schema')=='RACE_AI_RECENT_HISTORY_PROSPECTIVE_PAIR_V1','HISTORY_PAIR_SCHEMA_REQUIRED')
    need(pair.get('actual_purchases') is False and pair.get('auto_promoted') is False,'HISTORY_PAIR_RESEARCH_ONLY')
    a=pair['baseline']['snapshot'];b=pair['history']['snapshot']
    need(a['as_of']==b['as_of']==pair['generated_at'] and a['sales_cutoff_at']==b['sales_cutoff_at']==pair['cutoff_at'],
         'HISTORY_PAIR_CLOCK_MISMATCH')
    need(official_id(a['race_id'])==official_id(b['race_id'])==pair['race_id'],'HISTORY_PAIR_RACE_MISMATCH')
    need(b['sources'][:len(a['sources'])]==a['sources'],'HISTORY_PAIR_CURRENT_SOURCE_CHANGED')
    for left,right in zip(a['participants'],b['participants']):
        need(left['lane']==right['lane'] and left['registration_no']==right['registration_no'],'HISTORY_PAIR_ROSTER_CHANGED')
        need({k:v for k,v in left['features'].items() if k not in RECENT}=={k:v for k,v in right['features'].items() if k not in RECENT},
             'HISTORY_PAIR_NONHISTORY_FEATURE_CHANGED')
    for variant in ('baseline','history'):
        version=pair[variant];sealed(version['suite'],'suite_sha256')
        need(all(len(m['ordered_top8'])==8 for m in version['suite']['models'].values()),'HISTORY_PAIR_EXACT_EIGHT_REQUIRED')
    replay=prepare_pair(a,EvidenceHistory(pair['history_evidence']),pair['generated_at'])
    need(replay['pair_sha256']==pair['pair_sha256'],'HISTORY_PAIR_MODEL_OR_EVIDENCE_REPLAY_MISMATCH')
    return pair


def freeze_pair(pair,path):
    from scripts.boat_history_collect import private_root,save
    verify_pair(pair);path=Path(path).absolute();private_root(path.parent)
    save(path,(wire(pair)+'\n').encode())
    return path


def load_pair(path):
    path=Path(path)
    need(not path.is_symlink() and path.stat().st_size<=16*1024*1024,'HISTORY_PAIR_BOUNDED_FILE_REQUIRED')
    return verify_pair(json.loads(path.read_text()))


def score_pair(pair,observation,now):
    verify_pair(pair);clock=instant(now)
    need(instant(observation['captured_at'])<=clock and instant(observation['captured_at'])>=instant(pair['cutoff_at']),
         'HISTORY_PAIR_LATER_RESULT_REQUIRED')
    need(clock>=instant(pair['cutoff_at']),'HISTORY_PAIR_CUTOFF_NOT_REACHED')
    verdicts={}
    for variant in ('baseline','history'):
        version=pair[variant];snap=version['snapshot'];suite=version['suite']
        roster={str(p['lane']):p['registration_no'] for p in snap['participants']}
        verdicts[variant]={}
        for mid,model in suite['models'].items():
            row=dict(race_id=pair['race_id'],stage=snap['stage'],model_id=mid,as_of=snap['as_of'],
                cutoff_at=snap['sales_cutoff_at'],server_saved_at=pair['generated_at'],
                roster=roster,top8=model['ordered_top8'],ranked=[r['combination'] for r in model['candidates']])
            verdicts[variant][mid]=settle(row,observation)
    out=[]
    for mid in verdicts['baseline']:
        a=verdicts['baseline'][mid];b=verdicts['history'][mid]
        eligible=a['state'] in ('HIT','MISS') and b['state'] in ('HIT','MISS')
        out.append(dict(model_id=mid,paired=eligible,baseline_state=a['state'],history_state=b['state'],
            baseline_hit=a['state']=='HIT' if eligible else None,history_hit=b['state']=='HIT' if eligible else None,
            stake_yen_per_variant=800 if eligible else None,baseline_received_yen=a.get('received_yen'),history_received_yen=b.get('received_yen')))
    return dict(race_id=pair['race_id'],pair_sha256=pair['pair_sha256'],result_sha256=observation['source_sha256'],models=out,
        independent_pre_cutoff_receipt_verified=pair['independent_pre_cutoff_receipt_verified'],
        accuracy_improvement_proven=False,auto_promoted=False)
