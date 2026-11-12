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

    def test_github_contents_get_reads_full_encrypted_profile_even_above_128k(self):
        # No network: exercise only the GitHub Contents envelope size boundary.
        import base64, io, os
        from unittest.mock import patch
        key=hashlib.sha256(b'fixture-key-for-big-blob').digest()
        raw=bytes(range(256))*900
        ciphertext=m._pack(raw,key,m._id(key,'4002'),NOW.isoformat())
        response=json.dumps({'content':base64.b64encode(ciphertext).decode()}).encode()
        self.assertGreater(len(response),128*1024)
        class Fake(io.BytesIO):
            status=200
        with patch.dict(os.environ,{'GH_TOKEN':'fake-unit-only-not-a-token'}), \
             patch('urllib.request.urlopen',side_effect=lambda *a,**k:Fake(response)):
            restored=m._github(m.PREFIX+m.DAY+'/testonly.enc')
        self.assertEqual(restored,ciphertext)
        self.assertEqual(m._unpack(restored,key,m._id(key,'4002'))[0],raw)
        with patch.dict(os.environ,{'GH_TOKEN':'fake-unit-only-not-a-token'}), \
             patch('urllib.request.urlopen',side_effect=lambda *a,**k:Fake(b'x'*1_200_001)):
            with self.assertRaisesRegex(ValueError,'GITHUB_RESPONSE_BOUND'):
                m._github(m.PREFIX+m.DAY+'/testonly.enc')

    def test_current_independent_readback_accepts_new_SHA_without_historical_claim(self):
        raw=basic()
        key=hashlib.sha256(b'fixture-current-verified-source').digest()
        expected=dict(candidate(raw),historical_sha256='f'*64)
        tag=m._id(key,'4002')
        base=m.PREFIX+m.DAY+'/'+tag
        reservation=m._wire(dict(schema=m.SCHEMA,day=m.DAY,tag=tag,
            max_official_profile_gets=1,requested_source_kind='OFFICIAL_PROFILE',
            authorized_by='OWNER_ONE_SHOT',state='RESERVED'))+b'\n'
        captured=m._pack(raw,key,tag,NOW.isoformat())
        blobs={base+'.reservation.json':reservation,base+'.enc':captured}
        calls=[]
        def github(path,*,body=None):
            self.assertIsNone(body,'readback must never write a reservation')
            calls.append(path)
            return blobs[path]
        with patch.object(m,'_select',return_value=expected):
            result=m.execute('.',readback_current=True,key=key,now=NOW,
                             github=github,get_source=lambda url:self.fail('no GET'))
            self.assertEqual(result['status'],'PROFILE_CURRENT_OFFICIAL_HTML_READBACK_VERIFIED')
            self.assertEqual(result['authenticated_current_profile'],1)
            self.assertFalse(result['historical_source_sha_matched'])
            self.assertEqual(result['official_profile_gets'],0)
            self.assertFalse(result['display_name_auto_published'])
            self.assertEqual(len(calls),2)
            with self.assertRaisesRegex(ValueError,'HISTORICAL_HTML_SHA_MISMATCH'):
                m.execute('.',readback=True,key=key,now=NOW,github=github,
                          get_source=lambda url:self.fail('strict old SHA must not GET'))
            bad=json.loads(reservation)
            bad['max_official_profile_gets']=2
            blobs[base+'.reservation.json']=m._wire(bad)
            with self.assertRaisesRegex(ValueError,'CAPTURE_RESERVATION_NOT_VALID'):
                m.execute('.',readback_current=True,key=key,now=NOW,github=github,
                          get_source=lambda url:self.fail('reservation invalid must not GET'))
            blobs[base+'.reservation.json']=reservation
            bad=bytearray(captured);bad[-40]^=1
            blobs[base+'.enc']=bytes(bad)
            with self.assertRaises(ValueError):
                m.execute('.',readback_current=True,key=key,now=NOW,github=github,
                          get_source=lambda url:self.fail('cipher invalid must not GET'))
            blobs[base+'.enc']=captured
            with patch.object(m,'parse_basic_profile',side_effect=ValueError('current profile changed')):
                with self.assertRaises(ValueError):
                    m.execute('.',readback_current=True,key=key,now=NOW,
                              github=github,get_source=lambda url:self.fail('no GET'))

    def test_source_absent_or_already_named_never_calls_provider(self):
        key=hashlib.sha256(b'fixture-key4').digest()
        with patch.object(m,'_select',return_value=None):
            result=m.execute('.',now=NOW,key=key,github=lambda *a,**k:
                             self.fail('no state write'),get_source=lambda *a:
                             self.fail('no GET'))
        self.assertEqual(result['official_profile_gets'],0)
        self.assertEqual(result['status'],'ALREADY_NAMED')

if __name__=='__main__':unittest.main()
