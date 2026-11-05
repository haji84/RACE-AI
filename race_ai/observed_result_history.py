"""Captured official-result opportunities from already authenticated cycle ZIPs.

The ZIP receipt authenticates saved journal bytes, not upstream publication or
career completeness. Callers must independently authenticate parent membership
with ``validate_history_proofs`` when recovering a downstream P1 original.
"""
from copy import deepcopy
import io
import json
import math
import re
import zipfile

from .actions_contract import digest, stamp
from .boat_observed_pairwise_models import FEATURE_TRANSFORMS

SCHEMA = 'RACE_AI_OBSERVED_RESULT_HISTORY_V1'
EVIDENCE_SCHEMA = 'RACE_AI_OBSERVED_HISTORY_EVIDENCE_V1'
COVERAGE = 'CAPTURED_VERIFIED_PRIOR_RACE_OPPORTUNITIES_LAST10_NOT_CAREER'
RIGHTS = 'OWNER_PERSONAL_OFFICIAL_HTML_ANALYSIS_20261104'
MANIFEST_FIELDS = {'schema','receipt','verified_at','journal_index','journal_sha256','context_sha256'}


def need(ok, reason):
    if not ok: raise ValueError(reason)


def _seal(value, field):
    value[field] = digest({k:v for k,v in value.items() if k != field})
    return value


def _check(value, field):
    need(type(value) is dict and value.get(field) == digest({k:v for k,v in value.items() if k != field}),
         'history integrity mismatch: '+field)


def _race(rid):
    need(type(rid) is str and re.fullmatch(r'\d{8}-(?:0[1-9]|1\d|2[0-4])-(?:0[1-9]|1[0-2])',rid),
         'history race identity')
    stamp(rid[:4]+'-'+rid[4:6]+'-'+rid[6:8]+'T00:00:00+09:00')


def _roster(participants):
    need(type(participants) is list and len(participants)==6,'history six participants required')
    rows=[dict(lane=r['lane'],registration_no=r['registration_no']) for r in participants]
    need(all(type(r['lane']) is int and type(r['registration_no']) is str and
             re.fullmatch(r'[0-9]{4}',r['registration_no']) for r in rows) and
         {r['lane'] for r in rows}==set(range(1,7)) and
         len({r['registration_no'] for r in rows})==6,'history participant identity mismatch')
    return sorted(rows,key=lambda r:r['lane'])


def _receipt(receipt, verified_at):
    from .repeated_cycle import matches
    run=receipt.get('workflow_run',{}).get('id')
    need(type(receipt.get('id')) is int and receipt['id']>0 and type(run) is int and run>0 and
         receipt.get('expired') is False and receipt['workflow_run'].get('head_repository_id')==1416489937 and
         matches(receipt.get('name'),f'race-existing-cycle-{run}') and
         type(receipt.get('digest')) is str and re.fullmatch(r'sha256:[0-9a-f]{64}',receipt['digest']),
         'history parent receipt identity')
    need(stamp(receipt['created_at'])<=stamp(verified_at),'history receipt must precede verification')


def _index(observations):
    need(type(observations) is list and len(observations)<=20000,'bounded history journal')
    out=[];seen={}
    for observation in observations:
        _race(observation['race_id']);at=stamp(observation['captured_at'])
        sha=digest(observation);key=(observation['race_id'],at)
        need(key not in seen or seen[key]==sha,'same result capture has conflicting history body')
        seen[key]=sha
        data=observation.get('data')
        rows=data.get('results',[]) if type(data) is dict else []
        regs=sorted({r['racer_registration_id'] for r in rows if type(r) is dict and
                     type(r.get('racer_registration_id')) is str})
        out.append(dict(race_id=observation['race_id'],captured_at=observation['captured_at'],
                        observation_sha256=sha,registration_nos=regs))
    return out


def _manifest(context):
    return {k:deepcopy(v) for k,v in context.items() if k!='observations'}


