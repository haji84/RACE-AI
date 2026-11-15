"""Source-free real AES fixtures for historical failed-owner checkpoint audits."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'owner-source'))
import race_ai
for folder in ('pr64-reference','pr72-reference'):
    race_ai.__path__.append(str(ROOT/'owner-source'/folder/'race_ai'))
from race_ai import boat_private_original_archive as archive
from race_ai import boat_source_control as control
spec=importlib.util.spec_from_file_location('main_failed_checkpoint_audit',
                                          ROOT/'scripts/boat_owner_evidence_audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
KEY=bytes(range(32))
HEAD='5d1dabff0ab9bb83132cd7fbdd43f49fb4eef6c4'
NOW=datetime(2030,4,2,4,tzinfo=timezone.utc)


def zipped(name,raw):
    target=io.BytesIO()
    with zipfile.ZipFile(target,'w') as z:z.writestr(name,raw)
    return target.getvalue()


class FailedCheckpointAuditTests(unittest.TestCase):
    def fixture(self,**changes):
        session=dict(schema='RACE_AI_CONTINUOUS_REPEAT_V2',run_id=7,day_jst='2030-04-01',
            requests_used=0,completed_round=0,prepared_round=None,
            lifetime_requests_base=11524,lifetime_requests=11524,
            lifetime_completed_rounds_base=608,lifetime_completed_rounds=608,
            day_start_lifetime_requests=11072,source_wait=None,halted_reason=None,
            private_rows='PRIVATE_FORECAST_DO_NOT_EXPORT')
        session.update(changes)
        session['session_sha256']=sha256(json.dumps(session,sort_keys=True,
            separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        inner=zipped('repeat-session.json',json.dumps(session).encode())
        cipher=archive.seal_original_zip(inner,run_id=7,head_sha=HEAD,kind='CONTINUITY',key=KEY)
        self.summary=control.build_summary(cipher,run_id=7,head_sha=HEAD,key=KEY)
        self.run=dict(id=7,head_sha=HEAD,workflow_id=405276784,
            head_branch='production/boat-p0-p1-20261111',event='workflow_dispatch',
            status='completed',conclusion='failure',run_attempt=1,
            created_at='2030-04-01T02:00:00Z',updated_at='2030-04-01T02:02:00Z',
            repository=dict(id=1416489937,full_name='haji84/RACE-AI'),
            head_repository=dict(id=1416489937,full_name='haji84/RACE-AI'))
        self.packets={70:zipped('private-original.enc',cipher)}
        self.metadata={}
        for ident,prefix,created in ((70,'race-cycle-continuity','2030-04-01T02:01:00Z'),
                                     (71,'race-source-control','2030-04-01T02:01:01Z')):
            self.metadata[ident]=dict(id=ident,name=f'{prefix}-7',expired=False,
                created_at=created,expires_at='2030-05-01T02:00:00Z',
                workflow_run=dict(id=7,head_sha=HEAD,repository_id=1416489937,
                                  head_repository_id=1416489937))
        self.listed=list(self.metadata.values());self.calls=[]

    def read(self,*,key=KEY,now=NOW):
        self.packets[71]=zipped('source-control.json',json.dumps(self.summary).encode())
        for ident,raw in self.packets.items():
            self.metadata[ident].update(size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest())
        data={'actions/runs/7':json.dumps(self.run).encode(),
              'actions/runs/7/artifacts?per_page=100':json.dumps(
                  dict(total_count=len(self.listed),artifacts=self.listed)).encode()}
        for ident,raw in self.packets.items():
            data[f'actions/artifacts/{ident}']=json.dumps(self.metadata[ident]).encode()
            data[f'actions/artifacts/{ident}/zip']=raw
        def get(path):
            self.calls.append(path)
            return data[path]
        return audit.inspect_failed_checkpoint(get=get,run_id=7,now=now,key=key)

    def test_actual_aes_and_public_counters_match_without_granting_current_dispatch(self):
        self.fixture();before=deepcopy(self.summary)
        out=self.read()
        self.assertEqual(out['status'],'FAILED_OWNER_CHECKPOINT_AES_VERIFIED_READONLY')
        self.assertEqual(out['failed_session_requests'],0)
        self.assertEqual(out['inherited_same_day_requests'],452)
        self.assertEqual(out['lifetime_requests'],11524)
        self.assertEqual(out['lifetime_completed_rounds'],608)
        self.assertEqual(out['day_jst'],'2030-04-01')
        self.assertEqual(out['audit_at'],NOW.isoformat())
        self.assertFalse(out['successor_dispatch_allowed'])
        self.assertFalse(out['live_recovery_to_new_p1_proven'])
        self.assertNotIn('PRIVATE_',json.dumps(out))
        self.assertEqual(self.summary,before)
        self.assertEqual(out['official_source_requests'],0)
        self.assertEqual(out['new_forecasts'],0)

    def test_wrong_key_rejects_instead_of_trusting_opaque_cipher_binding(self):
        self.fixture()
        with self.assertRaises(ValueError):self.read(key=b'x'*32)

    def test_changed_public_counter_rejects_even_when_zip_digest_is_correct(self):
        self.fixture();self.summary['control']['lifetime_requests']+=1
        with self.assertRaises(ValueError):self.read()

    def test_pending_round_or_source_hold_cannot_be_called_zero_round(self):
        for change in (dict(prepared_round=1),dict(requests_used=1,lifetime_requests=11525),
                       dict(halted_reason='SOURCE_HTTP_403_NO_RETRY')):
            with self.subTest(change=change):
                self.fixture(**change)
                with self.assertRaises(ValueError):self.read()

    def test_p1_or_result_inventory_rejects_zero_round_claim(self):
        for name in ('boat-national-cutoff-7-cycle-01','race-existing-cycle-7-cycle-01'):
            self.fixture();self.listed.append(dict(id=72,name=name))
            with self.subTest(name=name),self.assertRaises(ValueError):self.read()

    def test_wrong_run_head_and_expired_or_future_checkpoint_reject(self):
        for change in ('wrong-run-head','wrong-receipt-head','expired','future-clock'):
            self.fixture()
            if change=='wrong-run-head':self.run['head_sha']='f'*40
            elif change=='wrong-receipt-head':self.metadata[70]['workflow_run']['head_sha']='f'*40
            elif change=='expired':self.metadata[70]['expired']=True
            else:self.metadata[70]['created_at']='2030-04-03T01:00:00Z'
            with self.subTest(change=change),self.assertRaises(ValueError):self.read()


if __name__=='__main__':unittest.main()
