"""Import already captured official BOAT sources into the private app sidecar.

No network, inference, forecast rewrite or background worker. Capture metadata
uses the actual local acquisition clock; a later import cannot backdate it.
"""
from datetime import date, datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read_capture(source_dir, metadata_name):
    from race_ai.private_cycle_capture import _parent_handle
    from race_ai.current_boat_inputs import _read, _json, _moment
    with _parent_handle(Path(source_dir)) as folder:
        metadata = _json(_read(folder, metadata_name, 64*1024))
        raw = _read(folder, metadata['file'], 20*1024*1024)
    if metadata.get('status') != 200 or metadata.get('sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('SOURCE_CAPTURE_HASH_MISMATCH')
    _moment(metadata['acquired_at'])
    return raw, metadata


def import_context(args):
    # CurrentBoatInputs registers the unchanged pinned source-parser modules.
    from race_ai import current_boat_inputs
    from race_ai.boat_observation_context import (parse_program_roster, parse_beforeinfo,
                                                 parse_pitreport, eligibility_for_cutoff)
    from race_ai.boat_context_store import save_context
    from race_ai.boat_entry_observations import build_entry_history_from_archives, conditional_profile_before
    rid=args.race_id
    if not current_boat_inputs.re.fullmatch(r'\d{8}-(?:0[1-9]|1\d|2[0-4])-(?:0[1-9]|1[0-2])',rid):
        raise ValueError('BOAT_CONTEXT_RACE_ID_INVALID')
    day=date.fromisoformat(f'{rid[:4]}-{rid[4:6]}-{rid[6:8]}')
    raw, meta=read_capture(args.source_dir,args.program_meta)
    program=parse_program_roster(raw,expected_race_id=rid,
        source_url=meta['url'],captured_at=meta['acquired_at'])
    if program['race_id']!=rid:raise ValueError('BOAT_CONTEXT_PROGRAM_MISMATCH')
    roster=[dict(lane=r['lane'],registration_number=r['registration_number']) for r in program['participants']]
    context=dict(schema='RACE_AI_BOAT_SUPPLEMENTAL_CONTEXT_V1',race_id=rid,
        cutoff_at=program['source_cutoff_at'],roster=roster,beforeinfo=None,pitreport=None,
        entry_history=None,forecast_inputs_used=False)
    for kind, filename, parser in [('beforeinfo',args.beforeinfo_meta,parse_beforeinfo),
                                   ('pitreport',args.pitreport_meta,parse_pitreport)]:
        if not filename:continue
        raw,meta=read_capture(args.source_dir,filename)
        parsed=parser(raw,source_url=meta['url'],captured_at=meta['acquired_at'],expected_race_id=rid,roster=roster)
        parsed.update(eligibility_for_cutoff(parsed,cutoff_at=context['cutoff_at']))
        context[kind]=parsed
    if args.history_b_meta or args.history_k_meta:
        if not (args.history_b_meta and args.history_k_meta and args.history_day):
            raise ValueError('BOTH_DATED_HISTORY_SOURCES_REQUIRED')
        b,b_meta=read_capture(args.source_dir,args.history_b_meta)
        k,k_meta=read_capture(args.source_dir,args.history_k_meta)
        source=lambda m:dict(source_url=m['url'],source_sha256=m['sha256'],captured_at=m['acquired_at'])
        history=build_entry_history_from_archives(b,k,day=date.fromisoformat(args.history_day),
            b_source=source(b_meta),k_source=source(k_meta))
        as_of=datetime.now(timezone.utc).isoformat()
        context['entry_history']=dict(profiles=[conditional_profile_before(history,as_of=as_of,
            racer_id=r['registration_number']) for r in roster])
    revision=save_context(args.private_dir,context)
    return dict(race_id=rid,context_sha256=revision,
        beforeinfo_status=context['beforeinfo']['status'] if context['beforeinfo'] else None,
        pitreport_status=context['pitreport']['status'] if context['pitreport'] else None,
        comments=sum(bool(p.get('comment')) for p in (context['pitreport'] or {}).get('participants',[])),
        historical_racer_starts=sum(p['sample_races'] for p in (context['entry_history'] or {}).get('profiles',[])),
        forecast_inputs_used=False,new_predictions=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--private-dir',type=Path,required=True)
    parser.add_argument('--race-id',required=True)
    parser.add_argument('--program-meta',required=True)
    parser.add_argument('--beforeinfo-meta')
    parser.add_argument('--pitreport-meta')
    parser.add_argument('--history-b-meta')
    parser.add_argument('--history-k-meta')
    parser.add_argument('--history-day')
    args=parser.parse_args()
    if not(args.beforeinfo_meta or args.pitreport_meta):parser.error('at least one current context capture required')
    print(json.dumps(import_context(args),ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
