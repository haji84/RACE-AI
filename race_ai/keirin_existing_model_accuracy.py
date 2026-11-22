"""Offline learned parameters for existing A; originals and production stay fixed.

This module accepts operator-supplied secondary-source research records. Hashes
and structural checks do not create issuer signatures or official settlement.
The unchanged generator remains the sole original-forecast replay authority.
"""
from datetime import datetime,timedelta,timezone
from hashlib import sha256
from itertools import permutations
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from . import keirin_nationwide_auto_generator as original

DEFAULT_WEIGHTS=(.50,.30,.14,.06,.055)
REGULARIZATION=(0.0,.1,1.0)
SCHEMA='RACE_AI_EXISTING_MODEL_PARAMETER_RESEARCH_V1'
SHADOW='RACE_AI_EXISTING_MODEL_PARAMETER_SHADOW_V1'
SCOPE='OPERATOR_SUPPLIED_SECONDARY_RESEARCH_NOT_OFFICIAL'
JST=timezone(timedelta(hours=9))
ARTIFACT_FIELDS=frozenset(('schema model_id scope created_at created_at_independently_attested '
    'source_model_sha256 research_code_sha256 weights selected_candidate trained_examples '
    'validation_examples training_boundary first_validation_input_at validation_labels_available_at '
    'train_race_ids validation_race_ids training_data_sha256 validation_data_sha256 '
    'validation_baseline validation_selected candidates selection_metric regularization_grid '
    'ticket_count calibrated production_promoted forward_improvement_proven '
    'registered_BOAT_study_changed artifact_sha256').split())


def _need(ok,code):
    if not ok:raise ValueError('KEIRIN_ACCURACY_'+code)


def _clock(clock):
    _need(clock is None or callable(clock),'CLOCK')
    now=datetime.now(timezone.utc) if clock is None else clock()
    _need(isinstance(now,datetime) and now.utcoffset() is not None,'CLOCK')
    return now.astimezone(timezone.utc)


def _weights(values):
    _need(type(values) in (list,tuple) and len(values)==5 and
        all(type(v) in (int,float) and math.isfinite(v) for v in values),'WEIGHTS')
    _need(all(0<=v<=1 for v in values[:4]) and 0<=values[4]<=.25 and
        math.isclose(math.fsum(values[:4]),1,rel_tol=0,abs_tol=1e-9),'WEIGHTS')
    return tuple(values)


def _features(snapshot):
    riders=snapshot['riders'];n=len(riders)
    low=min(r['competition_points'] for r in riders)
    span=max(r['competition_points'] for r in riders)-low
    return {r['car']:(((n+1-r['mark_rank'])/n if type(r['mark_rank']) is int else .10),
        ((r['competition_points']-low)/span if span else .5),r['recent_form_score'],
        min(r['h_count']+r['b_count'],30)/30) for r in riders}


def _rank(snapshot,weights):
    f=_features(snapshot);strength={car:weights[0]*x[0]+weights[1]*x[1]+
        weights[2]*x[2]+weights[3]*x[3] for car,x in f.items()}
    groups={car:i for i,g in enumerate(snapshot['line_groups']) for car in g}
    ranked=[]
    for a,b,c in permutations(f,3):
        score=1.00*strength[a]+.73*strength[b]+.52*strength[c]+weights[4]*(groups[a]==groups[b])
        ranked.append((score,(a,b,c)))
    ranked.sort(key=lambda row:(-row[0],row[1]))
    return [list(ticket) for unused,ticket in ranked]


def rank_tickets(snapshot,*,weights=DEFAULT_WEIGHTS,generated_at,ticket_count=8):
    _need(type(ticket_count) is int and 1<=ticket_count<=12,'TICKET_COUNT')
    _weights(weights)
    try:original.validate_snapshot(snapshot,computed_at=generated_at)
    except (ValueError,KeyError,TypeError):raise ValueError('KEIRIN_ACCURACY_SNAPSHOT_INVALID') from None
    return _rank(snapshot,weights)[:ticket_count]


def _provenance(row,kind):
    _need(type(row) is dict and set(row)=={'cipher_sha256','entry_created_at','kind','source_commit'} and
        row['kind']==kind and type(row['cipher_sha256']) is str and
        re.fullmatch('[a-f0-9]{64}',row['cipher_sha256']) and type(row['source_commit']) is str and
        re.fullmatch('[a-f0-9]{40}',row['source_commit']),'PROVENANCE')
    return original.when(row['entry_created_at'])


