"""Pinned B research candidates: private inference and existing-owner retention.

No active-model pin or workflow is changed. A candidate is not evidence of
prospective accuracy, independent source authentication, or calibrated confidence.
The completed pilot's discarded weights cannot be reconstructed from its hash.
"""
from __future__ import annotations

import argparse
import base64
import copy
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path

import numpy as np

from .back_phase_study import VERSION, SOURCE, SCENARIO_NAMES, prepare, mixture
from .data import MAX_DATABASE_BYTES
from .features import FEATURE_NAMES, retired_timing_feature, require_history_available
from .agari import AGARI_NAMES
from .abilities import ABILITY_NAMES
from .model import MODEL_ID, RankModel, digest
from .pipeline import check_splits, validate_prediction_inputs, write_private_json
from .policy import RACE_TIMEZONE, checked_day, checked_sha, clock, require
from .runtime import _canonical, _private_path, _write

SCHEMA='dt-r1-back-candidate-v2'
BUNDLE_SCHEMA='DT_R1_ENCRYPTED_BACK_CANDIDATE_V1'
PRIVATE_FILES=('back_candidate.json','aggregate.json')
MAX_FILE_BYTES=2*1024*1024
MAX_HISTORY_BYTES=MAX_DATABASE_BYTES
SOURCE_FILES=('back_candidate.py','back_phase_study.py','data.py','features.py',
              'agari.py','abilities.py','observations.py','model.py','pipeline.py',
              'policy.py','runtime.py','requirements.txt')
FIELDS={'schema','model_id','source_dataset_sha256','source_definition','splits',
        'created_at','parameter_information_end_day','source_code_sha256',
        'leader','conditional','direct','production_promoted','artifact_sha256'}
LEADER_FIELDS={'schema','feature_names','mean','scale','weights','before',
               'training_n','converged','training_fingerprint'}
RANK_FIELDS={'schema','model_id','feature_names','pair_names','mean','scale',
             'weights','pair_weights','temperature','fit_meta','model_sha256'}


def _source_pins():
    return {name:sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def _pairs(pairs):
    out={}
    for key,value in pairs:
        require(key not in out,'B_DUPLICATE_JSON_FIELD');out[key]=value
    return out


def _json(raw,expected_type=dict):
    try:
        value=json.loads(raw,object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('B_NONFINITE_JSON')))
    except (UnicodeError,TypeError,RecursionError) as error:
        raise ValueError('B_JSON_INVALID') from error
    require(isinstance(value,expected_type),'B_JSON_STRUCTURE_REQUIRED')
    return value


def _read(path,limit=MAX_FILE_BYTES):
    path=Path(path)
    require(path.is_file() and not path.is_symlink(),'B_FILE_MISSING_OR_SYMLINK')
    require(0<path.stat().st_size<=limit,'B_FILE_SIZE_INVALID')
    with path.open('rb') as handle:raw=handle.read(limit+1)
    require(0<len(raw)<=limit,'B_FILE_SIZE_INVALID')
    return raw


def _base_names():
    return tuple(n for n in FEATURE_NAMES+AGARI_NAMES+ABILITY_NAMES if not retired_timing_feature(n)
        and not n.startswith(('history_agari_context_','history_dt_motion_','history_dt_discovery_')))


