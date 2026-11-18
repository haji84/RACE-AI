"""Synthetic saved-grid comparisons with pinned readers; no live source requests."""
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT/'closed-a74-source'
sys.path.insert(0, str(OWNER))
import race_ai, scripts, tests
race_ai.__path__[:] = [str(OWNER/'race_ai')] + [
    str(ROOT/'owner-source'/folder/'race_ai')
    for folder in ('pr64-reference', 'pr72-reference')]
scripts.__path__[:] = [str(OWNER/'scripts')]
tests.__path__[:] = [str(OWNER/'tests'), str(ROOT/'tests')] + [
    str(ROOT/'owner-source'/folder/'tests')
    for folder in ('pr64-reference', 'pr72-reference')]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


for short in ('boat_owner_evidence_audit', 'boat_exact_all_model_zip_readback',
              'boat_owner_active_snapshot_audit', 'boat_current_pair_eligibility_audit'):
    module = load_module('scripts.'+short, ROOT/'scripts'/(short+'.py'))
    setattr(scripts, short, module)
MODULE = ROOT/'scripts/boat_cutoff_raw_replay_audit.py'
replay = load_module('scripts.boat_cutoff_raw_replay_audit', MODULE) if MODULE.is_file() else None
if replay is not None:
    setattr(scripts, 'boat_cutoff_raw_replay_audit', replay)

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import base64
import inspect
import json
import os
import unittest
from unittest.mock import patch

from race_ai import boat_official_program as program
from race_ai import official_race_updates as updates
from race_ai import boat_private_original_vault as vault
from race_ai.all_existing_model_intake import _time
from race_ai import all_existing_model_registry as registry
from race_ai.actions_contract import digest
from race_ai.observed_p1_connection import RIGHTS
from scripts import boat_current_pair_eligibility_audit as pairs

KEY = bytes(range(32))
FIXED_RUN = 44218343091
FIXED_OWNER = 'a74f1e940e7fc0852e63938f8138bdb58bd93163'
FIXED_COMMIT = 'a1c2c4ae588b5b31b3e653d14fcf41bc3fc0dabe'
DAY = date(2026, 11, 18)
ARCHIVED = datetime(2026, 11, 18, 13, tzinfo=timezone.utc)
COUNTERS = ('comparison_count', 'program_grid_match_count', 'result_grid_match_count',
            'missing_raw_side_count', 'inspector_rejected_side_count', 'grid_clock_disagreed_side_count')


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def receipt(raw, url, captured):
    return wire(dict(source_url=url, captured_at=captured, http_status=200,
                     source_sha256=sha256(raw).hexdigest()))


