"""Synthetic transport inputs only; no source URLs or original media are acquired."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib, importlib, json, unittest
from unittest.mock import patch
from web.race_contract import canonical
from race_ai.core import SourceError
from race_ai.exhibition_video_decode import select_variant, parse_vod
from tests.test_exhibition_video_decode import master, child, synthetic_ts
from tests.test_exhibition_video_source import MEDIA, SOURCE, NOW, program, run
from race_ai.exhibition_video_source import SourceResponse

NS='c'*32
NS_HASH=hashlib.sha256(NS.encode()).hexdigest()
KEY=f'https://d28jce9iiridbn.cloudfront.net/{NS}/11111111-2222-3333-4444-555555555555'
SEG=f'https://j-live-cp-boatrace-prod.streaks.jp/{MEDIA}/{SOURCE}/manifest_2_17.ts'
def scope():return dict(schema_version='normal-player-cdn/v1',date_jst='2026-10-15',venue_code='14',observed_target='20261015-14-04',observed_at=NOW,evidence_sha256='d'*64,opaque_key_namespace_sha256=NS_HASH,namespace_hash_preimage='RAW_HEX32_ASCII_CASE_SENSITIVE',permission_basis='OWNER_20261017_SEPARATE_STRICT_NORMAL_PLAYER_CONTRACT',transport_only=True)
def vod(query='?m=1234567890',key=KEY):
 return child(True).replace(f'https://key.streaks.jp/{MEDIA}/{SOURCE}/11111111-2222-3333-4444-555555555555',key).replace('live-cp-boatrace-prod.streaks.jp','j-live-cp-boatrace-prod.streaks.jp').replace('.ts\n','.ts'+query+'\n').encode()
class CdnTests(unittest.TestCase):
 def setUp(self):
  m=self.module();p=patch.object(m,'REGISTERED_SCOPE_SHA256',hashlib.sha256(canonical(scope())).hexdigest());p.start();self.addCleanup(p.stop)
 def module(self):
  try:return importlib.import_module('race_ai.exhibition_video_cdn_contract')
  except ModuleNotFoundError:self.fail('separate normal-player CDN contract missing')
 def parse(self,raw=None,sha=NS_HASH):return self.module().parse_normal_player_vod(vod() if raw is None else raw,MEDIA,SOURCE,select_variant(master().encode(),MEDIA,SOURCE),key_namespace_sha256=sha)
 def test_separate_grammar_accepts_bound_j_cdn_and_scope_hash(self):
  s=self.parse();self.assertEqual(len(s),1);self.assertEqual(s[0].sequence,17);self.assertEqual(s[0].duration,2);self.assertEqual(len(s[0].iv),16);self.assertNotIn('https:',repr(s))
 def test_default_parser_still_rejects_new_cdn(self):
  with self.assertRaises(SourceError):parse_vod(vod(),MEDIA,SOURCE,select_variant(master().encode(),MEDIA,SOURCE))
  self.assertEqual(len(self.parse(child(True).encode())),1)
 def test_namespace_hash_is_required_exact_type_and_match(self):
  for sha in [None,True,'bad','d'*64,NS_HASH.upper()]:
   with self.subTest(sha=sha),self.assertRaises(SourceError):self.parse(sha=sha)
 def test_query_empty_or_exact_decimal10_and_no_mixing(self):
  self.assertEqual(len(self.parse(vod(''))),1)
  self.assertEqual(len(self.parse(vod('?m=0123456789'))),1)
  for q in ['?','?m=123456789','?m=12345678901','?m=%31'+'2'*9,'?m=1234567890&m=1234567890','?M=1234567890','?m=1234567890&x=1','?m=','?x=1234567890']:
   with self.subTest(q=q),self.assertRaises(SourceError):self.parse(vod(q))
  for q in ['', '?m=1234567891']:
   two=vod().decode().replace('#EXT-X-ENDLIST',f'#EXTINF:2.0,\n{SEG.replace("_17.ts","_18.ts")}{q}\n#EXT-X-ENDLIST')
   with self.subTest(q=q),self.assertRaises(SourceError):self.parse(two.encode())
 def test_each_new_key_scope_predicate_rejects(self):
  for key in [KEY.replace('https:','http:'),KEY.replace('d28jce9iiridbn.cloudfront.net','evil.example'),KEY.replace('https://','https://u:p@'),KEY.replace('.net/','.net:443/'),KEY+'#x',KEY+'?x=1',KEY.replace(NS,'e'*32),KEY.replace('11111111-2222','not-a-uuid'),KEY+'/']:
   with self.subTest(key=key),self.assertRaises(SourceError):self.parse(vod(key=key))
 def test_segment_origin_identity_variant_sequence_and_fragment(self):
  for raw in [vod().replace(b'j-live-cp-boatrace-prod.streaks.jp',b'evil.example'),vod().replace(SOURCE.encode(),b'e'*32),vod().replace(b'manifest_2_17',b'manifest_3_17'),vod().replace(b'manifest_2_17',b'manifest_2_18'),vod().replace(b'.ts?',b'.ts#fragment?'),vod().replace(b'https://j-live',b'https://u@j-live')]:
   with self.subTest(raw=raw[:20]),self.assertRaises(SourceError):self.parse(raw)
 def test_mixed_origin_and_unknown_uri_tags_not_adopted(self):
  raw=vod().decode().replace('#EXT-X-ENDLIST',f'#EXTINF:2.0,\nhttps://live-cp-boatrace-prod.streaks.jp/{MEDIA}/{SOURCE}/manifest_2_18.ts\n#EXT-X-ENDLIST')
  with self.assertRaises(SourceError):self.parse(raw.encode())
  with self.assertRaises(SourceError):self.parse(vod().replace(b'#EXTINF:',b'#EXT-X-UNKNOWN:URI="https://evil.example/secret"\n#EXTINF:'))
 def test_drm_iv_duration_completeness_and_resource_bounds_preserved(self):
  bads=[vod().replace(b'AES-128',b'SAMPLE-AES'),vod().replace(b'KEYFORMATVERSIONS="1"',b'KEYFORMAT="com.widevine"'),vod().replace(b'0x00000000000000000000000000000001',b'0x0'),vod().replace(b'2.0,',b'nan,'),vod().replace(b'#EXT-X-ENDLIST',b''),vod().replace(b'#EXTINF:',b'#EXT-X-BYTERANGE:10@0\n#EXTINF:')]
  for raw in bads:
   with self.subTest(raw=raw[:20]),self.assertRaises(SourceError):self.parse(raw)
 def test_scope_current_day_venue_freshness_and_detachment(self):
  m=self.module();s=scope();now=datetime.fromisoformat(NOW);v=m.validate_normal_player_scope(s,program(),now);s['opaque_key_namespace_sha256']='e'*64;self.assertEqual(v['opaque_key_namespace_sha256'],NS_HASH)
  for field,value in [('date_jst','2026-10-14'),('venue_code','24'),('observed_at',(now+timedelta(seconds=1)).isoformat()),('observed_at',(now-timedelta(hours=6,seconds=1)).isoformat()),('evidence_sha256','bad'),('opaque_key_namespace_sha256',True),('schema_version','other')]:
   with self.subTest(field=field,value=value),self.assertRaises(SourceError):m.validate_normal_player_scope({**scope(),field:value},program(),now)
  with self.assertRaises(SourceError):m.validate_normal_player_scope({**scope(),'extra':'secret'},program(),now)
  with self.assertRaises(SourceError):m.validate_normal_player_scope({**scope(),'opaque_key_namespace_sha256':'e'*64,'evidence_sha256':'f'*64},program(),now)
  # Clock/target checks must also work for a correctly registered synthetic scope.
  for field,value in [('observed_at',(now+timedelta(seconds=1)).isoformat()),('observed_at',(now-timedelta(hours=6,seconds=1)).isoformat()),('date_jst','2026-10-14'),('venue_code','24')]:
   altered={**scope(),field:value}
   with patch.object(m,'REGISTERED_SCOPE_SHA256',hashlib.sha256(canonical(altered)).hexdigest()),self.assertRaises(SourceError):m.validate_normal_player_scope(altered,program(),now)
 def test_opt_in_decode_preserves_false_features_and_hides_query_values(self):
  self.module()
  from race_ai.exhibition_video_decode import analyze_exhibition
  from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
  from cryptography.hazmat.primitives.padding import PKCS7
  raw=synthetic_ts();key=b'0123456789abcdef';pad=PKCS7(128).padder();raw=pad.update(raw)+pad.finalize();cipher=Cipher(algorithms.AES(key),modes.CBC(bytes.fromhex('00'*15+'01'))).encryptor();encoded=cipher.update(raw)+cipher.finalize();descriptor,lease=run();calls=[];s=scope()
  def fetch(url,**kw):
   calls.append(url);s['opaque_key_namespace_sha256']='e'*64
   if 'manifest.streaks.jp/' in url:body,mime=master().encode(),'application/x-mpegURL'
   elif 'variants.streaks.jp/' in url:body,mime=vod(),'application/x-mpegURL'
   elif 'cloudfront.net/' in url:body,mime=key,'application/octet-stream'
   else:body,mime=encoded,'video/mp2t'
   return SourceResponse(200,url,mime,body)
  result=analyze_exhibition(descriptor,lease,program(),fetch=fetch,clock=lambda:datetime.fromisoformat(NOW),normal_player_cdn_scope=s,sample_interval=.5)
  self.assertEqual(len(calls),4);self.assertEqual(result['analysis_version'],'transient-hls-normal-player-cdn/v6');self.assertGreater(result['frames_decoded'],0);self.assertFalse(result['prediction_eligible']);self.assertEqual(result['boat_features'],[]);self.assertFalse(result['transport_contract']['namespace_owner_authenticated']);self.assertNotIn('1234567890',json.dumps(result));self.assertNotIn('https:',json.dumps(result))
 def test_bad_scope_rejects_before_any_get(self):
  self.module();from race_ai.exhibition_video_decode import analyze_exhibition
  descriptor,lease=run();calls=[]
  with self.assertRaises(SourceError):analyze_exhibition(descriptor,lease,program(),fetch=lambda *a,**k:calls.append(a),clock=lambda:datetime.fromisoformat(NOW),normal_player_cdn_scope={**scope(),'venue_code':'24'})
  self.assertEqual(calls,[])
 def test_initial_and_pre_get_clock_regression_reject_before_fetch(self):
  from race_ai.exhibition_video_decode import analyze_exhibition
  now=datetime.fromisoformat(NOW);older=now-timedelta(microseconds=1)
  for times in [[now,older],[now+timedelta(seconds=1),now],[now,now+timedelta(seconds=1),now]]:
   descriptor,lease=run();calls=[];values=iter(times)
   with self.subTest(times=times),self.assertRaises(SourceError):
    analyze_exhibition(descriptor,lease,program(),fetch=lambda *a,**k:calls.append(a),clock=lambda:next(values),normal_player_cdn_scope=scope())
   self.assertEqual(calls,[])
 def test_post_get_clock_regression_prevents_next_resource(self):
  from race_ai.exhibition_video_decode import analyze_exhibition
  now=datetime.fromisoformat(NOW);values=iter([now,now,now+timedelta(seconds=1),now]);calls=[];descriptor,lease=run()
  def fetch(url,**kw):
   calls.append(url);return SourceResponse(200,url,'application/x-mpegURL',master().encode())
  with self.assertRaises(SourceError):analyze_exhibition(descriptor,lease,program(),fetch=fetch,clock=lambda:next(values),normal_player_cdn_scope=scope())
  self.assertEqual(len(calls),1)