@lru_cache(maxsize=256)
def _exact_original(snapshot_json,baseline_json,source_sha):
    """Exact original-code replay; known historical runtimes, never float tolerance."""
    snapshot=json.loads(snapshot_json);baseline=json.loads(baseline_json)
    if original.generate_A_B(snapshot,generated_at=baseline['generated_at'],
            max_tickets=len(baseline['A']['ranked_tickets']))==baseline:return True
    # Python 3.12 changed built-in float summation. Retained originals were
    # actually created under both 3.11 (Actions) and 3.12 (owner research).
    # Invoke only installed known interpreters with fixed trusted source code.
    code="""import json,sys
from pathlib import Path
from hashlib import sha256
sys.path.insert(0,sys.argv[1])
from race_ai import keirin_nationwide_auto_generator as m
assert sha256(Path(m.__file__).read_bytes()).hexdigest()==sys.argv[2]
s,b=json.loads(sys.stdin.buffer.read())
print('MATCH' if m.generate_A_B(s,generated_at=b['generated_at'],max_tickets=len(b['A']['ranked_tickets']))==b else 'DIFFERENT')
"""
    root=str(Path(original.__file__).resolve().parents[1])
    for version in ((3,11),(3,12)):
        if version==sys.version_info[:2]:continue
        executable=shutil.which('python'+'.'.join(map(str,version)))
        if executable is None:continue
        try:
            result=subprocess.run([executable,'-c',code,root,source_sha],
                input=original.canonical([snapshot,baseline]),stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,timeout=10)
        except (OSError,subprocess.TimeoutExpired):continue
        if result.returncode==0 and result.stdout==b'MATCH\n':return True
    return False


def _available(row):
    return _provenance(row['result_provenance'],'results')


def _prepare(rows):
    from scripts.keirin_note_collect_results import checked_observation,MATCHED
    _need(type(rows) is list and rows,'ROWS')
    prepared=[];seen=set()
    for row in rows:
        _need(type(row) is dict and set(row)=={'snapshot','baseline','result','forecast_provenance','result_provenance'},'ROW_SCHEMA')
        snapshot,baseline,result=row['snapshot'],row['baseline'],row['result']
        _need(type(snapshot) is dict and type(baseline) is dict,'ORIGINAL')
        original.validate_snapshot(snapshot,computed_at=baseline['generated_at'])
        rid=snapshot['race_id'];cutoff=original.when(snapshot['published_cutoff_at'])
        _need(rid not in seen,'DUPLICATE_RACE_REVISION');seen.add(rid)
        _need(cutoff.astimezone(JST).strftime('%Y%m%d')==rid[:8],'RACE_DAY')
        _need(baseline['race_id']==rid and baseline['source_facts_sha256']==original.digest(snapshot) and
            baseline['prediction_sha256']==original.digest({k:v for k,v in baseline.items() if k!='prediction_sha256'}) and
            baseline['A']['model']==original.MODEL_A and baseline['B']['model']==original.MODEL_B,'ORIGINAL_HASH')
        a,b=baseline['A']['ranked_tickets'],baseline['B']['ranked_tickets']
        _need(type(a) is list and 8<=len(a)<=12 and type(b) is list and 1<=len(b)<=len(a),'ORIGINAL_TICKET_BUDGET')
        _need(_exact_original(original.canonical(snapshot),original.canonical(baseline),
            sha256(Path(original.__file__).read_bytes()).hexdigest()),'ORIGINAL_REPLAY')
        generated=original.when(baseline['generated_at'])
        _need(generated<=_provenance(row['forecast_provenance'],'research')<cutoff,'FORECAST_NOT_SAVED_PRE_CUTOFF')
        checked_observation(result)
        _need(result['state']==MATCHED and result['race_id']==rid,'MATCHED_RESULT_REQUIRED')
        captured=original.when(result['captured_at'])
        _need(cutoff<captured<=_available(row) and
            all(cutoff<original.when(receipt['observed_at']) for receipt in result['provider_receipts']),'RESULT_CLOCK')
        target=tuple(result['winning_triple'])
        _need(set(target)<=set(_features(snapshot)),'RESULT_ROSTER')
        prepared.append((snapshot,target,row))
    return prepared


def _score(prepared,weights):
    ranks=[]
    for snapshot,target,unused in prepared:
        ranked=_rank(snapshot,weights);ranks.append(ranked.index(list(target))+1)
    return dict(n=len(ranks),hits=sum(r<=8 for r in ranks),
        hit_at_8=sum(r<=8 for r in ranks)/len(ranks),mean_winning_rank=math.fsum(ranks)/len(ranks),
        ticket_count=8,official_evaluation=False)


def score_records(rows,*,weights=DEFAULT_WEIGHTS):
    _weights(weights)
    return _score(_prepare(rows),weights)


