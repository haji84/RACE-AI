import json
from pathlib import Path
from subprocess import CompletedProcess
import unittest
from copy import deepcopy
from hashlib import sha256
from unittest.mock import patch

from race_ai.keirin_public_rank_distribution import SCHEMA
from scripts import keirin_publish_rank_exhibit as exhibit
from tests.test_keirin_public_rank_distribution import CUTOFF, DAY, fixture, project


def body(value):
    return json.dumps(value).encode()


def inputs():
    races, rosters, results = [], [], []
    for number in range(1, 11):
        race_id = '2026112561' + f'{number:02d}'
        record, roster = fixture(range(1, 8))
        race = dict(project(record, roster), race_id=race_id)
        races.append(race)
        rosters.append(dict(race_id=race_id, published_cutoff_at=CUTOFF,
                            observed_riders=[{'number': n} for n in range(1, 8)]))
        results.append(dict(race_id=race_id))
    packet = dict(schema=SCHEMA, day=DAY, published_at=DAY + 'T23:00:00+09:00', races=races)
    roster = body(dict(schema='KEIRIN_PUBLIC_RESULT_ROSTER_V1', date=DAY, races=rosters))
    result = body(dict(schema='KEIRIN_PUBLISHED_RESULTS_V1', date=DAY,
                       checked_at=DAY + 'T22:50:00+09:00', races=results))
    receipt = body({'original_note_sha256': 'a' * 64})
    publication, witness = b'publication', b'witness'
    report = dict(date=DAY, registered=10, matched=10, trifecta_by_points={'4': {'matched': 10}},
                  original_plaintext_authentication='INDEPENDENT_RSA_READBACK_VERIFIED',
                  independent_research_plaintext_readback=True, actual_organizer_cutoff_authenticated=False,
                  accuracy_improvement_proven=False, original_note_sha256='a' * 64)
    for key, raw in (('roster', roster), ('results', result), ('recovery_receipt', receipt),
                     ('publication_receipt', publication), ('independent_witness', witness)):
        report[key + '_sha256'] = sha256(raw).hexdigest()
    return packet, report, roster, result, receipt, publication, witness


class PublishRankExhibitTests(unittest.TestCase):
    def test_uses_independent_order_and_reports_only_aggregate_brier_scores(self):
        value = inputs()
        with patch.object(exhibit.forward, 'confirmed_order', return_value=(1, 2, 3)) as confirmed:
            metrics = exhibit.validate_rank_cohort(*value)
        self.assertEqual(confirmed.call_count, 10)
        self.assertEqual(confirmed.call_args.args[1:3], (CUTOFF, set(range(1, 8))))
        self.assertEqual((metrics['races'], metrics['rider_starts']), (10, 70))
        self.assertNotIn('202611256101', repr(metrics))
        ranks = value[0]['races'][0]['riders']
        for k in (1, 2, 3):
            expected = sum((sum(row['probabilities'][:k]) - (row['number'] <= k)) ** 2
                           for row in ranks) / len(ranks)
            self.assertAlmostEqual(metrics['top_k_brier'][str(k)], expected)

    def test_bad_fold_source_or_missing_matches_held_before_scoring(self):
        original = inputs()
        for field, value in (('matched', 9), ('roster_sha256', 'b' * 64),
                             ('original_note_sha256', 'b' * 64),
                             ('trifecta_by_points', {'4': {'matched': 9}})):
            changed = deepcopy(original[1])
            changed[field] = value
            with self.subTest(field=field), patch.object(exhibit.forward, 'confirmed_order') as confirmed:
                with self.assertRaises(ValueError):
                    exhibit.validate_rank_cohort(original[0], changed, *original[2:])
                confirmed.assert_not_called()

    def test_named_source_must_have_pinned_bytes(self):
        raw = body(dict(schema='KEIRIN_PUBLISHED_LINE_RANK_V3', date=DAY, races=[
            dict(race_id='202611256101', cutoff_at=CUTOFF,
                 riders=[dict(name='名前', number=1, private='omit')])]))
        with patch.object(exhibit, 'ROSTER_SHA256', sha256(raw).hexdigest()):
            rows = exhibit.named_rosters(raw)
            self.assertEqual(rows[0]['riders'], [dict(name='名前', number=1)])
            with self.assertRaises(ValueError):
                exhibit.named_rosters(raw + b' ')

    def test_named_fetch_holds_redirect_without_reading_the_file(self):
        with patch.object(exhibit.subprocess, 'run', return_value=CompletedProcess([], 0, b'302')) as fetch:
            with self.assertRaisesRegex(ValueError, 'PUBLIC_ROSTER_STATUS'):
                exhibit.fetch_named_roster(Path('unused.json'))
        args = fetch.call_args.args[0]
        self.assertEqual(args[-1], exhibit.ROSTER_URL)
        self.assertNotIn('--location', args)
        self.assertEqual(args[args.index('--max-filesize') + 1], str(1024 * 1024))

    def test_holds_results_with_a_different_starter_set_even_if_snapshot_digest_matches(self):
        packet, report, roster_raw, *rest = inputs()
        roster = json.loads(roster_raw)
        roster['races'][0]['observed_riders'][0]['number'] = 9
        amended = body(roster)
        report['roster_sha256'] = sha256(amended).hexdigest()
        with patch.object(exhibit.forward, 'confirmed_order') as confirmed:
            with self.assertRaisesRegex(ValueError, 'OFFICIAL_ROSTER_BINDING'):
                exhibit.validate_rank_cohort(packet, report, amended, *rest)
            confirmed.assert_not_called()

    def test_rejects_noncanonical_runner_context(self):
        for name in exhibit.RUNNER_CONTEXT:
            context = dict(exhibit.RUNNER_CONTEXT)
            context[name] = 'unexpected'
            with self.subTest(name=name), self.assertRaises(ValueError):
                exhibit.require_runner(context)
        exhibit.require_runner(exhibit.RUNNER_CONTEXT)
