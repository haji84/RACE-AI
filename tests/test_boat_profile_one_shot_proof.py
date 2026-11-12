"""One allowed original official HTML request and independent AES readback tests."""
import hashlib
import json
import unittest
from unittest.mock import patch
from datetime import datetime,timezone
from race_ai.boat_pdca_state import PUBLIC_FIXTURE_KEY
from scripts import boat_profile_one_shot_proof as m
from tests.test_racer_profiles import basic

NOW=datetime(2026,11,12,8,25,tzinfo=timezone.utc)

def candidate(raw):
    return dict(registration='4002',name='架空選手二',
                url='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=4002',
                historical_sha256=hashlib.sha256(raw).hexdigest())

class OneOfficialProfileProof(unittest.TestCase):
    def test_immutable_source_sha_registration_and_name_are_required(self):
        raw=basic()
        self.assertTrue(m._proof(raw,candidate(raw)))
        for change in ('reg','name','sha','url'):
            item=candidate(raw)
            if change=='reg':item['registration']='4999'
            if change=='name':item['name']='別人'
            if change=='sha':item['historical_sha256']='a'*64
            if change=='url':item['url']='https://example.invalid/foreign'
            with self.subTest(change=change),self.assertRaises(ValueError):
                m._proof(raw,item)

    def test_encrypted_original_is_source_bound_and_tamper_detecting(self):
        key=hashlib.sha256(b'fixture-not-for-real-profile-data').digest()
        raw=basic()
        tag=m._id(key,'4002')
        secret=m._pack(raw,key,tag,NOW.isoformat())
        self.assertNotIn(raw,secret)
        self.assertNotIn(b'4002',secret)
        actual,header=m._unpack(secret,key,tag)
        self.assertEqual(actual,raw)
        self.assertEqual(header['source_bytes_sha256'],hashlib.sha256(raw).hexdigest())
        with self.assertRaises(ValueError):
            m._unpack(secret,key,m._id(key,'4003'))
        altered=json.loads(secret);altered['header']['day']='2026-11-11'
        with self.assertRaises(ValueError):
            m._unpack(m._wire(altered),key,tag)

    def test_exactly_one_GET_happens_after_atomic_durable_reservation(self):
        raw=basic()
        key=hashlib.sha256(b'fixture-key2').digest()
        writes={};events=[]
        def github(path,*,body=None):
            if body is not None:
                if path in writes:raise ValueError('BOAT_PROFILE_STATE_EXISTS_OR_UNAVAILABLE')
                writes[path]=body
                events.append('RESERVE' if path.endswith('.reservation.json') else 'SAVE_AES')
                return {'committed':True}
            return writes[path]
        def fetch(url):
            events.append('GET')
            self.assertTrue(url.endswith('toban=4002'))
            return raw
        with patch.object(m,'_select',return_value=candidate(raw)):
            outcome=m.execute('.',now=NOW,key=key,get_source=fetch,github=github)
            self.assertEqual(outcome['status'],'PROFILE_ORIGINAL_RAW_HASH_VERIFIED')
            self.assertEqual(outcome['official_profile_gets'],1)
            self.assertEqual(events,['RESERVE','GET','SAVE_AES'])
            self.assertEqual(len(writes),2)
            check=m.execute('.',readback=True,now=NOW,key=key,get_source=lambda url:
                            self.fail('readback must never GET'),github=github)
            self.assertEqual(check['status'],'PROFILE_ORIGINAL_INDEPENDENT_READBACK_VERIFIED')
            self.assertEqual(check['official_profile_gets'],0)
            with self.assertRaises(ValueError):
                m.execute('.',now=NOW,key=key,get_source=lambda url:
                          self.fail('rerun must not consume a second GET'),github=github)
        self.assertEqual(events.count('GET'),1)

    def test_wrong_original_sha_consummates_reservation_but_never_publishes(self):
        key=hashlib.sha256(b'fixture-key3').digest()
        raw=basic()
        bad=dict(candidate(raw),historical_sha256='f'*64)
        writes={};events=[]
        def github(path,*,body=None):
            if body is not None:
                if path in writes:raise ValueError('BOAT_PROFILE_STATE_EXISTS_OR_UNAVAILABLE')
                writes[path]=body
                events.append('RESERVE' if path.endswith('.reservation.json') else 'SAVE_AES')
                return {'committed':True}
            return writes[path]
        def source(url):
            events.append('GET');return raw
        with patch.object(m,'_select',return_value=bad):
            with self.assertRaisesRegex(ValueError,'HISTORICAL_HTML_SHA_MISMATCH'):
                m.execute('.',now=NOW,key=key,github=github,get_source=source)
            self.assertEqual(events,['RESERVE','GET','SAVE_AES'])
            # Even a changed observed page is private and recoverable for
            # future investigation; historical identity is NOT certified.
            tag=m._id(key,'4002')
            raw_back,header=m._unpack(writes[m.PREFIX+m.DAY+'/'+tag+'.enc'],key,tag)
            self.assertEqual(raw_back,raw)
            self.assertEqual(header['source_bytes_sha256'],hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError,'HISTORICAL_HTML_SHA_MISMATCH'):
                m.execute('.',readback=True,now=NOW,key=key,github=github,
                          get_source=lambda url:self.fail('readback must never GET'))
            with self.assertRaises(ValueError):
                m.execute('.',now=NOW,key=key,github=github,get_source=source)
        self.assertEqual(events.count('GET'),1)

    def test_source_absent_or_already_named_never_calls_provider(self):
        key=hashlib.sha256(b'fixture-key4').digest()
        with patch.object(m,'_select',return_value=None):
            result=m.execute('.',now=NOW,key=key,github=lambda *a,**k:
                             self.fail('no state write'),get_source=lambda *a:
                             self.fail('no GET'))
        self.assertEqual(result['official_profile_gets'],0)
        self.assertEqual(result['status'],'ALREADY_NAMED')

if __name__=='__main__':unittest.main()