def _validate(candidate):
    require(isinstance(candidate,dict) and set(candidate)==FIELDS,'B_CANDIDATE_FIELDS')
    require(candidate['schema']==SCHEMA and candidate['model_id']==MODEL_ID,'B_CANDIDATE_SCHEMA')
    require(candidate['production_promoted'] is False,'B_RESEARCH_ONLY')
    require(candidate['source_definition']==SOURCE,'B_SOURCE_DEFINITION')
    checked_sha(candidate['source_dataset_sha256'])
    require(digest({k:v for k,v in candidate.items() if k!='artifact_sha256'})==candidate['artifact_sha256'],
            'B_CANDIDATE_ARTIFACT_HASH_MISMATCH')
    require(candidate['source_code_sha256']==_source_pins(),'B_SOURCE_CODE_MISMATCH')
    splits=check_splits(candidate['splits']);frozen=clock(candidate['created_at'])
    information_end=checked_day(candidate['parameter_information_end_day']).isoformat()
    # This schema is an unselected fit-period candidate. Later temperature,
    # blend or feature selection requires a new schema/contract and tune receipt.
    require(information_end==splits['fit']['end'],'B_PARAMETER_INFORMATION_BOUNDARY')
    leader=candidate['leader'];names=_base_names()
    require(isinstance(leader,dict) and set(leader)==LEADER_FIELDS,'B_LEADER_FIELDS')
    require(leader['schema']==VERSION and tuple(leader['feature_names'])==names,'B_LEADER_SCHEMA')
    for key in ('mean','scale','weights'):
        require(isinstance(leader[key],list) and all(type(v) in (int,float) for v in leader[key]),'B_LEADER_ARRAY')
        value=np.asarray(leader[key],dtype=float)
        require(value.shape==(len(names),) and np.isfinite(value).all(),'B_LEADER_ARRAY')
        if key=='scale':require(np.all(value>0),'B_LEADER_ARRAY_SCALE')
    require(type(leader['training_n']) is int and leader['training_n']>=30 and
            type(leader['converged']) is bool,'B_LEADER_TRAINING_METADATA')
    checked_sha(leader['training_fingerprint'])
    require(leader['before']==splits['tune']['start'],'B_TRAINING_BINDING')
    for key,expected_names in (('direct',names),('conditional',names+SCENARIO_NAMES)):
        raw=candidate[key]
        require(isinstance(raw,dict) and set(raw)==RANK_FIELDS,'B_RANK_FIELDS')
        for name in ('mean','scale','weights','pair_weights'):
            values=raw[name]
            require(isinstance(values,list),'B_RANK_ARRAY')
            if name in ('weights','pair_weights'):
                require(all(isinstance(row,list) for row in values),'B_RANK_ARRAY')
                values=[v for row in values for v in row]
            require(all(type(v) in (int,float) for v in values),'B_RANK_ARRAY')
        model=RankModel.from_dict(raw);meta=model.fit_meta
        require(model.feature_names==expected_names,'B_RANK_FEATURE_SCHEMA')
        require(meta.get('fit_before_day')==leader['before'] and
                meta.get('training_races')==leader['training_n'],'B_TRAINING_BINDING')
        first=checked_day(meta.get('training_first_day')).isoformat()
        last=checked_day(meta.get('training_last_day')).isoformat()
        require(splits['fit']['start']<=first<=last<=information_end<leader['before'],'B_TRAINING_BINDING')
        require(meta.get('feature_digest_required') is True and
                meta.get('cohort')=='retrospective_archived_inputs_no_pre_cutoff_attestation','B_TRAINING_METADATA')
        require(model.temperature==1. and not any(k in meta for k in
            ('selection','temperature_calibration','parameter_information_end_day')),'B_UNSELECTED_FIT_CANDIDATE_REQUIRED')
        require(clock(meta.get('created_at'))<=frozen,'B_FREEZE_BEFORE_FIT')
    return candidate


def freeze_candidate(leader,conditional,direct,*,source_dataset_sha256,splits,created_at=None):
    """Freeze the existing supervised recipe before scoring any later period."""
    out={'schema':SCHEMA,'model_id':MODEL_ID,'source_dataset_sha256':source_dataset_sha256,
         'source_definition':SOURCE,'splits':copy.deepcopy(splits),
         'created_at':created_at or datetime.now(timezone.utc).isoformat(),
         'parameter_information_end_day':splits['fit']['end'],'source_code_sha256':_source_pins(),
         'leader':copy.deepcopy(leader),'conditional':conditional.to_dict(),'direct':direct.to_dict(),
         'production_promoted':False}
    out=copy.deepcopy(out);out['artifact_sha256']=digest(out)
    return _validate(out)


def load_candidate(path,*,expected_sha256):
    """The byte pin must come from a separately retained receipt, not this file."""
    checked_sha(expected_sha256,'B_EXTERNAL_CANDIDATE_SHA_REQUIRED')
    raw=_read(path)
    require(sha256(raw).hexdigest()==expected_sha256,'B_CANDIDATE_BYTES_SHA_MISMATCH')
    return _validate(_json(raw))


