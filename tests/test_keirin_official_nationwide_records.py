"""New dynamic records retain the existing model and encrypted original format."""
from copy import deepcopy
from hashlib import sha256
from datetime import datetime
from io import BytesIO
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_form_fall_shadow as shadow
from tests.test_keirin_official_nationwide_extension import NationwideExtensionTests
from tests.test_keirin_official_canary_join import fixture


class NationwideRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
        cls.private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        cls.public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        cls.pin=sha256(key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        pin=patch.object(storage,'PINNED_OWNER_SPKI_SHA256',self.pin);pin.start();self.addCleanup(pin.stop)

    def api(self): return importlib.import_module('race_ai.keirin_official_nationwide_records')

    def payload(self, folder, conditioned=True):
        from race_ai import keirin_official_nationwide_extension as ext
        from race_ai.keirin_official_nationwide_sources import build_condition_candidate
        args=NationwideExtensionTests().baseline_arguments();at=args.pop('now')
        snapshot=ext.build_baseline_candidate(**args,now=at)['snapshot']
        baseline=model.generate_A_B(snapshot,generated_at=at.isoformat())
        root=Path(folder);root.chmod(0o700)
        base_path=root/'original.sealed.json'
        base=storage.seal_once(snapshot=snapshot,prediction=baseline,public_key_pem=self.public,path=base_path,sealed_at=at.isoformat())
        registry=NationwideExtensionTests().registry();rid=snapshot['race_id'];registry['registered_race_ids']=[rid]
        cohort=self.api().cohort(registry)
        payload=dict(schema=self.api().PRE_SCHEMA,day_jst=registry['event_day'],race_id=rid,
            producer_run_id='123456789',producer_commit='a'*40,cohort=cohort,cohort_sha256=model.digest(cohort),
            snapshot=snapshot,baseline=baseline,baseline_sealed_at=at.isoformat(),
            baseline_cipher_sha256=base['cipher_sha256'],baseline_arguments=args,
            conditioned=None,supplement=None,conditioned_cipher_sha256=None,conditioned_sealed_at=None,
            history_manifest=None,source_bytes_by_sha={},identity_proof=None,availability=None,
            condition_state='NO_CONDITIONED_ORIGINAL')
        raw_conditioned=None
        if conditioned:
            captured=fixture()
            joined=build_condition_candidate(snapshot=snapshot,card_arguments=args['card_arguments'],
                prediction_source=args['prediction_source'],prediction_scripts=args['prediction_scripts'],
                history_manifest=captured['history_manifest'],source_bytes_by_sha=captured['source_bytes_by_sha'],now=at)
            adjusted=shadow.generate_shadow(snapshot,joined['supplement'],baseline=baseline,generated_at=at.isoformat())
            path=root/'original.form.sealed.json'
            sealed=shadow.seal_shadow_once(snapshot=snapshot,supplement=joined['supplement'],shadow=adjusted,
                public_key_pem=self.public,path=path,sealed_at=at.isoformat())
            payload.update(conditioned=adjusted,supplement=joined['supplement'],
                conditioned_cipher_sha256=sealed['file_sha256'],conditioned_sealed_at=at.isoformat(),
                history_manifest=captured['history_manifest'],source_bytes_by_sha=captured['source_bytes_by_sha'],
                identity_proof=joined['identity_proof'],availability=joined['availability'],
                condition_state='CONDITIONED_ARCHIVED_AWAITING_READBACK')
            raw_conditioned=path.read_bytes()
        return payload,base_path.read_bytes(),raw_conditioned

    def test_dynamic_original_replay_authenticates_same_four_arms_and_real_input_shapes(self):
        with tempfile.TemporaryDirectory() as folder:
            payload,raw,conditioned=self.payload(folder)
            result=self.api().replay_original(payload=payload,raw_baseline=raw,raw_conditioned=conditioned,owner_private_pem=self.private)
            self.assertEqual(result['baseline'],payload['baseline'])
            self.assertEqual(result['conditioned'],payload['conditioned'])
            self.assertEqual(result['snapshot'],payload['snapshot'])

    def test_missing_or_corrupt_condition_does_not_remove_authenticated_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            payload,raw,conditioned=self.payload(folder)
            for value in (None,b'corrupt'):
                result=self.api().replay_original(payload=payload,raw_baseline=raw,raw_conditioned=value,owner_private_pem=self.private)
                self.assertEqual(result['baseline'],payload['baseline'])
                self.assertIsNone(result['conditioned'])
                self.assertEqual(result['condition_state'],'CONDITIONED_ARCHIVE_UNVERIFIED')

    def test_source_change_or_wrong_key_cannot_admit_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            payload,raw,conditioned=self.payload(folder,False)
            bad=deepcopy(payload);bad['baseline_arguments']['profile_sources'][0]['raw_bytes']+=b'changed'
            with self.assertRaises(ValueError): self.api().replay_original(payload=bad,raw_baseline=raw,raw_conditioned=None,owner_private_pem=self.private)
            with self.assertRaises(ValueError): self.api().replay_original(payload=payload,raw_baseline=raw,raw_conditioned=None,owner_private_pem=b'invalid')

    def test_reindexed_result_cipher_cannot_change_its_race_or_writer(self):
        from race_ai import keirin_official_run_history as history
        from race_ai import keirin_nationwide_cipher_history as archive
        api=self.api();day='2030-01-15';at=day+'T15:00:00+09:00'
        payload=dict(schema=api.RESULT_SCHEMA,day_jst=day,race_id='203001159801',
            producer_run_id='123456789',producer_commit='a'*40,safe_report={'day_jst':day})
        raw=history.seal_evidence(payload,self.public,day,at);envelope=history._checked_cipher(raw)
        meta=dict(kind='result',race_id='203001159802',producer_run_id='123456789',producer_commit='a'*40,
            evidence_sha256=envelope['evidence_plaintext_sha256'],cipher_sha256=sha256(raw).hexdigest(),observed_at=at)
        store=object.__new__(api.RecordStore);store.repo='/synthetic';store.head='a'*40;store.day=day
        with patch.object(archive,'read_blob_bytes',return_value=raw):
            with self.assertRaises(ValueError):store.read(meta,self.private)
            meta.update(race_id=payload['race_id'],producer_run_id='999999999')
            with self.assertRaises(ValueError):store.read(meta,self.private)

    def test_local_git_atomic_encrypted_index_readback_and_immutable_original(self):
        from tests.test_keirin_official_run_history import git
        from race_ai import keirin_nationwide_cipher_history as archive
        api=self.api();day='2030-01-15';at=day+'T14:00:00+09:00';rid='203001159801'
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{
                'GITHUB_RUN_ID':'123456789','GITHUB_SHA':'a'*40}):
            root=Path(folder);origin=root/'origin.git';repo=root/'repo'
            git(root,'init','--bare','-b',archive.BRANCH,str(origin));git(root,'clone',str(origin),str(repo))
            git(repo,'config','user.name','Fixture');git(repo,'config','user.email','fixture@example.invalid')
            (repo/'README.md').write_text('synthetic existing archive\n');git(repo,'add','README.md')
            git(repo,'commit','-m','fixture');git(repo,'push','origin','HEAD:refs/heads/'+archive.BRANCH)
            payload=dict(schema=api.PRE_SCHEMA,day_jst=day,race_id=rid,
                producer_run_id='123456789',producer_commit='a'*40,
                baseline={'published_cutoff_at':day+'T15:00:00+09:00'},baseline_cipher_sha256='c'*64,
                private_source=b'PRIVATE_SOURCE_BYTES_NEVER_PUBLIC',safe_report={'day_jst':day})
            store=api.RecordStore(repo,day,synthetic_local=True)
            meta=store.append(kind='original',payload=payload,public_pem=self.public,observed_at=at,race_id=rid)
            independent=api.RecordStore(repo,day,synthetic_local=True)
            self.assertEqual(independent.read(meta,self.private),payload)
            before=git(origin,'rev-parse',archive.BRANCH)
            self.assertEqual(store.append(kind='original',payload=payload,public_pem=self.public,
                observed_at=at,race_id=rid),meta)
            self.assertEqual(git(origin,'rev-parse',archive.BRANCH),before)
            with self.assertRaisesRegex(ValueError,'IMMUTABLE_ORIGINAL_CHANGED'):
                store.append(kind='original',payload=dict(payload,private_source=b'changed'),
                    public_pem=self.public,observed_at=at,race_id=rid)
            self.assertEqual(git(origin,'rev-parse',archive.BRANCH),before)
            for path in git(repo,'ls-tree','-r','--name-only',store.head,'--',api.ROOT).splitlines():
                self.assertNotIn('PRIVATE_SOURCE_BYTES_NEVER_PUBLIC',git(repo,'show',store.head+':'+path))

    def comparison_fixture(self,folder):
        from tests.test_keirin_form_canary_origin import fixture as origin_fixture,replace_report
        from tests.test_keirin_official_sp_receipt import html
        from race_ai import keirin_official_reviewed_pdf as unit
        from race_ai import keirin_official_nationwide_sources as sources
        payload,raw,adjusted=self.payload(folder);payload['producer_run_id']='123456'
        original=self.api().replay_original(payload=payload,raw_baseline=raw,
            raw_conditioned=adjusted,owner_private_pem=self.private)
        producer,reader=origin_fixture()
        for packet,role,member in ((producer,'producer','summary.json'),(reader,'readback','keirin-git-independent.json')):
            for section in ('run','job','artifact'):
                for key,value in packet[section].items():
                    if type(value) is str:
                        packet[section][key]=value.replace('2026-11-20','2030-01-15').replace('T00:','T02:').replace('T01:','T03:')
            packet['run']['event']='schedule'
            packet['job']['name']='official-sp-capture' if role=='producer' else 'official-sp-independent-readback'
            packet['artifact']['name']=('keirin-official-sp-receipt-' if role=='producer' else 'keirin-official-sp-readback-')+'123456'
            with ZipFile(BytesIO(packet['archive_bytes'])) as z:report=json.loads(z.read(member))
            report['day_jst']=payload['day_jst']
            row=report['new_encrypted_originals' if role=='producer' else 'records'][0]
            row.update(race_id=payload['race_id'],cipher_sha256=payload['baseline_cipher_sha256'],
                conditioned_cipher_sha256=payload['conditioned_cipher_sha256'],
                baseline_prediction_sha256=payload['baseline']['prediction_sha256'],cohort_sha256=payload['cohort_sha256'])
            replace_report(packet,member,report)
        card=payload['baseline_arguments']['card_arguments']
        listing=sources.cards.receipt._embedded(sources.cards.browser_source._document(card['list_raw']))
        for group in listing['SJ0301']['kaisaiDayList']:
            for row in group['raceProgramList']:row['strRaceLnkKbn']='2'
        linked=''.join('<script src="'+path+'"></script>' for path in sources.LIST_SCRIPTS)
        list_raw=html(listing).replace(b'</body>',linked.encode()+b'</body>')
        observed='2030-01-15T13:01:00+09:00'
        listed=dict(venue_code=98,raw_bytes=list_raw,expected_sha256=sha256(list_raw).hexdigest(),
            observed_at=observed,http_status=200)
        cal=card['calendar_receipt']
        parsed=sources.cards.receipt.parse_race_list(list_raw,expected_day=payload['day_jst'],expected_venue_code=98,
            observed_at=datetime.fromisoformat(observed),expected_sha256=listed['expected_sha256'],
            calendar_receipt=dict(cal,observed_at=datetime.fromisoformat(cal['observed_at'])))
        ref=next(r for r in parsed['race_references'] if r['race_no']==1)
        starters=[dict(car=r['car'],registration_id=r['athlete_id']) for r in original['snapshot']['riders']]
        rows=[dict(syaban=str(r['car']),sensyuRegistNo=r['registration_id'],tyaku=str(r['car']),
            kojinStateItemSubData=[]) for r in starters]
        head=dict(txtEventDate='2030/01/15',selRaceNo=1,aftBetDate='203001151247',flgRaceCancel=False,flgKekkaRefund=False)
        final=dict(resultCd=0,tyakujyunDispFlg=True,haraiGakuDispFlg=True,bikouDispFlg=False,
            lastUpdateTime='2030/01/15 13:00&nbsp;更新',
            digestUrl='https://wm.st.keirin.jp/wm-keirin98/20300115-98-02-01-01-00.mp4',
            tyakujyunItemSubData=rows,haraiGakuSubData=dict(APartReturnDispFlg=False,
                RT3HaraiGakuDispItemSubData=[dict(kumiBan='1-2-3',haraiGaku='1,230',kumiDispFlg=True)]))
        raw_result=html(dict(SC0201=dict(resultCd=0,C0201data=head),SJ0326=final))
        url='https://www.hofukeirin.jp/ticket/';guide=unit.UNIT_URLS[url].encode();digest=sha256(guide).hexdigest()
        capture=dict(raw_result=raw_result,observed_at=observed,
            expected_reference=dict(source_url='https://keirin.jp/sp/race',method='POST',disp='SJ0326',
                token=ref['opaque_reference'],official_cutoff_at=original['baseline']['published_cutoff_at'],starters=starters),
            unit_evidence=dict(url=url,source_sha256=digest,observed_at='2030-01-15T13:01:01+09:00',
                verified_payout_basis_yen=100,exact_excerpt=unit.UNIT_URLS[url]),
            unit_verified_at='2030-01-15T13:01:02+09:00',payout_unit_state='VERIFIED',
            source_bytes_by_sha={digest:guide,sha256(raw_result).hexdigest():raw_result},calendar_receipt=cal,
            list_source=listed,list_scripts={path:''.join(parts).encode() for path,parts in sources.LIST_SCRIPTS.items()},
            safe_diagnostics=[])
        return original,payload,raw,adjusted,dict(producer=producer,readback=reader),capture

    def test_real_crypto_dynamic_server_proofs_and_result_bytes_reach_existing_four_arm_scorer(self):
        with tempfile.TemporaryDirectory() as folder:
            original,payload,raw,adjusted,packets,capture=self.comparison_fixture(folder)
            args=dict(original=original,payload=payload,raw_baseline=raw,raw_conditioned=adjusted,
                packets=packets,final_capture=capture)
            scored=self.api().compare_result(**args)
            self.assertEqual(scored['comparison']['paired_comparable_races'],1)
            self.assertEqual(set(scored['arms']),{'A','B','adjusted_A','adjusted_B'})
            doc=self.api().result_updates(original,scored,capture)
            self.assertEqual(doc['races'][0]['payout_status'],'confirmed')
            self.assertEqual(doc['races'][0]['arms']['C']['state'],'pending')
            changed=deepcopy(packets);changed['readback']['job']['completed_at']='2030-01-15T03:46:00Z'
            with self.assertRaises(ValueError):self.api().compare_result(**dict(args,packets=changed))
            baseline_only=dict(original,conditioned=None)
            just_base=self.api().compare_result(**dict(args,original=baseline_only))
            self.assertIsNone(just_base['comparison']);self.assertEqual(set(just_base['arms']),{'A','B'})
            order=dict(capture,unit_evidence=None,unit_verified_at=None,payout_unit_state='UNAVAILABLE')
            just_order=self.api().compare_result(**dict(args,final_capture=order))
            self.assertIsNone(just_order['comparison'])
            self.assertFalse(just_order['monetary_comparison_eligible'])
            order_doc=self.api().result_updates(original,just_order,order)['races'][0]
            self.assertEqual(order_doc['payout_status'],'pending');self.assertEqual(order_doc['payouts_100yen'],{})
            self.assertIsNone(order_doc['arms']['A']['return_yen'])
            saved=dict(schema=self.api().RESULT_SCHEMA,race_id=original['race_id'],
                original_evidence_sha256='d'*64,origin_packets=packets,final_capture=capture,scored=scored)
            class Store:
                def read(self,meta,key):return saved if meta.get('kind')=='result' else payload
            with patch.object(self.api(),'archived_original',return_value=(raw,adjusted)):
                replay=self.api().replay_saved_result(Store(),dict(evidence_sha256='d'*64),
                    dict(kind='result',monetary_complete=True),self.private)
                self.assertEqual(replay,doc)
                saved['scored']['arms']['A']['points']+=1
                with self.assertRaisesRegex(ValueError,'SAVED_RESULT_NOT_REPRODUCIBLE'):
                    self.api().replay_saved_result(Store(),dict(evidence_sha256='d'*64),
                        dict(kind='result',monetary_complete=True),self.private)


if __name__=='__main__': unittest.main()