def _validate_manifest(manifest):
    need(type(manifest) is dict and set(manifest)==MANIFEST_FIELDS and manifest['schema']==SCHEMA,
         'history context schema')
    _check(manifest,'context_sha256');_receipt(manifest['receipt'],manifest['verified_at'])
    need(type(manifest['journal_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',manifest['journal_sha256']) and
         type(manifest['journal_index']) is list and len(manifest['journal_index'])<=20000,'history journal manifest')
    seen={}
    for item in manifest['journal_index']:
        need(type(item) is dict and set(item)=={'race_id','captured_at','observation_sha256','registration_nos'},'history journal index shape')
        _race(item['race_id']);key=(item['race_id'],stamp(item['captured_at']))
        need(type(item['observation_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',item['observation_sha256']) and
             type(item['registration_nos']) is list and all(type(x) is str for x in item['registration_nos']) and
             item['registration_nos']==sorted(set(item['registration_nos'])),'history journal index values')
        need(key not in seen or seen[key]==item['observation_sha256'],'same result capture has conflicting history body')
        seen[key]=item['observation_sha256']


def _validate_context(context):
    need(type(context) is dict and set(context)==MANIFEST_FIELDS|{'observations'},'history context fields')
    manifest=_manifest(context);_validate_manifest(manifest)
    need(digest(context['observations'])==context['journal_sha256'] and
         _index(context['observations'])==context['journal_index'],'history journal integrity mismatch')
    return manifest


def context_from_result_archive(raw, receipt, *, verified_at):
    """Read one complete saved journal; ``verified_at`` is actual local capture.

    The context seal covers its manifest; journal_sha256 separately covers the
    complete ordered original journal. Evidence can then omit irrelevant full
    bodies while retaining the authenticated complete version inventory.
    """
    from .cycle_recovery import result_archive, _result_day
    _receipt(receipt,verified_at)
    day=_result_day(raw,receipt)
    observations=result_archive(raw,receipt,day)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        need(sum(i.file_size for i in archive.infolist())<=512*1024*1024 and archive.testzip() is None,
             'history archive member CRC/bounds')
        report=None
        if 'status.json' in archive.namelist():
            need(archive.getinfo('status.json').file_size<=16*1024*1024,'history parent report bounded')
            report=json.loads(archive.read('status.json'))
    if report is not None:
        _check(report,'report_sha256')
        need(('day_jst' not in report or report['day_jst']==day) and ('result_observation_versions' not in report or
             report['result_observation_versions']==len(observations)), 'history report journal identity/count mismatch')
    manifest=dict(schema=SCHEMA,receipt=deepcopy(receipt),verified_at=verified_at,
                  journal_index=_index(observations),journal_sha256=digest(observations))
    _seal(manifest,'context_sha256')
    return dict(manifest,observations=deepcopy(observations))


def history_proof(context):
    """Stable parent proof; populate from independent API receipt and ZIP reads."""
    _validate_context(context);receipt=context['receipt']
    return dict(id=receipt['id'],digest=receipt['digest'],created_at=receipt['created_at'],
                receipt_sha256=digest(receipt),context_sha256=context['context_sha256'],
                journal_sha256=context['journal_sha256'],journal_index=deepcopy(context['journal_index']),
                observation_sha256s=sorted({r['observation_sha256'] for r in context['journal_index']}))


def _latest_relevant(manifest, race_id, participants, as_of):
    clock=stamp(as_of);regs={r['registration_no'] for r in participants}
    relevant={i['race_id'] for i in manifest['journal_index'] if regs.intersection(i['registration_nos'])}
    latest={}
    for item in manifest['journal_index']:
        rid=item['race_id'];at=stamp(item['captured_at'])
        if rid==race_id or rid not in relevant or at>clock:continue
        if rid not in latest or at>stamp(latest[rid]['captured_at']):latest[rid]=item
    return sorted(latest.values(),key=lambda i:(stamp(i['captured_at']),i['race_id']))


def _official_rows(observation, clock, saved):
    """Never use an older positive capture when the newest capture is unknown."""
    try:
        rid=observation['race_id']
        from .observed_p1_connection import locator
        locator(observation['source_url'],'raceresult',rid)
        need(type(observation.get('source_sha256')) is str and re.fullmatch(r'[0-9a-f]{64}',observation['source_sha256']), 'history official source hash')
        captured=stamp(observation['captured_at']);available=stamp(observation['available_at']);closed=stamp(observation['closed_at'])
        need(closed<clock and closed<=captured<=saved and available<=captured and available<=clock,'history result eligibility')
        need(observation.get('body_identity_verified') is True and observation.get('kind')=='raceresult' and
             observation.get('information_phase')=='official_result' and observation.get('status')=='AVAILABLE', 'history official body flags')
        data=observation['data']
        need(type(data) is dict and data.get('finish_confirmed') is True and data.get('confirmed') is True,'history official result confirmation')
        rows=data['results']
        _roster([dict(lane=r['lane'],registration_no=r['racer_registration_id']) for r in rows])
        need(all(r.get('verified_official') is True and r.get('race_id')==rid and
                 r.get('source_url')==observation['source_url'] and
                 stamp(r['captured_at'])==captured for r in rows),'history official row binding')
        return {r['racer_registration_id']:r for r in rows}
    except (ValueError,TypeError,KeyError):
        return {}


def _numeric(value, low, high):
    return type(value) in (int,float) and math.isfinite(value) and low<=value<=high


def _features(opportunities, source_id, registration):
    missing=dict(course_mean_finish='NO_VERIFIED_COURSE',course_mean_st='NO_VERIFIED_COURSE')
    features={};hashes=[sha for _,sha in opportunities]
    window='captured-verified-last10-'+digest(dict(registration_no=registration,observations=hashes))
    for name in ('recent_mean_finish','recent_mean_st'):
        counts=dict(window_id=window,total_n=len(opportunities),ok_n=0,f_n=0,l_n=0,missing_n=0,unresolved_n=0)
        values=[]
        for row,_ in opportunities:
            status=row.get('finish_status') if name.endswith('finish') else row.get('actual_st_status')
            value=row.get('finish') if name.endswith('finish') else row.get('actual_st')
            ok=(status=='FINISHED' and type(value) is int and 1<=value<=6) if name.endswith('finish') else (status=='OK' and _numeric(value,0,1))
            if ok:counts['ok_n']+=1;values.append(value)
            elif status in ('F','L'):counts[status.lower()+'_n']+=1
            elif status in (None,'MISSING','PENDING') or name.endswith('finish') and status!='FINISHED':counts['missing_n']+=1
            else:counts['unresolved_n']+=1
        valid=values and counts['unresolved_n']==0 and (not name.endswith('finish') or len(values)==len(opportunities))
        if valid:
            features[name]=dict(value=sum(values)/len(values),sample_n=len(values),source_id=source_id,
                                transform_id=FEATURE_TRANSFORMS[name],history=counts)
        else:missing[name]='NO_PRIOR_SAMPLES' if not opportunities else 'UNRESOLVED_DISPOSITION'
    return features,missing


def _prepared(manifest, observations, *, race_id, participants, as_of):
    _validate_manifest(manifest);_race(race_id);participants=_roster(participants);clock=stamp(as_of)
    need(stamp(manifest['verified_at'])<=clock,'history verification after as_of')
    expected=_latest_relevant(manifest,race_id,participants,as_of)
    need([digest(o) for o in observations]==[i['observation_sha256'] for i in expected],
         'history latest observation membership mismatch')
    need(_index(observations)==expected,'history observation/index binding')
    receipt=manifest['receipt'];source_id='result-history-artifact-'+str(receipt['id'])
    source=dict(source_id=source_id,source_url=f'https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/{receipt["id"]}/zip',
                source_sha256=receipt['digest'][7:],source_rights_ref=RIGHTS,published_at=None,
                captured_at=manifest['verified_at'],evidence_basis='CAPTURED_BY_CLAIM')
    rows=[];windows={}
    available=[(o,_official_rows(o,clock,stamp(receipt['created_at']))) for o in observations]
    for participant in participants:
        reg=participant['registration_no']
        opportunities=[(r[reg],digest(o)) for o,r in available if reg in r][-10:]
        features,missing=_features(opportunities,source_id,reg)
        rows.append(dict(participant,features=features,missing=missing));windows[reg]=[sha for _,sha in opportunities]
    evidence=dict(schema=EVIDENCE_SCHEMA,context_manifest=deepcopy(manifest),observations=deepcopy(observations),
                  race_id=race_id,participants=deepcopy(participants),as_of=as_of,windows=windows,coverage=COVERAGE)
    _seal(evidence,'evidence_sha256')
    return dict(source=source,participants=rows,evidence=evidence)


def prepare_history(context, *, race_id, participants, as_of):
    manifest=_validate_context(context);participants=_roster(participants)
    wanted=_latest_relevant(manifest,race_id,participants,as_of)
    by_sha={digest(o):o for o in context['observations']}
    return _prepared(manifest,[by_sha[i['observation_sha256']] for i in wanted],
                     race_id=race_id,participants=participants,as_of=as_of)


def verify_history_evidence(evidence, *, race_id, participants, as_of):
    """Replay exact membership/features; independent parent authentication follows."""
    _check(evidence,'evidence_sha256')
    need(evidence.get('schema')==EVIDENCE_SCHEMA and evidence.get('race_id')==race_id and
         evidence.get('participants')==_roster(participants) and evidence.get('as_of')==as_of,
         'history evidence input binding mismatch')
    result=_prepared(evidence['context_manifest'],evidence['observations'],race_id=race_id,participants=participants,as_of=as_of)
    need(result['evidence']==evidence,'history evidence replay differs')
    return result


def validate_history_proofs(evidence, proofs):
    """Self seals are integrity only: require an independently read parent ZIP."""
    verify_history_evidence(evidence,race_id=evidence['race_id'],participants=evidence['participants'],as_of=evidence['as_of'])
    manifest=evidence['context_manifest'];receipt=manifest['receipt'];proof=proofs.get(str(receipt['id']))
    need(type(proof) is dict and proof.get('id')==receipt['id'] and proof.get('digest')==receipt['digest'] and
         proof.get('created_at')==receipt['created_at'] and proof.get('receipt_sha256')==digest(receipt) and
         proof.get('journal_sha256')==manifest['journal_sha256'] and proof.get('journal_index')==manifest['journal_index'],
         'history lacks independently verified parent receipt/journal')
    expected={i['observation_sha256'] for i in manifest['journal_index']}
    need(set(proof.get('observation_sha256s',[]))==expected and
         all(digest(o) in expected for o in evidence['observations']),
         'history observation lacks authenticated parent membership')