def forecast_candidate(path,*,expected_sha256,record,history,prediction_at=None,full=False):
    """Guard declared clocks; admission/readback still authenticate the sources."""
    candidate=load_candidate(path,expected_sha256=expected_sha256)
    require(isinstance(record,dict) and record.get('cohort') in ('prospective','retrospective'),
            'B_EXPLICIT_COHORT_REQUIRED')
    history=list(history)
    require(all(r['day']<record['day'] for r in history),'HISTORY_MUST_PRECEDE_TARGET_DAY')
    meta={'created_at':candidate['created_at'],'training_last_day':candidate['parameter_information_end_day'],
          'parameter_information_end_day':candidate['parameter_information_end_day']}
    prospective,cutoff=validate_prediction_inputs(record,prediction_at=prediction_at,model_meta=meta)
    if prospective:require_history_available(history,prediction_at)
    rows=prepare(history+[record]);row=next(r for r in rows if r['race_id']==record['race_id'])
    validate_prediction_inputs(row,prediction_at=prediction_at,model_meta=meta)
    output={'race_id':row['race_id'],'day':row['day'],'model_id':MODEL_ID,
        'model_sha256':candidate['artifact_sha256'],'candidate_bytes_sha256':expected_sha256,
        'input_sha256':row.get('input_sha256'),'feature_input_sha256':row.get('feature_input_sha256'),
        'cohort':'prospective' if prospective else 'retrospective','prediction_at':prediction_at,
        'cutoff_at':cutoff if prospective else None,'field_size':len(row['riders']),
        'source_attestation_sha256':row.get('source_attestation_sha256'),
        'independent_source_attestation':False,'production_promoted':False,
        'confidence':{'label':'HOLD','reason':'NO_B_SPECIFIC_AUDITED_CALIBRATION'},
        'scope':'prospective_shadow_pending_independent_readback' if prospective else 'retrospective_reused_archive'}
    if row.get('feature_status')!='READY':
        return dict(output,status='HOLD',reason=row.get('feature_status','MISSING_FEATURE_STATUS'))
    checked_sha(output['input_sha256'],'B_INPUT_SHA_REQUIRED')
    checked_sha(output['feature_input_sha256'],'B_FEATURE_INPUT_SHA_REQUIRED')
    output['feature_schema_sha256']=digest(row['feature_names'])
    law=mixture(candidate['leader'],RankModel.from_dict(candidate['conditional']),row,full=full)
    # The probability law's statistical-scenario warning is separate from the
    # forecast's prospective/retrospective evidence scope.
    law['scenario_scope']=law.pop('scope')
    return dict(output,status='READY',**law)


def _private_documents(directory,expected_candidate_sha256):
    directory=_private_path(directory)
    require(directory.is_dir() and {p.name for p in directory.iterdir()}==set(PRIVATE_FILES),'B_PRIVATE_FILE_SET')
    files={name:_read(directory/name) for name in PRIVATE_FILES}
    require(sha256(files['back_candidate.json']).hexdigest()==expected_candidate_sha256,'B_CANDIDATE_BYTES_SHA_MISMATCH')
    candidate=_validate(_json(files['back_candidate.json']))
    report=_json(files['aggregate.json'])
    require(report.get('artifact_sha256')==candidate['artifact_sha256'] and
            report.get('production_promoted') is False,'B_AGGREGATE_BINDING')
    return candidate,files


def export_candidate(directory,destination,owner_public_pem,*,expected_candidate_sha256,now=None):
    """Seal exactly two bounded files. No raw model/report is made public."""
    from race_ai import keirin_official_run_history as codec
    checked_sha(expected_candidate_sha256,'B_EXTERNAL_CANDIDATE_SHA_REQUIRED')
    candidate,files=_private_documents(directory,expected_candidate_sha256)
    codec.storage.checked_public_key(owner_public_pem)
    at=now or datetime.now(timezone.utc).isoformat();day=clock(at).astimezone(RACE_TIMEZONE).date().isoformat()
    require(clock(at)>=clock(candidate['created_at']),'B_EXPORT_BEFORE_FREEZE')
    dest=Path(destination)
    require(not dest.is_symlink() and not dest.exists(),'B_DESTINATION_NO_REPLACE')
    inventory=[{'file':name,'sha256':sha256(files[name]).hexdigest(),'bytes':len(files[name])} for name in PRIVATE_FILES]
    identity=digest({'artifact_sha256':candidate['artifact_sha256'],'files':inventory})
    payload={'schema':BUNDLE_SCHEMA,'day_jst':day,'bundle_id':identity,
        'files':{name:base64.b64encode(raw).decode('ascii') for name,raw in files.items()},
        'safe_report':{'day_jst':day,'scope':BUNDLE_SCHEMA,'production_promoted':False}}
    sealed=codec.seal_evidence(payload,owner_public_pem,day,at)
    manifest={'schema':BUNDLE_SCHEMA,'bundle_id':identity,'created_at':at,'day':day,
        'owner_spki_sha256':codec.storage.PINNED_OWNER_SPKI_SHA256,
        'artifact_sha256':candidate['artifact_sha256'],'dataset_sha256':candidate['source_dataset_sha256'],
        'files':inventory,'cipher':{'file':'candidate.sealed.json','bytes':len(sealed),'sha256':sha256(sealed).hexdigest()},
        'production_promoted':False,'owner_decryption_verified':False}
    raw=_canonical(manifest)
    dest.parent.mkdir(parents=True,exist_ok=True);dest.mkdir(mode=0o700)
    _write(dest/'candidate.sealed.json',sealed);_write(dest/'manifest.json',raw)
    pin=sha256(raw).hexdigest();verify_candidate_bundle(dest,expected_manifest_sha256=pin)
    return {'status':'ENCRYPTED_B_CANDIDATE_SAVED','manifest_sha256':pin,
        'candidate_bytes_sha256':expected_candidate_sha256,'artifact_sha256':candidate['artifact_sha256'],
        'production_promoted':False,'owner_decryption_verified':False}