def _tables(prepared):
    import numpy as np
    tables=[]
    for snapshot,target,unused in prepared:
        f=_features(snapshot);groups={car:i for i,g in enumerate(snapshot['line_groups']) for car in g}
        triples=list(permutations(sorted(f),3))
        x=np.asarray([[*(f[a][j]+.73*f[b][j]+.52*f[c][j] for j in range(4)),
            float(groups[a]==groups[b])] for a,b,c in triples],dtype=float)
        tables.append((x,triples.index(target)))
    return tables


def _objective(theta,tables,regularization):
    import numpy as np
    from scipy.special import logsumexp,softmax
    loss=0.;grad=np.zeros(5)
    for x,target in tables:
        scores=10*(x@theta)
        loss+=float(logsumexp(scores)-scores[target])
        grad+=10*(softmax(scores)@x-x[target])
    delta=theta-np.asarray(DEFAULT_WEIGHTS)
    return (loss/len(tables)+regularization*float(delta@delta),
        grad/len(tables)+2*regularization*delta)


def _selection_key(candidate):
    metrics=candidate['validation']
    distance=math.fsum((v-d)**2 for v,d in zip(candidate['weights'],DEFAULT_WEIGHTS))
    return (-metrics['hits'],metrics['mean_winning_rank'],distance,candidate['selection'])


def fit_candidates(train_rows,validation_rows,*,clock=None):
    """Fit TRAIN only; select on a separate later-day cohort; no test-label API."""
    import numpy as np
    from scipy.optimize import minimize
    train=_prepare(train_rows);validation=_prepare(validation_rows)
    _need(len(train)>=6 and len(validation)>=2,'COHORT_TOO_SMALL')
    train_ids={s['race_id'] for s,unused,row in train};valid_ids={s['race_id'] for s,unused,row in validation}
    _need(not train_ids&valid_ids and max(rid[:8] for rid in train_ids)<min(rid[:8] for rid in valid_ids),'COHORT_OVERLAP')
    train_boundary=max(max(original.when(s['published_cutoff_at']),_available(row))
        for s,unused,row in train)
    _need(train_boundary<min(original.when(s['as_of']) for s,unused,row in validation),'TRAIN_LABEL_AFTER_VALIDATION_INPUT')
    now=_clock(clock)
    _need(all(_available(row)<=now for unused,target,row in train+validation),'LABEL_NOT_YET_AVAILABLE')
    tables=_tables(train)
    candidates=[dict(selection='unchanged_baseline',weights=list(DEFAULT_WEIGHTS),optimizer_success=True,
        validation=_score(validation,DEFAULT_WEIGHTS),training_surrogate_loss=_objective(np.asarray(DEFAULT_WEIGHTS),tables,0.)[0])]
    for regularization in REGULARIZATION:
        result=minimize(lambda theta:_objective(theta,tables,regularization),np.asarray(DEFAULT_WEIGHTS),
            method='SLSQP',jac=True,bounds=[(0.,1.)]*4+[(0.,.25)],
            constraints=[dict(type='eq',fun=lambda t:float(np.sum(t[:4])-1),jac=lambda t:np.asarray([1.,1.,1.,1.,0.]))],
            options=dict(maxiter=250,ftol=1e-10))
        if not result.success or not np.isfinite(result.x).all():continue
        weights=np.clip(result.x,0.,[1.,1.,1.,1.,.25]);weights[:4]/=np.sum(weights[:4]);weights=weights.tolist();_weights(weights)
        candidates.append(dict(selection='train_l2_'+str(regularization),weights=weights,optimizer_success=True,
            validation=_score(validation,weights),training_surrogate_loss=_objective(np.asarray(weights),tables,0.)[0]))
    selected=min(candidates,key=_selection_key)
    artifact=dict(schema=SCHEMA,model_id=original.MODEL_A,scope=SCOPE,created_at=now.isoformat(),
        created_at_independently_attested=False,source_model_sha256=sha256(Path(original.__file__).read_bytes()).hexdigest(),
        research_code_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),weights=selected['weights'],
        selected_candidate=selected['selection'],trained_examples=len(train),validation_examples=len(validation),
        training_boundary=train_boundary.isoformat(),
        first_validation_input_at=min(original.when(s['as_of']) for s,unused,row in validation).isoformat(),
        validation_labels_available_at=max(_available(row) for s,unused,row in validation).isoformat(),
        train_race_ids=sorted(train_ids),validation_race_ids=sorted(valid_ids),
        training_data_sha256=original.digest(sorted(train_rows,key=lambda r:r['snapshot']['race_id'])),
        validation_data_sha256=original.digest(sorted(validation_rows,key=lambda r:r['snapshot']['race_id'])),
        validation_baseline=candidates[0]['validation'],validation_selected=selected['validation'],
        candidates=candidates,selection_metric='VALIDATION_HIT_AT_8_THEN_MEAN_WINNING_RANK_THEN_BASELINE_DISTANCE',
        regularization_grid=list(REGULARIZATION),ticket_count=8,calibrated=False,production_promoted=False,
        forward_improvement_proven=False,registered_BOAT_study_changed=False)
    artifact['artifact_sha256']=original.digest(artifact)
    return artifact


