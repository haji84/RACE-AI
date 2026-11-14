"""Append already-saved native projections to the encrypted owner view."""
from copy import deepcopy
import re
from .boat_pdca_state import need
from .boat_saved_model_view import merge_saved_views
from .boat_history_store import instant
from .saved_view_feed import forecast_anchor,ensure_append_only
from .private_cycle_projection import project_state

def hydrate_saved_originals(view,get,*,key=None,max_archives=128):
    """Read missing native evidence once, retaining every sealed prediction."""
    import json
    from .actions_contract import digest
    from .boat_saved_model_view import saved_prediction_identity
    from .boat_saved_prediction_evidence import hydrate_prediction_evidence
    need(type(max_archives) is int and 1<=max_archives<=128,'FEED_EVIDENCE_ARCHIVE_BOUND')
    missing=set()
    for row in view['records']:
        known=row.get('saved_prediction_evidence',{})
        for prediction in _predictions(row):
            identity=digest([row['race_id'],saved_prediction_identity(prediction)])
            ident=prediction.get('artifact_id')
            if identity not in known and type(ident) is int and ident>0 and any(
                    prediction.get(field) is None for field in ('generated_at','input_sha256','model_version')):
                missing.add(ident)
    archives=[];unsupported=0
    for ident in sorted(missing)[:max_archives]:
        raw_meta=get(f'actions/artifacts/{ident}')
        need(type(raw_meta) is bytes and len(raw_meta)<=128*1024,'FEED_EVIDENCE_METADATA_BOUND')
        metadata=json.loads(raw_meta)
        need(type(metadata) is dict and metadata.get('id')==ident,'FEED_EVIDENCE_ARTIFACT_ID')
        name=metadata.get('name','')
        if not isinstance(name,str) or not name.startswith(('boat-p0-existing-','boat-national-cutoff-')):
            unsupported+=1;continue
        archives.append((get(f'actions/artifacts/{ident}/zip'),metadata))
    output,counts=hydrate_prediction_evidence(view,archives,key=key)
    counts.update(deferred_archives=max(0,len(missing)-max_archives),unsupported_archives=unsupported)
    return output,counts

def _predictions(row):return [p for p in [row.get('prediction'),*row.get('comparison_predictions',[])] if p is not None]

def _native_key(rid,p):
    if p.get('artifact_id') is None:return None
    return (rid,p.get('stage'),p.get('model_id'),p.get('variant'),p.get('prediction_sha256') or p.get('output_sha256'),p['artifact_id'])

def append_views(view,additions=(),*,names=None):
    """Retain exact prior dictionaries when the same native archive is replayed."""
    known={_native_key(r['race_id'],p):p for r in view['records'] for p in _predictions(r) if _native_key(r['race_id'],p) is not None}
    prepared=[]
    for addition in additions:
        copied=deepcopy(addition)
        for row in copied['records']:
            keep=[]
            for p in _predictions(row):
                key=_native_key(row['race_id'],p);old=known.get(key) if key is not None else None
                if old is not None:
                    fields=('ordered_top8','as_of','cutoff_at','persisted_at')
                    # The dispatcher cites the canonical containing-document
                    # hash; archive readers retain the exact JSON-byte hash.
                    # A reused model is already bound by its native seal and
                    # artifact ID. Keep that older original and its byte hash.
                    if p.get('dispatch_status')!='ORIGINAL_REUSED':fields+=('original_json_sha256',)
                    need(all(old.get(k)==p.get(k) for k in fields),
                         'FEED_NATIVE_ORIGINAL_CONFLICT')
                    need(all(old.get(k) is None or p.get(k) is None or old[k]==p[k]
                             for k in ('generated_at','source_code_commit','model_version')),
                         'FEED_NATIVE_ORIGINAL_CONFLICT')
                else:
                    keep.append(p)
                    if key is not None:known[key]=p
            row['prediction']=keep[0] if keep else None;row['comparison_predictions']=keep[1:]
        prepared.append(copied)
    out=merge_saved_views(view,prepared,names=names)
    out['forecast_base_sha256']=forecast_anchor(view)
    ensure_append_only(view,out)
    return out

def project_native_state(state,*,documents=()):
    """Called only on the worker's authenticated continuity readback."""
    view=project_state(state,dataset_status='REAL_REPORTED',original_documents=list(documents))
    receipts={r['id']:r for r in state.get('receipts',[])}
    for row in view['records']:
        for p in _predictions(row):
            receipt=receipts.get(p['artifact_id'],{});run=receipt.get('workflow_run',{})
            head=run.get('head_sha')
            need(run.get('repository_id')==1416489937 and run.get('head_repository_id')==1416489937 and
                 type(head) is str and re.fullmatch('[a-f0-9]{40}',head) and
                 instant(receipt['created_at'])==instant(p['persisted_at']),'FEED_NATIVE_RECEIPT_INVALID')
            p['source_code_commit']=head;p['external_receipt_verified']=True
            p['missing_reasons']=[r for r in p['missing_reasons'] if r!='EXTERNAL_RECEIPT_NOT_INDEPENDENTLY_VERIFIED']
    return view
