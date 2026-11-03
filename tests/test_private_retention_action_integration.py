"""Local native vault integration; authored authority is never genuine proof."""
from pathlib import Path
import hashlib
import io
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_private_retention_action_synthetic import LocalPrivateWireTestBridge,exercise_existing_case,_run_child,ROOT


def binary_claim(wire):
    sha = lambda data: hashlib.sha256(data).hexdigest()
    return dict(schema='RACE_AI_LOCAL_PRIVATE_WIRE_CLAIM_V1',
        destination_contract='LOCAL_SQLITE_D1_BATCH_CANDIDATE_V1',
        destination_ref='local-private-vault-fictional-integration',
        owner_ref='fictional-local-test-owner', request_sha256='a'*64,
        wire_sha256=sha(wire), delivery_sha256='b'*64,
        model_source_sha40='c'*40, retention_request_sha256='d'*64,
        reservation_sha256='e'*64, reservation_row_sha256='f'*64,
        reservation_commit_guard_at='2030-01-15T00:16:00.123456+00:00',
        retain_until='2030-02-15T00:30:00+00:00',
        protection_policy='LOCAL_INSERT_ONLY_SQL_V1', wire_bytes=len(wire),
        chunk_sha256=[sha(wire[n:n+524288]) for n in range(0,len(wire),524288)])


class LocalPrivateWireBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='race35-private-bridge-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.node=Path(os.environ['RACE_AI_TEST_NODE_EXE'])
        self.destination=self.root/'fixed-vault.sqlite'
        self.bridge=LocalPrivateWireTestBridge(self.destination,node_executable=self.node)

    def test_actual_vault_whole_bytes_and_missing_read_are_unverified(self):
        wire=bytes(range(256))*2051
        claim=binary_claim(wire)
        locator=self.bridge.locator(claim)
        missing=self.bridge.read(claim,locator)
        self.assertEqual(missing['status'],'UNRESOLVED')
        self.assertIsNone(missing['wire'])
        self.assertFalse(self.destination.exists())
        created=self.bridge.create(claim,wire)
        self.assertEqual(created['status'],'LOCAL_CREATED')
        self.assertEqual(created['wire'],wire)
        self.assertEqual(created['claim'],claim)
        self.assertEqual(created['claim']['reservation_commit_guard_at'],claim['reservation_commit_guard_at'])
        original=self.destination.read_bytes()
        read=self.bridge.read(claim,locator)
        self.assertEqual(read['status'],'LOCAL_READBACK')
        self.assertIs(type(read['wire']),bytes)
        self.assertEqual(read['wire'],wire)
        self.assertEqual(self.destination.read_bytes(),original)
        self.assertFalse(read['independent_retention_proof'])
        self.assertEqual(read['retention_status'],'RETENTION_UNVERIFIED')
        self.assertEqual(self.bridge.create_calls,1)
        self.assertEqual(self.bridge.read_calls,2)

    def test_oversized_wire_denies_before_native_destination(self):
        wire=b'x'*(4194304+1)
        with self.assertRaisesRegex(ValueError,'LOCAL_VAULT_TEST_BRIDGE_REJECTED'):
            self.bridge.create(binary_claim(wire),wire)
        self.assertFalse(self.destination.exists())

    def test_wrong_locator_never_spawns_or_creates_database(self):
        with patch('subprocess.Popen',side_effect=AssertionError('MUST_NOT_SPAWN')) as child:
            with self.assertRaisesRegex(ValueError,'^LOCAL_VAULT_TEST_BRIDGE_REJECTED$'):
                self.bridge.read(binary_claim(b'wire'),'0'*64)
        self.assertEqual(child.call_count,0)
        self.assertEqual(self.bridge.read_calls,0)
        self.assertFalse(self.destination.exists())

    def test_bounded_node_file_read_refuses_growth_before_unbounded_materialization(self):
        # Exercise the ACTUAL bounded() implementation with controlled fs.
        # A file growing after stat must not trigger unbounded readFileSync.
        program=r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const text=fs.readFileSync(process.argv[1],'utf8');
const start=text.indexOf('function bounded('),end=text.indexOf('function exclusive(',start);
assert(start>=0&&end>start);
let unbounded=0,maxRead=0,closed=0,offset=0;
const context={Buffer,lstatSync:()=>({isFile:()=>true,isSymbolicLink:()=>false,nlink:1,size:1,dev:1,ino:1}),
  openSync:()=>7,fstatSync:()=>({dev:1,ino:1,size:1}),closeSync:()=>{closed++;},
  readFileSync:()=>{unbounded++;return Buffer.alloc(4096);},
  readSync:(fd,b,pos,length)=>{maxRead=Math.max(maxRead,length);let n=Math.min(length,4096-offset);b.fill(120,pos,pos+n);offset+=n;return n;},
  fail:()=>{throw Error('EXPECTED_REJECTION');}};
