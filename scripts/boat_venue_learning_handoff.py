"""Publish or restore owner-encrypted research coefficients on existing state."""
import argparse,json,re
from pathlib import Path
from race_ai.boat_venue_learning_handoff import publish_learning_candidate,restore_learning_candidate
from scripts.boat_all_racers import _key_ready,_read,_write

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',default='.')
 commands=p.add_subparsers(dest='action',required=True)
 a=commands.add_parser('publish');a.add_argument('--folder',required=True);a.add_argument('--pointer-out',required=True)
 b=commands.add_parser('readback');b.add_argument('--input',required=True);b.add_argument('--out-dir',required=True)
 args=p.parse_args(argv)
 try:
  if not _key_ready():print(json.dumps(dict(status='HOLD_OWNER_STATE_KEY_MISSING',plaintext_published=False)));return 0
  if args.action=='publish':
   r=publish_learning_candidate(args.folder,args.repo);_write(Path(args.pointer_out),json.dumps(r,sort_keys=True).encode()+b'\n')
  else:r=restore_learning_candidate(json.loads(_read(Path(args.input),8192)),args.out_dir,args.repo)
  print(json.dumps(r,sort_keys=True));return 0
 except Exception as exc:
  reason=str(exc) if isinstance(exc,ValueError) and re.fullmatch('(VENUE_LEARNING|OWNER_STATE|VENUE_EXISTING)_[A-Z_]{1,80}',str(exc)) else 'VENUE_LEARNING_HANDOFF_REJECTED'
  print(json.dumps(dict(status='VENUE_LEARNING_HANDOFF_REJECTED',reason=reason,plaintext_published=False)));return 2

if __name__=='__main__':raise SystemExit(main())