def verify_candidate_bundle(directory,*,expected_manifest_sha256):
    from race_ai import keirin_official_run_history as codec
    checked_sha(expected_manifest_sha256,'B_EXTERNAL_MANIFEST_SHA_REQUIRED')
    directory=Path(directory)
    require(not directory.is_symlink() and directory.is_dir() and
            {p.name for p in directory.iterdir()}=={'manifest.json','candidate.sealed.json'},'B_PUBLIC_FILE_SET')
    raw=_read(directory/'manifest.json',64*1024)
    require(sha256(raw).hexdigest()==expected_manifest_sha256,'B_MANIFEST_SHA_MISMATCH')
    manifest=_json(raw)
    require(raw==_canonical(manifest) and set(manifest)=={'schema','bundle_id','created_at','day',
        'owner_spki_sha256','artifact_sha256','dataset_sha256','files','cipher',
        'production_promoted','owner_decryption_verified'} and manifest['schema']==BUNDLE_SCHEMA,'B_MANIFEST_FIELDS')
    require(manifest['production_promoted'] is False and manifest['owner_decryption_verified'] is False,'B_RESEARCH_ONLY')
    require(manifest['owner_spki_sha256']==codec.storage.PINNED_OWNER_SPKI_SHA256,'B_OWNER_PIN_MISMATCH')
    require(clock(manifest['created_at']).astimezone(RACE_TIMEZONE).date()==checked_day(manifest['day']),'B_MANIFEST_CLOCK')
    for key in ('bundle_id','artifact_sha256','dataset_sha256'):checked_sha(manifest[key])
    files=manifest['files']
    require(isinstance(files,list) and len(files)==2 and [v.get('file') for v in files]==list(PRIVATE_FILES),'B_PRIVATE_FILE_SET')
    for item in files:
        require(set(item)=={'file','bytes','sha256'} and type(item['bytes']) is int and
                0<item['bytes']<=MAX_FILE_BYTES,'B_PRIVATE_FILE_SIZE')
        checked_sha(item['sha256'])
    require(digest({'artifact_sha256':manifest['artifact_sha256'],'files':files})==manifest['bundle_id'],'B_BUNDLE_IDENTITY')
    cipher=manifest['cipher']
    require(isinstance(cipher,dict) and set(cipher)=={'file','bytes','sha256'} and
            cipher['file']=='candidate.sealed.json','B_CIPHER_FIELDS')
    sealed=_read(directory/cipher['file'],codec.MAX_CIPHER_BYTES)
    require(type(cipher['bytes']) is int and len(sealed)==cipher['bytes'] and
            sha256(sealed).hexdigest()==cipher['sha256'],'B_CIPHER_SHA_MISMATCH')
    envelope=codec._checked_cipher(sealed)
    require(envelope['day_jst']==manifest['day'] and envelope['observed_at']==manifest['created_at'],'B_CIPHER_CLOCK')
    return manifest


