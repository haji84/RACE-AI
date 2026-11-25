"""A separate display recipient; invented packets, local Git, no state secret."""
import base64
from hashlib import sha256
import importlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


class NoteFeedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)

    def api(self):
        return importlib.import_module('race_ai.keirin_note_feed')

    def packet(self):
        return dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1', dates=['2030-01-15'],
            files={}, formal_model_admission=False, production_weight_switch=False,
            original_files_preserved=True, source_commit='a'*40,
            imported_at='2030-01-15T00:00:00Z')

    def test_only_owner_private_key_decrypts_a_public_recipient_snapshot(self):
        api = self.api()
        recipient = api.create_recipient(self.root/'owner')
        public = recipient['public']
        self.assertEqual(set(public), {'schema','recipient_id','public_key'})
        snapshot = api.seal_snapshot(self.packet(), public, kind='import')
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key = serialization.load_der_private_key(
            base64.urlsafe_b64decode(Path(recipient['private_key']).read_text().strip()+'=='),None)
        entry, wire = snapshot['entry'], snapshot['cipher']
        ephemeral = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),
            api.unb64(entry['ephemeral_public_key']))
        secret = key.exchange(ec.ECDH(), ephemeral)
        aes = HKDF(algorithm=hashes.SHA256(),length=32,salt=api.unb64(entry['salt']),
            info=api.INFO+public['recipient_id'].encode()).derive(secret)
        envelope = json.loads(wire)
        plain = AESGCM(aes).decrypt(base64.b64decode(envelope['nonce']),
            base64.b64decode(envelope['ciphertext']),api.canonical(envelope['header']))
        self.assertEqual(json.loads(plain),self.packet())
        self.assertEqual(sha256(wire).hexdigest(),entry['cipher_sha256'])
        self.assertNotIn(Path(recipient['private_key']).read_bytes().strip(),wire)
        self.assertIn('#notefeed=',Path(recipient['owner_url']).read_text())

    def test_index_is_append_only_and_provider_denial_cannot_be_reset(self):
        api=self.api();p=api.create_recipient(self.root/'owner')['public']
        a=api.seal_snapshot(self.packet(),p,kind='import')['entry']
        initial=api.append_index(None,p,entry=a)
        stopped=api.append_index(initial,p,denied=True)
        self.assertTrue(stopped['provider_denied'])
        with self.assertRaises(ValueError):api.append_index(stopped,p,entry=a)
        self.assertEqual(len(stopped['entries']),1)
        other=api.create_recipient(self.root/'other')['public']
        with self.assertRaises(ValueError):api.append_index(stopped,other)

    def test_result_plaintext_commitment_has_private_randomness_outside_public_metadata(self):
        from race_ai import keirin_result_updates as updates
        from race_ai import keirin_official_public_source as official
        from tests.test_keirin_official_public_source import fixtures, transport, DAY, RACE, NOW
        from cryptography.hazmat.primitives import serialization, hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        api = self.api()
        cap = api.create_recipient(self.root/'owner')
        get = transport(fixtures())
        schedule = official.fetch_day_schedule(DAY, fetcher=get, clock=lambda:NOW)
        record = official.fetch_race_result(RACE, schedule=schedule, fetcher=get, clock=lambda:NOW)
        doc = updates.from_official_records({RACE:record}, {})
        note = updates.note_packet(doc, source_commit='a'*40)
        original = api.canonical(note)
        first = api.seal_snapshot(note, cap['public'], kind='result', clock=lambda:NOW)
        second = api.seal_snapshot(note, cap['public'], kind='result', clock=lambda:NOW)
        self.assertNotEqual(first['entry']['source_content_sha256'],
                            second['entry']['source_content_sha256'],
                            'LOW_ENTROPY_RESULT_PLAINTEXT_HASH_MUST_NOT_BE_GUESSABLE')
        self.assertEqual(first['entry']['result_revisions'], second['entry']['result_revisions'])
        self.assertEqual(api.canonical(note), original, 'CALLER_PACKET_MUST_NOT_BE_MUTATED')
        key = serialization.load_der_private_key(api.unb64(
            Path(cap['private_key']).read_text().strip()), None)
        private_nonces = []
        for snap in (first, second):
            entry = snap['entry']; envelope = json.loads(snap['cipher'])
            ephemeral = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),
                api.unb64(entry['ephemeral_public_key']))
            aes = HKDF(algorithm=hashes.SHA256(), length=32, salt=api.unb64(entry['salt']),
                info=api.INFO+cap['public']['recipient_id'].encode()).derive(key.exchange(ec.ECDH(), ephemeral))
            plain = AESGCM(aes).decrypt(base64.b64decode(envelope['nonce']),
                base64.b64decode(envelope['ciphertext']), api.canonical(envelope['header']))
            unpacked = json.loads(plain)
            nonce = unpacked.pop('result_private_nonce')
            private_nonces.append(nonce)
            self.assertEqual(len(api.unb64(nonce)), 32)
            self.assertEqual(api.canonical(unpacked), original)
            self.assertEqual(sha256(plain).hexdigest(), entry['source_content_sha256'])
            self.assertEqual(set(envelope['header']), {'schema', 'source_content_sha256'})
            index = api.append_index(None, cap['public'], entry=entry)
            self.assertNotIn('result_private_nonce', json.dumps(index))
            self.assertNotIn(nonce, json.dumps(index))
            self.assertNotIn(nonce.encode(), snap['cipher'])
        self.assertNotEqual(*private_nonces)

    def test_shadow_verification_seal_keeps_the_measurement_and_nonce_off_the_index(self):
        from datetime import datetime
        from tests.test_keirin_note_browser import DAY, shadow_packet, source

        api=self.api()
        cap=api.create_recipient(self.root/'owner')
        def clock(hour_minute):
            return lambda:datetime.fromisoformat(f'{DAY}T{hour_minute}:00+00:00')
        archive=api.seal_snapshot(self.packet(),cap['public'],kind='archive',clock=clock('00:06'))
        note,record=shadow_packet(archive['entry']['cipher_sha256'])
        a=api.seal_snapshot(note,cap['public'],kind='shadow-verification',clock=clock('01:02'))
        b=api.seal_snapshot(note,cap['public'],kind='shadow-verification',clock=clock('01:02'))
        self.assertNotEqual(a['entry']['source_content_sha256'],b['entry']['source_content_sha256'])
        official_note,official=shadow_packet(archive['entry']['cipher_sha256'],
                                             scope='OFFICIAL_COMPLETE_FINISH_RESEARCH')
        for market in official['scores'].values():
            market['saved_hit']=False
            market['challenger_hit']=False
        official_note['files'][f'data/{DAY}/shadow_verification.json']=source(official)
        c=api.seal_snapshot(official_note,cap['public'],kind='shadow-verification',clock=clock('01:02'))
        self.assertEqual(len(a['cipher']),len(c['cipher']))
        self.assertNotIn('shadow_verification_private_nonce',note)
        index=api.append_index(None,cap['public'],entry=archive['entry'])
        index=api.append_index(index,cap['public'],entry=a['entry'])
        self.assertEqual(index['entries'][0],archive['entry'])
        self.assertEqual(index['covered_race_ids'],[])
        self.assertEqual(index['priority_window_race_ids'],[])
        encoded=json.dumps(index)
        for private in (record['race_id'],record['original']['sha256'],
                        record['result']['evidence_sha256'],'challenger_hit','tracking_learning',
                        'shadow_verification_private_nonce'):
            self.assertNotIn(private,encoded)
            self.assertNotIn(private.encode('ascii'),a['cipher'])

        from race_ai import keirin_shadow_verification as shadow
        shadow.checked_archive_binding(record,archive['entry'],a['entry']['created_at'])
        with self.assertRaises(ValueError):
            shadow.checked_archive_binding(record,{**archive['entry'],'created_at':f'{DAY}T00:40:00Z'},
                                           a['entry']['created_at'])
        with self.assertRaises(ValueError):
            shadow.checked_archive_binding(record,{**archive['entry'],'days':['2030-01-16']},
                                           a['entry']['created_at'])

    def test_shadow_verification_rejects_extra_evidence_and_unpaired_or_unbound_scores(self):
        from datetime import datetime
        from tests.test_keirin_note_browser import DAY, shadow_packet, source
        api=self.api()
        cap=api.create_recipient(self.root/'owner')
        clock=lambda:datetime.fromisoformat(f'{DAY}T01:02:00+00:00')
        for invalid in ('out-of-day','changed-points','numeric-hit','unknown-scope','source-doc',
                        'other-file','late-clock','malformed-offset','list-scope','promotion',
                        'tracking-approval','forecast-coverage'):
            with self.subTest(invalid=invalid):
                note,receipt=shadow_packet('c'*64,scope='OFFICIAL_COMPLETE_FINISH_RESEARCH')
                args={}
                if invalid=='out-of-day':receipt['race_id']='203001169801'
                if invalid=='changed-points':receipt['scores']['exacta']['points']=4
                if invalid=='numeric-hit':receipt['scores']['exacta']['saved_hit']=1
                if invalid=='unknown-scope':receipt['result']['scope']='AI ESTIMATE'
                if invalid=='list-scope':receipt['result']['scope']=[]
                if invalid=='source-doc':receipt['result']['raw']='fixture private source'
                if invalid=='other-file':note['files'][f'data/{DAY}/verification.json']=source({})
                if invalid=='late-clock':receipt['verified_at']=f'{DAY}T01:03:00Z'
                if invalid=='malformed-offset':receipt['verified_at']=f'{DAY}T02:00:00+00:60'
                if invalid=='promotion':receipt['production_weights_promoted']=True
                if invalid=='tracking-approval':receipt['tracking_learning']='VALIDATED'
                if invalid=='forecast-coverage':args['captured_ids']=[receipt['race_id']]
                note['files'][f'data/{DAY}/shadow_verification.json']=source(receipt)
                with self.assertRaises(ValueError):
                    api.seal_snapshot(note,cap['public'],kind='shadow-verification',clock=clock,**args)

    def test_public_index_rejects_secret_or_unapproved_fields(self):
        api=self.api();p=api.create_recipient(self.root/'owner')['public']
        index=api.append_index(None,p);index['key']='not-allowed'
        with self.assertRaises(ValueError):api.checked_index(index,p)
        with self.assertRaises(ValueError):api.create_recipient(self.root/'owner')

    def test_python_writer_and_webcrypto_reader_share_the_same_owner_capability(self):
        import shutil
        if not shutil.which('node'):self.skipTest('Node WebCrypto unavailable')
        api=self.api();cap=api.create_recipient(self.root/'owner')
        from race_ai.keirin_note_view import import_site
        folder=self.root/'site/data/2030-01-15';folder.mkdir(parents=True)
        (folder/'races.json').write_text(json.dumps({'races':[dict(
            race_id='203001159801',venue='Invented',race_no=1,riders=[])]}))
        note=import_site(self.root/'site',source_commit='a'*40)
        snap=api.seal_snapshot(note,cap['public'],kind='import')
        index=api.append_index(None,cap['public'],entry=snap['entry'])
        archive=api.seal_snapshot({**note,'files':{}},cap['public'],kind='archive')
        index=api.append_index(index,cap['public'],entry=archive['entry'])
        payload=dict(key=Path(cap['private_key']).read_text().strip(),
            index=index,cipher=list(snap['cipher']))
        script="""
        let raw='';process.stdin.on('data',x=>raw+=x);process.stdin.on('end',async()=>{
          try{const v=JSON.parse(raw),F=require('./web/keirin-note-feed.js');let calls=[];
            const signal=new AbortController().signal;
            Object.defineProperty(signal,'throwIfAborted',{value:undefined});
            const data=await F.open(v.key,{signal,fetcher:async(url,opt)=>{
              if(url.includes(v.key)||opt.credentials!=='omit')throw Error();calls.push(url);
              return new Response(url.endsWith('index.json')?JSON.stringify(v.index):new Uint8Array(v.cipher));
            }});
            if(data.days.get('2030-01-15').length!==1||calls.length!==2)throw Error();
            v.index.recipient_id='0'.repeat(64);
            try{F.checkIndex(v.index,'1'.repeat(64));process.exitCode=1;}catch{}
          }catch{process.exitCode=1;}
        });"""
        r=subprocess.run(['node','-e',script],input=json.dumps(payload).encode(),
            cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(r.returncode,0,'Cross-language display decryption failed')
        self.assertEqual(r.stdout,b'')

    def test_git_write_preserves_previous_cipher_and_checkout_index(self):
        api=self.api();repo=self.root/'repo';remote=self.root/'origin.git'
        def git(*args,cwd=None):
            return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.DEVNULL)
        git('init','--bare',str(remote));git('init',str(repo));git('remote','add','origin',str(remote),cwd=repo)
        class LocalFeedGit(api.NoteFeedGit):
            def _remote(self):return 'origin'
        store=LocalFeedGit(repo)
        p=api.create_recipient(self.root/'owner')['public']
        a=api.seal_snapshot(self.packet(),p,kind='import')
        first=api.publish_snapshot(store,p,a,expected_parent=None)
        oldtree=git('ls-tree','-r',first['source_commit'],'--','views',cwd=repo)
        b=api.seal_snapshot(self.packet(),p,kind='research',captured_ids=['203001159801'])
        second=api.publish_snapshot(store,p,b,expected_parent=first['source_commit'])
        self.assertIn(oldtree.strip(),git('ls-tree','-r',second['source_commit'],'--','views',cwd=repo))
        self.assertFalse((repo/'.git/index').exists())
        with self.assertRaises(ValueError):api.publish_snapshot(store,p,expected_parent=second['source_commit'],
            result_checks={'203001159801':dict(checked_at='2030-01-16T00:00:00Z',digest='a'*64,status='MATCHED')})
        with self.assertRaises(ValueError):api.publish_snapshot(store,p,b,expected_parent=first['source_commit'])
        index=api.checked_index(json.loads(store.read(second['source_commit'],'index.json')),p)
        self.assertEqual(len(index['entries']),2)
        # A retained object changed under its public identity must stop the
        # next run before acquisition; it cannot authorize a state reset.
        tampered=store.commit({'views/'+a['entry']['cipher_sha256']+'.json':b'changed'},second['source_commit'])
        store.push(tampered,second['source_commit'])
        with self.assertRaises(ValueError):api.load_index(store,p,tampered)

    def test_python_result_only_cipher_opens_and_joins_in_real_webcrypto_reader(self):
        api=self.api();cap=api.create_recipient(self.root/'owner')
        from race_ai.keirin_note_view import import_site
        from scripts.keirin_note_collect_results import SCHEMA,_held,fact_digest
        folder=self.root/'site/data/2030-01-15';folder.mkdir(parents=True)
        (folder/'races.json').write_text(json.dumps({'races':[dict(
            race_id='203001159801',venue='Invented',race_no=1,riders=[])]}))
        original=api.seal_snapshot(import_site(self.root/'site',source_commit='a'*40),cap['public'],kind='import')
        result_dir=self.root/'result/data/2030-01-15';result_dir.mkdir(parents=True)
        observation=_held('203001159801','PENDING_RESULT_NOT_PUBLISHED')
        digest=fact_digest(observation);observation.update(captured_at='2030-01-16T00:00:00Z',
            observation_sha256=digest,previous_observation_sha256=None)
        (result_dir/'research_results.json').write_text(json.dumps(dict(
            schema=SCHEMA,day_jst='2030-01-15',observations=[observation])))
        result=api.seal_snapshot(import_site(self.root/'result',source_commit='a'*40),cap['public'],kind='results')
        index=api.append_index(None,cap['public'],entry=original['entry'])
        index=api.append_index(index,cap['public'],entry=result['entry'],result_checks={
            '203001159801':dict(checked_at='2030-01-16T00:00:00Z',digest=digest,status='PENDING')})
        payload=dict(key=Path(cap['private_key']).read_text().strip(),index=index,
            wires={s['entry']['cipher_sha256']:list(s['cipher']) for s in (original,result)})
        script="""
        let raw='';process.stdin.on('data',x=>raw+=x);process.stdin.on('end',async()=>{
          try{const v=JSON.parse(raw),F=require('./web/keirin-note-feed.js');
            const data=await F.open(v.key,{fetcher:async(url,opt)=>{
              if(url.includes(v.key)||opt.credentials!=='omit')throw Error();
              const id=url.split('/').at(-1).replace('.json','');
              return new Response(url.endsWith('index.json')?JSON.stringify(v.index):new Uint8Array(v.wires[id]));
            }});
            const row=data.days.get('2030-01-15')[0];
            if(row.researchResultHistory.length!==1||row.latestResearchResult.observation.state!=='PENDING_RESULT_NOT_PUBLISHED')throw Error();
          }catch{process.exitCode=1;}
        });"""
        r=subprocess.run(['node','-e',script],input=json.dumps(payload).encode(),
            cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(r.returncode,0,'Python result delta did not bind to the WebCrypto feed')
        self.assertEqual(r.stdout,b'')

    def test_public_recipient_writer_rejects_an_alternate_push_destination(self):
        api=self.api();repo=self.root/'repo'
        def git(*args):return subprocess.check_output(['git',*args],cwd=repo,stderr=subprocess.DEVNULL)
        subprocess.check_call(['git','init',str(repo)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        git('remote','add','origin','https://github.com/haji84/RACE-AI.git')
        git('config','remote.origin.pushurl','https://github.com/example/another.git')
        with self.assertRaises(ValueError):api.NoteFeedGit(repo)

    def test_optional_result_checks_are_monotonic_and_do_not_change_forecast_coverage(self):
        api=self.api();p=api.create_recipient(self.root/'owner')['public']
        entry=api.seal_snapshot(self.packet(),p,kind='import')['entry']
        old=api.append_index(None,p,entry=entry)
        self.assertNotIn('result_checks',old)
        checks={'203001159801':dict(checked_at='2030-01-16T00:00:00Z',digest='a'*64,status='MATCHED')}
        changed=api.append_index(old,p,result_checks=checks)
        self.assertEqual(changed['covered_race_ids'],[])
        self.assertEqual(changed['result_checks'],checks)
        backward={'203001159801':{**checks['203001159801'],'checked_at':'2030-01-15T00:00:00Z'}}
        with self.assertRaises(ValueError):api.append_index(changed,p,result_checks=backward)
        result_entry=api.seal_snapshot(self.packet(),p,kind='results')['entry']
        current=api.append_index(changed,p,entry=result_entry)
        self.assertEqual(current['covered_race_ids'],[])
        self.assertEqual(current['result_checks'],checks)
        with self.assertRaises(ValueError):api.seal_snapshot(self.packet(),p,kind='results',captured_ids=['203001159801'])

    def test_public_result_checks_reject_result_values_and_malformed_clocks(self):
        api=self.api();p=api.create_recipient(self.root/'owner')['public']
        base=api.append_index(None,p,entry=api.seal_snapshot(self.packet(),p,kind='import')['entry'])
        row=dict(checked_at='2030-01-16T00:00:00Z',digest=None,status='HOLD')
        for bad in ({**row,'winning_triple':[1,2,3]}, {**row,'checked_at':'2030-01-16T09:00:00+09:00'},
                    {**row,'digest':'wrong'}, {**row,'status':'OFFICIAL'}, {**row,'status':'MATCHED'}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):api.append_index(base,p,result_checks={'203001159801':bad})

    def test_results_entry_cannot_encrypt_forecasts_under_empty_coverage_metadata(self):
        api=self.api();p=api.create_recipient(self.root/'owner')['public']
        for name in ('races.json','forecasts.json','environment.json'):
            packet=self.packet();packet['files']={'data/2030-01-15/'+name:{}}
            with self.subTest(name=name):
                with self.assertRaises(ValueError):api.seal_snapshot(packet,p,kind='results')

    def test_official_result_revisions_and_research_result_checks_coexist_without_changing_coverage(self):
        from race_ai import keirin_result_updates as updates
        from race_ai import keirin_official_public_source as official
        from tests.test_keirin_official_public_source import fixtures,transport,DAY,RACE,NOW
        api=self.api();recipient=api.create_recipient(self.root/'owner')['public']
        get=transport(fixtures())
        schedule=official.fetch_day_schedule(DAY,fetcher=get,clock=lambda:NOW)
        record=official.fetch_race_result(RACE,schedule=schedule,fetcher=get,clock=lambda:NOW)
        doc=updates.from_official_records({RACE:record},{})
        official_snapshot=api.seal_snapshot(updates.note_packet(doc,source_commit='a'*40),
            recipient,kind='result',clock=lambda:NOW)
        packet=self.packet();packet['dates']=[DAY]
        imported=api.seal_snapshot(packet,recipient,kind='import',clock=lambda:NOW)
        index=api.append_index(None,recipient,entry=imported['entry'])
        checks={RACE:dict(checked_at=NOW.isoformat(),digest='a'*64,status='HOLD')}
        index=api.append_index(index,recipient,result_checks=checks)
        research=api.seal_snapshot(packet,recipient,kind='results',clock=lambda:NOW)
        index=api.append_index(index,recipient,entry=research['entry'])
        stopped=api.append_index(index,recipient,denied=True)
        merged=api.append_index(stopped,recipient,entry=official_snapshot['entry'])
        self.assertEqual([entry['kind'] for entry in merged['entries']],['import','results','result'])
        self.assertEqual(merged['entries'][-1]['result_revisions'],{RACE:doc['races'][0]['revision']})
        self.assertEqual(merged['result_checks'],checks)
        self.assertEqual(merged['covered_race_ids'],[])
        self.assertEqual(merged['priority_window_race_ids'],[])
        self.assertTrue(merged['provider_denied'])
        with self.assertRaises(ValueError):api.append_index(stopped,recipient,entry=research['entry'])
        with self.assertRaises(ValueError):api.append_index(stopped,recipient,result_checks=checks)


if __name__=='__main__':unittest.main()
