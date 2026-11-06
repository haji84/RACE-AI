"""Explicitly record the owner's personal-research decision for a fixed corpus.

This command authenticates owner intent, not a provider's permission. It does
not fit models or issue a decision merely because a checked-in file exists.
"""
import argparse,json,re
from datetime import datetime,timedelta,timezone
from pathlib import Path
from race_ai.actions_contract import digest
from race_ai.boat_venue_learning import training_intake
from race_ai.boat_venue_research import issue_owner_research_decision
from race_ai.teiai_history import need
from scripts.boat_venue_learning import load_verified_intake
from scripts.boat_all_racers import _key_ready,_read,_write


def main(argv=None,*,now=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--restored-dir',required=True);p.add_argument('--out-file',required=True)
    p.add_argument('--state-input',default='audit/state/boat-pdca-production-input.json')
    p.add_argument('--dataset-input',default='audit/state/boat-venue-dataset-input.json')
    p.add_argument('--expires-at',help='Operational review expiry; default90days, not a provider licence expiry')
    args=p.parse_args(argv);now=now or datetime.now(timezone.utc)
    try:
        output=Path(args.out_file)
        need(not output.exists() and not any(v.is_symlink() for v in (output.absolute(),*output.absolute().parents)),'OWNER_RESEARCH_RECORD_EXISTS_OR_SYMLINK')
        if not _key_ready():
            print(json.dumps(dict(state='HOLD_OWNER_STATE_KEY_MISSING',provider_permission_confirmed=False)));return 0
        rows,obs,pointer,content=load_verified_intake(args.restored_dir,args.state_input,now=now,authenticate_owner_cipher=True)
        dp=json.loads(_read(Path(args.dataset_input),8192));intake=training_intake(rows,obs,dataset_pointer=dp)
        end=datetime.fromisoformat(args.expires_at.replace('Z','+00:00')) if args.expires_at else now+timedelta(days=90)
        record=issue_owner_research_decision(source_pointer=pointer,state_content_sha256=content,
            dataset_pointer=dp,source_refs=intake['source_refs'],now=now,expires_at=end)
        output.parent.mkdir(parents=True,exist_ok=True)
        _write(output,json.dumps(record,sort_keys=True,indent=2).encode()+b'\n')
        print(json.dumps(dict(state='OWNER_PERSONAL_RESEARCH_DECISION_RECORDED',decision_sha256=digest(record),
            source_count=len(intake['source_refs']),provider_permission_confirmed=False,production_promoted=False)));return 0
    except Exception as exc:
        reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch('(OWNER_RESEARCH|VENUE_LEARNING)_[A-Z_]{1,80}',str(exc)) else 'OWNER_RESEARCH_OPERATION_REJECTED'
        print(json.dumps(dict(state='OWNER_RESEARCH_RECORD_REJECTED',reason=reason,provider_permission_confirmed=False)));return 2


if __name__=='__main__':raise SystemExit(main())