def restore_candidate(directory,destination,*,expected_manifest_sha256,owner_private_pem):
    from race_ai import keirin_official_run_history as codec
    manifest=verify_candidate_bundle(directory,expected_manifest_sha256=expected_manifest_sha256)
    dest=_private_path(destination)
    require(not dest.exists(),'B_RESTORE_DESTINATION_NO_REPLACE')
    sealed=_read(Path(directory)/'candidate.sealed.json',codec.MAX_CIPHER_BYTES)
    require(sha256(sealed).hexdigest()==manifest['cipher']['sha256'],'B_CIPHER_SHA_MISMATCH')
    payload=codec.decrypt_evidence(sealed,owner_private_pem)
    require(set(payload)=={'schema','day_jst','bundle_id','files','safe_report'} and
            payload['schema']==BUNDLE_SCHEMA and payload['day_jst']==manifest['day'] and
            payload['bundle_id']==manifest['bundle_id'],'B_RESTORED_BINDING')
    require(isinstance(payload['files'],dict) and set(payload['files'])==set(PRIVATE_FILES),'B_RESTORED_FILE_SET')
    documents={}
    for item in manifest['files']:
        value=payload['files'][item['file']]
        require(isinstance(value,str) and len(value)<=4*((item['bytes']+2)//3),'B_RESTORED_FILE_SIZE')
        raw=base64.b64decode(value,validate=True)
        require(len(raw)==item['bytes'] and sha256(raw).hexdigest()==item['sha256'],'B_RESTORED_FILE_SHA')
        documents[item['file']]=raw
    candidate=_validate(_json(documents['back_candidate.json']));report=_json(documents['aggregate.json'])
    require(candidate['artifact_sha256']==manifest['artifact_sha256']==report.get('artifact_sha256') and
            candidate['source_dataset_sha256']==manifest['dataset_sha256'] and
            report.get('production_promoted') is False,'B_RESTORED_IDENTITY_MISMATCH')
    # Authentication, inventory, code and all component checks precede writes.
    dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True);dest.mkdir(mode=0o700,exist_ok=False)
    for name,raw in documents.items():_write(dest/name,raw)
    return {'status':'B_CANDIDATE_RESTORED','artifact_sha256':candidate['artifact_sha256'],
            'manifest_sha256':expected_manifest_sha256,'production_promoted':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    forecast=sub.add_parser('forecast',help='Private research forecast; source authentication remains independent.')
    for flag in ('candidate','record','history','output'):forecast.add_argument('--'+flag,type=Path,required=True)
    forecast.add_argument('--candidate-sha256',required=True);forecast.add_argument('--at')
    export=sub.add_parser('export',help='Encrypt an already completed future B study without retraining.')
    for flag in ('study-dir','output-dir','owner-public-key'):export.add_argument('--'+flag,type=Path,required=True)
    export.add_argument('--candidate-sha256',required=True)
    verify=sub.add_parser('verify',help='Verify ciphertext against an external manifest pin; no decryption claim.')
    restore=sub.add_parser('restore',help='Restore with the existing owner key into a new private directory.')
    for command in (verify,restore):
        command.add_argument('--bundle-dir',type=Path,required=True);command.add_argument('--manifest-sha256',required=True)
    restore.add_argument('--output-dir',type=Path,required=True)
    restore.add_argument('--private-key-env',default='RACE_AI_KEIRIN_PRIVATE_RSA_PEM')
    args=parser.parse_args(argv)
    if args.command=='forecast':
        history=_json(_read(args.history,MAX_HISTORY_BYTES),expected_type=list)
        require(all(isinstance(row,dict) for row in history),'B_HISTORY_RECORDS_REQUIRED')
        prediction=forecast_candidate(args.candidate,expected_sha256=args.candidate_sha256,
            record=_json(_read(args.record)),history=history,prediction_at=args.at,full=True)
        write_private_json(args.output,prediction)
        receipt={'status':prediction['status'],'private_original_saved':True,'production_promoted':False}
    elif args.command=='export':
        receipt=export_candidate(args.study_dir,args.output_dir,args.owner_public_key.read_bytes(),
                                 expected_candidate_sha256=args.candidate_sha256)
    elif args.command=='verify':
        value=verify_candidate_bundle(args.bundle_dir,expected_manifest_sha256=args.manifest_sha256)
        receipt={'status':'B_CIPHERTEXT_VERIFIED','artifact_sha256':value['artifact_sha256'],
                 'owner_decryption_verified':False,'production_promoted':False}
    else:
        secret=os.environ.get(args.private_key_env)
        require(bool(secret),'B_EXISTING_OWNER_KEY_UNAVAILABLE')
        receipt=restore_candidate(args.bundle_dir,args.output_dir,expected_manifest_sha256=args.manifest_sha256,
                                  owner_private_pem=secret.encode())
    print(json.dumps(receipt,sort_keys=True,allow_nan=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