class SavedGridFixture(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, RACE_AI_STATE_KEY=base64.b64encode(KEY).decode())
        environment.start(); self.addCleanup(environment.stop)
        self.program_fixture = load_module('_raw_grid_program_fixture', OWNER/'tests/test_boat_official_program.py')
        self.result_fixture = load_module('_raw_grid_result_fixture',
            ROOT/'owner-source/pr64-reference/tests/test_official_race_updates.py')
        self.vault_fixture = load_module('_raw_grid_vault_fixture', OWNER/'tests/test_boat_private_original_vault.py')
        self.parsers = {'A74_PROGRAM': program, 'PR64_RESULT': updates, 'receipt_json': vault._json}

    def program_ref(self, digest, source_ref, captured_at, *, url_form='EXACT',
                    proof_path='SOURCE_EVIDENCE'):
        return dict(source_sha256=digest, source_ref=source_ref, captured_at=captured_at,
                    url_form=url_form, proof_path=proof_path)

    def pure(self, first, latest, captures, *, parsers=None):
        report = replay.diagnose_saved_cutoff_raw_replay(
            first, latest, captures, parsers=self.parsers if parsers is None else parsers, parse_time=_time)
        self.assert_safe(report)
        return report

    def data(self):
        program_raw = self.program_fixture.page(venue='18', race_no=1).replace(b'20300401', b'20261118')
        result_raw = self.result_fixture.page('raceresult', self.result_fixture.results(), day=DAY).replace(
            b'08:43', b'20:31')
        program_url = 'https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd=18&hd=20261118'
        result_url = 'https://www.boatrace.jp/owpc/pc/race/raceresult?rno=1&jcd=18&hd=20261118'
        program_at, result_at = '2026-11-18T18:00:00+09:00', '2026-11-18T21:00:00+09:00'
        program_receipt = receipt(program_raw, program_url, program_at)
        result_receipt = receipt(result_raw, result_url, result_at)
        observed_program = program.parse_program(program_raw, day=DAY, venue='18', race_no=1,
            source_url=program_url, captured_at=program_at)
        observed_result = updates.parse_update(result_raw, kind='raceresult', day=DAY, venue='18',
            race_no=1, source_url=result_url, captured_at=result_at, entries=None)
        race = '20261118-18-01'
        ref = self.program_ref(sha256(program_raw).hexdigest(), program_url, program_at)
        descriptor = dict(race=('boat', race), artifact_id=800, record_sha256='b'*64,
            cutoff_at='2026-11-18T09:00:00Z',
            info=dict(race_id=race, race_cutoff_at=observed_program['closed_at'],
                      roster={str(n):str(4000+n) for n in range(1,7)}),
            _raw_program_ref=ref)
        return ({('boat', race, 'P1', 'one'): descriptor}, {race: observed_result},
                ((program_raw, program_receipt), (result_raw, result_receipt)))

    def native_ref_cases(self):
        # These isolate the eight already-admitted source-selection bodies;
        # complete pair admission is exercised separately with its real AES fixture.
        first,_,_ = self.data()
        descriptor = next(iter(first.values()))
        race,clock,ref = descriptor['race'][1],descriptor['info']['race_cutoff_at'],descriptor['_raw_program_ref']
        proof = dict(source_ref=ref['source_ref'],source_sha256=ref['source_sha256'],
                     captured_at=ref['captured_at'],source_rights_ref=RIGHTS,evidence_basis='HTTP_BODY_SHA256')
        roster = {str(n):str(4000+n) for n in range(1,7)}
        for group in ('boat_ab','boat_tactical','boat_clite','boat_observed',
                      'shared','shared_learned','boat_full','boat_pdca'):
            model_id = next(ids[0] for name,ids in registry.GROUPS if name == group)
            native = dict(scope='OPERATOR_SUPPLIED_RESEARCH',source_evidence=[deepcopy(proof)])
            source = dict(race_id=race,cutoff_at=clock,captured_at=ref['captured_at'],
                          program_source_sha256=ref['source_sha256'],
                          boats=[dict(lane=n,racer_id=str(4000+n)) for n in range(1,7)])
            if group in ('boat_ab','boat_tactical'):
                native['source'] = source
            elif group == 'boat_clite':
                native['base_source'] = source
            elif group == 'boat_pdca':
                source['program_sha256'] = source.pop('program_source_sha256')
                source['source_url'] = ref['source_ref'].replace('/racelist?','/beforeinfo?')
                native['facts'] = source
            elif group in ('shared','shared_learned'):
                native['snapshot'] = dict(race=dict(race_id=race,sales_cutoff_at=clock,as_of=ref['captured_at']),
                    participants=[dict(number=n,identity=str(4000+n)) for n in range(1,7)])
            elif group == 'boat_full':
                native['snapshot'] = dict(race_id=race,sales_cutoff_at=clock,as_of=ref['captured_at'],
                    entrants=[dict(lane=n,participant_id=str(4000+n)) for n in range(1,7)])
            else:
                native.pop('source_evidence')
                native['snapshot'] = dict(race_id=race,stage='P1',sales_cutoff_at=clock,as_of=ref['captured_at'],
                    race_source_id='racelist-'+race,
                    participants=[dict(lane=n,registration_no=str(4000+n)) for n in range(1,7)],
                    sources=[dict(source_id='racelist-'+race,source_sha256=ref['source_sha256'],
                                  source_url='https://www.boatrace.jp/owpc/pc/race/racelist',
                                  captured_at=ref['captured_at'])])
            info = registry.identity(model_id,'boat',native,race_id=race)
            self.assertEqual(info['race_cutoff_at'],clock)
            self.assertEqual(info['roster'],roster)
            payload = dict(cell_key='boat/'+model_id,native_payload=native,source_sha256=digest(native),
                pair=dict(cell_key='boat/'+model_id,sport='boat',race_id=race,stage='P1',
                          input_sha256=digest(native),cutoff_at=clock,race_cutoff_at=clock))
            expected = dict(ref)
            if group == 'boat_observed':
                expected.update(source_ref='https://www.boatrace.jp/owpc/pc/race/racelist',
                                url_form='QUERY_FREE',proof_path='OBSERVED_RACE_SOURCE')
            yield group,payload,info,expected

    def local_vault(self, captures, *, head=FIXED_OWNER, later_captures=None, later_head=None):
        fixture = self.vault_fixture.VaultTests('runTest')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        writer = fixture.git('raw-grid-writer', ref=vault.VAULT_REF)
        reader = fixture.git('raw-grid-reader', ref=vault.VAULT_REF)
        parent = writer.commit({'unrelated/retained.enc': b'prior ciphertext'}, None)
        writer.push(parent, None)
        records = [vault._capture_record(captures, run_id=FIXED_RUN, head_sha=head, now=ARCHIVED)]
        for number in range(1,26):
            raw = ('<p>unrelated invented capture '+str(number)+'</p>').encode()
            metadata = receipt(raw,
                'https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=2&jcd=18&hd=20261118',
                '2026-11-18T18:'+str(number).zfill(2)+':00+09:00')
            selected = later_captures if number == 1 and later_captures is not None else ((raw,metadata),)
            producer = later_head if number == 1 and later_head is not None else head
            records.append(vault._capture_record(selected,run_id=FIXED_RUN,head_sha=producer,now=ARCHIVED))
        retained = vault._retain(records,writer.repo,expected_parent=parent,key=KEY,
            transport=writer,readback_transport=reader,now=ARCHIVED)
        self.assertEqual(retained['retained_originals'],26)
        self.assertEqual(len(retained['locators']),26)
        return fixture, writer, reader, retained['locators'][0]

    def alias_reader(self, reader, commit, *, overrides=None):
        calls = []
        owner = self
        class FixedLocalReader:
            repo = reader.repo
            ref = vault.VAULT_REF
            def fetch(self, selected):
                owner.assertEqual(selected, FIXED_COMMIT)
                calls.append(('fetch', selected))
                return reader.fetch(commit)
            def exists(self, selected, path):
                owner.assertEqual(selected, FIXED_COMMIT)
                calls.append(('exists', selected, path))
                return reader.exists(commit, path)
            def read(self, selected, path, maximum):
                owner.assertEqual(selected, FIXED_COMMIT)
                calls.append(('read', selected, path))
                if overrides is not None and path in overrides:
                    raw = overrides[path]
                    owner.assertLessEqual(len(raw), maximum)
                    return raw
                return reader.read(commit, path, maximum)
            def commit(self, *args, **kwargs):
                raise AssertionError('raw readback attempted commit')
            def push(self, *args, **kwargs):
                raise AssertionError('raw readback attempted push')
        return FixedLocalReader(), calls

    def fixed_adapter(self, first, latest, reader):
        def no_external_get(route):
            raise AssertionError('raw fixture has no external transport')
        def admitted(get, run_id, now, source, _diagnostic=None, _raw_cutoff_sink=None):
            self.assertIs(get, no_external_get)
            self.assertEqual((run_id, source), (FIXED_RUN, FIXED_OWNER))
            self.assertIs(now, ARCHIVED)
            self.assertTrue(callable(_raw_cutoff_sink))
            _raw_cutoff_sink(first, latest)
            raise ValueError('ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH')
        def reader_factory(repo, *, ref):
            self.assertEqual(Path(repo), Path(reader.repo))
            self.assertEqual(ref, vault.VAULT_REF)
            return reader
        before = deepcopy((first, latest))
        with patch.object(pairs, '_audit', side_effect=admitted), \
                patch.object(vault, 'VaultGitRepository', side_effect=reader_factory), \
                patch('urllib.request.urlopen', side_effect=AssertionError('provider GET')):
            result = replay.audit_fixed_a74_cutoff_raw_replay(
                get=no_external_get, repo=reader.repo, now=ARCHIVED)
        self.assertEqual((first, latest), before)
        return result

    def signed_header_change(self, writer, locator, change):
        _, mac_key = vault._keys(KEY)
        parent = locator['source_commit']
        signed_batch = vault._unsigned(writer.read(parent, locator['batch_path'], vault.MAX_INDEX), mac_key)
        entry = next(item for item in signed_batch['entries']
                     if sha256(vault._wire(item)).hexdigest() == locator['entry_sha256'])
        change(entry)
        batch_raw = vault._signed(signed_batch, mac_key)
        batch_sha = sha256(batch_raw).hexdigest()
        batch_path = vault.PREFIX+'2026-11/batches/'+batch_sha+'.json'
        reference = {name: locator[name] for name in
                     ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')}
        reference.update(batch_path=batch_path, batch_sha256=batch_sha,
                         entry_sha256=sha256(vault._wire(entry)).hexdigest())
        run_path = vault.PREFIX+'2026-11/runs/'+str(FIXED_RUN)+'.json'
        run = vault._unsigned(writer.read(parent, run_path, vault.MAX_INDEX), mac_key)
        for name, old in list(run['entries'].items()):
            if old['entry_sha256'] == locator['entry_sha256']:
                run['entries'][name] = reference
        run_raw = vault._signed(run, mac_key)
        month_path = vault.PREFIX+'2026-11/month.json'
        month = vault._unsigned(writer.read(parent, month_path, vault.MAX_INDEX), mac_key)
        month['runs'][str(FIXED_RUN)] = sha256(run_raw).hexdigest()
        changed = writer.commit({batch_path:batch_raw, run_path:run_raw,
                                 month_path:vault._signed(month,mac_key)}, parent)
        writer.push(changed, parent)
        return changed

    def assert_safe(self, report):
        self.assertEqual(set(report), {'schema','status','reason',*COUNTERS,
                                      'source_requests','originals_changed','broader_goals_proven'})
        self.assertEqual(report['schema'], 'RACE_AI_A74_SAVED_GRID_INSPECTION_COUNTS_V1')
        self.assertEqual(report['source_requests'], 0)
        self.assertIs(type(report['source_requests']), int)
        self.assertIs(report['originals_changed'], False)
        self.assertIs(report['broader_goals_proven'], False)
        public = json.dumps(report, allow_nan=False)
        for private in ('2026-11-18','20261118-18-01','https://','PRIVATE_SENTINEL',
                        'source_sha256','captured_at','roster','ordered_top3'):
            self.assertNotIn(private, public)
        if report['comparison_count'] is None:
            self.assertTrue(all(report[name] is None for name in COUNTERS))
        else:
            self.assertTrue(all(type(report[name]) is int and report[name]>=0 for name in COUNTERS))
            self.assertEqual(sum(report[name] for name in COUNTERS[1:]), 2*report['comparison_count'])

    def known(self, status, reason=None, **counts):
        values = dict.fromkeys(COUNTERS, 0); values.update(counts)
        return dict(schema='RACE_AI_A74_SAVED_GRID_INSPECTION_COUNTS_V1', status=status,
                    reason=reason, **values, source_requests=0,
                    originals_changed=False, broader_goals_proven=False)

    def held(self, reason):
        return dict(schema='RACE_AI_A74_SAVED_GRID_INSPECTION_COUNTS_V1', status='HOLD',
                    reason=reason, **dict.fromkeys(COUNTERS), source_requests=0,
                    originals_changed=False, broader_goals_proven=False)


class SavedGridCryptoControlTests(SavedGridFixture):
    def test_existing_fixed_inspectors_and_real_vault_fixture_establish_saved_grids(self):
        first, latest, captures = self.data()
        descriptor = next(iter(first.values()))
        self.assertEqual(descriptor['info']['race_cutoff_at'], '2026-11-18T20:30:00+09:00')
        self.assertEqual(latest['20261118-18-01']['closed_at'], '2026-11-18T20:31:00+09:00')
        self.assertNotEqual(_time(descriptor['info']['race_cutoff_at']),
                            _time(latest['20261118-18-01']['closed_at']))
        self.assertEqual(Path(program.__file__).resolve(), OWNER/'race_ai/boat_official_program.py')
        self.assertEqual(Path(vault.__file__).resolve(), OWNER/'race_ai/boat_private_original_vault.py')
        self.assertEqual(Path(updates.__file__).resolve(),
                         ROOT/'owner-source/pr64-reference/race_ai/official_race_updates.py')
        self.assertEqual(len(list(self.native_ref_cases())),8)
        _, writer, reader, locator = self.local_vault(captures)
        with patch('urllib.request.urlopen', side_effect=AssertionError('provider GET')):
            found = vault.list_originals('2026-11', reader.repo, source_commit=locator['source_commit'],
                                         run_id=FIXED_RUN, key=KEY, transport=reader)
            self.assertEqual(len(found), 26)
            selected = next(item for item in found if item['entry_sha256'] == locator['entry_sha256'])
            restored = vault.restore_capture_bundle(selected, reader.repo, key=KEY, transport=reader)
        self.assertEqual(tuple(restored['captures']), captures)
        self.assertEqual(restored['provenance']['receipt_scope'], 'OWNER_RETAINED_SOURCE_CAPTURES')
        self.assertIs(restored['provenance']['independent_git_readback_verified'], True)
        self.assertEqual(writer.head(), locator['source_commit'])


class CutoffRawReplayTests(SavedGridFixture):
    def setUp(self):
        self.assertIsNotNone(replay, 'fixed saved-grid raw replay audit module is missing')
        super().setUp()

    def test_fixed_inspectors_match_unequal_saved_clocks_and_deduplicate_only_identical_comparisons(self):
        first, latest, captures = self.data()
        race = '20261118-18-01'
        original = next(iter(first.values()))
        repeat = deepcopy(original)
        repeat['info']['race_cutoff_at'] = '2026-11-18T11:30:00Z'
        repeat['record_sha256'], repeat['artifact_id'] = 'c'*64, 801
        first[('boat', race, 'P1', 'two')] = repeat
        before = deepcopy((first, latest, captures))
        expected = self.known('SAVED_CLOCKS_MATCH_INSPECTED_GRIDS', comparison_count=1,
                              program_grid_match_count=1, result_grid_match_count=1)
        with patch('builtins.open',side_effect=AssertionError('pure inspector attempted file read')), \
                patch('urllib.request.urlopen',side_effect=AssertionError('pure inspector attempted source GET')), \
                patch.object(vault,'_keys',side_effect=AssertionError('pure inspector attempted key read')):
            self.assertEqual(self.pure(first, latest, captures+captures), expected)
        self.assertEqual((first, latest, captures), before)
        # Same source bodies but a different frozen first cutoff are two comparisons.
        repeat['info']['race_cutoff_at'] = '2026-11-18T20:29:00+09:00'
        self.assertEqual(self.pure(first, latest, captures), self.known(
            'HOLD', 'SAVED_CLOCK_DIFFERS_FROM_INSPECTED_GRID', comparison_count=2,
            program_grid_match_count=1, result_grid_match_count=2, grid_clock_disagreed_side_count=1))
        # Distinct authenticated program receipts also cannot be collapsed across cells.
        repeat['info']['race_cutoff_at'] = original['info']['race_cutoff_at']
        repeat['_raw_program_ref']['captured_at'] = '2026-11-18T18:01:00+09:00'
        extra_receipt = receipt(captures[0][0], original['_raw_program_ref']['source_ref'],
                                repeat['_raw_program_ref']['captured_at'])
        self.assertEqual(self.pure(first, latest, captures+((captures[0][0],extra_receipt),)), self.known(
            'SAVED_CLOCKS_MATCH_INSPECTED_GRIDS', comparison_count=2,
            program_grid_match_count=2, result_grid_match_count=2))

    def test_each_side_has_one_outcome_and_known_failures_do_not_repair_frozen_clocks(self):
        first, latest, captures = self.data()
        baseline = deepcopy((first, latest))
        repeated = deepcopy(next(iter(first.values())))
        first[('boat','20261118-18-01','P1','duplicate')] = repeated
        baseline = deepcopy((first, latest))
        for side in (0, 1):
            with self.subTest(side=side, outcome='missing'):
                selected = tuple(pair for index,pair in enumerate(captures) if index != side)
                counts = dict(comparison_count=1, missing_raw_side_count=1)
                counts['result_grid_match_count' if side == 0 else 'program_grid_match_count'] = 1
                self.assertEqual(self.pure(first, latest, selected), self.known('HOLD','RAW_CAPTURE_MISSING',**counts))
            for label, body, reason, counter in (
                    ('disagreed', captures[side][0].replace(b'20:30',b'20:29') if side == 0 else
                     captures[side][0].replace(b'20:31',b'20:32'),
                     'SAVED_CLOCK_DIFFERS_FROM_INSPECTED_GRID','grid_clock_disagreed_side_count'),
                    ('rejected', b'<html>PRIVATE_SENTINEL unsupported grid</html>',
                     'GRID_INSPECTOR_REJECTED','inspector_rejected_side_count')):
                with self.subTest(side=side, outcome=label):
                    changed_first, changed_latest = deepcopy((first, latest))
                    changed_captures = list(captures)
                    meta = json.loads(captures[side][1]);meta['source_sha256'] = sha256(body).hexdigest()
                    changed_captures[side] = (body,wire(meta))
                    if side == 0:
                        for item in changed_first.values():
                            item['_raw_program_ref']['source_sha256'] = meta['source_sha256']
                    else:
                        changed_latest['20261118-18-01']['source_sha256'] = meta['source_sha256']
                    counts = dict(comparison_count=1);counts[counter] = 1
                    counts['result_grid_match_count' if side == 0 else 'program_grid_match_count'] = 1
                    self.assertEqual(self.pure(changed_first,changed_latest,tuple(changed_captures)),
                                     self.known('HOLD',reason,**counts))
        self.assertEqual(self.pure(first,latest,()), self.known(
            'HOLD','RAW_CAPTURE_MISSING',comparison_count=1,missing_raw_side_count=2))
        self.assertEqual((first,latest),baseline)
        # A valid pending RESULT page still exposes its grid, not a fabricated result.
        pending = self.result_fixture.page('raceresult','<p>結果はまだありません。</p>',day=DAY).replace(
            b'08:43',b'20:31')
        meta = json.loads(captures[1][1]);meta['source_sha256'] = sha256(pending).hexdigest()
        pending_latest = deepcopy(latest);pending_latest['20261118-18-01']['source_sha256'] = meta['source_sha256']
        self.assertEqual(self.pure(first,pending_latest,(captures[0],(pending,wire(meta)))), self.known(
            'SAVED_CLOCKS_MATCH_INSPECTED_GRIDS',comparison_count=1,
            program_grid_match_count=1,result_grid_match_count=1))

    def test_supported_refs_are_explicit_and_unsafe_receipts_or_inspector_errors_are_redacted(self):
        first,latest,captures = self.data()
        descriptor = next(iter(first.values()))
        query_free = deepcopy(first)
        ref = next(iter(query_free.values()))['_raw_program_ref']
        ref.update(source_ref='https://www.boatrace.jp/owpc/pc/race/racelist',
                   url_form='QUERY_FREE',proof_path='OBSERVED_RACE_SOURCE')
        self.assertEqual(self.pure(query_free,latest,captures),self.known(
            'SAVED_CLOCKS_MATCH_INSPECTED_GRIDS',comparison_count=1,
            program_grid_match_count=1,result_grid_match_count=1))
        for group,payload,info,expected in self.native_ref_cases():
            with self.subTest(native_group=group):
                before = deepcopy(payload)
                actual = replay._program_ref_for_pair(payload,info=info,registry=registry,parse_time=_time)
                self.assertEqual(actual,expected)
                self.assertEqual(payload,before)
                bad_info = deepcopy(info);bad_info['race_cutoff_at'] = '2026-11-18T20:32:00+09:00'
                self.assertIsNone(replay._program_ref_for_pair(
                    payload,info=bad_info,registry=registry,parse_time=_time))
                if group != 'boat_observed':
                    ambiguous = deepcopy(payload)
                    second = deepcopy(ambiguous['native_payload']['source_evidence'][0])
                    second['captured_at'] = '2026-11-18T18:01:00+09:00'
                    ambiguous['native_payload']['source_evidence'].append(second)
                    ambiguous['source_sha256'] = digest(ambiguous['native_payload'])
                    ambiguous['pair']['input_sha256'] = ambiguous['source_sha256']
                    self.assertIsNone(replay._program_ref_for_pair(
                        ambiguous,info=info,registry=registry,parse_time=_time))
                else:
                    wrapped = deepcopy(payload)
                    original = deepcopy(wrapped['native_payload'])
                    wrapped['native_payload'].update(
                        original_native_payload=original,original_input_sha256=digest(original))
                    wrapped['source_sha256'] = digest(wrapped['native_payload'])
                    wrapped['pair']['input_sha256'] = wrapped['source_sha256']
                    expected_original = dict(expected,proof_path='ORIGINAL_OBSERVED_RACE_SOURCE')
                    self.assertEqual(replay._program_ref_for_pair(
                        wrapped,info=info,registry=registry,parse_time=_time),expected_original)
                    wrapped['native_payload']['original_input_sha256'] = 'e'*64
                    self.assertIsNone(replay._program_ref_for_pair(
                        wrapped,info=info,registry=registry,parse_time=_time))
        bad_refs = [
            dict(descriptor['_raw_program_ref'],proof_path='PRIVATE_SENTINEL'),
            dict(descriptor['_raw_program_ref'],url_form='GUESSED'),
            dict(descriptor['_raw_program_ref'],source_ref=descriptor['_raw_program_ref']['source_ref'].replace('rno=1','rno=2')),
            dict(descriptor['_raw_program_ref'],captured_at='2026-11-18T18:00:00'),
            dict(descriptor['_raw_program_ref'],source_sha256='urn:PRIVATE_SENTINEL'),
            None]
        for index,ref in enumerate(bad_refs):
            with self.subTest(reference=index):
                changed = deepcopy(first);next(iter(changed.values()))['_raw_program_ref'] = ref
                self.assertEqual(self.pure(changed,latest,captures),self.held('UNSUPPORTED_SOURCE_REF'))
        for field,value in (('http_status',403),('http_status',True),('source_sha256','a'*64),
                            ('source_url','https://private.invalid/PRIVATE_SENTINEL'),
                            ('captured_at','2026-11-18T18:00:00')):
            with self.subTest(receipt=field,value_type=type(value).__name__):
                metadata = json.loads(captures[0][1]);metadata[field] = value
                self.assertEqual(self.pure(first,latest,((captures[0][0],wire(metadata)),captures[1])),
                                 self.held('CAPTURE_AUTHENTICATION_UNAVAILABLE'))
        # Guards bound only this fixed diagnostic; they do not truncate producer data.
        too_many = {}
        for number in range(29):
            too_many[('boat','20261118-18-01','P1',str(number))] = deepcopy(descriptor)
        self.assertEqual(self.pure(too_many,latest,captures),self.held('RESOURCE_BOUND_EXCEEDED'))
        for oversized in (((b'x'*(4*1024*1024+1),captures[0][1]),),
                          ((captures[0][0],b' '*16385),),captures[:1]*6241):
            self.assertEqual(self.pure(first,latest,oversized),self.held('RESOURCE_BOUND_EXCEEDED'))
        touched = []
        class HostileError(RuntimeError):
            def __str__(self):touched.append('str');raise AssertionError('PRIVATE_SENTINEL')
            def __repr__(self):touched.append('repr');raise AssertionError('PRIVATE_SENTINEL')
        with patch.object(program,'parse_program',side_effect=HostileError('PRIVATE_SENTINEL https://private.invalid')):
            self.assertEqual(self.pure(first,latest,captures),self.held('UNEXPECTED_GRID_INSPECTION_FAILURE'))
        self.assertEqual(touched,[])
        class BorrowedProgramError(program.BoatProgramError):
            pass
        with patch.object(program,'parse_program',side_effect=BorrowedProgramError('PRIVATE_SENTINEL')):
            self.assertEqual(self.pure(first,latest,captures),self.held('UNEXPECTED_GRID_INSPECTION_FAILURE'))
        for malformed in (None,{},dict(closed_at=None),dict(closed_at='2026-11-18T20:30:00')):
            with self.subTest(inspector_return=type(malformed).__name__), \
                    patch.object(program,'parse_program',return_value=malformed):
                self.assertEqual(self.pure(first,latest,captures),self.held('UNEXPECTED_GRID_INSPECTION_FAILURE'))
        with patch.object(updates,'parse_update',side_effect=ValueError('PRIVATE_SENTINEL')):
            self.assertEqual(self.pure(first,latest,captures),self.held('UNEXPECTED_GRID_INSPECTION_FAILURE'))

    def test_fixed_adapter_authenticates_real_vault_then_distinguishes_availability_from_missing(self):
        first,latest,captures = self.data()
        _,writer,reader,locator = self.local_vault(captures)
        alias,calls = self.alias_reader(reader,locator['source_commit'])
        parent = writer.head()
        self.assertEqual(self.fixed_adapter(first,latest,alias), self.known(
            'SAVED_CLOCKS_MATCH_INSPECTED_GRIDS',comparison_count=1,
            program_grid_match_count=1,result_grid_match_count=1))
        self.assertEqual(writer.head(),parent)
        self.assertTrue(any(call[0]=='read' and '/batches/' in call[2] for call in calls))
        self.assertTrue(any(call[0]=='read' and '/chunks/' in call[2] for call in calls))
        unrelated = b'<p>unrelated retained synthetic page</p>'
        metadata = receipt(unrelated,'https://www.boatrace.jp/owpc/pc/race/racelist?rno=2&jcd=18&hd=20261118',
                           '2026-11-18T18:00:00+09:00')
        _,writer2,reader2,locator2 = self.local_vault(((unrelated,metadata),))
        alias2,calls2 = self.alias_reader(reader2,locator2['source_commit'])
        self.assertEqual(self.fixed_adapter(first,latest,alias2), self.known(
            'HOLD','RAW_CAPTURE_MISSING',comparison_count=1,missing_raw_side_count=2))
        self.assertFalse(any(call[0]=='read' and '/chunks/' in call[2] for call in calls2))
        self.assertEqual(writer2.head(),locator2['source_commit'])

    def test_authentication_scope_and_complete_inventory_failures_never_become_missing(self):
        first,latest,captures = self.data()
        _,writer,reader,locator = self.local_vault(captures)
        commit = locator['source_commit']
        month_path = vault.PREFIX+'2026-11/month.json'
        corrupted = bytearray(reader.read(commit,month_path,vault.MAX_INDEX))
        corrupted[len(corrupted)//2] ^= 1
        alias,_ = self.alias_reader(reader,commit,overrides={month_path:bytes(corrupted)})
        self.assertEqual(self.fixed_adapter(first,latest,alias),self.held('CAPTURE_AUTHENTICATION_UNAVAILABLE'))
        # An absent fixed month is not a conclusive authenticated empty run.
        class MissingMonth:
            repo,ref = alias.repo,alias.ref
            def fetch(self,selected):
                return alias.fetch(selected)
            def exists(self,selected,path):
                if path == month_path:return False
                return alias.exists(selected,path)
            def read(self,selected,path,maximum):
                return alias.read(selected,path,maximum)
        self.assertEqual(self.fixed_adapter(first,latest,MissingMonth()),
                         self.held('CAPTURE_AUTHENTICATION_UNAVAILABLE'))
        _,mac = vault._keys(KEY)
        reference = {name:locator[name] for name in
                     ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')}
        entry = vault._batch_entry(reader,commit,reference,mac)
        chunk_path = entry['chunks'][0]['path']
        chunk = bytearray(reader.read(commit,chunk_path,8*1024*1024));chunk[-1] ^= 1
        alias,_ = self.alias_reader(reader,commit,overrides={chunk_path:bytes(chunk)})
        self.assertEqual(self.fixed_adapter(first,latest,alias),self.held('CAPTURE_AUTHENTICATION_UNAVAILABLE'))
        _,wrong_writer,wrong_reader,wrong_locator = self.local_vault(captures,head='b'*40)
        alias,_ = self.alias_reader(wrong_reader,wrong_locator['source_commit'])
        self.assertEqual(self.fixed_adapter(first,latest,alias),self.held('CAPTURE_AUTHENTICATION_UNAVAILABLE'))
        # A valid MAC on an incomplete capture inventory is not conclusive absence.
        unrelated = b'<p>no wanted hash</p>'
        meta = receipt(unrelated,'https://www.boatrace.jp/owpc/pc/race/racelist?rno=2&jcd=18&hd=20261118',
                       '2026-11-18T18:00:00+09:00')
        _,incomplete_writer,incomplete_reader,incomplete_locator = self.local_vault(((unrelated,meta),))
        def incomplete(entry):
            files = entry['header']['files']
            files['capture-0001.raw'] = files.pop('capture-0000.raw')
        bad_commit = self.signed_header_change(incomplete_writer,incomplete_locator,incomplete)
        alias,bad_calls = self.alias_reader(incomplete_reader,bad_commit)
        self.assertEqual(self.fixed_adapter(first,latest,alias),self.held('CAPTURE_AUTHENTICATION_UNAVAILABLE'))
        self.assertFalse(any(call[0]=='read' and '/chunks/' in call[2] for call in bad_calls))
        # A later bundle cannot be ignored after an earlier complete match.
        extra_raw = b'<p>another retained body</p>'
        extra_meta = receipt(extra_raw,'https://www.boatrace.jp/owpc/pc/race/racelist?rno=2&jcd=18&hd=20261118',
                             '2026-11-18T18:00:00+09:00')
        _,later_writer,later_reader,later_locator = self.local_vault(
            captures,later_captures=((extra_raw,extra_meta),),later_head='c'*40)
        alias,_ = self.alias_reader(later_reader,later_locator['source_commit'])
        real_list = vault.list_originals
        def matching_first(*args,**kwargs):
            values = real_list(*args,**kwargs)
            return sorted(values,key=lambda item:item['entry_sha256'] != later_locator['entry_sha256'])
        with patch.object(vault,'list_originals',side_effect=matching_first):
            self.assertEqual(self.fixed_adapter(first,latest,alias),self.held('CAPTURE_AUTHENTICATION_UNAVAILABLE'))
        # Unknown receipt fields and JSON formatting cannot become new authority or conflict.
        duplicate_meta = json.loads(captures[0][1]);duplicate_meta['opaque_private'] = 'PRIVATE_SENTINEL'
        duplicate_receipt = json.dumps(duplicate_meta,indent=3).encode()+b'\n'
        _,duplicate_writer,duplicate_reader,duplicate_locator = self.local_vault(
            captures,later_captures=((captures[0][0],duplicate_receipt),captures[1]))
        alias,_ = self.alias_reader(duplicate_reader,duplicate_locator['source_commit'])
        self.assertEqual(self.fixed_adapter(first,latest,alias),self.known(
            'SAVED_CLOCKS_MATCH_INSPECTED_GRIDS',comparison_count=1,
            program_grid_match_count=1,result_grid_match_count=1))

    def test_private_sink_preserves_real_admission_public_hold_hashes_and_original_rejection(self):
        prior_path = sys.path[:]
        try:
            fixture_module = load_module('_raw_grid_current_pair_fixture',
                                         ROOT/'tests/test_boat_current_pair_eligibility_audit.py')
        finally:
            sys.path[:] = prior_path
        scripts.__path__[:] = [str(OWNER/'scripts')]
        fixture = fixture_module.CurrentPairFailureDiagnosticTests.fixture(self)
        normal = fixture.audit()
        original_bytes = deepcopy((fixture.raws,fixture.metas,fixture.payload))
        sink_calls = []
        def sink(first,latest):
            sink_calls.append(deepcopy((first,latest)))
        start = len(fixture.calls)
        result = pairs._audit(fixture.get,99,fixture_module.NOW,fixture_module.ATOMIC_SOURCE,
                              _raw_cutoff_sink=sink)
        self.assertEqual(result,normal)
        admission_reads = fixture.calls[start:]
        self.assertEqual(len(admission_reads),len(set(admission_reads)))
        self.assertEqual(sink_calls,[])
        self.assertEqual((fixture.raws,fixture.metas,fixture.payload),original_bytes)
        self.assertEqual(str(inspect.signature(pairs.audit_current_pairs)),
                         '(*, get, run_id, now, expected_owner_sha)')
        changed = deepcopy(fixture.settled)
        changed['closed_at'] = (datetime.fromisoformat(changed['closed_at'])+timedelta(seconds=1)).isoformat()
        fixture.results(2,[fixture.pending,changed])
        originals = deepcopy((fixture.raws,fixture.metas,fixture.payload))
        with self.assertRaises(ValueError) as caught:
            pairs._audit(fixture.get,99,fixture_module.NOW,fixture_module.ATOMIC_SOURCE,
                         _raw_cutoff_sink=sink)
        self.assertEqual(caught.exception.args,('ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH',))
        self.assertEqual(len(sink_calls),1)
        first,latest = sink_calls[0]
        self.assertEqual(len(first),1)
        self.assertIn('_raw_program_ref',next(iter(first.values())))
        self.assertEqual((fixture.raws,fixture.metas,fixture.payload),originals)
        with self.assertRaises(ValueError) as public:
            fixture.audit()
        error = public.exception
        self.assertIs(type(error),ValueError)
        self.assertEqual(error.args,('CURRENT_PAIR_AUDIT_REJECTED',))
        self.assertEqual(set(vars(error)),{'_current_pair_diagnostic'})
        self.assertEqual(pairs.current_pair_failure_diagnostic(error),dict(
            current_pair_failure_phase='PAIR_RESULT_JOIN',
            current_pair_failure_reason='ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH'))
        self.assertFalse(any('raw' in key for key in error._current_pair_diagnostic))
        def broken_sink(*args):
            raise RuntimeError('PRIVATE_SENTINEL https://private.invalid')
        with self.assertRaises(ValueError) as unchanged:
            pairs._audit(fixture.get,99,fixture_module.NOW,fixture_module.ATOMIC_SOURCE,
                         _raw_cutoff_sink=broken_sink)
        self.assertEqual(unchanged.exception.args,('ALL_MODEL_INTAKE_RESULT_ACTUAL_CUTOFF_MISMATCH',))
        self.assertEqual((fixture.raws,fixture.metas,fixture.payload),originals)
        for key in ('current_pair_qualifying_g8_denominator','current_pair_official_cutoff_verified'):
            self.assertIsNone(normal[key])
        self.assertEqual(normal['current_pair_qualifying_g8_count'],0)
        self.assertIs(normal['current_pair_promotion_allowed'],False)
        self.assertFalse(any(key.startswith('raw_') for key in normal))
        # No targets: no vault constructor, even if archival storage is unavailable.
        for selected_first,selected_latest in (({},{}),(self.data()[0],{})):
            self.assertEqual(self.pure(selected_first,selected_latest,()),self.known('NO_MISMATCH_TARGETS'))
        equal_first,equal_latest,_ = self.data()
        equal_latest['20261118-18-01']['closed_at'] = next(iter(equal_first.values()))['info']['race_cutoff_at']
        self.assertEqual(self.pure(equal_first,equal_latest,()),self.known('NO_MISMATCH_TARGETS'))
        def no_mismatch(*args,**kwargs):return deepcopy(normal)
        with patch.object(pairs,'_audit',side_effect=no_mismatch), \
                patch.object(vault,'VaultGitRepository',side_effect=AssertionError('no targets must not read vault')):
            report = replay.audit_fixed_a74_cutoff_raw_replay(get=fixture.get,repo=fixture.root,now=ARCHIVED)
        self.assertEqual(report,self.known('NO_MISMATCH_TARGETS'))


if __name__ == '__main__':
    unittest.main()
