"""TEST ONLY: fixed local Python/Node seam, never a production default runtime.

Authored admissions and native SQLite prove local behavior, not source rights,
physical UTC, a protected remote destination or an independent storage receipt.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
PIN='9aeb2b425de9d05a44cb31f72a242a5111ada80a'
REFERENCE=ROOT/'pr71-private-vault-reference'
FILES={
    'workers/private_wire_vault.mjs':'383264d3a676e04fc91a6c4956ef79d5bda709a09f6ad5b03e0d6062b6891024',
    'workers/private_wire_vault_schema.mjs':'950646a723ba6b6fed4446084a9f1510fb18b1540dcc0c5c5ff1cba0eae41b0c',
    'tests/support/local_private_wire_d1.mjs':'04c26b80e27110b891e297a0d615cf99e9db84446f4d1ee978274f64f88db215',
}
MAX_WIRE=4194304
MAX_META=65536
MAX_STDOUT=8192
ERROR='LOCAL_VAULT_TEST_BRIDGE_REJECTED'


def _fail():
    raise ValueError(ERROR) from None


def _raw(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')


def _pairs(items):
    out={}
    for key,value in items:
        if key in out:_fail()
        out[key]=value
    return out


def _json(data):
    def invalid(_):_fail()
    return json.loads(data.decode('utf-8'),object_pairs_hook=_pairs,parse_constant=invalid)


def _outside_git(path,*,directory=False,allow_missing=False):
    path=Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\','//')):_fail()
    for ancestor in reversed((path,*path.parents)):
        if not ancestor.exists():
            if ancestor==path and allow_missing:continue
            _fail()
        info=ancestor.lstat()
        if stat.S_ISLNK(info.st_mode):_fail()
        if ancestor!=path or directory:
            if not stat.S_ISDIR(info.st_mode) or (ancestor/'.git').exists():_fail()
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:_fail()
    return path


def _read_file(path,limit):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit:_fail()
    flags=os.O_RDONLY|getattr(os,'O_BINARY',0)|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags)
    try:
        opened=os.fstat(fd)
        if (opened.st_dev,opened.st_ino)!=(info.st_dev,info.st_ino) or opened.st_size>limit:_fail()
        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(limit+1)
        after=os.fstat(fd)
        if len(data)>limit or len(data)!=opened.st_size or after.st_size!=opened.st_size:_fail()
        return data
    finally:os.close(fd)


def verify_reference():
    """Exact public blobs only; this declaration is not runtime authentication."""
    manifest=_json(_read_file(ROOT/'config/private-wire-vault-reference-manifest.json',8192))
    if (set(manifest)!={'schema','source_commit_sha40','byte_representation','node_version','files','scope'}
            or manifest['schema']!='RACE_AI_PRIVATE_VAULT_REFERENCE_MANIFEST_V1'
            or manifest['source_commit_sha40']!=PIN or manifest['node_version']!='24.19.0'
            or manifest['byte_representation']!='EXACT_GIT_BLOB_LF'
            or manifest['scope']!='TEST_ONLY_FIXED_REFERENCE_NO_PRODUCTION_BRIDGE'
            or type(manifest['files']) is not list or len(manifest['files'])!=3):_fail()
    expected=[]
    for name,digest in FILES.items():
        data=_read_file(REFERENCE/name,65536)
        if hashlib.sha256(data).hexdigest()!=digest:_fail()
        expected.append(dict(path=name,bytes=len(data),sha256=digest))
    if manifest['files']!=expected:_fail()
    return manifest


def _run_child(command):
    """One deadline includes spawn, capped draining, kill, reap and join."""
    deadline=time.monotonic()+30
    process=None
    reader=None
    output=bytearray()
    invalid=threading.Event()
    def poll():
        try:return process.poll()
        except Exception:
            invalid.set()
            return None
    def stop():
        invalid.set()
        try:process.kill()
        except Exception:pass  # Still attempt reap/join; never emit child details.
    try:
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,shell=False,cwd=ROOT)
        def drain():
            try:
                while True:
                    chunk=process.stdout.read(1024)
                    if not chunk:break
                    room=MAX_STDOUT+1-len(output)
                    output.extend(chunk[:room])
                    if len(output)>MAX_STDOUT:
                        stop()
                        break
            except BaseException:
                invalid.set()
                if poll() is None:stop()
        reader=threading.Thread(target=drain,daemon=True)
        reader.start()
        process.wait(timeout=max(0,deadline-time.monotonic()-2))
    except Exception:
        invalid.set()
    finally:
        if process is not None:
            if poll() is None:stop()
            try:process.wait(timeout=max(0,deadline-time.monotonic()))
            except Exception:invalid.set()
            if reader is not None:
                try:reader.join(timeout=max(0,deadline-time.monotonic()))
                except Exception:invalid.set()
                if reader.is_alive():invalid.set()
            if reader is None or not reader.is_alive():
                try:
                    if process.stdout is not None:process.stdout.close()
                except Exception:invalid.set()
    if (process is None or poll() is None or invalid.is_set()
            or process.returncode!=0 or time.monotonic()>deadline):_fail()
    if _json(bytes(output))!={'schema':'RACE_AI_LOCAL_VAULT_TEST_CHILD_V1','status':'OK'}:_fail()


class LocalPrivateWireTestBridge:
    """Explicit local test binding to ONE destination; no URL/default/backend."""
    def __init__(self,destination,*,node_executable):
        try:
            self.destination=_outside_git(destination,allow_missing=True)
            self.node=_outside_git(node_executable)
            verify_reference()
            self.create_calls=self.read_calls=0
        except Exception:_fail()

    @staticmethod
    def locator(claim):
        try:
            data=_raw(claim)
            if len(data)>8192:_fail()
            return hashlib.sha256(b'RACE_AI_LOCAL_PRIVATE_WIRE_LOCATOR_V1\0'+data).hexdigest()
        except Exception:_fail()

    def create(self,claim,wire):
        return self._invoke('create',claim,wire,self.locator(claim))

    def read(self,claim,locator):
        return self._invoke('read',claim,None,locator)

    def _invoke(self,operation,claim,wire,locator):
        try:
            verify_reference()
            _outside_git(self.destination,allow_missing=True)
            _outside_git(self.node)
            if self.locator(claim)!=locator:_fail()
            if operation=='create' and (type(wire) is not bytes or not 0<len(wire)<=MAX_WIRE):_fail()
            if operation=='read' and wire is not None:_fail()
            control=_raw(dict(schema='RACE_AI_LOCAL_VAULT_TEST_IPC_V1',operation=operation,
                claim=claim,locator=locator,database_path=str(self.destination)))
            if len(control)>MAX_META:_fail()
            with tempfile.TemporaryDirectory(prefix='race35-vault-ipc-') as temporary:
                ipc=_outside_git(Path(temporary),directory=True)
                with (ipc/'control.json').open('xb') as stream:stream.write(control)
                if wire is not None:
                    with (ipc/'wire.bin').open('xb') as stream:stream.write(wire)
                if operation=='create':self.create_calls+=1
                else:self.read_calls+=1
                _run_child([str(self.node),str(ROOT/'scripts/private_retention_action_local_vault.mjs'),str(ipc)])
                result=_json(_read_file(ipc/'result.json',MAX_META))
                if (type(result) is not dict or set(result)!={'schema','result','wire_present'}
                        or result['schema']!='RACE_AI_LOCAL_VAULT_TEST_IPC_RESULT_V1'
                        or type(result['wire_present']) is not bool or type(result['result']) is not dict):_fail()
                value=result['result']
                if value.get('wire','MISSING') is not None:_fail()
                if result['wire_present']:
                    body=_read_file(ipc/'readback.bin',MAX_WIRE)
                    if (type(value.get('wire_bytes')) is not int or len(body)!=value['wire_bytes']
                            or hashlib.sha256(body).hexdigest()!=value.get('wire_sha256')):_fail()
                    value['wire']=body
                elif (ipc/'readback.bin').exists():_fail()
                return value
        except Exception:_fail()


def local_adapter_declaration():
    return dict(schema='RACE_AI_PRIVATE_RETENTION_LOCAL_ADAPTER_V1',
        destination_contract='LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1',
        runtime_scope='EXPLICIT_INJECTED_LOCAL_TEST_CANDIDATE_ONLY',
        source_commit_sha40=PIN,vault_module_sha256=FILES['workers/private_wire_vault.mjs'],
        vault_schema_sha256=FILES['workers/private_wire_vault_schema.mjs'],
        native_test_adapter_sha256=FILES['tests/support/local_private_wire_d1.mjs'])


def exercise_existing_case(root,original,request,seal,*,node_executable,lose_return=False):
    """Only load a previously prepared case; no producers or original mutation."""
    from contextlib import ExitStack
    from unittest.mock import patch
    from race_ai import permissioned_model_case as case
    from race_ai import permissioned_source_delivery as source
    from race_ai import isolated_model_case_runtime as runtime
    def forbidden(*args,**kwargs):raise AssertionError('OPERATIVE_MODEL_OR_NETWORK_CALL_FORBIDDEN')
    with ExitStack() as stack:
        for owner,name in ((case,'prepare_case'),(source,'deliver'),(runtime,'produce'),(runtime,'preflight')):
            stack.enter_context(patch.object(owner,name,side_effect=forbidden))
        stack.enter_context(patch('socket.create_connection',side_effect=forbidden))
        return _exercise_existing_case(root,original,request,seal,node_executable=node_executable,lose_return=lose_return)


def _exercise_existing_case(root,original,request,seal,*,node_executable,lose_return):
    from contextlib import closing
    from datetime import datetime,timezone
    import sqlite3
    from race_ai import permissioned_model_case as case
    from race_ai import retained_case_submission as retained
    from race_ai import private_retention_action as action
    from race_ai import private_wire_retention as retention
    from tests.test_offline_model_run import Clock,MODELS
    from tests.test_permissioned_case_submission import gates,RecordingTransport,BRANCH,PIN as EXECUTOR
    if not __debug__:raise RuntimeError('ENABLED_ASSERTIONS_REQUIRED')
    root=Path(root)
    before=Path(original).read_bytes()
    declaration=local_adapter_declaration()
    loaded=case.load_case(original,expected_request_sha256=seal['request_sha256'],
        private_path_verifier=gates()['private_path_verifier'])
    destination=dict(destination_ref='local-private-vault-fictional-owner-integration',
        owner_scope_ref='fictional-local-only-owner',
        adapter_contract_sha256=retention._hash(declaration['schema'],declaration),max_wire_bytes=MAX_WIRE)
    policy=dict(policy_ref='fictional-local-only-retention',retain_until='2030-02-15T00:30:00+00:00',
        protection_policy_sha256=hashlib.sha256(b'LOCAL_INSERT_ONLY_SQL_V1').hexdigest(),
        immutability_policy_sha256=hashlib.sha256(b'LOCAL_COOPERATIVE_SQL_NO_WORM').hexdigest())
    slot=dict(schema=retained.SLOT_SCHEMA,scope_ref='fictional-local-action-comparison',
        race_id=request['race_id'],race_revision=loaded['delivery']['snapshot']['race']['race_revision'],
        as_of_utc=datetime.fromisoformat(request['as_of']).astimezone(timezone.utc).isoformat(),model_ids=list(MODELS))
    attempt=root/'private-action-attempt.sqlite'
    reserved=retained.reserve_retained_case(attempt,original,
        expected_request_sha256=seal['request_sha256'],expected_branch=BRANCH,submission_source_sha40=EXECUTOR,
        slot=slot,assignment_ref='fictional-single-private-path-assignment',destination=destination,
        retention_policy=policy,clock=Clock('2030-01-15T00:16:00.123456+00:00'),
        private_path_verifier=gates()['private_path_verifier'],admit_store=gates()['admit_store'],
        submission_contract='PRIVATE_ACTION_V3')
    bridge=LocalPrivateWireTestBridge(root/'fixed-vault.sqlite',node_executable=node_executable)
    def create(claim,wire):
        result=bridge.create(claim,wire)
        if lose_return:raise RuntimeError('FICTIONAL_LOST_RETURN_PRIVATE_DETAIL_MUST_NOT_LEAK')
        return result
    identity=dict(expected_request_sha256=seal['request_sha256'],
        expected_reservation_sha256=reserved['reservation_sha256'],expected_branch=BRANCH,
        submission_source_sha40=EXECUTOR,private_path_verifier=gates()['private_path_verifier'],
        admit_store=gates()['admit_store'])
    result=action.consume_private_retention_action(attempt,original,**identity,
        private_adapter_declaration=declaration,clock=Clock('2030-01-15T00:17:00.123456+00:00'),
        admit_source_storage=lambda *a:True,admit_owner_destination=lambda *a:True,
        admit_coordinator=lambda *a:True,verify_cutoff=lambda *a:True,admit_model_roster=lambda *a:True,
        admit_private_action=lambda *a:True,admit_private_adapter=lambda *a:True,private_create=create)
    assert result['private_action_consumed'] is True and result['create_calls']==1 and result['read_calls']==0
    assert result['status']==('PRIVATE_ACTION_CONSUMED_READ_ONLY' if lose_return else 'LOCAL_PRIVATE_READBACK_UNVERIFIED')
    owner_bytes=attempt.read_bytes()
    vault_bytes=bridge.destination.read_bytes()
    # No declaration/clock/writer renewal even when the first return was lost.
    replay=action.consume_private_retention_action(attempt,original,**identity)
    assert replay['status']=='PRIVATE_ACTION_CONSUMED_READ_ONLY'
    assert replay['private_action_sha256']==result['private_action_sha256']
    assert replay['create_calls']==0 and replay['read_calls']==0
    recovered=action.read_private_retention_action(attempt,original,
        expected_request_sha256=seal['request_sha256'],expected_reservation_sha256=reserved['reservation_sha256'],
        expected_private_action_sha256=replay['private_action_sha256'],
        clock=Clock('2030-01-15T04:00:00+00:00'),private_path_verifier=gates()['private_path_verifier'],
        admit_store=gates()['admit_store'],admit_private_reader=lambda *a:True,private_read=bridge.read)
    assert recovered['status']=='LOCAL_PRIVATE_READBACK_UNVERIFIED'
    assert recovered['readback']['wire']==loaded['wire']
    assert recovered['read_calls']==1 and recovered['create_calls']==0
    assert bridge.create_calls==1 and bridge.read_calls==1
    assert attempt.read_bytes()==owner_bytes and bridge.destination.read_bytes()==vault_bytes
    material=retention._request(loaded,retention._settings(destination,policy,reserved['base_binding']))
    checked=retention.verify_retention_evidence(original,material,
        expected_case_request_sha256=seal['request_sha256'],expected_retention_request_sha256=retention._hash(retention.REQUEST,material),
        readback_bytes=recovered['readback']['wire'],readback_descriptor=None,receipt_claims=None,receipt_proof=None,
        clock=Clock('2030-01-15T00:20:00+00:00'),private_path_verifier=gates()['private_path_verifier'])
    assert checked['status']=='WHOLE_BYTES_MATCH_UNVERIFIED'
    transport=RecordingTransport()
    denied=retained.dispatch_retained_case(attempt,original,expected_request_sha256=seal['request_sha256'],
        expected_reservation_sha256=reserved['reservation_sha256'],expected_private_action_sha256=result['private_action_sha256'],
        expected_branch=BRANCH,submission_source_sha40=EXECUTOR,clock=Clock('2030-01-15T00:20:00+00:00'),
        **gates(),transport=transport,admit_retention_action=lambda *a:True,submission_contract='PRIVATE_ACTION_V3')
    assert denied['status']=='DENIED' and transport.calls==[]
    with closing(sqlite3.connect(attempt)) as db:
        assert db.execute('SELECT count(*) FROM submission_private_action').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM submission_retention').fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM submission_intents').fetchone()[0]==0
    assert Path(original).read_bytes()==before
    return dict(model_source_sha40=loaded['request']['model_source_sha40'],wire_sha256=loaded['wire_sha256'],
        wire_bytes=len(loaded['wire']),private_action_sha256=result['private_action_sha256'],
        lost_return_injected=lose_return,original_case_bytes_unchanged=True,private_create_calls=bridge.create_calls,
        private_read_calls=bridge.read_calls,source_rights_or_receipt_authenticated=False,
        readback_status=checked['status'],public_intents=0,public_http_calls=0)


def main():
    import sys
    from unittest.mock import patch
    if not __debug__:raise RuntimeError('ENABLED_ASSERTIONS_REQUIRED')
    sys.path.insert(0,str(ROOT))
    from tests.test_fixed_model_case_profiles import v2_fixture,v2_gates
    from tests.test_offline_model_run import Clock
    from race_ai.permissioned_model_case import prepare_case
    node=Path(os.environ['RACE_AI_TEST_NODE_EXE'])
    records=[]
    with tempfile.TemporaryDirectory(prefix='race35-four-sport-fictional-cli-') as directory, \
            patch('socket.create_connection',side_effect=AssertionError('NETWORK_FORBIDDEN')):
        for sport,count in (('boat',6),('keirin',7),('autorace',3),('horse',3)):
            local=Path(directory)/sport
            local.mkdir()
            request,raw,policy=v2_fixture(sport,count)
            original=local/'case.sqlite'
            seal=prepare_case(original,request,raw,policy,clock=Clock(),**v2_gates(request))
            result=exercise_existing_case(local,original,request,seal,node_executable=node,lose_return=True)
            records.append(dict(sport=sport,**result))
    print(json.dumps(dict(schema='RACE35_PRIVATE_ACTION_NATIVE_VAULT_SYNTHETIC_V1',scope='SYNTHETIC_ONLY',
        status='SYNTHETIC_CI_PASS',records=records,fictional_fixture_preparations=4,
        operative_replay_model_runs=0,real_forecasts=0,provider_or_cloud_calls=0,
        actual_storage_runtime_or_rights_authenticated=False),sort_keys=True))


if __name__=='__main__':
    main()
