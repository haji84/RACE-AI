"""Bounded runner tests: no provider access, ephemeral keys, real source fixtures."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import importlib
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch, Mock

from tests.test_keirin_official_nationwide_records import NationwideRecordTests
from tests.test_keirin_official_nationwide_extension import NationwideExtensionTests
from tests.test_keirin_official_schedule import meeting, page, venue
from tests.test_keirin_official_sp_receipt import AT, DAY, detail_data, html, list_data
from race_ai import keirin_official_nationwide_extension as extension
from race_ai import keirin_nationwide_auto_storage as storage


class FakeLease:
    def __init__(self):self.finished=[]
    def finish(self,**kwargs):self.finished.append(kwargs['state'])


class FakeStore:
    def __init__(self,repo,day):
        self.repo=repo;self.day=day;self.head='a'*40
        self.index={'registry':None,'originals':{},'results':{}}
        self.saved=[]
    def append(self,**kwargs):
        self.saved.append(deepcopy(kwargs))
        return {'evidence_sha256':'b'*64,'cipher_sha256':'c'*64}


def cutoff_fixture(venue_codes=(98, 99)):
    calendar_raw = page([venue(code, [meeting('2030-01-14', '2030-01-16', chr(code) * 43)])
                         for code in venue_codes])
    calendar = dict(raw_bytes=calendar_raw, expected_sha256=sha256(calendar_raw).hexdigest(),
                    observed_at=AT)
    listings, records = [], []
    for code in venue_codes:
        data = list_data()
        rows = data['SJ0301']['kaisaiDayList'][1]['raceProgramList']
        for number, label in enumerate(('A級特予選', 'A級特選', 'A級決勝'), 1):
            rows[number - 1]['strSyumokuName'] = label
        raw = html(data)
        listed = dict(venue_code=code, raw_bytes=raw, expected_sha256=sha256(raw).hexdigest(),
                      observed_at=AT, http_status=200)
        listings.append(listed)
        for number, cutoff in ((1, '12:47'), (2, '12:20'), (3, '11:50')):
            if (code, number) not in ((99, 1), (99, 2), (98, 3)):
                continue
            row = rows[number - 1]
            detail = detail_data()
            detail['SC0201']['C0201data'].update(selRaceNo=number, aftBetTime=cutoff,
                aftBetDate=DAY.replace('-', '') + cutoff.replace(':', ''))
            for index, rider in enumerate(detail['SJ0315']['sensyuTypeInfo']):
                rider['kyuhan'] = 'A1' if index % 2 else 'A2'
            detail_raw = html(detail)
            url = 'https://keirin.jp/sp/race'
            digest = sha256(detail_raw).hexdigest()
            source = dict(raw_bytes=detail_raw, expected_sha256=digest, observed_at=AT.isoformat(),
                          source_url=url, request_url=url, http_status=200,
                          receipt=dict(source_url=url, method='POST', http_status=200,
                            form_fields={'encp': row['strRaceLnkPrm'], 'disp': 'SJ0315'},
                            captured_at=AT.isoformat(), bytes_sha256=digest, kind='PROGRAM'))
            records.append(dict(race_id=DAY.replace('-', '') + f'{code:02d}{number:02d}',
                                class_label=row['strSyumokuName'], prediction_admitted=False,
                                list_source=listed, detail_source=source))
    registry = extension.register_day(calendar_receipt=calendar, list_sources=listings,
                                      event_day=DAY, now=AT)
    return dict(registry=registry, calendar_receipt=calendar, list_sources=listings), records


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):NationwideRecordTests.setUpClass.__func__(cls)
    def setUp(self):NationwideRecordTests.setUp(self)
    def api(self):return importlib.import_module('scripts.keirin_official_nationwide_continuation')
    def run_fixture(self,folder,*,condition_error=True,existing=False,capacity=(300,900),history_unavailable=False,history_cutoff_margin=None):
        from race_ai import keirin_official_nationwide_sources as sources
        args=NationwideExtensionTests().baseline_arguments();now=args.pop('now')
        candidate=extension.build_baseline_candidate(**args,now=now)
        candidate.update(arguments=args,card=extension.parse_extension_card(**args['card_arguments'],now=now))
        cal=args['card_arguments']['calendar_receipt'];listed=dict(
            raw_bytes=args['card_arguments']['list_raw'],expected_sha256=args['card_arguments']['list_sha256'],
            observed_at=args['card_arguments']['list_observed_at'],venue_code=98,http_status=200)
        registry=extension.register_day(calendar_receipt=cal,list_sources=[listed],event_day='2030-01-15',now=now)
        inventory=dict(registry=registry,calendar_receipt=cal,list_sources=[listed],source_bytes_by_sha={},
            state='DAY_SOURCES_CAPTURED',provider_denied=False,failure_code=None,source_receipts=[])
        lease=FakeLease();store=FakeStore('/synthetic','2030-01-15')
        class Session:
            halted=False;provider_denied=False;safe_diagnostics=[];count=0;sources={};receipts=[]
            request=None
            def has_capture_capacity(self, requests, *, seconds=0):
                return capacity[0] >= requests and capacity[1] > seconds
            def close(self):pass
        session=Session()
        captured_at = now
        def collect_baseline(**kwargs):
            nonlocal captured_at
            if history_cutoff_margin is not None:
                cutoff = datetime.fromisoformat(candidate['snapshot']['published_cutoff_at'])
                captured_at = cutoff - timedelta(seconds=history_cutoff_margin)
            return candidate
        def collect_history(**kwargs):
            session.halted=history_unavailable
            raise ValueError('PRIVATE_HISTORY_FAILURE')
        public=Path(folder)/'public.pem';public.write_bytes(self.public)
        root=Path(folder)/'private';root.mkdir(mode=0o700)
        env={'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123456789'}
        with (patch.dict('os.environ',env),
              patch.object(self.api(),'_runtime',return_value=(Path('/synthetic'),root,'2030-01-15',self.public,'a'*40)),
              patch.object(self.api(),'_begin_lease',return_value=lease),
              patch.object(self.api().records,'RecordStore',return_value=store),
              patch.object(self.api(),'_baseline_already_exists',return_value=existing),
              patch.object(sources,'OfficialSourceSession',return_value=session),
              patch.object(extension,'collect_day_inventory',return_value=inventory),
              patch.object(sources,'collect_candidate',side_effect=collect_baseline) as collect,
              patch.object(sources,'collect_conditions',side_effect=collect_history),
              patch.object(self.api().archive,'append_once',return_value={'state':'GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED'})):
            out=self.api().run_capture(repo='/synthetic',private_root=root,owner_public_pem=public,
                owner_private_pem=self.private,day='2030-01-15',clock=lambda:captured_at,max_races=1)
        return out,store,collect,lease

    def test_condition_failure_still_archives_baseline_and_keeps_full_day_denominator(self):
        with tempfile.TemporaryDirectory() as folder:
            out,store,collect,lease=self.run_fixture(folder)
        self.assertEqual(out['registered_races'],3)
        self.assertEqual(out['new_A_B_git_archived'],1)
        self.assertEqual(out['new_conditioned_A_B_git_archived'],0)
        saved=[r['payload'] for r in store.saved if r['kind']=='original']
        self.assertEqual(len(saved),1);self.assertIsNone(saved[0]['conditioned'])
        self.assertGreater(len(saved[0]['baseline']['A']['ranked_tickets']),0)
        self.assertLessEqual(len(saved[0]['baseline']['A']['ranked_tickets']),12)
        day=[r['payload'] for r in store.saved if r['kind']=='registry'][-1]
        self.assertEqual(len(day['states']),3)
        self.assertNotIn('PRIVATE_HISTORY_FAILURE',str(out))
        self.assertEqual(len(lease.finished),1)

    def test_intentional_capacity_deferral_keeps_attempt_counters_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            out,store,collect,lease=self.run_fixture(folder,capacity=(5,900))
        collect.assert_not_called()
        self.assertGreater(out['statuses']['SOURCE_CAPTURE_BUDGET_PENDING'],0)
        self.assertNotIn('SOURCE_UNAVAILABLE',out['statuses'])
        self.assertEqual(store.saved[-1]['payload']['source_attempt_counts'],{})
        self.assertEqual(out['source_requests'],0)
        self.assertEqual(lease.finished,['PARTIAL'])

    def test_baseline_is_still_frozen_when_history_cannot_fit_its_full_budget(self):
        for capacity in ((40,900),(300,150)):
            with self.subTest(capacity=capacity), tempfile.TemporaryDirectory() as folder:
                out,store,collect,lease=self.run_fixture(folder,capacity=capacity)
                self.assertEqual(out['new_A_B_git_archived'],1)
                self.assertEqual(out['new_conditioned_A_B_git_archived'],0)
                saved=[r['payload'] for r in store.saved if r['kind']=='original'][0]
                self.assertEqual(saved['condition_state'],'HISTORY_NOT_COLLECTED')
                self.assertIsNone(saved['conditioned'])
                self.assertFalse(out['provider_denied'])
                self.assertNotIn('SOURCE_UNAVAILABLE',out['statuses'])
                self.assertEqual(lease.finished,['PARTIAL'])

    def test_near_cutoff_defers_history_while_the_baseline_can_still_be_frozen(self):
        with tempfile.TemporaryDirectory() as folder:
            out,store,_,lease=self.run_fixture(folder,history_cutoff_margin=340)
        self.assertEqual(out['new_A_B_git_archived'],1)
        saved=[r['payload'] for r in store.saved if r['kind']=='original'][0]
        self.assertEqual(saved['condition_state'],'HISTORY_NOT_COLLECTED')
        self.assertEqual(lease.finished,['PARTIAL'])

    def test_true_source_failure_keeps_its_stop_even_after_freezing_a_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            out,store,collect,lease=self.run_fixture(folder,history_unavailable=True)
        self.assertEqual(out['new_A_B_git_archived'],1)
        self.assertEqual(out['state'],'HOLD_OFFICIAL_SP_SOURCE_UNAVAILABLE')

    def test_existing_original_never_fetches_sources_or_regenerates_for_that_race(self):
        with tempfile.TemporaryDirectory() as folder:
            out,store,collect,lease=self.run_fixture(folder,existing=True)
        collect.assert_not_called()
        self.assertEqual(out['new_A_B_git_archived'],0)
        self.assertFalse(any(r['kind']=='original' for r in store.saved))

    def test_eight_baselines_and_class_samples_fit_after_two_full_history_attempts(self):
        api = self.api()
        inventory, _ = cutoff_fixture((97, 98, 99))
        store = FakeStore('/synthetic', DAY)
        lease = FakeLease()
        session = Mock(halted=False, provider_denied=False, count=11, safe_diagnostics=[])
        session.has_capture_capacity.side_effect = lambda requests, *, seconds: session.count + requests <= 300
        generated = []

        def collect_baseline(*, session, inventory, race, clock):
            session.count += 11 if generated else 18
            generated.append(race['race_id'])
            return dict(snapshot=dict(published_cutoff_at=(AT+timedelta(hours=1)).isoformat()))

        def collect_history(**kwargs):
            session.count += 90
            raise api.sources.CaptureBudgetPending('CONDITION_CAPTURE_BUDGET')

        def collect_classes(**kwargs):
            session.count += 6
            return {'safe_summary': []}

        runtime = (Path('/synthetic'), Path('/private'), DAY, self.public, 'a'*40)
        with (patch.dict('os.environ',{'GITHUB_RUN_ID':'123456789','GITHUB_SHA':'a'*40}),
              patch.object(api,'_runtime',return_value=runtime),
              patch.object(api,'_begin_lease',return_value=lease),
              patch.object(api,'_baseline_already_exists',return_value=False),
              patch.object(api,'_seal_and_archive',return_value=({},'HISTORY_NOT_COLLECTED')),
              patch.object(api.records,'RecordStore',return_value=store),
              patch.object(api.capture_files,'_private_directory',return_value=Path('/private')),
              patch.object(api.sources,'OfficialSourceSession',return_value=session),
              patch.object(api.sources,'collect_candidate',side_effect=collect_baseline),
              patch.object(api.sources,'collect_conditions',side_effect=collect_history) as history,
              patch.object(extension,'collect_day_inventory',return_value=inventory),
              patch('race_ai.keirin_official_class_evidence.collect_unknown_class_evidence',
                    side_effect=collect_classes) as classes):
            result = api.run_capture(repo='/synthetic',private_root='/private',owner_public_pem='/public',
                owner_private_pem=self.private,day=DAY,clock=lambda:AT,max_races=8)
        self.assertEqual(result['new_A_B_git_archived'],8)
        self.assertEqual(history.call_count,2)
        classes.assert_called_once()
        self.assertEqual(result['source_requests'],292)
        self.assertEqual(result['statuses']['SOURCE_CAPTURE_BUDGET_PENDING'],1)
        self.assertEqual(store.saved[-1]['payload']['source_attempt_counts'],dict.fromkeys(generated,1))
        self.assertEqual(lease.finished,['PARTIAL'])

    def test_later_capture_uses_the_saved_queue_after_early_source_holds(self):
        from tests.test_keirin_official_sp_receipt import AT, DAY, calendar_receipt, html, list_data

        api=self.api()
        cal=calendar_receipt()
        raw=html(list_data())
        listed=dict(venue_code=98,raw_bytes=raw,expected_sha256=sha256(raw).hexdigest(),
                    observed_at=AT,http_status=200)
        registry=extension.register_day(calendar_receipt=cal,list_sources=[listed],event_day=DAY,now=AT)
        inventory=dict(registry=registry,calendar_receipt=cal,list_sources=[listed])
        ids=sorted(registry['registered_race_ids'])
        state=dict(race_id=ids[0],state='BASELINE_SOURCE_UNVERIFIED',condition_state='HISTORY_NOT_COLLECTED')
        previous=dict(schema=api.records.DAY_SCHEMA,day_jst=DAY,observed_at=AT.isoformat(),registry=registry,
            prior_race_ids=[],inventory=dict(calendar_receipt=cal,list_sources=[listed]),
            states=[state]+[dict(state,race_id=rid,state='SOURCE_CAPTURE_BUDGET_PENDING') for rid in ids[1:]])
        store=FakeStore('/synthetic',DAY)
        store.index['registry']={'evidence_sha256':'b'*64}
        attempted=[]
        def collect(*, session, inventory, race, clock):
            attempted.append(race['race_id'])
            raise ValueError('CARD_LAYOUT_NOT_AVAILABLE')
        session=Mock(halted=False,provider_denied=False,count=0,safe_diagnostics=[])
        runtime=(Path('/synthetic'),Path('/private'),DAY,self.public,'a'*40)
        with (patch.dict('os.environ',{'GITHUB_RUN_ID':'123456789','GITHUB_SHA':'a'*40}),
              patch.object(store,'read',side_effect=lambda meta,key:previous if not store.saved else store.saved[-1]['payload'],
                           create=True),
              patch.object(api,'_runtime',return_value=runtime),
              patch.object(api,'_begin_lease',return_value=FakeLease()),
              patch.object(api,'_baseline_already_exists',return_value=False),
              patch.object(api,'_label',return_value='S級一次予選1'),
              patch.object(api.records,'RecordStore',return_value=store),
              patch.object(api.capture_files,'_private_directory',return_value=Path('/private')),
              patch.object(api.sources,'OfficialSourceSession',return_value=session),
              patch.object(api.sources,'collect_candidate',side_effect=collect),
              patch.object(extension,'collect_day_inventory',return_value=inventory),
              patch('race_ai.keirin_official_class_evidence.collect_unknown_class_evidence',
                    return_value={'safe_summary':[]})):
            for _ in ids:
                result=api.run_capture(repo='/synthetic',private_root='/private',owner_public_pem='/public',
                    owner_private_pem=self.private,day=DAY,clock=lambda:AT,max_races=1)
        self.assertEqual(attempted,ids[1:]+ids[:1])
        latest=store.saved[-1]['payload']
        self.assertEqual(latest['source_attempt_counts'],dict.fromkeys(ids,1)|{ids[0]:2})
        self.assertEqual(result['new_A_B_git_archived'],0)

    def test_cutoff_priority_requires_an_untampered_current_official_card(self):
        from race_ai import keirin_official_class_evidence as evidence

        inventory, records = cutoff_fixture()
        record = next(row for row in records if row['race_id'] == '203001159901')
        day = dict(day_jst=DAY, observed_at=AT.isoformat(), registry=inventory['registry'],
                   inventory={k:inventory[k] for k in ('calendar_receipt','list_sources')},
                   unadmitted_class_evidence=dict(schema=evidence.SCHEMA, day_jst=DAY,
                       model_generation=0, records=[record],
                       safe_summary=[{'race_id':record['race_id'], 'official_cutoff_at':'untrusted'}]))
        expected = datetime.fromisoformat(f'{DAY}T12:47:00+09:00')
        self.assertEqual(evidence.replay_cutoff_hints(day, inventory, now=AT),
                         {record['race_id']:expected})
        opening_boundary = expected - timedelta(seconds=65)
        self.assertEqual(evidence.replay_cutoff_hints(day, inventory, now=opening_boundary),
                         {record['race_id']:expected})

        for changed in ('body', 'post', 'detail-clock', 'current-reference', 'current-label',
                        'too-close', 'expired'):
            with self.subTest(changed=changed):
                saved, current, now = deepcopy(day), deepcopy(inventory), AT
                raw = saved['unadmitted_class_evidence']['records'][0]['detail_source']
                if changed == 'body':
                    raw['raw_bytes'] = raw['raw_bytes'].replace(b'12:47', b'12:48')
                if changed == 'post':
                    raw['receipt']['form_fields']['encp'] = 'X' * 43
                if changed == 'detail-clock':
                    raw['observed_at'] = raw['receipt']['captured_at'] = (now + timedelta(seconds=1)).isoformat()
                if changed in ('current-reference', 'current-label'):
                    listing = current['list_sources'][1]
                    before, after = ((b'B' * 43, b'X' * 43) if changed == 'current-reference' else
                                     ('A級特予選'.encode(), 'A級予選'.encode()))
                    listing['raw_bytes'] = listing['raw_bytes'].replace(before, after)
                    listing['expected_sha256'] = sha256(listing['raw_bytes']).hexdigest()
                    current['registry'] = extension.register_day(calendar_receipt=current['calendar_receipt'],
                        list_sources=current['list_sources'],event_day=DAY,now=now)
                if changed == 'too-close':
                    now = opening_boundary + timedelta(seconds=1)
                if changed == 'expired':
                    now = expected
                self.assertEqual(evidence.replay_cutoff_hints(saved, current, now=now), {})

    def test_capture_uses_the_cutoff_only_within_equal_attempt_and_race_number(self):
        from race_ai import keirin_official_class_evidence as evidence

        api = self.api()
        inventory, records = cutoff_fixture()
        registry = inventory['registry']
        ids = registry['registered_race_ids']
        previous = dict(schema=api.records.DAY_SCHEMA, day_jst=DAY, observed_at=AT.isoformat(),
            registry=registry, prior_race_ids=[],
            inventory={k:inventory[k] for k in ('calendar_receipt','list_sources')},
            states=[dict(race_id=rid,state='SOURCE_CAPTURE_BUDGET_PENDING',
                         condition_state='HISTORY_NOT_COLLECTED') for rid in ids],
            source_attempt_counts={'203001159803':1},
            unadmitted_class_evidence=dict(schema=evidence.SCHEMA,day_jst=DAY,
                                           model_generation=0,records=records))
        store=FakeStore('/synthetic',DAY)
        store.index['registry']={'evidence_sha256':'b'*64}
        attempted=[]
        def collect(*, session, inventory, race, clock):
            attempted.append(race['race_id'])
            raise ValueError('CARD_LAYOUT_NOT_AVAILABLE')
        session=Mock(halted=False,provider_denied=False,count=0,safe_diagnostics=[])
        runtime=(Path('/synthetic'),Path('/private'),DAY,self.public,'a'*40)
        with (patch.dict('os.environ',{'GITHUB_RUN_ID':'123456789','GITHUB_SHA':'a'*40}),
              patch.object(store,'read',return_value=previous,create=True),
              patch.object(api,'_runtime',return_value=runtime),
              patch.object(api,'_begin_lease',return_value=FakeLease()),
              patch.object(api,'_baseline_already_exists',return_value=False),
              patch.object(api.records,'RecordStore',return_value=store),
              patch.object(api.capture_files,'_private_directory',return_value=Path('/private')),
              patch.object(api.sources,'OfficialSourceSession',return_value=session),
              patch.object(api.sources,'collect_candidate',side_effect=collect),
              patch.object(extension,'collect_day_inventory',return_value=inventory),
              patch.object(evidence,'collect_unknown_class_evidence',return_value={'safe_summary':[]})):
            result=api.run_capture(repo='/synthetic',private_root='/private',owner_public_pem='/public',
                owner_private_pem=self.private,day=DAY,clock=lambda:AT,max_races=6)
        self.assertEqual(attempted, ['203001159901','203001159801','203001159902','203001159802',
                                     '203001159903','203001159803'])
        self.assertEqual(result['new_A_B_git_archived'],0)
        self.assertEqual(store.saved[-1]['payload']['source_attempt_counts'],
                         dict.fromkeys(ids,1)|{'203001159803':2})

    def test_new_original_binds_the_same_confidence_in_source_bundle_and_both_cipher_arms(self):
        from race_ai import keirin_nationwide_auto_settlement as decrypt
        with tempfile.TemporaryDirectory() as folder:
            _,store,_,_=self.run_fixture(folder)
            saved=next(r['payload'] for r in store.saved if r['kind']=='original')
            self.assertIn('confidence_assessment',set(saved))
            raw=(Path(folder)/'private'/saved['race_id']/(saved['race_id']+'.sealed.json')).read_bytes()
            _,baseline,_,assessment=decrypt.decrypt_original_with_assessment(raw_cipher=raw,
                expected_cipher_sha256=saved['baseline_cipher_sha256'],owner_private_pem=self.private)
        self.assertEqual(assessment,saved['confidence_assessment'])
        self.assertEqual(baseline,saved['baseline'])
        self.assertNotIn('confidence_assessment',baseline)

    def test_publish_loads_only_the_needed_archive_blobs_from_a_temporary_shallow_view(self):
        from race_ai import keirin_nationwide_forecast_view as view

        api = self.api()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, private = folder / 'source', folder / 'private'
            source.mkdir(); private.mkdir(mode=0o700)
            def git(*args, cwd=source):
                return subprocess.check_output(['git', *map(str,args)], cwd=cwd,
                    stderr=subprocess.DEVNULL, text=True).strip()
            git('init', '-q')
            git('switch', '-q', '-c', api.archive.BRANCH)
            git('config', 'uploadpack.allowFilter', 'true')
            git('config', 'uploadpack.allowAnySHA1InWant', 'true')
            irrelevant = source / 'unneeded-ciphertext'
            irrelevant.write_bytes(b'invented unrelated bytes')
            blob = git('hash-object', irrelevant)
            git('add', irrelevant.name)
            git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','initial')
            inventory, _ = cutoff_fixture()
            registry = inventory['registry']
            payload = dict(schema=api.records.DAY_SCHEMA,day_jst=DAY,observed_at=AT.isoformat(),
                producer_run_id='123456789',producer_commit='a'*40,prior_race_ids=[],registry=registry,
                inventory={key:inventory[key] for key in ('calendar_receipt','list_sources')},
                safe_report=dict(day_jst=DAY,registered_races=len(registry['registered_race_ids'])),
                states=[dict(race_id=rid,state='WAITING_SOURCE_CAPTURE',
                             condition_state='HISTORY_NOT_COLLECTED')
                        for rid in registry['registered_race_ids']])
            raw = api.history.seal_evidence(api.records.wire(payload),self.public,DAY,AT.isoformat())
            digest = api.history._checked_cipher(raw)['evidence_plaintext_sha256']
            path = source / api.records.ROOT / DAY
            path.mkdir(parents=True)
            (path / (digest+'.sealed.json')).write_bytes(raw)
            index = dict(api.records._empty(DAY),registry=dict(
                kind='registry',evidence_sha256=digest,cipher_sha256=sha256(raw).hexdigest(),
                observed_at=AT.isoformat(),producer_run_id='123456789',producer_commit='a'*40))
            (path / 'index.json').write_bytes(api.history._canonical(index))
            git('add', api.records.ROOT)
            git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','registry')

            checked_out = folder / 'protected-checkout'
            runtime = (checked_out,private,DAY,self.public,'b'*40)
            command, remote, load = api.archive._cmd, api.archive._remote, api.records.load_admitted_day
            fetches, views = [], []
            def local_git(repo,*args,**kwargs):
                if args[:3] == ('remote','add','origin'):
                    self.assertEqual(args[3:],(f'https://github.com/{api.archive.REPO}.git',))
                    args = (*args[:3],source.as_uri())
                if args[0] == 'fetch':
                    fetches.append(args)
                return command(repo,*args,**kwargs)
            def local_archive(repo,*,synthetic_local):
                self.assertFalse(synthetic_local)
                return remote(repo,synthetic_local=True)
            def read_archive(repo,*args,**kwargs):
                self.assertEqual(Path(repo).parent,private)
                views.append(Path(repo))
                result = load(repo,*args,**kwargs)
                tracking = f'refs/remotes/origin/{api.archive.BRANCH}'
                self.assertEqual(git('rev-list','--count',tracking,cwd=repo),'1')
                self.assertIn('?'+blob,git('rev-list','--missing=print','--objects',tracking,cwd=repo))
                self.assertEqual(result['registry'],registry)
                return result
            with (patch.object(api,'_runtime',return_value=runtime),
                  patch.object(api.archive,'_cmd',side_effect=local_git),
                  patch.object(api.archive,'_remote',side_effect=local_archive),
                  patch.object(api.records,'load_admitted_day',side_effect=read_archive),
                  patch.object(view,'publish_day',return_value={
                      'state':'EXISTING_NATIONWIDE_DISPLAY_REUSED','provider_requests':0}) as publish):
                report=api.run_publish(repo=checked_out,private_root=private,owner_public_pem='/public',
                    owner_private_pem=self.private,day=DAY,clock=lambda:AT)
            branch = api.archive.BRANCH
            self.assertEqual(fetches,[('fetch','--no-tags','--depth=1','--filter=blob:none',
                '--no-recurse-submodules','origin',f'refs/heads/{branch}:refs/remotes/origin/{branch}')])
            self.assertEqual(len(views),1)
            self.assertFalse(views[0].exists())
            self.assertEqual(publish.call_args.args[0],checked_out)
            self.assertEqual(publish.call_args.args[1]['registry'],registry)
            self.assertEqual(report['source_requests'],0)

    def test_settlement_archive_timeout_reports_a_hold_before_any_provider_call(self):
        api = self.api()
        context = api.SettlementContext()
        timed_out = api.archive.GitCipherFetchTimeout('GIT_COMMAND_OR_REMOTE_UNAVAILABLE')
        with (patch.object(api.records, 'RecordStore', side_effect=timed_out) as store,
              patch.object(context, 'ensure') as open_provider):
            report = api.settle_tick(repo='/synthetic', owner_private_pem=self.private,
                private_root='/synthetic', clock=lambda: AT, context=context, days=[DAY],
                source_commit='a'*40)
        store.assert_called_once_with('/synthetic', DAY, retry_archive_timeout=True)
        open_provider.assert_not_called()
        self.assertEqual(report['source_requests'], 0)
        self.assertTrue(report['no_provider_tick'])
        self.assertEqual(report['safe_holds'],
                         [{'stage': 'RESULT_ARCHIVE_FETCH', 'code': 'ENCRYPTED_ARCHIVE_FETCH_TIMEOUT'}])
        self.assertFalse(context.allow_archive_timeout_retry())

    def test_pending_current_day_rotates_and_newly_due_order_precedes_unit_retry(self):
        api=self.api();context=api.SettlementContext();context.client=object();context.tick=1
        store=FakeStore('/synthetic','2030-01-15')
        ids=['2030011598'+str(n).zfill(2) for n in range(1,5)]
        store.index['originals']={rid:dict(race_id=rid,cutoff_at='2030-01-15T12:00:00+09:00') for rid in ids}
        store.read=lambda meta,key:dict(race_id=meta['race_id'])
        clock=lambda:datetime.fromisoformat('2030-01-15T15:00:00+09:00')
        with patch.object(api.records,'RecordStore',return_value=store),\
                patch.object(api.records,'admit_original',side_effect=lambda store,payload,key,**kw:(payload,{})):
            first,_=api._pending_originals('/synthetic',self.private,clock,context,2,days=[store.day])
            context.tick+=1
            second,_=api._pending_originals('/synthetic',self.private,clock,context,2,days=[store.day])
        self.assertEqual([r['original']['race_id'] for r in first],ids[:2])
        self.assertEqual([r['original']['race_id'] for r in second],ids[2:])

    def test_archive_success_publication_failure_recovers_on_next_tick_without_result_fetch(self):
        api=self.api();day='2030-01-15';rid='203001159801';clock=lambda:datetime.fromisoformat(day+'T15:00:00+09:00')
        store=FakeStore('/synthetic',day);meta=dict(race_id=rid,cutoff_at=day+'T12:00:00+09:00',evidence_sha256='a'*64)
        store.index['originals'][rid]=meta
        payload=dict(race_id=rid);store.read=lambda receipt,key:payload
        original=dict(race_id=rid,day_jst=day)
        events=[]
        def append(**kwargs):
            events.append('archive')
            store.index['results'][rid]=[dict(evidence_sha256='b'*64,monetary_complete=True)]
            return store.index['results'][rid][-1]
        store.append=append
        context=api.SettlementContext();context.client=object()
        session=Mock(halted=False,provider_denied=False,count=0,safe_diagnostics=[])
        context.ensure=Mock(return_value=session)
        doc={'races':[]};scored=dict(official_result=dict(source_sha256='c'*64),monetary_comparison_eligible=True,comparison=None)
        def publish(*args):
            events.append('publish')
            if events.count('publish')==1:raise ValueError('PRIVATE_PUBLISH_FAILURE')
            return dict(published_races=1)
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'123456789','GITHUB_SHA':'a'*40}),\
                patch.object(api.pipeline,'check_owner_private_key',return_value=self.public),\
                patch.object(api.records,'RecordStore',return_value=store),\
                patch.object(api.records,'admit_original',return_value=(original,{})),\
                patch.object(api.extension,'collect_day_inventory',return_value={'registry':{},'list_sources':[]}),\
                patch.object(api.sources,'collect_final',return_value={}) as collect,\
                patch.object(api.records,'archived_original',return_value=(b'base',None)),\
                patch.object(api.records,'compare_result',return_value=scored),\
                patch.object(api.records,'result_updates',return_value=doc),\
                patch.object(api.records,'replay_saved_result',return_value=doc) as replay,\
                patch.object(api,'_join_updates',return_value=doc),\
                patch.object(api,'_publish_result',side_effect=publish):
            first=api.settle_tick(repo='/synthetic',owner_private_pem=self.private,private_root='/private',
                clock=clock,context=context,days=[day])
            second=api.settle_tick(repo='/synthetic',owner_private_pem=self.private,private_root='/private',
                clock=clock,context=context,days=[day])
        self.assertEqual(events,['archive','publish','publish'])
        self.assertEqual(collect.call_count,1)
        self.assertEqual(context.ensure.call_count,1)
        self.assertEqual(replay.call_count,1)
        self.assertEqual(first['settled_races'],1)
        self.assertEqual(second['published_races'],1)
        self.assertTrue(second['no_provider_tick'])
        self.assertNotIn('PRIVATE_PUBLISH_FAILURE',str(first))

    def test_ordinary_tick_recovers_original_before_result_while_provider_is_stopped(self):
        from race_ai import keirin_nationwide_forecast_view as display
        api=self.api();day='2030-01-15';rid='203001159801'
        store=FakeStore('/synthetic',day)
        store.index.update(registry={'evidence_sha256':'a'*64},originals={rid:{'evidence_sha256':'b'*64}},
            results={rid:[dict(evidence_sha256='c'*64,monetary_complete=True)]})
        admitted={'records':[dict(race_id=rid,condition_state='NO_CONDITIONED_ORIGINAL')],
            'states':[dict(race_id=rid,state='A_B_AUTHENTICATED_PRE_CUTOFF',condition_state='NO_CONDITIONED_ORIGINAL')]}
        context=api.SettlementContext();events=[];doc={'races':[]}
        def original(*args):
            events.append('original')
            return dict(state='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',provider_requests=0,
                published_originals=1,published_day_status=1)
        def result(*args):events.append('result');return dict(published_races=1)
        with patch.dict('os.environ',{'GITHUB_SHA':'a'*40,'RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED':'false'}),\
                patch.object(api.pipeline,'check_owner_private_key',return_value=self.public),\
                patch.object(api.records,'RecordStore',return_value=store),\
                patch.object(api.records,'load_admitted_day',return_value=admitted) as load,\
                patch.object(display,'publish_day',side_effect=original) as publish,\
                patch.object(api.records,'replay_saved_result',return_value=doc),\
                patch.object(api,'_publish_result',side_effect=result),\
                patch.object(api,'_pending_originals',return_value=([{}],0)),\
                patch.object(api,'_begin_lease',side_effect=ValueError('PERSISTENT_SOURCE_STOP')) as gate,\
                patch.object(api.sources,'OfficialSourceSession') as transport,\
                patch.object(api,'_join_updates',return_value=doc):
            first=api.settle_tick(repo='/synthetic',owner_private_pem=self.private,private_root='/private',
                clock=lambda:datetime.fromisoformat(day+'T15:00:00+09:00'),context=context,days=[day])
            api.settle_tick(repo='/synthetic',owner_private_pem=self.private,private_root='/private',
                clock=lambda:datetime.fromisoformat(day+'T15:01:00+09:00'),context=context,days=[day])
        self.assertEqual(events,['original','result'])
        self.assertEqual(first['published_originals'],1);self.assertEqual(first['published_races'],1)
        self.assertEqual(first['source_requests'],0);self.assertTrue(first['no_provider_tick'])
        self.assertEqual(load.call_count,1);self.assertEqual(publish.call_count,1)
        self.assertEqual(gate.call_count,2);transport.assert_not_called()

    def test_original_recovery_retries_failed_or_pending_admission_before_caching(self):
        from race_ai import keirin_nationwide_forecast_view as display
        api=self.api();context=api.SettlementContext();store=FakeStore('/synthetic','2030-01-15')
        rid='203001159801';store.index.update(registry={'evidence_sha256':'a'*64},originals={rid:{'evidence_sha256':'b'*64}})
        pending={'records':[],'states':[dict(race_id=rid,state='ORIGIN_PROOF_PENDING',condition_state='NO_CONDITIONED_ORIGINAL')]}
        ready={'records':[dict(race_id=rid,condition_state='NO_CONDITIONED_ORIGINAL')],
            'states':[dict(race_id=rid,state='A_B_AUTHENTICATED_PRE_CUTOFF',condition_state='NO_CONDITIONED_ORIGINAL')]}
        ack=dict(state='KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',provider_requests=0,
            published_originals=0,published_day_status=1)
        with patch.object(api.records,'RecordStore',return_value=store),\
                patch.object(api.records,'load_admitted_day',side_effect=[pending,ready,ready]) as load,\
                patch.object(display,'publish_day',side_effect=[ack,ValueError('PRIVATE_PUBLISH_ERROR'),ack]) as publish:
            for number in range(1,5):
                context.tick=number;context.stores={}
                report=dict(published_originals=0,original_publication_acks=0,published_day_status=0,origin_held=0)
                api._recover_saved_originals('/synthetic',self.private,context,[store.day],'a'*40,True,report)
        self.assertEqual(load.call_count,3);self.assertEqual(publish.call_count,3)
        self.assertNotIn('PRIVATE_PUBLISH_ERROR',str(context.safe_holds))

    def test_tick_refreshes_real_mutable_origin_metadata_but_preserves_artifacts_and_denial(self):
        from race_ai.keirin_github_evidence_client import GitHubEvidenceClient,API
        from tests.test_keirin_github_origin_evidence import evidence_fixture
        from tests.test_keirin_github_evidence_client import Response
        from urllib.error import HTTPError
        producer,reader=evidence_fixture();ready=False;calls=[];denied=False
        payloads={API+'/actions/runs/123456':producer['run'],
            API+'/actions/runs/123456/jobs?per_page=100&filter=all':dict(total_count=2,jobs=[producer['job'],reader['job']])}
        archives={p['artifact']['archive_download_url']:p['archive_bytes'] for p in (producer,reader)}
        def request(req,**kwargs):
            calls.append(req.full_url)
            if denied:raise HTTPError(req.full_url,403,'PRIVATE_DENIAL_TOKEN',{},None)
            if req.full_url in archives:return Response(archives[req.full_url],url=req.full_url)
            if req.full_url.endswith('/artifacts?per_page=100'):
                body=dict(total_count=2 if ready else 1,artifacts=[producer['artifact'],reader['artifact']] if ready else [producer['artifact']])
            else:body=payloads[req.full_url]
            return Response(json.dumps(body).encode(),url=req.full_url)
        context=self.api().SettlementContext();context.client=GitHubEvidenceClient(token='',open_request=request)
        context.packet_cache['completed']=object();saved_packet=context.packet_cache['completed']
        immutable='/actions/artifacts/'+str(producer['artifact']['id'])+'/zip'
        context.client._read(immutable,archive=True)
        with self.assertRaises(ValueError):context.client.read_run_bundle('123456')
        ready=True
        self.api()._refresh_origin_metadata(context)
        bundle=context.client.read_run_bundle('123456')
        self.assertEqual(bundle['readback']['artifact']['id'],reader['artifact']['id'])
        self.assertEqual(calls.count(API+immutable),1)
        self.assertIs(context.packet_cache['completed'],saved_packet)
        denied=True;self.api()._refresh_origin_metadata(context)
        with self.assertRaisesRegex(ValueError,'HTTP_403'):context.client.read_run_bundle('123456')
        count=len(calls);self.api()._refresh_origin_metadata(context)
        with self.assertRaisesRegex(ValueError,'HTTP_403'):context.client.read_run_bundle('123456')
        self.assertEqual(len(calls),count)


if __name__=='__main__':unittest.main()
