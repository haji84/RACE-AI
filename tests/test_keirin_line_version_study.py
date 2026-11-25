import copy
from datetime import datetime
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import keirin_line_version_study as versions


def card(groups, clock):
    return {'date':'2026-11-24','race_id':'202611241101','deadline_time':'08:45',
            'fetched_at':f'2026-11-24T{clock}:00+09:00','lines':groups,
            'riders':[{'number':i,'name':f'Starter {i}'} for i in range(1,6)]}


class LineVersionTests(unittest.TestCase):
    def test_outer_order_preserves_the_line_and_inner_order_changes_it(self):
        old=card([[1,2],[3,4,5]],'06:00')
        self.assertEqual(versions.compare(old,card([[3,4,5],[1,2]],'08:30')),'unchanged')
        self.assertEqual(versions.compare(old,card([[3,4,5],[2,1]],'08:30')),'within_line_order')

    def test_publication_and_split_are_distinct(self):
        self.assertEqual(versions.compare(card(None,'06:00'),card([[1,2],[3,4],[5]],'08:30')),'newly_listed')
        self.assertEqual(versions.compare(card([[1,2],[3,4,5]],'06:00'),card([[1,2],[3,4],[5]],'08:30')),'split')

    def test_reject_version_at_cutoff_and_name_changes(self):
        old=card([[1,2],[3,4,5]],'06:00')
        with self.assertRaisesRegex(ValueError,'before the same cutoff'):
            versions.compare(old,card([[1,2],[3,4,5]],'08:45'))
        new=card([[1,2],[3,4,5]],'08:30')
        new['riders'][0]['name']='Someone else'
        with self.assertRaisesRegex(ValueError,'same full field'):
            versions.compare(old,new)


