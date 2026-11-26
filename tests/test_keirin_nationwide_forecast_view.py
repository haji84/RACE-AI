"""Nationwide display uses invented races and ephemeral test-only owner keys."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_form_fall_shadow as shadow
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_note_feed as feed
from race_ai.keirin_note_view import canonical as canonical_display
from tests.test_keirin_frozen_forecast_view import frozen_payload

DAY = '2026-11-20'
RACE = '202611209901'
NOW = datetime(2026, 11, 21, 4, tzinfo=timezone.utc)


def admitted_fixture(*, conditioned=False):
    payload = frozen_payload()
    payload.update(schema='RACE_AI_KEIRIN_OFFICIAL_NATIONWIDE_PRE_CUTOFF_V1', race_id=RACE,
                   producer_run_id='12345', producer_commit='a'*40)
    payload['snapshot']['race_id'] = RACE
    payload['supplement']['race_id'] = RACE
    payload['baseline'] = model.generate_A_B(payload['snapshot'], generated_at=payload['baseline']['generated_at'])
    payload['conditioned'] = shadow.generate_shadow(payload['snapshot'], payload['supplement'],
        baseline=payload['baseline'], generated_at=payload['baseline']['generated_at'])
    payload['cohort'] = dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_DAY_COHORT_V1', day_jst=DAY,
                            race_ids=[RACE, '202611209902', '202611209903'], max_tickets_per_arm=12,
                            calendar_source_sha256='a'*64)
    payload['cohort_sha256'] = model.digest(payload['cohort'])
    payload['condition_state'] = 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF' if conditioned else 'HISTORY_SOURCE_UNAVAILABLE'
    if not conditioned:
        for key in ('conditioned', 'supplement', 'conditioned_cipher_sha256', 'conditioned_sealed_at'):
            payload[key] = None
    registry = dict(schema='RACE_AI_OFFICIAL_EXTENSION_DAY_REGISTRY_V1', event_day=DAY,
        day_inventory_complete=True, missing_venues=[], disappeared_race_ids=[],
        registered_race_ids=list(payload['cohort']['race_ids']), races=[dict(race_id=rid,
            venue_code=99, race_no=int(rid[-2:]), official_cutoff_at=None,
            source_state='RACECARD_PUBLISHED', list_source_sha256='b'*64)
            for rid in payload['cohort']['race_ids']])
    return dict(day_jst=DAY, registry=registry, observed_at=NOW.isoformat(), records=[payload], states=[
        dict(race_id=RACE, state='A_B_AUTHENTICATED_PRE_CUTOFF', condition_state=payload['condition_state']),
        dict(race_id='202611209902', state='UNSUPPORTED_CLASS_OR_ROUND', condition_state='NO_CONDITIONED_ORIGINAL'),
        dict(race_id='202611209903', state='WAITING_SOURCE_CAPTURE', condition_state='HISTORY_NOT_COLLECTED')])


def nationwide_document(*, conditioned=False):
    """Invented display-only document, never an authenticated production record."""
    from race_ai.keirin_nationwide_forecast_view import checked_day, SCHEMA
    admitted=admitted_fixture(conditioned=conditioned); payload=admitted['records'][0]
    original={key:deepcopy(payload[key]) for key in ('race_id','baseline_cipher_sha256',
        'conditioned_cipher_sha256','baseline_sealed_at','conditioned_sealed_at','baseline','conditioned')}
    original['facts']={key:deepcopy(payload['snapshot'][key]) for key in ('competition','line_groups','riders')}
    original['revision']='e'*64
    rows=[]
    for state in admitted['states']:
        saved=state['race_id']==RACE
        rows.append(dict(**state, venue_code=99, race_no=int(state['race_id'][-2:]),
            cutoff_at=payload['baseline']['published_cutoff_at'] if saved else None,
            original_identity=dict(baseline='f'*64,conditioned='d'*64 if conditioned else None) if saved else None,
            original=original if saved else None))
    return checked_day(dict(schema=SCHEMA,day_jst=DAY,revision='1'*64,observed_at=NOW.isoformat(),
        registry_available=True,inventory_complete=True,missing_venues=[],disappeared_race_ids=[],races=rows))


class NationwideForecastViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        cls.private = key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        cls.pin = sha256(key.public_key().public_bytes(serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()

    def setUp(self):
        p = patch.object(storage, 'PINNED_OWNER_SPKI_SHA256', self.pin)
        p.start(); self.addCleanup(p.stop)

    def api(self):
        return importlib.import_module('race_ai.keirin_nationwide_forecast_view')

    def test_public_forecasts_use_frozen_top_eight_without_private_parts(self):
        from race_ai import keirin_public_forecasts as public
        doc = nationwide_document(conditioned=True)
        body = public.project(doc, published_at=NOW)
        first, pending, _ = body['races']
        original = doc['races'][0]['original']
        self.assertEqual(first['a'], original['baseline']['A']['ranked_tickets'][:8])
        self.assertEqual(first['b'], original['baseline']['B']['ranked_tickets'][:8])
        self.assertEqual(first['saved_at'], original['baseline_sealed_at'])
        self.assertEqual(body['published_at'], NOW.isoformat())
        self.assertEqual(set(first), {'race_id', 'cutoff_at', 'status', 'saved_at', 'a', 'b'})
        self.assertEqual(pending, dict(race_id=DAY.replace('-', '')+'9902', cutoff_at=None,
                                      status='pending', saved_at=None, a=[], b=[]))
        self.assertEqual(len(body['races']), len(doc['races']))
        for field in ('conditioned', 'source_facts_sha256', 'line_groups', 'six_phase_scenarios'):
            self.assertNotIn(field,json.dumps(body))

    def test_public_forecast_git_update_preserves_existing_results_and_picks(self):
        from race_ai import keirin_public_forecasts as public
        with TemporaryDirectory() as folder:
            root=Path(folder); repo,remote=root/'repo',root/'remote.git'
            def git(*args,cwd=None):
                return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.DEVNULL)
            git('init','--bare',str(remote)); git('init',str(repo))
            git('remote','add','origin',str(remote),cwd=repo)
            class LocalStore(public.PublicForecastGit):
                def _remote(self): return 'origin'
            store=LocalStore(repo)
            result_path='results/'+DAY+'.json'
            previous_result=b'{"fixture":"public-result"}\n'
            start=store.commit({result_path:previous_result},None)
            result_ref='refs/heads/state/keirin-public-results'
            git('push','origin',start+':'+result_ref,cwd=repo)
            body=public.project(nationwide_document(),published_at=NOW)
            receipt=public.publish(repo,body,store=store)
            head=store.head()
            self.assertEqual(receipt['state'],'PUBLIC_FORECASTS_UPDATED')
            self.assertEqual(receipt['published_races'],1)
            self.assertTrue(git('ls-remote','origin',result_ref,cwd=repo).decode().startswith(start+'\t'))
            self.assertEqual(git('show',start+':'+result_path,cwd=repo),previous_result)
            self.assertNotIn('ranked_tickets',json.dumps(receipt))
            later = public.project(nationwide_document(),published_at=NOW)
            later['races'][0]['a']=list(reversed(later['races'][0]['a']))
            with self.assertRaisesRegex(ValueError,'SAVED_PUBLIC_FORECAST_CHANGED'):
                public.publish(repo,later,store=store)
            self.assertEqual(store.head(),head)
            self.assertEqual(public.publish(repo,body,store=store)['state'],'PUBLIC_FORECASTS_CURRENT')

    def test_baseline_only_keeps_all_registered_races_without_regenerating_or_inventing_arms(self):
        admitted = admitted_fixture(); original = deepcopy(admitted)
        with patch.object(model, 'generate_A_B', side_effect=AssertionError('no regeneration')), \
             patch.object(shadow, 'generate_shadow', side_effect=AssertionError('no regeneration')):
            doc = self.api().from_admitted(admitted, self.private)
        self.assertEqual(len(doc['races']), 3)
        saved = doc['races'][0]['original']
        self.assertEqual(saved['baseline'], admitted['records'][0]['baseline'])
        self.assertIsNone(saved['conditioned'])
        self.assertEqual(saved['baseline']['C'], {'state':'HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS'})
        self.assertEqual(doc['races'][1]['state'], 'UNSUPPORTED_CLASS_OR_ROUND')
        self.assertIsNone(doc['races'][1]['original'])
        self.assertIsNone(doc['races'][2]['original_identity'])
        text = json.dumps(doc)
        for forbidden in ('source_bytes_by_sha', 'source_pages', 'supplement', 'producer_run_id'):
            self.assertNotIn(forbidden, text)
        self.assertEqual(admitted, original)

    def test_full_conditioned_original_uses_the_existing_strict_validator(self):
        api = self.api(); doc = api.from_admitted(admitted_fixture(conditioned=True), self.private)
        saved = doc['races'][0]['original']
        from race_ai.keirin_frozen_forecast_view import checked_forecasts, SCHEMA
        checked_forecasts(dict(schema=SCHEMA, races=[saved]))
        missing = deepcopy(saved)
        for name in ('conditioned', 'conditioned_cipher_sha256', 'conditioned_sealed_at'): missing[name] = None
        with self.assertRaises(ValueError): checked_forecasts(dict(schema=SCHEMA, races=[missing]))
        bad = deepcopy(doc); bad['races'][0]['original']['conditioned']['baseline_prediction_sha256'] = '0'*64
        with self.assertRaises(ValueError): api.checked_day(bad)

    def test_saved_confidence_survives_baseline_only_and_conditioned_display_without_rescoring(self):
        from race_ai import keirin_confidence as confidence
        for conditioned in (False,True):
            with self.subTest(conditioned=conditioned):
                admitted=admitted_fixture(conditioned=conditioned);payload=admitted['records'][0]
                legacy=self.api().from_admitted(admitted,self.private)
                payload['confidence_assessment']=confidence.assess_baseline(payload['snapshot'],payload['baseline'],
                    assessed_at=payload['baseline_sealed_at'])
                before=deepcopy(payload)
                with patch.object(confidence,'assess_baseline',side_effect=AssertionError('no reassessment')):
                    doc=self.api().from_admitted(admitted,self.private)
                    packet=self.api().note_packet(doc,'a'*40)
                saved=json.loads(packet['files']['data/'+DAY+'/nationwide_forecasts.json']['text'])['races'][0]['original']
                self.assertEqual(saved.get('confidence_assessment'),payload['confidence_assessment'])
                self.assertEqual(saved['baseline'],payload['baseline'])
                self.assertEqual(saved['conditioned'],payload['conditioned'])
                self.assertEqual(payload,before)
                self.assertNotEqual(doc['races'][0]['original_identity']['baseline'],
                    legacy['races'][0]['original_identity']['baseline'])
                for change in (lambda r:r['confidence_assessment'].__setitem__('extra',True),
                        lambda r:r['confidence_assessment'].__setitem__('source_facts_sha256','f'*64),
                        lambda r:r.__setitem__('confidence_assessment',None),
                        lambda r:r.__setitem__('unknown_metadata',True)):
                    bad=deepcopy(doc);change(bad['races'][0]['original'])
                    with self.assertRaises(ValueError):self.api().checked_day(bad)

    def test_unavailable_inventory_is_unknown_and_missing_races_never_become_zero_ticket_predictions(self):
        api = self.api()
        empty = dict(day_jst=DAY, registry=None, records=[], states=[], observed_at=NOW.isoformat())
        doc = api.from_admitted(empty, self.private)
        self.assertFalse(doc['registry_available']); self.assertFalse(doc['inventory_complete'])
        self.assertEqual(doc['races'], [])
        partial = admitted_fixture(); partial['registry']['day_inventory_complete'] = False
        partial['registry']['missing_venues'] = [88]
        doc = api.from_admitted(partial, self.private)
        self.assertEqual(doc['missing_venues'], [88]); self.assertEqual(len(doc['races']), 3)
        for row in doc['races'][1:]: self.assertIsNone(row['original'])
        for change in (
            lambda value: value['states'].pop(),
            lambda value: value['records'][0]['baseline']['A']['ranked_tickets'].reverse(),
            lambda value: value['records'][0].__setitem__('baseline_sealed_at', DAY+'T17:07:01+09:00'),
        ):
            bad = admitted_fixture(); change(bad)
            with self.assertRaises(ValueError): api.from_admitted(bad, self.private)

    def test_source_time_only_does_not_change_publication_identity_and_private_key_is_required(self):
        api = self.api(); admitted = admitted_fixture()
        first = api.from_admitted(admitted, self.private)
        admitted['observed_at'] = '2026-11-21T05:00:00Z'
        second = api.from_admitted(admitted, self.private)
        self.assertEqual(first['revision'], second['revision'])
        self.assertEqual(first['races'][0]['original_identity'], second['races'][0]['original_identity'])
        with self.assertRaises(ValueError): api.from_admitted(admitted, b'not a key')

    def test_encrypted_publication_extends_condition_arms_without_replacing_baseline_or_denominator(self):
        from race_ai import keirin_official_public_card_details as details
        from race_ai import keirin_public_forecasts as public

        api = self.api()
        with TemporaryDirectory() as folder:
            root = Path(folder); root.chmod(0o700); repo, remote = root/'repo', root/'remote.git'
            def git(*args, cwd=None):
                return subprocess.check_output(['git',*args], cwd=cwd, stderr=subprocess.DEVNULL)
            git('init','--bare',str(remote)); git('init',str(repo)); git('remote','add','origin',str(remote),cwd=repo)
            class LocalStore(feed.NoteFeedGit):
                def _remote(self): return 'origin'

            class LocalPublicStore(public.PublicForecastGit):
                def _remote(self): return 'origin'

            store = LocalStore(repo); cap = feed.create_recipient(root/'owner'); recipient = cap['public']
            seed = dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1', dates=[DAY], files={},
                formal_model_admission=False, production_weight_switch=False,
                source_commit='a'*40, imported_at=NOW.isoformat())
            feed.publish_snapshot(store,recipient,feed.seal_snapshot(seed,recipient,kind='import'),
                                  expected_parent=None,denied=True)
            base = admitted_fixture()
            ack = api.publish_day(repo,base,'a'*40,self.private,store=store,recipient=recipient,clock=lambda:NOW)
            self.assertEqual(ack['published_originals'],1); self.assertEqual(ack['published_day_status'],1)
            first = store.head(); index = feed.load_index(store,recipient,first); entry = index['entries'][-1]
            self.assertEqual(entry['kind'],'nationwide'); self.assertTrue(index['provider_denied'])
            self.assertEqual(index['covered_race_ids'],[]); self.assertEqual(len(entry['registered_race_ids']),3)
            self.assertEqual(entry['original_revisions'][RACE]['conditioned'],None)
            for private_sha in (base['records'][0]['baseline']['prediction_sha256'],base['records'][0]['baseline']['source_facts_sha256']):
                self.assertNotIn(private_sha,json.dumps(index))
            self.assertNotIn(b'ranked_tickets',store.read(first,'views/'+entry['cipher_sha256']+'.json'))
            replay = deepcopy(base); replay['observed_at']='2026-11-21T05:00:00Z'
            reused = api.publish_day(repo,replay,'b'*40,self.private,store=store,recipient=recipient,clock=lambda:NOW)
            self.assertEqual(reused['state'],'EXISTING_NATIONWIDE_DISPLAY_REUSED'); self.assertEqual(store.head(),first)
            public_store = LocalPublicStore(repo)
            publication_time = NOW + timedelta(hours=2)
            with patch.object(public, 'PublicForecastGit', return_value=public_store):
                published = api.publish_day(repo, replay, 'b'*40, self.private, store=store,
                    recipient=recipient, clock=lambda: publication_time, public_view=True)
                self.assertEqual(published['state'], 'EXISTING_NATIONWIDE_DISPLAY_REUSED')
                self.assertEqual(published['public_forecasts']['state'], 'PUBLIC_FORECASTS_UPDATED')
                self.assertEqual(published['public_details']['matched_official_races'], 1)
                with patch.object(details, 'publish', side_effect=ValueError('fixture detail unavailable')):
                    held = api.publish_day(repo, replay, 'b'*40, self.private, store=store,
                        recipient=recipient, clock=lambda: publication_time, public_view=True)
                self.assertEqual(held['state'], 'EXISTING_NATIONWIDE_DISPLAY_REUSED')
                self.assertEqual(held['public_forecasts']['state'], 'PUBLIC_FORECASTS_CURRENT')
                self.assertEqual(held['public_details'], {'state': 'HOLD_PUBLIC_OFFICIAL_DETAILS'})
                self.assertEqual(store.head(), first)
            changed_status=deepcopy(base); changed_status['states'][1]['state']='SOURCE_CAPTURE_BUDGET_PENDING'
            changed_status['observed_at']='2026-11-21T05:00:00Z'
            with patch.object(feed,'seal_snapshot',wraps=feed.seal_snapshot) as seal:
                ack=api.publish_day(repo,changed_status,'b'*40,self.private,store=store,recipient=recipient,clock=lambda:NOW)
                delta=json.loads(next(iter(seal.call_args.args[0]['files'].values()))['text'])
            self.assertEqual(ack['published_originals'],0)
            self.assertEqual(len(delta['races']),3); self.assertTrue(all(r['original'] is None for r in delta['races']))
            self.assertIsNotNone(delta['races'][0]['original_identity'])
            self.assertLess(len(canonical_display(delta)),len(canonical_display(api.from_admitted(base,self.private)))/3)
            with patch.object(feed,'seal_snapshot',wraps=feed.seal_snapshot) as seal:
                api.publish_day(repo,base,'b'*40,self.private,store=store,recipient=recipient,clock=lambda:NOW)
                reverted=json.loads(next(iter(seal.call_args.args[0]['files'].values()))['text'])
            self.assertEqual(reverted['revision'],entry['day_revision']); self.assertIsNone(reverted['races'][0]['original'])
            full = admitted_fixture(conditioned=True); full['observed_at']='2026-11-21T05:00:00Z'
            ack = api.publish_day(repo,full,'b'*40,self.private,store=store,recipient=recipient,clock=lambda:NOW)
            self.assertEqual(ack['published_originals'],1)
            second = store.head(); next_entry = feed.load_index(store,recipient,second)['entries'][-1]
            self.assertEqual(entry['original_revisions'][RACE]['baseline'],next_entry['original_revisions'][RACE]['baseline'])
            self.assertIsNotNone(next_entry['original_revisions'][RACE]['conditioned'])
            changed = admitted_fixture(); changed['records'][0]['baseline_cipher_sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'IMMUTABLE_ORIGINAL_CHANGED'):
                api.publish_day(repo,changed,'b'*40,self.private,store=store,recipient=recipient,clock=lambda:NOW)
            shrunk = admitted_fixture(); shrunk['registry']['registered_race_ids'].pop(); shrunk['registry']['races'].pop(); shrunk['states'].pop()
            shrunk['records'][0]['cohort']['race_ids'].pop(); shrunk['records'][0]['cohort_sha256']=model.digest(shrunk['records'][0]['cohort'])
            with self.assertRaisesRegex(ValueError,'REGISTERED_DENOMINATOR_SHRANK'):
                api.publish_day(repo,shrunk,'b'*40,self.private,store=store,recipient=recipient,clock=lambda:NOW)
            self.assertEqual(store.head(),second)

    def test_oversize_day_is_rejected_without_truncating_any_original(self):
        api=self.api(); doc=api.from_admitted(admitted_fixture(conditioned=True),self.private); original=deepcopy(doc)
        self.assertEqual(api.MAX_FILE_BYTES,32*1024*1024)
        with patch.object(api,'MAX_FILE_BYTES',100):
            with self.assertRaisesRegex(ValueError,'DAY_FILE_TOO_LARGE'):api.note_packet(doc,'a'*40)
        self.assertEqual(doc,original)

    def test_display_status_allowlists_match_the_authenticated_records_loader(self):
        from race_ai import keirin_official_nationwide_records as records
        self.assertEqual(self.api().RACE_STATES,records.STATES)
        self.assertEqual(self.api().CONDITION_STATES,records.CONDITION_STATES)

    def test_python_encryption_and_webcrypto_show_baseline_without_prior_import_and_bind_metadata(self):
        api = self.api(); doc = api.from_admitted(admitted_fixture(),self.private); note = api.note_packet(doc,'a'*40)
        from race_ai.keirin_note_view import canonical
        with TemporaryDirectory() as folder:
            root=Path(folder); root.chmod(0o700); cap=feed.create_recipient(root/'owner')
            sealed=feed.seal_snapshot(note,cap['public'],kind='nationwide',clock=lambda:NOW)
            again=feed.seal_snapshot(note,cap['public'],kind='nationwide',clock=lambda:NOW)
            self.assertNotEqual(sealed['entry']['source_content_sha256'],sha256(canonical(note)).hexdigest())
            self.assertNotEqual(sealed['entry']['source_content_sha256'],again['entry']['source_content_sha256'])
            self.assertEqual(sealed['entry']['day_revision'],again['entry']['day_revision'])
            index=feed.append_index(None,cap['public'],entry=sealed['entry'],denied=True)
            payload=dict(key=Path(cap['private_key']).read_text().strip(),index=index,day=DAY,race=RACE,
                wire=list(sealed['cipher']),expected=doc['races'][0]['original'])
            script="""
            let raw='';process.stdin.on('data',s=>raw+=s);process.stdin.on('end',async()=>{
              try{
                const v=JSON.parse(raw),F=require('./web/keirin-note-feed.js'),M=require('./web/keirin-note-model.js');let calls=0;
                const fetcher=async(url,opt)=>{calls++;if(url.includes(v.key)||opt.credentials!=='omit'||opt.redirect!=='error')throw Error('unsafe request');return url.endsWith('index.json')?new Response(JSON.stringify(v.index)):new Response(new Uint8Array(v.wire));};
                const session=await F.createSession(v.key,{fetcher});const data=await session.refresh(),rows=M.rows(data,v.day),row=rows.find(r=>r.id===v.race);
                if(rows.length!==3||!data.feed.providerDenied||!require('node:util').isDeepStrictEqual(row.frozenForecast,v.expected))throw Error('wrong baseline');
                if(!M.frozenArm(row,'A').tickets.length||!M.frozenArm(row,'B').tickets.length||M.frozenArm(row,'adjusted_A')!==null||M.frozenArm(row,'C')!==null)throw Error('independence');
                if(rows.filter(r=>r.frozenForecast).length!==1||calls!==2)throw Error('denominator');await session.refresh();if(calls!==3)throw Error('cache');session.close();
                for(const change of [e=>e.day_revision='0'.repeat(64),e=>e.original_revisions[v.race].baseline='0'.repeat(64),e=>e.registered_race_ids.pop()]){
                  const saved=structuredClone(v.index);change(v.index.entries[0]);let rejected=false;try{await F.open(v.key,{fetcher});}catch{rejected=true;}if(!rejected)throw Error('forged metadata');v.index=saved;
                }
              }catch(error){process.stderr.write(error.message);process.exitCode=1;}
            });"""
            proc=subprocess.run(['node','-e',script],input=json.dumps(payload).encode(),
                cwd=Path(__file__).resolve().parents[1],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            self.assertEqual(proc.returncode,0,proc.stderr.decode()); self.assertEqual(proc.stdout,b'')


class PublicReferenceForecastTests(unittest.TestCase):
    def setUp(self):
        from race_ai import keirin_public_forecasts as public
        from race_ai.keirin_note_view import import_site
        from scripts.keirin_note_collect_inputs import collect_day
        from tests.test_keirin_note_collect_inputs import DAY, NOW, pages_for, rid

        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.root.chmod(0o700)
        self.public, self.day, self.now = public, DAY, NOW
        self.ids = [rid(1), rid(2)]
        self.recipient = feed.create_recipient(self.root/'test-recipient')['public']
        collected = collect_day(day_jst=DAY, private_root=self.root/'capture',
            fetch=pages_for([(1, '12:12'), (2, '13:00')]).__getitem__,
            clock=lambda: NOW, model_source_commit='a'*40)
        self.note = import_site(Path(collected['site_root']), source_commit='a'*40,
            clock=lambda: NOW+timedelta(seconds=1))
        self.note.update(scope='OWNER_MATCHED_SOURCE_RESEARCH_REFRESH', source_site=None,
            source_profile='owner-imported-kdreams-netkeirin-20261120',
            actual_four_model_forecast_saved=False)
        self.reference_path = f'data/{DAY}/reference_AB.json'
        self.reference_key = f'references/{DAY}.json'

    def seal(self, note, *, ids=None):
        return feed.seal_snapshot(note, self.recipient, kind='research',
            captured_ids=self.ids if ids is None else ids,
            clock=lambda: self.now+timedelta(seconds=2))['entry']

    def project(self, *, published_at=None):
        return self.public.project_reference(self.note, self.seal(self.note),
            published_at=published_at or self.now+timedelta(seconds=3))

    def test_reference_is_exactly_the_first_eight_existing_candidates(self):
        projected = self.project()
        self.assertEqual(set(projected), {'schema','day','published_at','races'})
        self.assertEqual(projected['schema'], 'RACE_AI_KEIRIN_PUBLIC_REFERENCE_FORECASTS_V1')
        self.assertEqual(projected['day'], self.day)
        self.assertEqual(projected['published_at'], '2030-01-15T12:00:03+09:00')
        research = json.loads(self.note['files'][self.reference_path]['text'])
        outputs = {row['output']['race_id']:row['output'] for row in research}
        self.assertEqual([row['race_id'] for row in projected['races']], self.ids)
        for row in projected['races']:
            existing = outputs[row['race_id']]
            self.assertGreater(len(existing['A']['ranked_tickets']), 8)
            self.assertEqual(row, dict(race_id=existing['race_id'], cutoff_at=existing['published_cutoff_at'],
                saved_at='2030-01-15T03:00:02+00:00', a=existing['A']['ranked_tickets'][:8],
                b=existing['B']['ranked_tickets'][:8]))

    def test_readback_at_or_after_cutoff_excludes_individual_races(self):
        partly_late = self.project(published_at=self.now+timedelta(minutes=12))
        self.assertEqual([row['race_id'] for row in partly_late['races']], self.ids[1:])
        all_late = self.project(published_at=self.now+timedelta(hours=1))
        self.assertEqual(all_late['races'], [])
        with self.assertRaisesRegex(ValueError, 'PUBLICATION_CLOCK'):
            self.project(published_at=self.now.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            self.project(published_at=self.now+timedelta(seconds=1))

    def test_reference_requires_bound_note_and_complete_captured_set(self):
        valid_entry = self.seal(self.note)
        at = self.now+timedelta(seconds=3)
        with self.assertRaises(ValueError):
            self.public.project_reference(self.note, self.seal(self.note, ids=self.ids[:1]), published_at=at)
        with self.assertRaises(ValueError):
            self.public.project_reference(dict(self.note, dates=['2030-01-16']), valid_entry, published_at=at)
        with self.assertRaises(ValueError):
            self.public.project_reference(dict(self.note, source_commit='b'*40), valid_entry, published_at=at)

    def test_reference_rejects_resealed_mismatched_models_and_nonfinite_json(self):
        raw = self.note['files'][self.reference_path]['text']
        for text in (raw.replace('"model_source_commit":"'+'a'*40, '"model_source_commit":"'+'b'*40),
                     raw.replace('"model_source_sha256":"', '"model_source_sha256":"bad'),
                     raw.replace('"model_source_sha256":', '"unused":1e999,"model_source_sha256":'),
                     raw.replace('"independent_runner_readback":false', '"independent_runner_readback":true')):
            with self.subTest(text_length=len(text)):
                self.assertNotEqual(text, raw)
                note = deepcopy(self.note)
                note['files'][self.reference_path] = dict(text=text,
                    bytes=len(text.encode()), sha256=sha256(text.encode()).hexdigest())
                with self.assertRaises(ValueError):
                    self.public.project_reference(note, self.seal(note),
                        published_at=self.now+timedelta(seconds=3))

    def test_reference_append_preserves_first_candidates_and_official_blob(self):
        public, root = self.public, self.root
        repo, remote = root/'repo', root/'remote.git'

        def git(*args, cwd=None):
            return subprocess.check_output(['git',*args], cwd=cwd, stderr=subprocess.DEVNULL)

        class LocalStore(public.PublicForecastGit):
            def _remote(self):
                return 'origin'

        git('init','--bare',str(remote))
        git('init',str(repo))
        git('remote','add','origin',str(remote),cwd=repo)
        store = LocalStore(repo)
        at = self.now+timedelta(seconds=3)
        official_body = dict(schema=public.SCHEMA, day=self.day, published_at=at.isoformat(),
            races=[dict(race_id=self.ids[0], cutoff_at=None, status='pending', saved_at=None, a=[], b=[])])
        official = public.publish(repo, official_body, store=store)
        official_path = f'forecasts/{self.day}.json'
        official_bytes = store.read_previous(official['commit'], official_path)

        projected = self.project()
        first, second = projected['races']
        receipt = public.publish_reference(repo, dict(projected, races=[first]), store=store)
        changed = dict(first, a=list(reversed(first['a'])))
        duplicate = public.publish_reference(repo, dict(projected, races=[changed]), store=store)
        self.assertEqual(duplicate['commit'], receipt['commit'])
        self.assertEqual(store.head(), receipt['commit'])
        next_body = dict(projected, published_at=(self.now+timedelta(minutes=13)).isoformat(),
            races=[changed,second])
        appended = public.publish_reference(repo, next_body, store=store)
        self.assertEqual(appended['published_races'], 2)
        self.assertEqual(store.read_previous(appended['commit'], official_path), official_bytes)
        self.assertEqual(json.loads(store.read_previous(appended['commit'], self.reference_key)),
            dict(next_body, races=[first,second]))
        self.assertEqual(store.run(['rev-list','--parents','-n','1',appended['commit']]).decode().split(),
            [appended['commit'],receipt['commit']])

    def test_reference_retries_fast_forward_and_keeps_the_concurrent_first_pick(self):
        public = self.public
        repo, remote = self.root/'retry-repo', self.root/'retry.git'
        for args, cwd in ((['init','--bare',str(remote)],None), (['init',str(repo)],None),
                          (['remote','add','origin',str(remote)],repo)):
            subprocess.check_output(['git',*args], cwd=cwd, stderr=subprocess.DEVNULL)

        class LocalStore(public.PublicForecastGit):
            def _remote(self):
                return 'origin'

        other = LocalStore(repo)
        projected = self.project()
        first, second = projected['races']
        winner = dict(first, a=list(reversed(first['a'])))
        initial = other.commit({f'forecasts/{self.day}.json':b'{"official_fixture":true}\n'}, None)
        other.push(initial, None)
        later = (self.now+timedelta(seconds=4)).isoformat()
        concurrent_revisions = []

        class RacingStore(LocalStore):
            def push(self, commit, parent):
                if not concurrent_revisions:
                    concurrent = public.publish_reference(repo,
                        dict(projected,published_at=later,races=[winner]), store=other)
                    concurrent_revisions.append(concurrent['commit'])
                return super().push(commit, parent)

        store = RacingStore(repo)
        saved = public.publish_reference(repo, projected, store=store)
        self.assertEqual(json.loads(store.read_previous(saved['commit'], self.reference_key))['races'],
            [winner,second])
        self.assertEqual(saved['published_at'], later)
        self.assertEqual(store.run(['rev-list','--parents','-n','1',saved['commit']]).decode().split(),
            [saved['commit'],concurrent_revisions[0]])


class PublicResultUnreadForecastTests(unittest.TestCase):
    def test_real_model_uses_only_five_registered_cars_after_cutoff(self):
        from race_ai import keirin_public_forecasts as public

        cars = [1, 3, 4, 6, 7]
        scheduled = dict(race_id=RACE, official_cutoff_at=DAY+'T17:00:00+09:00',
            source_observed_at=DAY+'T09:00:00+09:00', starters=[{'car':car} for car in cars])
        snapshot = dict(race_id=RACE, competition='S', line_groups=[[1,3],[4,6],[7]], line_warnings=[],
            riders=[dict(car=car, name='架空選手', competition_points=points, style=style, mark_rank=rank)
                for car,points,style,rank in zip(cars,[112,102,95,88,82],
                    ['NIGE','ALLROUND','NIGE','MARK','MARK'], [1,2,3,4,'UNMARKED'])])
        row = public.project_research_race(snapshot, scheduled, generated_at=NOW)
        self.assertEqual(row['starter_cars'], cars)
        self.assertEqual(row['cutoff_at'], scheduled['official_cutoff_at'])
        self.assertGreater(model.when(row['generated_at']), model.when(row['cutoff_at']))
        self.assertTrue(row['a']); self.assertTrue(row['b'])
        self.assertTrue(all(set(ticket) <= set(cars) for ticket in row['a'] + row['b']))
        with self.assertRaisesRegex(ValueError, 'RESULT_UNREAD_INPUT'):
            public.project_research_race(dict(snapshot, result=[1,3,4]), scheduled, generated_at=NOW)
        with self.assertRaisesRegex(ValueError, 'RESEARCH_STARTER_ROSTER'):
            public.project_research_race(snapshot, dict(scheduled, starters=[{'car':c} for c in (1,2,3,4,5)]),
                                        generated_at=NOW)

    def test_research_publication_requires_registered_races_and_preserves_existing_files(self):
        from race_ai import keirin_public_forecasts as public

        class LocalStore(public.PublicForecastGit):
            def _remote(self):
                return 'origin'

        with TemporaryDirectory() as folder:
            root = Path(folder)
            repo, remote = root/'research-repo', root/'research.git'
            for args, cwd in ((['init','--bare',str(remote)],None), (['init',str(repo)],None),
                              (['remote','add','origin',str(remote)],repo)):
                subprocess.check_output(['git',*args], cwd=cwd, stderr=subprocess.DEVNULL)
            store = LocalStore(repo)
            registry = dict(schema=public.SCHEMA, day=DAY, published_at=NOW.isoformat(), races=[
                dict(race_id=RACE, cutoff_at=None, status='pending', saved_at=None, a=[], b=[])])
            original = public.publish(repo, registry, store=store)['commit']
            row = dict(race_id=RACE, cutoff_at=DAY+'T17:00:00+09:00', generated_at=NOW.isoformat(),
                       starter_cars=[1,3,4,6,7], a=[[1,4,3]], b=[])
            body = dict(schema='RACE_AI_KEIRIN_PUBLIC_RESULT_UNREAD_AB_V1', day=DAY,
                        published_at=NOW.isoformat(), races=[row])
            for bad in [dict(row, starter_cars=[1,3,3,6,7]), dict(row, a=[[1,2,4]]),
                        dict(row, a=[]), dict(row, payout=100),
                        dict(row, generated_at=(NOW+timedelta(seconds=1)).isoformat())]:
                with self.assertRaises(ValueError):
                    public.checked_research(dict(body, races=[bad]))
            with self.assertRaisesRegex(ValueError, 'RESEARCH_UNREGISTERED_RACE'):
                public.publish_research(repo, dict(body, races=[dict(row, race_id='202611209902')]), store=store)
            first = public.publish_research(repo, body, store=store)
            repeat = public.publish_research(repo, dict(body, races=[dict(row, a=[[4,1,3]])]), store=store)
            self.assertEqual(first['published_races'], 1)
            self.assertEqual(repeat['commit'], first['commit'])
            self.assertEqual(json.loads(store.read_previous(first['commit'], f'research/{DAY}.json')), body)
            self.assertEqual(store.read_previous(first['commit'], f'forecasts/{DAY}.json'),
                             store.read_previous(original, f'forecasts/{DAY}.json'))
