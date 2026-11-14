"""Connect owner-restored venue observations to existing shadow-model learning.

No provider GETs, backfill, new model, plaintext publication or promotion.
Use a scoped owner personal-research decision or external source-use review.
An owner decision is never represented as a provider licence or promotion.
"""
import argparse,hmac,json,os,re
from datetime import datetime,timezone
from pathlib import Path

from race_ai.boat_venue_learning import rows_from_journal,fit_venue_rows,seal_candidate
from race_ai.boat_pdca_state import PdcaState,state_key,restore_state
from race_ai.permissioned_source_delivery import PermissionPolicy,SourceDeliveryError
from race_ai.teiai_history import need
from scripts.boat_all_racers import _key_ready,_read,_write
from scripts.boat_history_collect import private_root


def load_verified_intake(restored_dir,state_input,*,now,authenticate_owner_cipher=False):
    root=private_root(restored_dir)
    pointer=json.loads(_read(Path(state_input),8192))
    status=json.loads(_read(root/'production-readback-status.json',1000000))
    need(status.get('production_schema_readback_verified') is True and
         status['source_commit']==pointer['source_commit'],'VENUE_LEARNING_READBACK_BINDING')
    if authenticate_owner_cipher:
        # Reauthenticate the exact pointer scope/cipher before an owner's
        # decision is issued or consumed, independently of the status JSON.
        import tempfile
        with tempfile.TemporaryDirectory(prefix='owner-cipher-check-',dir=root) as tmp:
            verified=restore_state(root/'state.enc',Path(tmp)/'state.sqlite',
                expected_sha256=pointer['cipher_sha256'],expected_scope=pointer['scope'])
            try:need(verified.content_sha256()==status['state_content_sha256'],'VENUE_LEARNING_READBACK_CONTENT_CHANGED')
            finally:verified.close()
    state=PdcaState(root/'state.sqlite')
    try:
        need(state.content_sha256()==status['state_content_sha256'],'VENUE_LEARNING_READBACK_CONTENT_CHANGED')
        rows,obs=rows_from_journal(state,root/'materialized',now=now.isoformat())
    finally:state.close()
    return rows,obs,pointer,status['state_content_sha256']


def main(argv=None,*,now=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--restored-dir',required=True);p.add_argument('--out-dir',required=True)
    p.add_argument('--state-input',default='audit/state/boat-pdca-production-input.json')
    p.add_argument('--dataset-input',default='audit/state/boat-venue-dataset-input.json')
    p.add_argument('--permission-policy')
    p.add_argument('--owner-research-record',help='Verify a previously authenticated owner research decision; never issue one implicitly')
    args=p.parse_args(argv);now=now or datetime.now(timezone.utc)
    try:
        if not _key_ready():
            result=dict(state='HOLD_OWNER_STATE_KEY_MISSING',plaintext_published=False,production_promoted=False,encrypted_readback_verified=False)
            out=Path(args.out_dir);out.mkdir(parents=True,mode=0o700,exist_ok=False)
            _write(out/'summary.json',json.dumps(result,sort_keys=True).encode())
            print(json.dumps(result));return 0
        allow=None;policy_sha=None;review_reason='MODEL_TRAINING_REVIEW_NOT_CONFIGURED'
        if args.permission_policy:
            # Same independent reviewer key used by the existing source bridge;
            # an encryption key never signs a source use permission implicitly.
            key=os.environ.get('RACE_AI_SOURCE_REVIEW_KEY','').encode()
            need(not hmac.compare_digest(key,state_key('production')) and
                 not hmac.compare_digest(key,os.environ.get('RACE_AI_STATE_KEY','').encode()),'VENUE_LEARNING_INDEPENDENT_REVIEWER_REQUIRED')
            try:
                policy=PermissionPolicy(json.loads(_read(Path(args.permission_policy),1000000)),key,at=now.isoformat())
                allow=policy.authorize;policy_sha=policy.document_sha256;review_reason='AUTHENTICATED_REVIEW_RECORD'
            except SourceDeliveryError as exc:
                review_reason={
                    'source grant not currently effective':'SOURCE_GRANT_NOT_CURRENTLY_EFFECTIVE',
                    'source policy signature unverified':'SOURCE_POLICY_SIGNATURE_UNVERIFIED',
                    'independent reviewer key not configured':'INDEPENDENT_REVIEWER_KEY_NOT_CONFIGURED',
                }.get(str(exc),'MODEL_TRAINING_REVIEW_REJECTED')
        rows,obs,pointer,content=load_verified_intake(args.restored_dir,args.state_input,now=now,
            authenticate_owner_cipher=bool(args.owner_research_record))
        owner_record=json.loads(_read(Path(args.owner_research_record),64000)) if args.owner_research_record else None
        payload=fit_venue_rows(rows,obs,dataset_pointer=json.loads(_read(Path(args.dataset_input),8192)),now=now,allow_training=allow,
            owner_research_record=owner_record,source_pointer=pointer,state_content_sha256=content)
        payload['summary'].update(source_commit=pointer['source_commit'],source_content_sha256=content,permission_policy_sha256=policy_sha,permission_review_reason=review_reason)
        result=seal_candidate(payload,args.out_dir);print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch('VENUE_LEARNING_[A-Z_]{1,80}',str(exc)) else 'VENUE_LEARNING_OPERATION_REJECTED'
        print(json.dumps(dict(state='VENUE_LEARNING_REJECTED',reason=reason,plaintext_published=False,production_promoted=False)));return 2


if __name__=='__main__':raise SystemExit(main())
