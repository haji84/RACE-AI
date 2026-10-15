"""Synthetic immutable archives: retrospective replay is not validation evidence."""
import copy
from datetime import timedelta
import hashlib
import importlib
import math
import re
import unittest

from tests.test_name_bound_evaluation import fixture
from tests.test_live_evaluation_contract import rehash as rehash_record
from web import race_contract as facts, name_bound_result as labels
from web.name_bound_evaluation import build_name_bound_evaluation
from web.name_bound_prediction import build_name_bound_prediction


TOP = set('schema_version operation as_of status scope research_only validation_status purchase_decision purchase_recommendations physical_exhibition_timing_verified holdout_status calibration_status model_adoption_status input_count race_count day_count requested_race_ids evaluated_race_ids evaluated_dates excluded models observations signature_sha256 snapshot_id'.split())
OBSERVATION = set('race_id date_jst forecast_request_id result_request_id archive_kind manifest_sha256 program_sha256 forecast_sha256 result_sha256 evaluation_sha256 original_evaluation_as_of status exclusion_reason model_rows'.split())
MODEL = set('phase model_id model_version race_count ticket_count_per_race mean_multiclass_brier mean_log_loss mean_winner_probability mean_brier_delta_from_baseline mean_log_loss_delta_from_baseline'.split())
PHASES = ['B_ONLY_BASELINE', 'DISPLAY_V2', 'ORIGINAL_V2']
OLD_MANIFEST = set('schema_version status failure_reason race_id forecast_request_id commit_sha backups reads_used posts_attempted official_source_requests max_seconds validation_status purchase_decision purchase_recommendations'.split())
NEW_MANIFEST = OLD_MANIFEST | {'operation', 'request_id'}


def sha(value):
    return hashlib.sha256(facts.canonical(value)).hexdigest()


def inventory(entry):
    """Resign only synthetic inventories, never production archive material."""
    keys = ['program', 'forecast', 'result', 'evaluation']
    if entry['archive_kind'] == 'RESULT_PUBLICATION':
        keys.append('request')
    entry['manifest']['backups'] = {
        key + '.json': dict(bytes=len(facts.canonical(entry[key])), sha256=sha(entry[key]))
        for key in keys}
    return entry


def file_bytes(entry):
    keys = ['manifest', 'program', 'forecast', 'result', 'evaluation']
    if entry['archive_kind'] == 'RESULT_PUBLICATION':
        keys.append('request')
    return sum(len(facts.canonical(entry[key])) for key in keys)


