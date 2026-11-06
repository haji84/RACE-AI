"""Owner recipient metadata and encrypted PDCA delivery; never exports root keys."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from race_ai.boat_pdca_recipient import (receiver_document,encrypt_transfer,receive_transfer,
    verify_received_checkpoint,publish_incoming,publish_received,_json)
from race_ai.boat_history_store import wire
from scripts.boat_history_collect import private_root,save


def bounded_json(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=16384:
        raise ValueError('RECIPIENT_INPUT_FILE_INVALID')
    return _json(path.read_bytes(),16384)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    a=commands.add_parser('receiver');a.add_argument('--private-dir',type=Path,required=True)
    a.add_argument('--run-id',default=os.environ.get('GITHUB_RUN_ID'))
    a.add_argument('--source-head',default=os.environ.get('RACE_AI_SOURCE_HEAD'))
    b=commands.add_parser('encrypt');b.add_argument('--state',type=Path,required=True)
    b.add_argument('--receiver',type=Path,required=True);b.add_argument('--receiver-sha',required=True)
    b.add_argument('--receiver-run-id',required=True);b.add_argument('--receiver-head',required=True)
    b.add_argument('--private-dir',type=Path,required=True);b.add_argument('--previous-input',type=Path)
    c=commands.add_parser('receive');c.add_argument('--input',type=Path,required=True)
    c.add_argument('--previous-input',type=Path);c.add_argument('--private-dir',type=Path,required=True)
    c.add_argument('--run-id',default=os.environ.get('GITHUB_RUN_ID'))
    c.add_argument('--source-head',default=os.environ.get('RACE_AI_SOURCE_HEAD'))
    d=commands.add_parser('verify');d.add_argument('--folder',type=Path,required=True)
    d.add_argument('--private-dir',type=Path,required=True);d.add_argument('--transfer-sha',required=True)
    d.add_argument('--run-id',default=os.environ.get('GITHUB_RUN_ID'))
    d.add_argument('--source-head',default=os.environ.get('RACE_AI_SOURCE_HEAD'))
    e=commands.add_parser('publish-incoming');e.add_argument('--folder',type=Path,required=True)
    e.add_argument('--repo',type=Path,default=ROOT);e.add_argument('--private-dir',type=Path,required=True)
    f=commands.add_parser('publish-received');f.add_argument('--folder',type=Path,required=True)
    f.add_argument('--repo',type=Path,default=ROOT);f.add_argument('--private-dir',type=Path,required=True)
    f.add_argument('--consumer-proof',type=Path,required=True);f.add_argument('--consumer-sha',required=True)
    f.add_argument('--producer-run-id',required=True);f.add_argument('--producer-head',required=True)
    f.add_argument('--transfer-sha',required=True);f.add_argument('--recipient-key-id',required=True)
    f.add_argument('--initialize',action='store_true');f.add_argument('--expected-parent')
    args=parser.parse_args(argv)
    try:
        previous=None
        if getattr(args,'previous_input',None):
            supplied=bounded_json(args.previous_input)
            if supplied.get('status')!='WAITING_ENCRYPTED_INPUT':previous=supplied
        if args.command=='receiver':
            try:
                doc=receiver_document(run_id=args.run_id,source_head=args.source_head)
                report=dict(status='OWNER_RECIPIENT_READY',key_id=doc['key_id'],root_key_exported=False)
            except ValueError as exc:
                if not str(exc).startswith('OWNER_STATE_KEY_REQUIRED'):raise
                doc=dict(schema='RACE_AI_BOAT_OWNER_RECIPIENT_V1',status='HOLD_OWNER_STATE_KEY_MISSING')
                report=dict(status='HOLD_OWNER_STATE_KEY_MISSING',root_key_exported=False)
            root=private_root(args.private_dir);save(root/'receiver.json',(wire(doc)+'\n').encode())
        elif args.command=='encrypt':
            report=encrypt_transfer(args.state,bounded_json(args.receiver),expected_receiver_sha=args.receiver_sha,
                expected_run_id=args.receiver_run_id,expected_source_head=args.receiver_head,
                output=args.private_dir,previous_pointer=previous)
            root=private_root(args.private_dir)
        elif args.command=='receive':
            report=receive_transfer(bounded_json(args.input),args.private_dir,run_id=args.run_id,
                source_head=args.source_head,previous_pointer=previous)
            root=private_root(args.private_dir)
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'],'a') as out:
                    out.write('encrypted='+str(report.get('encrypted_checkpoint_created') is True).lower()+'\n')
                    if report.get('encrypted_checkpoint_created'):
                        handoff=bounded_json(root/'sealed/handoff-proof.json')
                        out.write('transfer_sha256='+handoff['transfer_sha256']+'\n')
        elif args.command=='verify':
            report=verify_received_checkpoint(args.folder,args.private_dir,expected_run_id=args.run_id,
                expected_source_head=args.source_head,expected_transfer_sha=args.transfer_sha)
            root=private_root(args.private_dir)
        elif args.command=='publish-incoming':
            report=publish_incoming(args.repo,args.folder);root=private_root(args.private_dir)
            save(root/'transfer-input.json',(wire(report)+'\n').encode())
        else:
            report=publish_received(args.repo,args.folder,consumer_proof=args.consumer_proof,
                expected_run_id=args.producer_run_id,expected_source_head=args.producer_head,
                expected_transfer_sha=args.transfer_sha,expected_consumer_sha=args.consumer_sha,
                expected_recipient_key_id=args.recipient_key_id,initialize=args.initialize,expected_parent=args.expected_parent)
            root=private_root(args.private_dir);save(root/'production-input.json',(wire(report)+'\n').encode())
        save(root/'status.json',(wire(report)+'\n').encode());print(wire(report));return 0
    except Exception as exc:
        message=str(exc)
        reason=message if isinstance(exc,ValueError) and re.fullmatch(r'(?:RECIPIENT_|STATE_|OWNER_)[A-Z0-9_]{1,90}',message) else 'RECIPIENT_OPERATION_FAILED'
        print(wire(dict(status='OWNER_TRANSFER_REJECTED',reason=reason,plaintext_published=False)));return 2


if __name__=='__main__':raise SystemExit(main())
