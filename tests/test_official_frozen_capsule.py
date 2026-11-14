"""Synthetic keys/originals through actual AES and legacy recovery readers."""
from copy import deepcopy
from hashlib import sha256
import unittest

from race_ai.actions_contract import digest
from race_ai.boat_all_model_store import open_forecasts,seal_forecasts
from tests.test_all_existing_model_official_recovery import fixture,KEY,NOW


def binding(target):
    return dict(schema='RACE_AI_OFFICIAL_FROZEN_SOURCE_BINDING_V1',tested_execution_head_sha=target['head_sha'],
        intent_head_sha='c'*40,intent_parent_sha='d'*40,target=deepcopy(target),issue_request_blob_sha256='e'*64,
        recovery_request_blob_sha256='f'*64,protected_files_sha256='a'*64)


class FrozenCapsuleTests(unittest.TestCase):
    def api(self):
        from race_ai import all_existing_model_official_recovery as legacy
        import importlib.util
        name='race_ai.all_existing_model_official_frozen_capsule'
        self.assertIsNotNone(importlib.util.find_spec(name),'frozen capsule wrapper missing')
        from race_ai import all_existing_model_official_frozen_capsule as api
        return api,legacy

    def test_typed_outer_preserves_exact_inner_and_legacy_authority(self):
        api,legacy=self.api();data,_,_=fixture();inner=legacy.issue_consume_capsule(data,KEY);scope=binding(data['target'])
        outer=api.wrap_capsule(inner,scope,key=KEY)
        self.assertNotEqual(inner,outer)
        self.assertEqual(api.unwrap_capsule(outer,expected_binding=scope,key=KEY),inner)
        current=dict(data['first_attempt'],run_attempt=2,status='in_progress',conclusion=None)
        auth=legacy.validate_capsule(api.unwrap_capsule(outer,expected_binding=scope,key=KEY),request=data['request'],
            current_run=current,first_attempt=data['first_attempt'],old_run=data['old_run'],now=NOW,key=KEY,
            prior_runs=data.get('prior_runs',()))
        self.assertEqual(auth.audit()['request_sha256'],digest(data['request']))
        self.assertEqual(api.archival_inner(outer,request=data['request'],target=data['target'],key=KEY),inner)
        self.assertEqual(api.archival_inner(inner,request=data['request'],target=data['target'],key=KEY),inner)

    def test_wrong_current_intent_hash_target_or_inner_never_falls_back(self):
        api,legacy=self.api();data,_,_=fixture();inner=legacy.issue_consume_capsule(data,KEY);scope=binding(data['target'])
        outer=api.wrap_capsule(inner,scope,key=KEY)
        for field in ('intent_head_sha','intent_parent_sha','protected_files_sha256','recovery_request_blob_sha256'):
            changed=deepcopy(scope);changed[field]='9'*len(changed[field])
            with self.subTest(field=field),self.assertRaises(ValueError):api.unwrap_capsule(outer,expected_binding=changed,key=KEY)
        with self.assertRaises(ValueError):api.unwrap_capsule(inner,expected_binding=scope,key=KEY)
        with self.assertRaises(ValueError):api.unwrap_capsule(outer,expected_binding=scope,key=b'x'*32)
        value=open_forecasts(outer,key=KEY);value['inner_sha256']='0'*64
        altered=seal_forecasts(value,run_id=str(data['target']['run_id']),round_no=api.ROUND,key=KEY)
        with self.assertRaises(ValueError):api.unwrap_capsule(altered,expected_binding=scope,key=KEY)
        wrong=deepcopy(scope);wrong['target']['run_id']+=1
        with self.assertRaises(ValueError):api.wrap_capsule(inner,wrong,key=KEY)

    def test_archival_is_not_current_execution_and_rejects_scope_substitution(self):
        api,legacy=self.api();data,_,_=fixture();inner=legacy.issue_consume_capsule(data,KEY);scope=binding(data['target'])
        outer=api.wrap_capsule(inner,scope,key=KEY)
        # No mutable current-PR or present expiry is consulted in this transport
        # decoder. The caller's existing archival MAC reader verifies old grant.
        self.assertEqual(sha256(api.archival_inner(outer,request=data['request'],target=data['target'],key=KEY)).digest(),
                         sha256(inner).digest())
        wrong=deepcopy(data['request']);wrong['probe_sport']='keirin'
        with self.assertRaises(ValueError):api.archival_inner(outer,request=wrong,target=data['target'],key=KEY)
        probe=getattr(api,'archival_probe_inner',None)
        self.assertTrue(callable(probe),'hash-bound prior-probe decoder missing')
        self.assertEqual(probe(outer,request_sha256=digest(data['request']),target=data['target'],key=KEY),inner)
        with self.assertRaises(ValueError):probe(outer,request_sha256='9'*64,target=data['target'],key=KEY)
        for change in (dict(extra=True),dict(schema='unknown'),dict(target=dict(scope['target'],run_attempt=True))):
            with self.subTest(change=change),self.assertRaises(ValueError):api.wrap_capsule(inner,dict(scope,**change),key=KEY)


if __name__=='__main__':unittest.main()