def relocated_fixture(*, day_offset=0, race_no=1, body=None, uniform=False):
    """Rebuild a wholly synthetic dependency graph on another race/day.

    This helper changes generated test facts before archival. It does not
    modify archive replay clocks or copy any real-source artifacts.
    """
    race, forecast, bundle, now = fixture(body, uniform=uniform)
    if day_offset == 0 and race_no == 1:
        return race, forecast, bundle, now
    original_race = copy.deepcopy(race)
    old_base_sha = sha(forecast['baseline'])
    old_binding_sha = sha(forecast['name_binding'])
    day = facts._time(race['closed_at']).astimezone(facts.JST).date()
    target = day + timedelta(days=day_offset)
    old_id, new_id = race['race_id'], f'{target:%Y%m%d}-18-{race_no:02}'

    def move(value):
        if isinstance(value, dict):
            return {k: move(v) for k, v in value.items()}
        if isinstance(value, list):
            return [move(v) for v in value]
        if not isinstance(value, str):
            return value
        if value == 'user-confirmation-2026-10-15-official-facts':
            return value
        if re.match(r'^2026-10-\d\dT', value):
            # Retain parser precision and timezone spelling in synthetic facts.
            prefix = value[:10]
            shifted = facts._time(prefix + 'T12:00:00+00:00').date() + timedelta(days=day_offset)
            return shifted.isoformat() + value[10:]
        return (value.replace(old_id, new_id).replace(day.isoformat(), target.isoformat())
            .replace(day.strftime('%Y%m%d'), target.strftime('%Y%m%d'))
            .replace('202610/b261015.lzh', f'{target:%Y%m}/b{target:%y%m%d}.lzh')
            .replace('rno=1&', f'rno={race_no}&').replace('_18_01.txt', f'_18_{race_no:02}.txt'))

    race, forecast, bundle = map(move, (race, forecast, bundle))
    now += timedelta(days=day_offset)
    mapping = {facts.program_digest(original_race): facts.program_digest(race)}
    projected = copy.deepcopy(race)
    for row, binding in zip(projected['boats'], forecast['name_binding']['receipt']['snapshot']['bindings']):
        row['name'] = binding['verified_full_name']
    mapping[forecast['inputs']['original_observation']['program_identity_sha256']] = facts.program_digest(projected)

    def replace(value):
        if isinstance(value, dict):
            for key in value:
                value[key] = replace(value[key])
        elif isinstance(value, list):
            value[:] = [replace(v) for v in value]
        elif isinstance(value, str):
            return mapping.get(value, value)
        return value

    def resign(value, key='snapshot_id', excluded=None):
        old = value[key]
        replace(value)
        value[key] = sha({k: v for k, v in value.items() if k not in (excluded or {key})})
        mapping[old] = value[key]

    base = forecast['baseline']
    for model in base['snapshot']['models']:
        resign(model, 'content_sha256')
    resign(base['snapshot'])
    replace(base)
    mapping[old_base_sha] = sha(base)
    binding = forecast['name_binding']
    resign(binding['receipt']['snapshot'])
    replace(binding['receipt'])
    binding['finalization']['receipt_sha256'] = sha(binding['receipt'])
    replace(binding['finalization'])
    mapping[old_binding_sha] = sha(binding)
    inputs = forecast['inputs']
    resign(inputs['beforeinfo_record'], excluded=facts.STORE_FIELDS)
    resign(inputs['original_observation'])
    resign(inputs)
    snapshot = forecast['receipt']['snapshot']
    forecast['receipt']['snapshot'] = build_name_bound_prediction(inputs, race, base, binding,
        runner_saved_at=facts._time(snapshot['input_link']['runner_saved_at']),
        input_cloud_saved_at=facts._time(snapshot['input_link']['input_cloud_saved_at']),
        parents_resolved_at=facts._time(snapshot['parents_resolved_at']), now=facts._time(snapshot['generated_at']))
    replace(forecast['finalization'])
    forecast['finalization'].update(snapshot_id=forecast['receipt']['snapshot']['snapshot_id'],
        input_snapshot_id=inputs['snapshot_id'], receipt_sha256=sha(forecast['receipt']))
    record = bundle['records'][0]['record']
    resign(record, excluded=facts.STORE_FIELDS)
    replace(bundle)
    build_name_bound_evaluation(forecast, bundle, race, now)
    return race, forecast, bundle, now


def archive_fixture(*, publication=False, day_offset=0, race_no=1, body=None, uniform=False):
    race, forecast, result, now = relocated_fixture(day_offset=day_offset, race_no=race_no, body=body, uniform=uniform)
    request = None
    if publication:
        record = result['records'][0]['record']
        captured = facts._time(record['captured_at'])
        packet = labels.build_name_bound_result(record, race, forecast,
            parents_read_at=captured-timedelta(seconds=1), generated_at=captured+timedelta(seconds=2), now=now)
        receipt = dict(schema_version=1, request_id='123500-1', forecast_request_id=forecast['receipt']['request_id'],
            snapshot=packet, runner_saved_at=facts.stamp(captured+timedelta(seconds=3)),
            cloud_saved_at=facts.stamp(captured+timedelta(seconds=4)), cloud_eligible_pre_race=False)
        result = dict(receipt=receipt, finalization=dict(schema_version=1, race_id=race['race_id'],
            request_id=receipt['request_id'], forecast_request_id=receipt['forecast_request_id'],
            snapshot_id=packet['snapshot_id'], receipt_sha256=sha(receipt), receipt_confirmed_at=facts.stamp(captured+timedelta(seconds=5))))
        request = dict(publication_review='user-confirmation-2026-10-15-official-facts', race_id=race['race_id'],
            **{k: copy.deepcopy(receipt[k]) for k in ('request_id', 'forecast_request_id', 'snapshot', 'runner_saved_at')})
        bundle = labels.result_bundle(result, race, forecast, now=now)
    else:
        bundle = result
    report = build_name_bound_evaluation(forecast, bundle, race, now)
    manifest = dict(schema_version=1, status='COMPLETED', failure_reason=None, race_id=race['race_id'],
        forecast_request_id=forecast['receipt']['request_id'], commit_sha='a'*40, backups={},
        reads_used=5 if publication else 4, posts_attempted=1 if publication else 0,
        official_source_requests=1 if publication else 0, max_seconds=240 if publication else 180,
        validation_status='UNVALIDATED', purchase_decision='skip', purchase_recommendations=[])
    if publication:
        manifest.update(operation='NAME_BOUND_RESULT_PUBLICATION', request_id='123500-1')
    return inventory(dict(archive_kind='RESULT_PUBLICATION' if publication else 'READ_ONLY_EVALUATION',
        manifest=manifest, program=race, forecast=forecast, request=request, result=result, evaluation=report)), now


class NameBoundArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.c = importlib.import_module('race_ai.name_bound_archive')
        except ModuleNotFoundError:
            cls.c = None
        cls.old, cls.now = archive_fixture()
        cls.new, _ = archive_fixture(publication=True, race_no=2)

    def setUp(self):
        self.assertIsNotNone(self.c, 'pure immutable archive replay module required')

    def build(self, entries=None, now=None):
        return self.c.build_archived_name_bound_cohort(entries if entries is not None else [self.old, self.new], now=now or self.now)

    def reject(self, entries, now=None):
        with self.assertRaisesRegex(ValueError, '^NAME_BOUND_ARCHIVE_INVALID$'):
            self.c.build_archived_name_bound_cohort(entries, now=now if now is not None else self.now)

    def test_both_archive_generations_are_replayed_without_mutation(self):
        entries = copy.deepcopy([self.new, self.old])
        before = copy.deepcopy(entries)
        report = self.build(entries, self.now+timedelta(days=9))
        self.assertEqual(entries, before)
        self.assertEqual(set(report), TOP)
        self.assertEqual(report['as_of'], facts.stamp(self.now+timedelta(days=9)))
        self.assertEqual((report['input_count'], report['race_count'], report['day_count']), (2, 2, 1))
        self.assertEqual(report['requested_race_ids'], ['20261015-18-01', '20261015-18-02'])
        self.assertEqual(report['evaluated_race_ids'], report['requested_race_ids'])
        self.assertEqual(report['evaluated_dates'], ['2026-10-15'])
        self.assertEqual(report['excluded'], [])
        self.assertEqual(report['status'], 'EXPLORATORY_AGGREGATE')
        self.assertEqual(report['operation'], 'OFFLINE_NAME_BOUND_ARCHIVE_COHORT')
        self.assertEqual(report['scope'], 'RETROSPECTIVE_ARCHIVE_REPLAY_DIFFERENT_FEATURE_PHASES')
        self.assertEqual(self.build(entries[::-1], self.now+timedelta(days=9)), report)
        self.assertEqual(set(entries[1]['manifest']), OLD_MANIFEST)
        self.assertEqual(set(entries[0]['manifest']), NEW_MANIFEST)
        for entry, observation in zip([self.old, self.new], report['observations']):
            self.assertEqual(set(observation), OBSERVATION)
            for key in ('manifest', 'program', 'forecast', 'result', 'evaluation'):
                self.assertEqual(observation[key+'_sha256'], sha(entry[key]))
            self.assertEqual(observation['model_rows'], entry['evaluation']['models'])
            self.assertEqual(observation['original_evaluation_as_of'], entry['evaluation']['as_of'])
            self.assertEqual(observation['result_request_id'], '123500-1' if entry['request'] else None)
        self.assertEqual(report['snapshot_id'], sha({k:v for k,v in report.items() if k != 'snapshot_id'}))
        signature = []
        snapshot = self.old['forecast']['receipt']['snapshot']
        base = next(m for m in self.old['forecast']['baseline']['snapshot']['models'] if m['model_id'] == snapshot['baseline_link']['model_id'])
        for phase, model in zip(PHASES, [base, *snapshot['models']]):
            signature.append(dict(phase=phase, model_id=model['model_id'], model_version=model['model_version'],
                parameters=None if phase == PHASES[0] else model['parameters']))
        self.assertEqual(report['signature_sha256'], sha(signature))
        detached = self.c.validate_archived_name_bound_cohort(report, entries, now=self.now+timedelta(days=10))
        detached['observations'][0]['model_rows'][0]['log_loss'] = 99
        self.assertNotEqual(detached, report)
        self.assertEqual(entries, before)

    def test_means_and_paired_differences_use_common_races_and_original_distributions(self):
        from tests.test_official_race_updates import results
        second_truth = (results().replace('is-boatColor1">1</td><td>4001 選手1', 'SWAP')
            .replace('is-boatColor2">2</td><td>4002 選手2', 'is-boatColor1">1</td><td>4001 選手1')
            .replace('SWAP', 'is-boatColor2">2</td><td>4002 選手2').replace('1-2-3','2-1-3'))
        second, _ = archive_fixture(race_no=3, body=second_truth)
        entries = [self.old, second]
        report = self.build(entries)
        expected = []
        for entry in entries:
            forecast = entry['forecast']
            snap = forecast['receipt']['snapshot']
            base = next(m for m in forecast['baseline']['snapshot']['models'] if m['model_id'] == snap['baseline_link']['model_id'])
            rows = []
            for model in [base, *snap['models']]:
                probs = [x['probability'] for x in model['triples']]
                truth = [1,2,3] if entry is self.old else [2,1,3]
                target = [x['combination'] == truth for x in model['triples']]
                winner = probs[target.index(True)]
                rows.append((math.fsum((p-int(hit))**2 for p,hit in zip(probs,target)), -math.log(winner), winner))
            expected.append(rows)
        self.assertEqual([row['phase'] for row in report['models']], PHASES)
        for index, row in enumerate(report['models']):
            self.assertEqual(set(row), MODEL)
            self.assertEqual((row['race_count'], row['ticket_count_per_race']), (2, 120))
            for metric, field in enumerate(['mean_multiclass_brier','mean_log_loss','mean_winner_probability']):
                self.assertEqual(row[field], math.fsum(r[index][metric] for r in expected)/2)
            self.assertEqual(row['mean_brier_delta_from_baseline'], math.fsum(r[index][0]-r[0][0] for r in expected)/2)
            self.assertEqual(row['mean_log_loss_delta_from_baseline'], math.fsum(r[index][1]-r[0][1] for r in expected)/2)
        self.assertEqual(report['models'][0]['mean_brier_delta_from_baseline'], 0.0)
        self.assertEqual(report['models'][0]['mean_log_loss_delta_from_baseline'], 0.0)

    def test_multiday_history_is_replayed_on_its_own_original_day(self):
        historical, _ = archive_fixture(day_offset=-2)
        report = self.build([self.new, historical], self.now+timedelta(days=3))
        self.assertEqual((report['race_count'],report['day_count']), (2,2))
        self.assertEqual(report['evaluated_dates'], ['2026-10-13','2026-10-15'])
        self.assertEqual(report['observations'][0]['original_evaluation_as_of'], historical['evaluation']['as_of'])
        self.assertEqual((report['research_only'], report['physical_exhibition_timing_verified']), (True,False))
        self.assertEqual((report['validation_status'],report['purchase_decision'],report['purchase_recommendations']), ('UNVALIDATED','skip',[]))
        self.assertEqual((report['holdout_status'],report['calibration_status'],report['model_adoption_status']), ('NOT_ESTABLISHED','NOT_EVALUATED','NOT_EVALUATED'))

    def test_valid_exclusions_are_preserved_and_never_counted_as_evaluated(self):
        from tests.test_official_race_updates import results
        excluded, _ = archive_fixture(body=results(refund=True))
        report = self.build([excluded])
        self.assertEqual((report['input_count'],report['race_count'],report['day_count']), (1,0,0))
        self.assertEqual(report['status'], 'NO_SCORABLE_RACES')
        self.assertEqual((report['models'],report['evaluated_dates'],report['evaluated_race_ids']), ([],[],[]))
        self.assertEqual(report['excluded'], [dict(race_id='20261015-18-01',forecast_request_id='123499-1',
            status='RESULT_UNSUPPORTED',reason='OFFICIAL_REFUND_OUTCOME_UNSUPPORTED')])
        self.assertEqual(report['observations'][0]['model_rows'], [])
        mixed = self.build([excluded,self.new])
        self.assertEqual((mixed['input_count'],mixed['race_count'],mixed['day_count']), (2,1,1))
        for index,row in enumerate(mixed['models']):
            self.assertEqual(row['mean_log_loss'], self.new['evaluation']['models'][index]['log_loss'])
        pending, _ = archive_fixture(body='<p>結果はまだありません。</p>')
        pending_report = self.build([pending])
        self.assertEqual(pending_report['excluded'], [dict(race_id='20261015-18-01', forecast_request_id='123499-1',
            status='RESULT_PENDING', reason='OFFICIAL_RESULT_PENDING')])
        self.assertEqual(pending_report['observations'][0]['model_rows'], [])
        self.assertEqual((pending_report['race_count'],pending_report['day_count']), (0,0))
        missing = copy.deepcopy(self.old)
        record = copy.deepcopy(missing['forecast']['inputs']['beforeinfo_record'])
        saved = missing['forecast']['receipt']['cloud_saved_at']
        missing['result'].update(latest={'beforeinfo':record['snapshot_id']}, published_at=saved,
            records=[dict(record=record,program_sha256=missing['result']['program_sha256'],cloud_saved_at=saved,cloud_eligible_pre_race=True)])
        missing['evaluation'] = build_name_bound_evaluation(missing['forecast'],missing['result'],missing['program'],self.now)
        self.assertIsNone(missing['evaluation']['result_proof'])
        inventory(missing)
        self.reject([missing])
        for target in ('result','evaluation'):
            bad = copy.deepcopy(excluded)
            if target == 'result':
                bad['result']['records'][0]['record']['data']['results'][0]['name'] = 'fake'
                rehash_record(bad['result']['records'][0]['record'])
            else:
                bad['evaluation']['exclusion_reason'] = 'OTHER'
            inventory(bad)
            self.reject([bad])

    def test_actual_audit_clock_and_stored_original_clocks_are_strict(self):
        for clock in (self.now-timedelta(microseconds=1), self.now.replace(tzinfo=None), facts.stamp(self.now)):
            self.reject([self.old], clock)
        report = self.build(now=self.now+timedelta(days=1))
        for clock in (self.now, self.now.replace(tzinfo=None)):
            with self.assertRaisesRegex(ValueError,'^NAME_BOUND_ARCHIVE_INVALID$'):
                self.c.validate_archived_name_bound_cohort(report, [self.old,self.new], now=clock)
        for instant in (self.now+timedelta(days=1), self.now-timedelta(hours=2)):
            bad = copy.deepcopy(self.old)
            bad['evaluation']['as_of'] = facts.stamp(instant)
            inventory(bad)
            self.reject([bad], self.now+timedelta(days=3))

    def test_exact_entry_types_counts_and_duplicate_races_reject(self):
        for entries in ([], [self.old]*25, None, {}, (self.old,), [None], [True]):
            self.reject(entries)
        self.reject([self.old, copy.deepcopy(self.old)])
        duplicate = copy.deepcopy(self.old)
        duplicate['forecast']['receipt']['request_id'] = '123501-1'
        duplicate['forecast']['finalization']['request_id'] = '123501-1'
        duplicate['forecast']['finalization']['receipt_sha256'] = sha(duplicate['forecast']['receipt'])
        duplicate['evaluation'] = build_name_bound_evaluation(duplicate['forecast'],duplicate['result'],duplicate['program'],self.now)
        duplicate['manifest']['forecast_request_id'] = '123501-1'
        inventory(duplicate)
        self.reject([self.old, duplicate])
        for field in self.old:
            bad = copy.deepcopy(self.old); del bad[field]
            self.reject([bad])
        for field,value in [('extra',1),('archive_kind','OTHER'),('archive_kind',False),('request',{})]:
            bad = copy.deepcopy(self.old); bad[field] = value
            self.reject([bad])
        bad = copy.deepcopy(self.new); bad['request'] = None
        self.reject([bad])

    def test_manifest_exactness_literal_types_inventory_and_generation_counters(self):
        for original in (self.old,self.new):
            changes = [('schema_version',True),('schema_version',1.0),('status','STOPPED'),('failure_reason','OTHER'),
                ('race_id','20261015-18-12'),('forecast_request_id','0-1'),('commit_sha','A'*40),
                ('reads_used',True),('posts_attempted',False),('official_source_requests',False),
                ('max_seconds',180.0),('validation_status','VALIDATED'),('purchase_decision','buy'),
                ('purchase_recommendations',{}),('extra',1),('backups',{})]
            changes += [('reads_used',4),('posts_attempted',0),('official_source_requests',0),('max_seconds',180),('operation','OTHER'),('request_id','123501-1')] if original['request'] else [('reads_used',5),('posts_attempted',1),('official_source_requests',1),('max_seconds',240),('operation','NAME_BOUND_RESULT_PUBLICATION')]
            for field,value in changes:
                bad = copy.deepcopy(original); bad['manifest'][field] = value
                with self.subTest(generation=original['archive_kind'],field=field,value=value):
                    self.reject([bad])
            for field in original['manifest']:
                bad = copy.deepcopy(original); del bad['manifest'][field]
                self.reject([bad])
            for meta in ({'bytes':True,'sha256':sha(original['program'])}, {'bytes':len(facts.canonical(original['program'])),'sha256':'0'*64}, {'bytes':0,'sha256':'a'*64}, {'bytes':256001,'sha256':'a'*64}, {'bytes':1,'sha256':'A'*64}, {'bytes':1,'sha256':'a'*64,'extra':1}):
                bad = copy.deepcopy(original); bad['manifest']['backups']['program.json'] = meta
                self.reject([bad])

    def test_rehashed_full_evidence_and_report_tampering_are_rejected(self):
        mutations = [lambda e:e['program']['boats'][0].update(racer_registration_id='4999'),
            lambda e:e['forecast']['baseline'].update(request_id='123498-1'),
            lambda e:e['forecast']['receipt']['snapshot']['models'][0]['triples'][0].update(probability=.5),
            lambda e:e['forecast']['receipt']['snapshot']['models'][1]['parameters'].update(extra=.5),
            lambda e:e['forecast']['receipt']['snapshot']['boats'][0]['contributions']['lap_s'].update(coefficient_per_second=10),
            lambda e:e['evaluation']['models'][0].update(log_loss=0),
            lambda e:e['evaluation'].update(physical_exhibition_timing_verified=True),
            lambda e:e['evaluation'].update(result_proof=None),
            lambda e:e['forecast'].update(extra=float('nan')),
            lambda e:e['program'].update(extra=float('inf'))]
        for original in (self.old,self.new):
            for mutate in mutations:
                bad = copy.deepcopy(original); mutate(bad)
                try: inventory(bad)
                except ValueError: pass
                self.reject([bad])
        for mutate in (
                lambda s:s['models'][0]['triples'][0].update(probability=.5),
                lambda s:s['models'][1]['parameters'].update(extra=.5),
                lambda s:s['boats'][0]['contributions']['lap_s'].update(coefficient_per_second=10)):
            bad = copy.deepcopy(self.old)
            snapshot = bad['forecast']['receipt']['snapshot']
            mutate(snapshot)
            snapshot['snapshot_id'] = sha({k:v for k,v in snapshot.items() if k != 'snapshot_id'})
            bad['forecast']['finalization'].update(snapshot_id=snapshot['snapshot_id'], receipt_sha256=sha(bad['forecast']['receipt']))
            bad['evaluation']['forecast_proof'].update(snapshot_id=snapshot['snapshot_id'],envelope_sha256=sha(bad['forecast']))
            inventory(bad)
            self.reject([bad])
        for field,value in [('publication_review','other'),('race_id','20261015-18-01'),('request_id','0-1'),
                ('forecast_request_id','123498-1'),('runner_saved_at',facts.stamp(self.now)),('extra',1)]:
            bad = copy.deepcopy(self.new); bad['request'][field] = value; inventory(bad)
            self.reject([bad])
        bad = copy.deepcopy(self.new); bad['request']['snapshot']['forecast_link']['envelope_sha256'] = '0'*64; inventory(bad)
        self.reject([bad])
        bad = copy.deepcopy(self.new); bad['result']['finalization']['receipt_confirmed_at'] = facts.stamp(self.now+timedelta(seconds=1)); inventory(bad)
        self.reject([bad])

    def test_full_aggregate_validation_rejects_rehashed_types_values_and_schema(self):
        report = self.build()
        with self.assertRaisesRegex(ValueError,'^NAME_BOUND_ARCHIVE_INVALID$'):
            self.c.validate_archived_name_bound_cohort(dict(report,padding='x'*256000),[self.old,self.new],now=self.now)
        changes = [('schema_version',True),('input_count',2.0),('race_count',240),('day_count',120),('research_only',1),
            ('physical_exhibition_timing_verified',0),('holdout_status','ESTABLISHED'),('signature_sha256','0'*64),
            ('as_of',report['as_of'].replace('+00:00','Z')),('extra',1),('requested_race_ids',list(reversed(report['requested_race_ids'])))]
        for field,value in changes:
            bad = copy.deepcopy(report); bad[field] = value; bad['snapshot_id'] = sha({k:v for k,v in bad.items() if k != 'snapshot_id'})
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'^NAME_BOUND_ARCHIVE_INVALID$'):
                self.c.validate_archived_name_bound_cohort(bad,[self.old,self.new],now=self.now)
        for field in report:
            bad = copy.deepcopy(report); del bad[field]
            with self.assertRaisesRegex(ValueError,'^NAME_BOUND_ARCHIVE_INVALID$'):
                self.c.validate_archived_name_bound_cohort(bad,[self.old,self.new],now=self.now)

    def test_individually_valid_different_model_signatures_cannot_be_blended(self):
        # A program without usable ratings legitimately selects the uniform
        # baseline. Each archive replays, but these signatures must not blend.
        other, _ = archive_fixture(race_no=4, uniform=True)
        self.assertEqual(self.build([other])['race_count'],1)
        self.assertEqual(self.build([self.old])['race_count'],1)
        self.reject([self.old,other])

    def test_perfile_bound_and_total_bound_include_original_manifests_only(self):
        bad = copy.deepcopy(self.old)
        raw_size = len(facts.canonical(bad['program']))
        bad['program']['padding'] = 'x'*(256000-raw_size-len(facts.canonical({'padding':''}))+1)
        self.assertEqual(len(facts.canonical(bad['program'])),256000)
        inventory(bad)
        self.assertEqual(self.build([bad])['race_count'],1)
        bad['program']['padding'] += 'x'; inventory(bad)
        self.reject([bad])
        entries = [archive_fixture(day_offset=-offset)[0] for offset in range(24)]
        # Fill existing valid program files while keeping every file bounded.
        for entry in entries:
            entry['program']['padding'] = ''
            inventory(entry)
        needed = 8000000-sum(map(file_bytes,entries))
        for entry in entries:
            if needed <= 0: break
            before = file_bytes(entry)
            room = 256000-len(facts.canonical(entry['program']))
            entry['program']['padding'] = 'x'*min(room,needed)
            inventory(entry)
            needed -= file_bytes(entry)-before
        # The metadata byte-count digits may add a few bytes during filling.
        total = sum(map(file_bytes,entries))
        adjusted = next(e for e in entries if e['program']['padding'])
        adjusted['program']['padding'] = adjusted['program']['padding'][:len(adjusted['program']['padding'])+8000000-total]
        inventory(adjusted)
        self.assertEqual(sum(map(file_bytes,entries)),8000000)
        report = self.build(entries)
        self.assertEqual((report['input_count'],report['race_count'],report['day_count']),(24,24,24))
        self.assertEqual((report['holdout_status'],report['model_adoption_status']),('NOT_ESTABLISHED','NOT_EVALUATED'))
        self.assertLessEqual(len(facts.canonical(report)),256000)
        adjusted['program']['padding'] += 'x'; inventory(adjusted)
        self.assertEqual(sum(map(file_bytes,entries)),8000001)
        self.reject(entries)


if __name__ == '__main__':
    unittest.main()