def _artifact(artifact):
    _need(type(artifact) is dict and set(artifact)==ARTIFACT_FIELDS and artifact.get('schema')==SCHEMA and
        artifact.get('model_id')==original.MODEL_A and artifact.get('scope')==SCOPE and
        artifact.get('artifact_sha256')==original.digest({k:v for k,v in artifact.items() if k!='artifact_sha256'}),'ARTIFACT')
    _weights(artifact['weights'])
    _need(artifact.get('source_model_sha256')==sha256(Path(original.__file__).read_bytes()).hexdigest() and
        artifact.get('research_code_sha256')==sha256(Path(__file__).read_bytes()).hexdigest(),'MODEL_CODE_CHANGED')
    _need(all(artifact.get(k) is False for k in ('calibrated','production_promoted','forward_improvement_proven',
        'registered_BOAT_study_changed','created_at_independently_attested')) and artifact.get('ticket_count')==8,'RESEARCH_SCOPE')
    created=original.when(artifact['created_at']);boundary=original.when(artifact['training_boundary'])
    _need(boundary<original.when(artifact['first_validation_input_at']) and
        original.when(artifact['validation_labels_available_at'])<=created and boundary<created,'ARTIFACT_CHRONOLOGY')
    candidates=artifact['candidates']
    _need(type(candidates) is list and candidates and
        len({c['selection'] for c in candidates})==len(candidates),'CANDIDATES')
    for candidate in candidates:
        _weights(candidate['weights'])
        _need(candidate['optimizer_success'] is True and
            type(candidate['validation']['n']) is int and candidate['validation']['n']==artifact['validation_examples'] and
            type(candidate['validation']['hits']) is int and 0<=candidate['validation']['hits']<=artifact['validation_examples'] and
            candidate['validation']['ticket_count']==8,'CANDIDATE_METRICS')
    winner=min(candidates,key=_selection_key)
    baseline=next((c for c in candidates if c['selection']=='unchanged_baseline'),None)
    _need(baseline is not None and baseline['weights']==list(DEFAULT_WEIGHTS) and
        artifact['weights']==winner['weights'] and artifact['selected_candidate']==winner['selection'] and
        artifact['validation_selected']==winner['validation'] and artifact['validation_baseline']==baseline['validation'],
        'SELECTED_CANDIDATE_INCONSISTENT')
    return artifact


def forecast_candidate(snapshot,artifact,*,clock=None,expected_artifact_sha256=None):
    artifact=_artifact(artifact);now=_clock(clock)
    _need(expected_artifact_sha256 is None or artifact['artifact_sha256']==expected_artifact_sha256,'LOCK_DIGEST_CHANGED')
    _need(original.when(artifact['created_at'])<=now,'FORECAST_PRECEDES_ARTIFACT')
    _need(original.when(artifact['training_boundary'])<original.when(snapshot['as_of']),'INPUT_PRECEDES_TRAINING')
    _need(original.when(snapshot['published_cutoff_at']).astimezone(JST).strftime('%Y%m%d')==snapshot['race_id'][:8] and
        snapshot['race_id'] not in set(artifact['train_race_ids'])|set(artifact['validation_race_ids']),'FITTING_RACE_OR_DAY_CONFLICT')
    generated=now.isoformat()
    selected=rank_tickets(snapshot,weights=artifact['weights'],generated_at=generated)
    baseline=rank_tickets(snapshot,generated_at=generated)
    result=dict(schema=SHADOW,model_id=original.MODEL_A,candidate_sha256=artifact['artifact_sha256'],
        race_id=snapshot['race_id'],source_facts_sha256=original.digest(snapshot),source_as_of=snapshot['as_of'],
        generated_at=generated,published_cutoff_at=snapshot['published_cutoff_at'],ranked_tickets=selected,
        baseline_ranked_tickets=baseline,ticket_count=8,scope=SCOPE,calibrated=False,
        forward_improvement_proven=False,production_promoted=False,wagers_placed=False)
    result['forecast_sha256']=original.digest(result)
    return result
