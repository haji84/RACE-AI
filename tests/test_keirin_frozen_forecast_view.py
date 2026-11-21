"""Frozen display fixtures use invented inputs and ephemeral owner keys only."""
from copy import deepcopy
from datetime import datetime, timezone
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
from tests.test_keirin_nationwide_auto_generator import fixture
from tests.test_keirin_rider_form_evidence import pack

RACE = '202611208105'
DAY = '2026-11-20'
NOW = datetime(2026, 11, 21, 4, tzinfo=timezone.utc)


def frozen_payload():
    snapshot = fixture(6, girls=True)
    snapshot.update(race_id=RACE, as_of=DAY+'T13:00:00+09:00',
                    published_cutoff_at=DAY+'T17:07:00+09:00')
    snapshot['cutoff_source']['captured_at'] = snapshot['as_of']
    for page in snapshot['source_pages']: page['captured_at'] = snapshot['as_of']
    supplement = pack(); supplement['race_id'] = RACE
    supplement['condition_evidence']['as_of'] = snapshot['as_of']
    supplement['source_pages'][0]['captured_at'] = snapshot['as_of']
    baseline = model.generate_A_B(snapshot, generated_at=DAY+'T13:01:00+09:00')
    conditioned = shadow.generate_shadow(snapshot, supplement, baseline=baseline,
                                         generated_at=baseline['generated_at'])
    return dict(schema='RACE_AI_KEIRIN_OFFICIAL_FORM_CANARY_PRE_CUTOFF_V1',
        day_jst=DAY, race_id=RACE, snapshot=snapshot, supplement=supplement,
        baseline=baseline, conditioned=conditioned,
        baseline_cipher_sha256=sha256(b'invented baseline envelope').hexdigest(),
        conditioned_cipher_sha256=sha256(b'invented conditioned envelope').hexdigest(),
        baseline_sealed_at=DAY+'T13:01:01+09:00',
        conditioned_sealed_at=DAY+'T13:01:01+09:00',
        source_bytes_by_sha={'invented': b'private source bytes must never enter the display'})


def frozen_document():
    """An invented display-only fixture; not an authenticated production receipt."""
    from race_ai.keirin_frozen_forecast_view import checked_forecasts, SCHEMA
    payload = frozen_payload()
    row = {key:deepcopy(payload[key]) for key in ('race_id','baseline_cipher_sha256',
        'conditioned_cipher_sha256','baseline_sealed_at','conditioned_sealed_at','baseline','conditioned')}
    row['facts'] = {key:deepcopy(payload['snapshot'][key]) for key in ('competition','line_groups','riders')}
    row['revision'] = 'e'*64
    return checked_forecasts(dict(schema=SCHEMA, races=[row]))