class PrivateRevisionTests(unittest.TestCase):
    def setUp(self):
        self.original = card(None, '06:00')
        self.original.update(cutoff_at='2026-11-24T08:45:00+09:00',
                             forecast_generated_at='2026-11-24T06:01:00+09:00')
        self.pub = dict(schema='KEIRIN_PUBLISHED_LINE_RANK_V3', date='2026-11-24', races=[self.original])
        self.card = card([[1, 2], [3, 4, 5]], '08:42')
        self.card.update(listed_lines=self.card['lines'], no_today_results_used=True, source_sha256='a'*64,
                         source_url='https://keirin.kdreams.jp/hakodate/racedetail/1120261124010001/')
        stats = dict(captured_at=self.card['fetched_at'], url=self.card['source_url'], bytes_sha256='a'*64)
        h_receipt = dict(captured_at=self.card['fetched_at'], bytes_sha256='b'*64,
                         url='https://keirin.netkeiba.com/race/entry/?race_id=202611241101')
        for row in self.card['riders']:
            row.update({field: 1 for field in versions.RIDER_FIELDS if field not in row})
            row['field_sources'] = dict(statistics=stats.copy(), H=h_receipt.copy())
        self.meta = dict(captured_at='2026-11-24T08:43:00+09:00', ref='d'*40, cipher_sha256='e'*64)
        self.now = datetime.fromisoformat('2026-11-24T08:44:00+09:00')
        self.rid = self.original['race_id']

    def compare(self, observations):
        return versions.select_revisions(self.pub, observations, self.now)

    def test_fresh_input_inside_last_five_minutes_preserves_original(self):
        initial = copy.deepcopy(self.pub)
        result = self.compare([(self.card, self.meta)])
        self.assertEqual(result['states'], {'newly_listed': 1})
        selected = result['races'][self.rid]
        self.assertEqual(selected['lines'], [[1, 2], [3, 4, 5]])
        self.assertNotIn('field_sources', selected['riders'][0])
        self.assertEqual(self.pub, initial)
        self.now = datetime.fromisoformat(self.original['cutoff_at'])
        self.assertEqual(self.compare([(self.card, self.meta)])['states'], {'outside_open_window': 1})

    def test_packet_arriving_after_original_uses_source_age(self):
        self.original.update(source_as_of='2026-11-24T06:00:00+09:00',
                             forecast_generated_at='2026-11-24T08:00:00+09:00')
        self.card['fetched_at'] = '2026-11-24T07:59:00+09:00'
        for rider in self.card['riders']:
            for evidence in rider['field_sources'].values():
                evidence['captured_at'] = self.card['fetched_at']
        self.meta['captured_at'] = '2026-11-24T08:01:00+09:00'
        self.assertEqual(self.compare([(self.card, self.meta)])['states'], {'newly_listed': 1})
        self.original['source_as_of'] = '2026-11-24T08:02:00+09:00'
        with self.assertRaisesRegex(ValueError, 'original race date, source time'):
            self.compare([(self.card, self.meta)])

    def test_cutoff_roster_attestations_and_active_field(self):
        for mutate in (lambda c: c.update(deadline_time='08:59'),
                       lambda c: c['riders'][0]['field_sources']['H'].update(url=c['source_url']),
                       lambda c: c['riders'][0]['field_sources']['statistics'].update(bytes_sha256='0'*64),
                       lambda c: c.update(no_today_results_used=False),
                       lambda c: c.update(source_url=c['source_url'] + '?pageType=result'),
                       lambda c: c.update(listed_lines=[[1], [2, 3]])):
            candidate = copy.deepcopy(self.card)
            mutate(candidate)
            self.assertEqual(self.compare([(candidate, self.meta)])['states'], {'unverified_latest_observation': 1})
        for reason, mutate in (
            ('starter_or_identity_changed', lambda c: c['riders'][0].update(name='different')),
            ('withdrawal_reported', lambda c: c['riders'][0].update(is_absent=True)),
            ('latest_line_unavailable', lambda c: c.update(listed_lines=[])),
            ('latest_line_sources_disagree', lambda c: c.update(listed_lines=[[1, 3], [2, 4, 5]])),
        ):
            candidate = copy.deepcopy(self.card)
            mutate(candidate)
            self.assertEqual(self.compare([(candidate, self.meta)])['states'], {reason: 1})
        later_packet = dict(self.meta, captured_at='2026-11-24T08:46:00+09:00')
        self.assertEqual(self.compare([(self.card, later_packet)])['states'], {'no_new_observation': 1})

    def test_choose_latest_and_hold_conflicts_independent_of_packet_order(self):
        earlier = copy.deepcopy(self.card)
        earlier['fetched_at'] = '2026-11-24T08:40:00+09:00'
        earlier['lines'] = earlier['listed_lines'] = [[1, 3, 5], [2, 4]]
        for r in earlier['riders']:
            r['field_sources']['statistics']['captured_at'] = earlier['fetched_at']
        obs = [(earlier, self.meta), (self.card, self.meta), (self.card, self.meta)]
        self.original['lines'] = earlier['lines']
        self.assertEqual(self.compare(obs), self.compare(list(reversed(obs))))
        self.assertEqual(self.compare(obs)['states'], {'changed': 1})
        conflict = copy.deepcopy(self.card)
        conflict['lines'] = conflict['listed_lines'] = earlier['lines']
        self.assertEqual(self.compare(obs + [(conflict, self.meta)])['states'], {'conflicting_latest_observation': 1})
        self.original['lines'] = list(reversed(self.card['lines']))
        self.assertEqual(self.compare(obs)['states'], {'unchanged': 1})

    def test_ambiguous_riders_are_held_but_an_independent_field_passes(self):
        for race in (self.original, self.card):
            race['riders'][1]['name'] = race['riders'][0]['name'] + ' '
        self.assertEqual(self.compare([(self.card, self.meta)])['states'], {'unverified_latest_observation': 1})
        for race in (self.original, self.card):
            race['riders'][1]['name'] = 'Second'
            race['riders'][0]['number'] = True
        self.assertEqual(self.compare([(self.card, self.meta)])['states'], {'unverified_latest_observation': 1})
        self.assertIsNone(versions.registered_program_riders([1, 2], lambda r: '111111'))
        self.assertIsNone(versions.registered_program_riders([1, 2], lambda r: None))
        self.assertEqual(versions.registered_program_riders([1, 2], lambda r: str(r)), ['1', '2'])

    def test_freeze_drops_only_race_that_closes_during_durable_readback(self):
        times = [self.now.replace(minute=n) for n in (44, 45, 45, 46)]
        rows = [
            dict(race_id='first', cutoff_at=self.original['cutoff_at']),
            dict(race_id='second', cutoff_at=self.now.replace(minute=50).isoformat()),
        ]
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'predictions.json'
            receipt = versions.freeze_private_rankings(path, rows, context={}, packet_hashes=dict(first='a', second='b'),
                                                        clock=lambda: times.pop(0))
            self.assertEqual(json.loads(path.read_bytes())['races'], rows[1:])
            self.assertEqual(receipt['expired'], 1)
            self.assertEqual(receipt['frozen_at'], self.now.replace(minute=46).isoformat())
            self.assertEqual(receipt['prediction_sha256'], sha256(path.read_bytes()).hexdigest())
            self.assertEqual(receipt, json.loads(path.with_name(path.name + '.receipt.json').read_bytes()))
            with self.assertRaises(FileExistsError):
                versions.freeze_private_rankings(path, [], context={}, packet_hashes={})

    def test_native_weights_and_source_hashes_checked_before_use(self):
        with TemporaryDirectory() as tmp:
            source = Path(tmp)
            sha = lambda data: sha256(data).hexdigest()
            for name in ('coefficients.owner.pkl','fallback.json','snapshot_inputs.owner.json','snapshot_predictions.owner.json'):
                (source / name).write_bytes(name.encode())
            pub = dict(schema='KEIRIN_PUBLISHED_LINE_RANK_V3', model_id='video_line_ordered',
                       weights_sha256=sha(b'coefficients.owner.pkl'), fallback_weights_sha256=sha(b'fallback.json'))
            receipt = dict(inputs_sha256=sha(b'snapshot_inputs.owner.json'), prediction_sha256=sha(b'snapshot_predictions.owner.json'))
            (source / 'forward-commitment.json').write_text(json.dumps(receipt))
            self.assertEqual(versions.verified_public_weights(pub, source, source/'fallback.json'), b'coefficients.owner.pkl')
            with self.assertRaisesRegex(ValueError, 'weights'):
                versions.verified_public_weights(dict(pub,weights_sha256='0'*64), source, source/'fallback.json')
            (source / 'snapshot_inputs.owner.json').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'snapshot'):
                versions.verified_public_weights(pub, source, source/'fallback.json')

    def test_cli_binds_bytes_refuses_overwrite_and_keeps_private_output(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            pub = path / 'published.gz'
            pub.write_bytes(gzip.compress(json.dumps(self.pub).encode()))
            body = json.dumps(dict(date=self.pub['date'], races=[self.card])).encode()
            (path / 'owner-races.json').write_bytes(body)
            hashes = {'data/2026-11-24/races.json': sha256(body).hexdigest()}
            (path / 'provenance.json').write_text(json.dumps(dict(self.meta, file_hashes=hashes)))
            output = path / 'research.json'
            argv = ['--published', str(pub), '--restored', str(path), '--output', str(output), '--as-of', self.now.isoformat()]
            # Supply a fixed later wall clock so the replay also runs before 2026 in CI.
            from unittest.mock import patch
            with patch.object(versions, 'datetime', wraps=datetime) as timer:
                timer.now.return_value = self.now
                self.assertEqual(versions.main(argv), 0)
                expected = output.read_bytes()
                self.assertEqual(output.stat().st_mode & 0o077, 0)
                with self.assertRaises(SystemExit):
                    versions.main(argv)
                self.assertEqual(output.read_bytes(), expected)
                (path / 'owner-races.json').write_bytes(body + b' ')
                with self.assertRaisesRegex(ValueError, 'digest mismatch'):
                    versions.restored_packet(path, self.pub['date'])


if __name__=='__main__':
    unittest.main()
