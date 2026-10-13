"""Usage: python -m race_ai.cli [import-k|import-b|stats|exhibition-import|exhibition-at|entry-evidence|pair]"""
import argparse
import json
from pathlib import Path
from .video import index_video
from .motor import setup_motor, import_motor_observation, import_motor_service, analyze_motor
from .core import (connect, import_official, histories, save_exhibition,
                   exhibition_asof, record_entry_evidence, pair_summary, SourceError)


def main():
    p=argparse.ArgumentParser(description='RACE AI v0.8 offline verified-data research')
    p.add_argument('--db',default='race_ai.sqlite3')
    sub=p.add_subparsers(dest='command',required=True)
    for cmd in ('import-k','import-b'):
        s=sub.add_parser(cmd)
        s.add_argument('file');s.add_argument('--date',required=True)
        s.add_argument('--published-at',required=True);s.add_argument('--captured-at',required=True)
    s=sub.add_parser('stats');s.add_argument('--racer',required=True)
    s.add_argument('--lane',type=int,required=True);s.add_argument('--course',type=int,required=True)
    s.add_argument('--asof',required=True)
    s=sub.add_parser('exhibition-import');s.add_argument('json_file')
    s=sub.add_parser('exhibition-at');s.add_argument('--race-id',required=True);s.add_argument('--asof',required=True)
    s=sub.add_parser('entry-evidence');s.add_argument('json_file')
    s=sub.add_parser('video-index');s.add_argument('file');s.add_argument('--rights-confirmed',action='store_true')
    s.add_argument('--sample-seconds',type=float,default=2.0)
    s=sub.add_parser('motor-observation');s.add_argument('json_file')
    s=sub.add_parser('motor-service');s.add_argument('json_file')
    s=sub.add_parser('motor-report');s.add_argument('--venue',required=True)
    s.add_argument('--cycle',required=True);s.add_argument('--motor',type=int,required=True)
    s.add_argument('--asof',required=True);s.add_argument('--target-meeting-id')
    s=sub.add_parser('pair');s.add_argument('--challenger',required=True)
    s.add_argument('--defender',required=True);s.add_argument('--asof',required=True)
    a=p.parse_args()
    try:
        if a.command=='video-index':
            print(json.dumps(index_video(a.file,rights_confirmed=a.rights_confirmed,
                 sample_seconds=a.sample_seconds),ensure_ascii=False,indent=2))
            return
        with connect(a.db) as db:
            if a.command.startswith('motor-'):
                setup_motor(db)
            if a.command=='motor-observation':
                result=import_motor_observation(db,json.loads(Path(a.json_file).read_text()))
            elif a.command=='motor-service':
                result=import_motor_service(db,json.loads(Path(a.json_file).read_text()))
            elif a.command=='motor-report':
                result=analyze_motor(db,a.venue,a.cycle,a.motor,a.asof,target_meeting_id=a.target_meeting_id)
            elif a.command in ('import-k','import-b'):
                result=import_official(db,a.file,a.command[-1].upper(),a.date,a.published_at,a.captured_at)
            elif a.command=='stats':
                result=histories(db,a.racer,a.lane,a.course,a.asof)
            elif a.command=='exhibition-import':
                result=save_exhibition(db,json.loads(Path(a.json_file).read_text()))
            elif a.command=='exhibition-at':
                result=exhibition_asof(db,a.race_id,a.asof)
            elif a.command=='entry-evidence':
                result=record_entry_evidence(db,json.loads(Path(a.json_file).read_text()))
            else:
                result=pair_summary(db,a.challenger,a.defender,a.asof)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (SourceError,KeyError,ValueError) as exc:
        p.exit(2, f'SAFE_STOP: {exc}\n')

if __name__=='__main__':
    main()