class FrozenForecastViewTests(unittest.TestCase):
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
        return importlib.import_module('race_ai.keirin_frozen_forecast_view')

    def test_exact_frozen_arms_are_copied_without_forecast_regeneration(self):
        payload = frozen_payload()
        with patch.object(model, 'generate_A_B', side_effect=AssertionError('no regeneration')), \
             patch.object(shadow, 'generate_shadow', side_effect=AssertionError('no regeneration')):
            doc = self.api().from_payload(payload, self.private)
        row = doc['races'][0]
        self.assertEqual(row['baseline'], payload['baseline'])
        self.assertEqual(row['conditioned'], payload['conditioned'])
        self.assertEqual(row['baseline']['C'], {'state':'HOLD_NO_INDEPENDENT_HISTORICAL_FOLLOW_LABELS'})
        self.assertNotIn('source_bytes_by_sha', json.dumps(doc))
        self.assertNotIn('source_pages', json.dumps(doc))
        self.assertNotIn('supplement', row)
        self.assertNotEqual(row['revision'], payload['baseline']['prediction_sha256'])
        self.assertEqual(payload, frozen_payload())

    def test_fixed_historical_canary_cannot_acquire_a_confidence_sidecar(self):
        from race_ai import keirin_confidence as confidence
        payload=frozen_payload()
        payload['confidence_assessment']=confidence.assess_baseline(payload['snapshot'],payload['baseline'],
            assessed_at=payload['baseline_sealed_at'])
        before=deepcopy(payload)
        with self.assertRaisesRegex(ValueError,'HISTORICAL_CANARY_CONFIDENCE_NOT_ALLOWED'):
            self.api().from_payload(payload,self.private)
        self.assertEqual(payload,before)
        payload['confidence_assessment']=None
        with self.assertRaisesRegex(ValueError,'HISTORICAL_CANARY_CONFIDENCE_NOT_ALLOWED'):
            self.api().from_payload(payload,self.private)

    def test_changed_frozen_identity_duplicate_tickets_and_post_cutoff_sealing_are_rejected(self):
        payload = frozen_payload()
        for mutate in (
            lambda p: p['baseline']['A']['ranked_tickets'].reverse(),
            lambda p: p['conditioned'].__setitem__('baseline_prediction_sha256', '0'*64),
            lambda p: p.__setitem__('baseline_sealed_at', DAY+'T17:07:01+09:00'),
        ):
            bad = deepcopy(payload); mutate(bad)
            with self.assertRaises(ValueError): self.api().from_payload(bad, self.private)
        doc = self.api().from_payload(payload, self.private)
        row = doc['races'][0]
        row['baseline']['A']['ranked_tickets'][1] = row['baseline']['A']['ranked_tickets'][0]
        row['baseline']['prediction_sha256'] = model.digest({k:v for k,v in row['baseline'].items() if k != 'prediction_sha256'})
        row['conditioned']['baseline_prediction_sha256'] = row['baseline']['prediction_sha256']
        row['conditioned']['sha256'] = model.digest({k:v for k,v in row['conditioned'].items() if k != 'sha256'})
        with self.assertRaises(ValueError): self.api().checked_forecasts(doc)

    def test_owner_key_pin_and_no_extra_private_fields(self):
        with self.assertRaises(ValueError): self.api().from_payload(frozen_payload(), b'not an owner key')
        doc = self.api().from_payload(frozen_payload(), self.private)
        doc['races'][0]['baseline']['source_bytes'] = 'must not leak'
        with self.assertRaises(ValueError): self.api().checked_forecasts(doc)

    def test_encrypted_original_publication_is_immutable_idempotent_and_stop_preserving(self):
        with TemporaryDirectory() as folder:
            root = Path(folder); root.chmod(0o700); repo, remote = root/'repo', root/'remote.git'
            def git(*args, cwd=None):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.DEVNULL)
            git('init', '--bare', str(remote)); git('init', str(repo))
            git('remote', 'add', 'origin', str(remote), cwd=repo)
            class LocalStore(feed.NoteFeedGit):
                def _remote(self): return 'origin'
            store = LocalStore(repo); cap = feed.create_recipient(root/'owner'); recipient = cap['public']
            seed = dict(schema='RACE_AI_KEIRIN_NOTE_VIEW_V1', dates=[DAY], files={},
                formal_model_admission=False, production_weight_switch=False,
                source_commit='a'*40, imported_at=NOW.isoformat())
            feed.publish_snapshot(store, recipient, feed.seal_snapshot(seed, recipient, kind='import'),
                                  expected_parent=None, denied=True)
            payload = frozen_payload()
            result = self.api().publish_frozen_forecast(repo, payload, 'a'*40, self.private,
                store=store, recipient=recipient, clock=lambda: NOW)
            head = store.head(); index = feed.load_index(store, recipient, head)
            self.assertTrue(index['provider_denied']); self.assertEqual(index['covered_race_ids'], [])
            entry = index['entries'][-1]
            self.assertEqual(entry['kind'], 'canary-original')
            self.assertEqual(result['published_originals'], 1)
            self.assertNotIn(payload['baseline']['prediction_sha256'], json.dumps(index))
            self.assertNotIn(payload['conditioned']['sha256'], json.dumps(index))
            self.assertNotIn(b'ranked_tickets', store.read(head, 'views/'+entry['cipher_sha256']+'.json'))
            again = self.api().publish_frozen_forecast(repo, payload, 'b'*40, self.private,
                store=store, recipient=recipient, clock=lambda: NOW)
            self.assertEqual(again['state'], 'EXISTING_FROZEN_DISPLAY_REUSED'); self.assertEqual(store.head(), head)
            wrong = deepcopy(payload); wrong['baseline_cipher_sha256'] = 'd'*64
            with self.assertRaises(ValueError):
                self.api().publish_frozen_forecast(repo, wrong, 'a'*40, self.private,
                    store=store, recipient=recipient, clock=lambda: NOW)

    def test_python_original_packet_and_webcrypto_reader_bind_the_same_frozen_arms(self):
        from race_ai.keirin_note_view import canonical
        doc = self.api().from_payload(frozen_payload(), self.private)
        note = self.api().note_packet(doc, 'a'*40)
        def source(value):
            raw = canonical(value)
            return dict(text=raw.decode(), bytes=len(raw), sha256=sha256(raw).hexdigest())
        seed = {**note, 'files': {f'data/{DAY}/races.json': source([dict(
            race_id=RACE, venue='Invented', race_no=5, riders=[])]),
            f'data/{DAY}/reference_AB.json': source([dict(race_id=RACE,
                A=dict(ranked_tickets=[[3,1,2]]), B=dict(ranked_tickets=[[2,3,1]]))])}}
        with TemporaryDirectory() as folder:
            root = Path(folder); root.chmod(0o700); cap = feed.create_recipient(root/'owner')
            initial = feed.seal_snapshot(seed, cap['public'], kind='import', clock=lambda: NOW)
            sealed = feed.seal_snapshot(note, cap['public'], kind='canary-original', clock=lambda: NOW)
            again = feed.seal_snapshot(note, cap['public'], kind='canary-original', clock=lambda: NOW)
            self.assertNotEqual(sealed['entry']['source_content_sha256'], sha256(canonical(note)).hexdigest())
            self.assertNotEqual(sealed['entry']['source_content_sha256'], again['entry']['source_content_sha256'])
            self.assertEqual(sealed['entry']['original_revisions'], again['entry']['original_revisions'])
            index = feed.append_index(None, cap['public'], entry=initial['entry'], denied=True)
            index = feed.append_index(index, cap['public'], entry=sealed['entry'])
            payload = dict(key=Path(cap['private_key']).read_text().strip(), index=index,
                day=DAY, race=RACE, expected=doc['races'][0],
                ciphers={s['entry']['cipher_sha256']:list(s['cipher']) for s in (initial,sealed)})
            script = """
            let raw='';process.stdin.on('data',s=>raw+=s);process.stdin.on('end',async()=>{
              try{
                const v=JSON.parse(raw),F=require('./web/keirin-note-feed.js'),M=require('./web/keirin-note-model.js');let calls=0;
                const fetcher=async(url,opt)=>{
                  calls++;if(url.includes(v.key)||opt.credentials!=='omit')throw Error('private request');
                  if(url.endsWith('index.json'))return new Response(JSON.stringify(v.index));
                  const sha=url.split('/').at(-1).replace('.json','');if(!v.ciphers[sha])throw Error('unexpected request');
                  return new Response(new Uint8Array(v.ciphers[sha]));
                };
                const session=await F.createSession(v.key,{fetcher});
                const first=await session.refresh(),row=M.rows(first,v.day)[0];
                if(!first.feed.providerDenied||!require('node:util').isDeepStrictEqual(row.frozenForecast,v.expected)||
                  M.forecast(row,'3t','A').tickets[0].combo!=='3-1-2'||M.frozenArm(row,'C')!==null)throw Error('wrong original');
                for(const name of ['A','B','adjusted_A','adjusted_B'])if(!M.frozenArm(row,name).tickets.length)throw Error('missing arm');
                if(calls!==3)throw Error('missing read');await session.refresh();if(calls!==4)throw Error('not cached');session.close();
                v.index.entries[1].original_revisions[v.race]='0'.repeat(64);
                let rejected=false;try{await F.open(v.key,{fetcher});}catch{rejected=true;}if(!rejected)throw Error('forged metadata');
              }catch(error){process.stderr.write(error.message);process.exitCode=1;}
            });"""
            proc = subprocess.run(['node','-e',script], input=json.dumps(payload).encode(),
                cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            self.assertEqual(proc.stdout, b'')

    def test_saved_export_requires_successful_existing_replay_before_publication(self):
        from scripts import keirin_official_form_canary as canary
        payload = frozen_payload(); receipt = {'invented': True}; pair = ({'fixture':'result'}, {'fixture':'receipt'})
        events = []
        with patch.object(canary, '_load_original_bundle', return_value=(payload,receipt,[pair])), \
             patch.object(canary, '_archived_pair', return_value=(b'base',b'adjusted',{})), \
             patch.object(canary, 'replay_saved_result', side_effect=lambda **kw:events.append('verified')), \
             patch.object(self.api(), 'publish_frozen_forecast', side_effect=lambda *args:events.append('published') or {'published_originals':1}):
            self.api().saved_frozen_forecast('/invented', self.private, 'a'*40)
            self.assertEqual(events, ['verified','published'])
        with patch.object(canary, '_load_original_bundle', return_value=(payload,receipt,[pair])), \
             patch.object(canary, '_archived_pair', return_value=(b'base',b'adjusted',{})), \
             patch.object(canary, 'replay_saved_result', side_effect=ValueError('invalid saved witness')), \
             patch.object(self.api(), 'publish_frozen_forecast') as publish:
            with self.assertRaises(ValueError):self.api().saved_frozen_forecast('/invented', self.private, 'a'*40)
            publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()
