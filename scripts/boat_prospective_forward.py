"""Existing Actions push opt-in; no provider function or workflow writer."""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path

from race_ai import boat_prospective_forward as policy
from race_ai.actions_contract import canonical, digest, stamp
from race_ai.permissioned_source_delivery import read_json_bytes

DOMAIN = b'RACE_AI_BOAT_PROSPECTIVE_FORWARD_STATE_V1\0'


def utc_now():
    return datetime.now(timezone.utc)


def active():
    path = os.environ.get('RACE_AI_FORWARD_REQUEST','')
    policy.need(path in ('', policy.REQUEST_PATH), 'FIXED_REQUEST_PATH')
    return bool(path)


def _cycle():
    import race_ai
    reference = str(Path(__file__).resolve().parents[1]/'pr64-reference/race_ai')
    if reference not in race_ai.__path__: race_ai.__path__.append(reference)
    from scripts import boat_all_model_cycle
    return boat_all_model_cycle


def _get(path):
    from scripts.github_existing_cycle import _live_gh
    return read_json_bytes(_live_gh(path))


def _root():
    from scripts.boat_history_collect import private_root
    return private_root(_cycle()._environment()['temp']/'boat-prospective-forward')


def _key():
    _cycle()._environment()
    from race_ai.boat_pdca_state import state_key
    return state_key('production')  # Existing Actions environment only.


def _save(name, data):
    from scripts.boat_history_collect import save
    record = dict(data=data, mac=hmac.new(_key(), DOMAIN+canonical(data).encode(),sha256).hexdigest())
    save(_root()/name, (canonical(record)+'\n').encode())


def _load(name):
    cycle = _cycle(); env = cycle._environment()
    record = read_json_bytes(cycle._read(_root()/name, 32768, private=True))
    policy.need(type(record) is dict and set(record) == {'data','mac'} and
        hmac.compare_digest(record['mac'],hmac.new(_key(),DOMAIN+canonical(record['data']).encode(),sha256).hexdigest()),
        'PRIVATE_STATE_MAC')
    data = record['data']
    policy.need(data['run_id'] == int(env['run_id']) and data['head_sha'] == env['head'] and
        sha256(cycle._read(cycle.ROOT/policy.REQUEST_PATH,16384)).hexdigest() == data['request_sha256'] and
        sha256(cycle._read(cycle.ROOT/policy.GRID_PATH,16384)).hexdigest() == data['request']['grid_input_sha256'] and
        sha256(cycle._read(cycle.ROOT/'audit/state/boat-model-runtime-input.json',65536)).hexdigest() ==
        data['request']['runtime_pointer_sha256'], 'CURRENT_REQUEST_BINDING')
    return data


def request(round_no=None):
    if not active(): return None
    data = _load('preloaded.json')
    policy.need(round_no in (None,1), 'ONE_CAPTURE_ROUND')
    cycle = _cycle()
    policy.validate_request(data['request'],now=utc_now(),
        grid_raw=cycle._read(cycle.ROOT/policy.GRID_PATH,16384),
        runtime_raw=cycle._read(cycle.ROOT/'audit/state/boat-model-runtime-input.json',65536))
    return data['request']


def done():
    if not active(): return False
    path = _root()/'ready.json'
    if not path.exists(): return False
    data = _load('ready.json')
    policy.need(data['proof']['status'] == 'PROSPECTIVE_BOAT_NATIVE14_READY', 'READY_PROOF')
    return True