vm.createContext(context);vm.runInContext(text.slice(start,end)+';this.bounded=bounded;',context);
assert.throws(()=>context.bounded('synthetic-only',64));
assert.equal(unbounded,0);assert(maxRead<=65);assert.equal(closed,1);
process.stdout.write('{"schema":"RACE_AI_LOCAL_VAULT_TEST_CHILD_V1","status":"OK"}');
"""
        _run_child([str(self.node),'-e',program,str(ROOT/'scripts/private_retention_action_local_vault.mjs')])


class BoundedChildLifecycleTests(unittest.TestCase):
    GOOD=b'{"schema":"RACE_AI_LOCAL_VAULT_TEST_CHILD_V1","status":"OK"}'

    class FakeProcess:
        def __init__(self,body,*,kill_error=False):
            self.stdout=io.BytesIO(body)
            self.returncode=None
            self.kill_error=kill_error
            self.waits=self.kills=0

        def poll(self):return self.returncode

        def wait(self,timeout):
            self.waits+=1
            if self.kill_error and self.waits==1:raise subprocess.TimeoutExpired('FICTIONAL_ONLY',timeout)
            if self.returncode is None:self.returncode=0
            return self.returncode

        def kill(self):
            self.kills+=1
            if self.kill_error:raise OSError('FICTIONAL_PRIVATE_KILL_DETAIL')
            self.returncode=-9

    def test_kill_failure_still_reaps_and_sanitizes(self):
        process=self.FakeProcess(self.GOOD,kill_error=True)
        with patch('subprocess.Popen',return_value=process) as spawn:
            with self.assertRaisesRegex(ValueError,'^LOCAL_VAULT_TEST_BRIDGE_REJECTED$'):
                _run_child(['NO_ACTUAL_SUBPROCESS'])
        self.assertEqual(spawn.call_count,1)
        self.assertGreaterEqual(process.waits,2)
        self.assertGreaterEqual(process.kills,1)

    def test_stdout_cap_accepts_boundary_and_rejects_overflow_without_respawn(self):
        for size,denied in ((8192,False),(8193,True)):
            with self.subTest(size=size):
                process=self.FakeProcess(self.GOOD+b' '*(size-len(self.GOOD)))
                with patch('subprocess.Popen',return_value=process) as spawn:
                    if denied:
                        with self.assertRaisesRegex(ValueError,'^LOCAL_VAULT_TEST_BRIDGE_REJECTED$'):
                            _run_child(['NO_ACTUAL_SUBPROCESS'])
                    else:_run_child(['NO_ACTUAL_SUBPROCESS'])
                self.assertEqual(spawn.call_count,1)


class ConsumedPrivateActionNativeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.test_fixed_model_case_profiles import v2_fixture,v2_gates
        from tests.test_offline_model_run import Clock
        from race_ai.permissioned_model_case import prepare_case
        cls.fixture=tempfile.TemporaryDirectory(prefix='race35-authored-fixture-')
        cls.original=Path(cls.fixture.name)/'case.sqlite'
        cls.request,raw,policy=v2_fixture('autorace',3)
        cls.seal=prepare_case(cls.original,cls.request,raw,policy,clock=Clock(),**v2_gates(cls.request))

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def test_normally_returned_private_commit_consumes_same_owner_and_blocks_public(self):
        with tempfile.TemporaryDirectory(prefix='race35-native-owner-normal-') as directory:
            result=exercise_existing_case(Path(directory),self.original,self.request,self.seal,
                node_executable=Path(os.environ['RACE_AI_TEST_NODE_EXE']))
            self.assertEqual(result['private_create_calls'],1)
            self.assertEqual(result['private_read_calls'],1)
            self.assertEqual(result['public_intents'],0)

    def test_lost_actual_vault_return_bootstraps_and_recovers_without_second_create(self):
        with tempfile.TemporaryDirectory(prefix='race35-native-owner-lost-return-') as directory:
            result=exercise_existing_case(Path(directory),self.original,self.request,self.seal,
                node_executable=Path(os.environ['RACE_AI_TEST_NODE_EXE']),lose_return=True)
            self.assertTrue(result['lost_return_injected'])
            self.assertEqual(result['private_create_calls'],1)
            self.assertFalse(result['source_rights_or_receipt_authenticated'])


if __name__=='__main__':
    unittest.main()
