"""Publish or restore owner-encrypted research coefficients on existing state."""
import argparse,json,os,re
from datetime import datetime,timezone
from pathlib import Path
from race_ai.boat_venue_learning_handoff import publish_learning_candidate,restore_learning_candidate
from scripts.boat_all_racers import _key_ready,_read,_write

# Fixed runtime validation codes only; transport text or an unknown code under
# the same prefix must remain sanitized.
PUBLIC_RUNTIME_REASONS=frozenset('VENUE_RESEARCH_RUNTIME_'+suffix for suffix in (
 'ARTIFACT_BYTES_MISMATCH','ARTIFACT_EXPIRED_DURING_RESTORE','ARTIFACT_UNAVAILABLE',
 'AWARE_CLOCK_REQUIRED','CLOCK_REGRESSED','CONTEXT_INPUT_INVALID',
 'CURRENT_ARTIFACT_IDENTITY_REQUIRED','CURRENT_OWNER_IDENTITY_REQUIRED',
 'DATASET_INPUT_INVALID','DATASET_PIN_MISMATCH','DATASET_READBACK_REJECTED','DATASET_READBACK_REQUIRED',
 'INTENDED_CANDIDATE_REQUIRED','METADATA_ROUTE_INVALID','NEW_ARTIFACT_CLOCK_REQUIRED','NEW_ARTIFACT_REQUIRED',
 'OUTPUT_EXISTS_DO_NOT_RESET','PRIVATE_FILE_REQUIRED','PRIVATE_PATH_REQUIRED',
 'PRIVATE_READY_AUTHENTICATION_FAILED','PRIVATE_READY_BINDING_INVALID','PRIVATE_READY_REQUIRED',
 'READBACK_CLOCK_INVALID','RESTORED_BINDING_MISMATCH','RESTORED_BYTES_MISMATCH','RESTORE_CLOCK_INVALID',
 'RETAINED_PIN_INVALID','RETAINED_PIN_MISMATCH','RUN_PIN_MISMATCH','TRAINING_PIN_MISMATCH'))

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',default='.')
 commands=p.add_subparsers(dest='action',required=True)
 a=commands.add_parser('publish');a.add_argument('--folder',required=True);a.add_argument('--pointer-out',required=True)
 b=commands.add_parser('readback');b.add_argument('--input',required=True);b.add_argument('--out-dir',required=True)
 for name in ('restore-context','verify-context'):
  c=commands.add_parser(name)
  c.add_argument('--context-input',default='audit/state/boat-venue-learning-context-input.json')
  c.add_argument('--retained-input',default='audit/state/all-existing-model-full-native-ci-learning-input.json')
  c.add_argument('--out-dir',required=True)
  if name=='verify-context':c.add_argument('--artifact-id',required=True,type=int)
 args=p.parse_args(argv)
 try:
  if not _key_ready():
   print(json.dumps(dict(status='HOLD_OWNER_STATE_KEY_MISSING',plaintext_published=False)))
   return 2 if args.action in ('restore-context','verify-context') else 0
  if args.action=='publish':
   r=publish_learning_candidate(args.folder,args.repo);_write(Path(args.pointer_out),json.dumps(r,sort_keys=True).encode()+b'\n')
  elif args.action=='readback':r=restore_learning_candidate(json.loads(_read(Path(args.input),8192)),args.out_dir,args.repo)
  else:
   from race_ai.boat_venue_research_runtime import restore_learning_context,readback_learning_context
   if args.action=='restore-context':
    r=restore_learning_context(args.context_input,args.retained_input,args.out_dir,args.repo,
       env=os.environ,now=datetime.now(timezone.utc))
   else:
    from scripts.github_existing_cycle import _live_gh
    r=readback_learning_context(args.context_input,args.retained_input,args.out_dir,args.artifact_id,args.repo,
       env=os.environ,gh=_live_gh)
  if args.action in ('restore-context','verify-context') and os.environ.get('GITHUB_OUTPUT'):
   with open(os.environ['GITHUB_OUTPUT'],'a') as output:
    output.write(('ready' if args.action=='restore-context' else 'verified')+'=true\n')
  print(json.dumps(r,sort_keys=True));return 0
 except Exception as exc:
  reason=str(exc) if isinstance(exc,ValueError) and (str(exc) in PUBLIC_RUNTIME_REASONS or re.fullmatch('(VENUE_LEARNING|OWNER_STATE|VENUE_EXISTING)_[A-Z_]{1,80}',str(exc))) else 'VENUE_LEARNING_HANDOFF_REJECTED'
  print(json.dumps(dict(status='VENUE_LEARNING_HANDOFF_REJECTED',reason=reason,plaintext_published=False)));return 2

if __name__=='__main__':raise SystemExit(main())