def _outputs(**values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as target:
            for key,value in values.items(): target.write(key+'='+str(value)+'\n')


def admit():
    if not active():
        _outputs(research='false',grid_input=''); return dict(status='ORDINARY_PUSH_UNCHANGED')
    cycle = _cycle(); env = cycle._environment()
    event = read_json_bytes(cycle._read(Path(os.environ['GITHUB_EVENT_PATH']),2*1024*1024))
    activation = policy.activation((cycle.ROOT/policy.TRIGGER).read_text(),event['head_commit']['message'].splitlines()[0])
    policy.need(activation is not None,'PREFIX_REQUIRED')
    data = policy.admit(raw=cycle._read(cycle.ROOT/policy.REQUEST_PATH,16384),activation=activation,
        env=os.environ,get=_get,now=utc_now(),grid_raw=cycle._read(cycle.ROOT/policy.GRID_PATH,16384),
        runtime_raw=cycle._read(cycle.ROOT/'audit/state/boat-model-runtime-input.json',65536))
    from race_ai.boat_venue_future_grid import validate_manifest
    validate_manifest(read_json_bytes(cycle._read(cycle.ROOT/policy.GRID_PATH,16384)))
    _save('admitted.json',data)
    _outputs(research='true',grid_input=policy.GRID_PATH)
    return dict(status='EXPLICIT_RESEARCH_ADMITTED',request_sha256=data['request_sha256'])


def preload():
    policy.need(active(),'EXPLICIT_REQUEST_REQUIRED')
    from scripts import first_p0_bootstrap as first, github_existing_cycle as existing
    cycle = _cycle(); env = cycle._environment(); data = _load('admitted.json'); req = data['request']
    policy.validate_request(req,now=utc_now(),grid_raw=cycle._read(cycle.ROOT/policy.GRID_PATH,16384),
        runtime_raw=cycle._read(cycle.ROOT/'audit/state/boat-model-runtime-input.json',65536))
    # The existing owner reader authenticates the real closed control/continuity.
    # Public mirror pins alone never authorize a source request.
    control = first.previous_source_control(existing.gh,req['day_jst'],current_run=int(env['run_id']))
    policy.check_predecessor(req,control)
    bootstrap = first.bootstrap_control(req['day_jst'],int(env['run_id']))
    policy.need(bootstrap['requests_used'] == 0 and bootstrap.get('source_wait') is None and
        bootstrap.get('previous_halted_reason') is None and
        bootstrap.get('inherited_source_receipt') == control['receipt'] and
        bootstrap['lifetime_requests_base'] == control['lifetime_requests'] and
        not (cycle.ROOT/'cycle_recovery_output/repeat-session.json').exists(), 'BEFORE_BOOTSTRAP_SOURCE')
    policy.no_other_workers(_get,int(env['run_id']))
    marker = cycle.prepare_runtime(round_no=1,prospective_grid_input=policy.GRID_PATH)
    _save('preloaded.json',dict(data,grid_capability_sha256=digest(marker['prospective_grid'])))
    return dict(status='GRID_AUTHENTICATED_BEFORE_BOOTSTRAP',request_sha256=data['request_sha256'])


def prepare(round_no, grid_input):
    if not active():
        _cycle().prepare_runtime(round_no=round_no,prospective_grid_input=grid_input)
        return dict(status='LEGACY_EXPLICIT_GRID_PREPARED')
    req = request(round_no)
    policy.need(grid_input == req['grid_input_path'],'SAME_EXPLICIT_GRID')
    # Reuse the original pre-bootstrap capability and its actual verified clock.
    cap = _cycle().require_prospective_prepared(round_no,grid_input)
    policy.need(digest(cap.record) == _load('preloaded.json')['grid_capability_sha256'],
        'ORIGINAL_PRE_BOOTSTRAP_CAPABILITY_CHANGED')
    return dict(status='ORIGINAL_GRID_PRELOAD_REUSED')


def validate_rows(rows, *, now):
    req = request(1)
    manifest = read_json_bytes(_cycle()._read(_cycle().ROOT/policy.GRID_PATH,16384))
    policy.need(all(row['native_payload'].get('prospective_grid_evidence',{}).get('manifest') == manifest
        for row in rows), 'EXACT_REQUESTED_GRID')
    return policy.check_case(req,rows,now=now)


def prove(round_no, artifact):
    req = request(round_no); policy.need(type(artifact) is int and artifact > 0,'ACTUAL_ARTIFACT_REQUIRED')
    from scripts.github_existing_cycle import gh
    from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
    cycle = _cycle(); env = cycle._environment(); started = utc_now()
    metadata = read_json_bytes(gh(f'actions/artifacts/{artifact}')); raw = gh(f'actions/artifacts/{artifact}/zip')
    summary,payloads = _verified_private_pairs_artifact(raw,metadata,now=started,
        expected_run_id=int(env['run_id']),expected_head_sha=env['head'],key=_key())
    policy.need(metadata['name'] == f'all-existing-model-pairs-{env["run_id"]}-{round_no}' and
        summary['independent_pre_cutoff_receipt_verified'] is True and summary['partition_count'] == 14 and
        summary['cell_count'] == 14 and summary['unique_races'] == 1 and summary['captured_native_input_count'] == 14,
        'EXACT_ONE_CASE_ARTIFACT')
    rows = [dict(cell_key=cap['cell_key'],native_payload=cap['native_payload'])
            for payload in payloads for cap in payload.get('captured_native_inputs',[])]
    verified = utc_now()
    policy.need(verified >= started,'READBACK_CLOCK_REGRESSION')
    validate_rows(rows,now=verified)
    proof = policy.check_rows(req,rows,now=verified,saved_at=metadata['created_at'])
    data = _load('preloaded.json')
    proof.update(status='PROSPECTIVE_BOAT_NATIVE14_READY',request_sha256=data['request_sha256'],
        artifact_id=artifact,artifact_digest=metadata['digest'],saved_at=metadata['created_at'],
        run_id=int(env['run_id']),head_sha=env['head'],independent_pre_cutoff_receipt_verified=True,
        plaintext_published=False,production_promoted=False)
    finished = utc_now()
    policy.need(finished >= verified and finished+timedelta(seconds=600) <
        stamp(req['target']['cutoff_at']),'FRESH_READBACK_SIX_HUNDRED_MARGIN')
    proof['verified_at'] = finished.isoformat()
    _save('ready.json',dict(data,proof=proof))
    return proof


def finalize():
    policy.need(active(),'EXPLICIT_REQUEST_REQUIRED')
    from scripts.boat_history_collect import save
    try:
        policy.need(done(),'NO_VERIFIED_ONE_CASE_RECEIPT')
        proof = _load('ready.json')['proof']
    except Exception:
        proof = dict(status='HOLD_PROSPECTIVE_BOAT_NATIVE14',independent_pre_cutoff_receipt_verified=False,
            native_cell_count=None,unique_races=None,plaintext_published=False,production_promoted=False)
    # Count/hash-only public artifact; full request and originals stay private.
    save(_root()/'proof.json',(canonical(proof)+'\n').encode())
    print(json.dumps(proof,sort_keys=True))
    return proof['status'] == 'PROSPECTIVE_BOAT_NATIVE14_READY'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('admit','preload','prepare','prove','finalize'))
    parser.add_argument('--round',dest='round_no',type=int)
    parser.add_argument('--prospective-grid-input'); parser.add_argument('--artifact',type=int)
    args = parser.parse_args(argv)
    if args.command == 'finalize': return 0 if finalize() else 2
    if args.command == 'admit': result = admit()
    elif args.command == 'preload': result = preload()
    elif args.command == 'prepare': result = prepare(args.round_no,args.prospective_grid_input)
    else: result = prove(args.round_no,args.artifact)
    print(json.dumps(result,sort_keys=True)); return 0


if __name__ == '__main__': raise SystemExit(main())
