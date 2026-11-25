import copy
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.keirin_research_ledger import collect, SCHEMA
from tests.test_keirin_forward_score import fixtures


def payload(obj):
    return json.dumps(obj, sort_keys=True).encode()


def digest(obj):
    return sha256(obj).hexdigest()


class ResearchLedgerTests(unittest.TestCase):
    protocol = 'b' * 64
    revision = 'c' * 40
    git_path = 'docs/evidence/experiment/commitment.json'

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.blobs = {}
        self.manifest = dict(schema=SCHEMA, days=[])

    def save(self, path, contents):
        dest = self.path / path
        dest.parent.mkdir(exist_ok=True, parents=True)
        dest.write_bytes(contents)
        return path

    def add(self, date='2026-11-25', protocol=None, scope=None, name='candidate', witness='05:01:00Z',
            batch='', revision=None):
        rows = fixtures()
        stamp = [x.replace('2026-11-25', date).replace('20261125', date.replace('-', '')) for x in
                 (json.dumps(doc, sort_keys=True) for doc in rows)]
        plan, receipt, roster, results = map(json.loads, stamp)
        if scope is not None:
            plan['races'] = [plan['races'][i] for i in scope]
        raw = payload(plan)
        original = raw + b'\n'
        protocol = protocol or self.protocol
        revision = revision or self.revision
        git_file = f'docs/evidence/{date}/{name}{batch}.json'
        blob = payload(dict(forecast_sha256=digest(original), provenance=dict(protocol_sha256=protocol)))
        self.blobs[revision, git_file] = (date + 'T' + witness, blob)
        receipt.update(
            prediction_sha256=digest(raw),
            provenance=dict(
                git_commit=revision, commit_time=date + 'T' + witness, git_path=git_file,
                git_blob_sha256=digest(blob), original_prediction_sha256=digest(original), pub_sha256='a' * 64,
                original_frozen_at=receipt['frozen_at'], roster_sha256=digest(payload(roster)),
            ),
        )
        studies = next((v['studies'] for v in self.manifest['days'] if v['roster'].startswith(date + '/')), None)
        if studies is None:
            studies = []
            self.manifest['days'].append(dict(
                roster=self.save(f'{date}/roster.json', payload(roster)),
                results=self.save(f'{date}/results.json', payload(results)), studies=studies,
            ))
        folder = f'{date}/{name}{batch}'
        study = dict(name=name, protocol_sha256=protocol,
                     predictions=self.save(f'{folder}/predictions.json', raw),
                     original=self.save(f'{folder}/original.json', original),
                     receipt=self.save(f'{folder}/receipt.json', payload(receipt)))
        studies.append(study)
        return study

    def collect(self):
        return collect(self.manifest, self.path, lambda revision, name: self.blobs[revision, name])

    def test_days_and_ticket_points_are_counted_once_per_method(self):
        self.add()
        self.add('2026-11-26')
        self.add('2026-11-26', name='another-study', scope=[0, 4])
        summary = self.collect()
        self.assertEqual(summary['total_public_roster_races'], 12)
        self.assertEqual(summary['total_distinct_registered_races'], 12)
        records = {x['method']: x for x in summary['methods']}
        method = records['candidate']
        self.assertEqual(method['total']['matched'], 6)
        self.assertEqual(method['total']['trial_hits'], 4)
        self.assertEqual(method['total']['gained'], 2)
        self.assertEqual(method['total']['lost'], 2)
        self.assertEqual(method['total']['changed_matched'], 6)
        self.assertEqual(method['total']['target_95_hits_on_matched'], 6)
        self.assertEqual(method['total']['gap_to_95_hits_on_matched'], 2)
        self.assertEqual(method['total']['held'], 2)
        self.assertEqual(method['total']['source_disagreement_holds'], 2)
        self.assertEqual(method['total']['special_result_holds'], 0)
        self.assertTrue(method['covers_every_matched_roster_race'])
        self.assertEqual(records['another-study']['not_scored_among_matched_roster_races'], 5)
        self.assertFalse(records['another-study']['covers_every_matched_roster_race'])
        self.assertEqual(method['total']['pending'], 2)
        self.assertEqual(method['total']['missing'], 2)
        self.assertEqual(method['by_points'][1]['matched'], 4)
        self.assertEqual(method['by_points'][2]['matched'], 2)
        self.assertEqual(records['another-study']['unregistered_on_those_dates'], 4)
        saved_json = json.dumps(summary)
        self.assertNotIn('202611256201', saved_json)
        self.assertNotIn('predictions.json', saved_json)

    def test_changed_protocols_are_not_summed(self):
        self.add()
        self.add('2026-11-26', protocol='d' * 64)
        methods = self.collect()['methods']
        self.assertEqual([x['days'] for x in methods], [1, 1])
        self.assertEqual({x['protocol_sha256'] for x in methods}, {'b'*64, 'd'*64})

    def test_disallows_duplicate_dates_and_a_race_in_two_same_method_batches(self):
        self.add()
        self.manifest['days'].append(copy.deepcopy(self.manifest['days'][0]))
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_RESEARCH_DATE'):
            self.collect()
        self.manifest['days'].pop()
        self.manifest['days'][0]['studies'] *= 2
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_STUDY_RACE'):
            self.collect()

    def test_separate_disjoint_freezes_can_cover_a_day_without_counting_the_day_twice(self):
        self.add(scope=[0, 2], batch='-1')
        second_revision = 'e' * 40
        self.add(scope=[1, 4], batch='-2', revision=second_revision)
        summary = self.collect()
        self.assertEqual(summary['date_count'], 1)
        self.assertEqual(summary['total_public_roster_races'], 6)
        self.assertEqual(summary['total_distinct_registered_races'], 4)
        method = summary['methods'][0]
        self.assertEqual(method['days'], 1)
        self.assertEqual(method['daily'][0]['commitments'], [self.revision, second_revision])
        self.assertEqual(method['total']['matched'], 3)
        self.assertEqual(method['total']['registered'], 4)
        self.assertEqual(method['roster_races_on_registered_dates'], 6)

        self.add(scope=[2, 5], batch='-3', revision='f' * 40)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_STUDY_RACE'):
            self.collect()

    def test_no_observations_have_no_rate_or_95_percent_gap(self):
        self.add(scope=[3, 5])
        summary = self.collect()
        method = summary['methods'][0]
        self.assertIsNone(method['total']['trial_hit_pct'])
        self.assertIsNone(method['total']['gap_to_95_hits_on_matched'])
        self.assertFalse(method['covers_every_matched_roster_race'])

    def test_rejects_late_commit_and_tampered_original(self):
        study = self.add(witness='07:00:00Z')
        with self.assertRaisesRegex(ValueError, 'GIT_COMMITMENT_AT_OR_AFTER_CUTOFF'):
            self.collect()
        self.save(study['original'], b'not originally committed')
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_PREDICTION_DIGEST_MISMATCH'):
            self.collect()

    def test_requires_roster_and_source_clock_binding(self):
        study = self.add()
        p = self.path / study['receipt']
        receipt = json.loads(p.read_bytes())
        receipt['provenance']['roster_sha256'] = '0' * 64
        p.write_bytes(payload(receipt))
        with self.assertRaisesRegex(ValueError, 'OWNER_ROSTER_DIGEST_MISMATCH'):
            self.collect()
        receipt['provenance']['roster_sha256'] = digest((self.path / '2026-11-25/roster.json').read_bytes())
        receipt['provenance']['commit_time'] = '2026-11-25T05:03:00Z'
        p.write_bytes(payload(receipt))
        with self.assertRaisesRegex(ValueError, 'GIT_COMMITMENT_TIME_MISMATCH'):
            self.collect()

    def test_day_without_forecasts_remains_in_coverage_universe(self):
        self.add()
        self.add('2026-11-26')
        self.manifest['days'][1]['studies'].clear()
        summary = self.collect()
        self.assertEqual(summary['total_public_roster_races'], 12)
        self.assertEqual(summary['total_matched_roster_races'], 6)
        self.assertEqual(summary['total_distinct_registered_races'], 6)
        method = summary['methods'][0]
        self.assertEqual(method['unregistered_in_manifest'], 6)
        self.assertEqual(method['not_scored_among_matched_roster_races'], 3)
        self.assertFalse(method['covers_every_matched_roster_race'])

    def set_native(self, mapped=False):
        study = self.add(scope=[0, 1, 2])
        item = self.manifest['days'][0]
        roster = json.loads((self.path / item['roster']).read_bytes())
        plan = json.loads((self.path / study['predictions']).read_bytes())
        receipt = json.loads((self.path / study['receipt']).read_bytes())
        previous = receipt.pop('provenance')
        pub = payload(dict(races=[
            dict(race_id=r['race_id'], predictions={'3t': r['published']}, default_trifecta_points=r['points'])
            for r in plan['races']
        ]))
        roster['forecast_asset_sha256'] = digest(pub)
        roster_raw = payload(roster)
        self.save(item['roster'], roster_raw)
        wire_hash = 'd' * 64
        original = ({r['race_id']: dict(old=r['published'], new=r['trial'], points=r['points'], cutoff=r['cutoff_at'])
                     for r in plan['races']} if mapped else plan)
        orig_raw = json.dumps(original, indent=2).encode()
        self.save(study['original'], orig_raw)
        self.save(study['receipt'], payload(receipt))
        readback = dict(normalized_sha256=digest(pub), wire_sha256=wire_hash)
        release = dict(date=roster['date'], result_roster_sha256=digest(roster_raw), anonymous_readback=readback,
                       deployment_time_utc='2026-11-25T04:30:00Z')
        proof = dict(commit=previous['git_commit'], path=previous['git_path'], commit_time=previous['commit_time'])
        blob = dict(forecast_sha256=digest(orig_raw), protocol_sha256=self.protocol,
                    published_sha256=wire_hash, frozen_at=receipt['frozen_at'])
        self.blobs[proof['commit'], proof['path']] = (proof['commit_time'], payload(blob))
        study.update(published=self.save('published.json', pub), publication=self.save('publication.json', payload(release)),
                     git_proof=self.save('proof.json', payload(proof)))
        return study, plan, receipt

    def test_native_whitespace_differences_do_not_invalidate_predictions(self):
        self.set_native()
        self.assertEqual(self.collect()['methods'][0]['total']['matched'], 3)

    def test_native_projection_rejects_changed_normalized_picks(self):
        study, plan, receipt = self.set_native(mapped=True)
        self.assertEqual(self.collect()['methods'][0]['total']['trial_hits'], 2)
        plan['races'][0]['trial'].reverse()
        raw = payload(plan)
        receipt['prediction_sha256'] = digest(raw)
        self.save(study['predictions'], raw)
        self.save(study['receipt'], payload(receipt))
        with self.assertRaisesRegex(ValueError, 'NATIVE_NORMALIZATION_MISMATCH'):
            self.collect()
