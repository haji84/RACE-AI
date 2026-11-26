from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from race_ai import keirin_official_nationwide_records as records
from race_ai import keirin_official_rider_history as history
from scripts import keirin_official_day_pipeline as pipeline
from scripts import keirin_daily_rider_update as dossier


FIRST = '2026-11-23'
NEXT = '2026-11-24'
NOW = datetime(2026, 11, 24, 15, tzinfo=timezone.utc)
RIDER = '991001'


class PublicStore:
    def __init__(self):
        self.current = 'a' * 40
        self.trees = {self.current: {'odds/2026-11-23.json': b'preexisting'}}
        self.changed = {}
        self.published = 0

    def head(self):
        return self.current

    def fetch(self, head):
        assert head in self.trees

    def read_previous(self, head, path):
        return self.trees[head].get(path)

    def commit(self, files, parent):
        commit = sha256(b''.join(files.values())).hexdigest()[:40]
        self.changed[commit] = set(files)
        self.trees[commit] = {**self.trees[parent], **files}
        return commit

    def run(self, args):
        if args[0] == 'diff-tree':
            return '\n'.join(sorted(self.changed[args[-1]])).encode()
        assert args[0] == 'ls-tree'
        return '\n'.join(path for path in self.trees[args[-3]]
                         if path.startswith('rider-history/')).encode()

    def push(self, commit, parent):
        assert parent == self.head()
        self.current = commit
        self.published += 1


def receipt(day, rank, signature='b'):
    counts = [0] * 9
    counts[rank - 1] = 1
    return dict(schema='RACE_AI_KEIRIN_PUBLIC_RIDER_HISTORY_DAY_V1', day=day,
                source_sha256=signature * 64, archive_races=1, verified_races=1,
                riders=[dict(registration=RIDER, finish_counts=counts)])


class DailyHistoryPublicationTests(unittest.TestCase):
    def setUp(self):
        self.store = PublicStore()

    def publish(self, days, at=NOW):
        prior = dossier.read_latest(self.store)[1]
        return dossier.publish_days(self.store, prior, days, published_at=at)

    def latest(self):
        return json.loads(self.store.read_previous(self.store.head(), dossier.LATEST))

    def test_daily_results_accumulate_and_a_correction_replaces_that_day(self):
        self.publish({'a' * 40: receipt(FIRST, 1), 'b' * 40: receipt(NEXT, 3)})
        self.assertEqual(self.latest()['riders'], [dict(registration=RIDER,
            finish_counts=[1, 0, 1, 0, 0, 0, 0, 0, 0],
            first_observed_day=FIRST, latest_observed_day=NEXT)])
        old_second = self.store.read_previous(self.store.head(), f'rider-history/{NEXT}.json')
        self.publish({'c' * 40: receipt(FIRST, 2, signature='d')}, NOW.replace(minute=1))
        head = self.store.head()
        self.assertEqual(self.store.changed[head], {dossier.LATEST, f'rider-history/{FIRST}.json'})
        self.assertEqual(self.latest()['riders'][0]['finish_counts'], [0, 1, 1, 0, 0, 0, 0, 0, 0])
        self.assertEqual([row['day'] for row in self.latest()['days']], [FIRST, NEXT])
        self.assertEqual(self.store.read_previous(head, f'rider-history/{NEXT}.json'), old_second)
        self.assertEqual(self.store.read_previous(head, 'odds/2026-11-23.json'), b'preexisting')
        self.publish({'c' * 40: receipt(FIRST, 2, signature='d')}, NOW.replace(minute=2))
        self.assertEqual(self.store.published, 2)

    def test_malformed_or_overlapping_data_does_not_replace_the_directory(self):
        self.publish({'a' * 40: receipt(FIRST, 1)})
        original = self.store.head()
        for change in (
            dict(receipt('2026-11-22', 1)),
            dict(receipt(NEXT, 1), verified_races=0),
            dict(receipt(NEXT, 1), source_url='private'),
        ):
            with self.subTest(day=change['day']), self.assertRaises(ValueError):
                self.publish({'c' * 40: change}, NOW.replace(minute=1))
            self.assertEqual(original, self.store.head())

    def test_recent_view_keeps_updating_after_the_first_result_ages_out(self):
        self.publish({'a' * 40: receipt(FIRST, 1), 'b' * 40: receipt(NEXT, 2)})
        first_path = f'rider-history/{FIRST}.json'
        first_raw = self.store.read_previous(self.store.head(), first_path)
        later_day = '2027-12-28'
        at = datetime(2027, 12, 28, tzinfo=timezone.utc)

        self.publish({'c' * 40: receipt(later_day, 3)}, at)
        self.assertEqual([row['day'] for row in self.latest()['days']], [NEXT, later_day])
        self.assertEqual(self.latest()['riders'][0]['finish_counts'], [0, 1, 1, 0, 0, 0, 0, 0, 0])
        self.assertEqual(self.store.read_previous(self.store.head(), first_path), first_raw)

        self.assertIsNone(self.publish({'c' * 40: receipt(later_day, 3)}, at.replace(minute=1)))
        self.publish({'d' * 40: receipt(NEXT, 4, 'e')}, at.replace(minute=2))
        self.assertEqual(self.latest()['riders'][0]['finish_counts'], [0, 0, 1, 1, 0, 0, 0, 0, 0])
        self.assertEqual(self.store.read_previous(self.store.head(), first_path), first_raw)

    def test_mismatched_previous_day_bytes_and_newer_snapshot_stop_the_write(self):
        self.publish({'a' * 40: receipt(FIRST, 1)})
        prior = self.latest()
        self.publish({'b' * 40: receipt(NEXT, 2)}, NOW.replace(minute=1))
        with self.assertRaises(ValueError):
            dossier.publish_days(self.store, prior, {'c' * 40: receipt(FIRST, 3)},
                                 published_at=NOW.replace(minute=2))
        fresh = self.store.head()
        next_day = f'rider-history/{NEXT}.json'
        self.store.trees[fresh][next_day] = self.store.trees[fresh][next_day] + b' '
        with self.assertRaises(ValueError):
            self.publish({'c' * 40: receipt(FIRST, 3)}, NOW.replace(minute=2))
        self.assertEqual(self.store.head(), fresh)

    def test_unrelated_archive_updates_do_not_take_the_replay_slots(self):
        days = [f'2026-11-{day}' for day in range(23, 29)]
        previous = {s * 40: receipt(day, 1) for s, day in zip('abc', (days[0], days[1], days[4]))}
        self.publish(previous, datetime(2026, 11, 28, tzinfo=timezone.utc))
        indexes = {day: f'{i+1:040x}' for i, day in enumerate(days)}
        checked = []

        def open_day(reader, day, *, index_commit):
            return SimpleNamespace(day=day, index={'results': {} if day in (days[3], days[5]) else {'race': 1}})

        def replay(store, private, *, now):
            checked.append(store.day)
            return receipt(store.day, 2, 'c')

        directory = Path(__file__).resolve().parents[1]
        pin = directory / 'docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem'
        with (patch.object(pipeline, 'check_owner_private_key', return_value=pin.read_bytes()),
              patch.object(records, 'fetch_partial_head', return_value='e' * 40),
              patch.object(records, 'discover_days_at', return_value=days),
              patch.object(dossier, '_archive_indexes', return_value=indexes),
              patch.object(records, 'RecordStore', side_effect=open_day),
              patch.object(history, 'archive_signature', return_value='b' * 64),
              patch.object(history, 'project_rider_day', side_effect=replay)):
            report = dossier.refresh(directory, 'synthetic', b'', store=self.store,
                                     clock=lambda: datetime(2026, 11, 29, tzinfo=timezone.utc))
        self.assertEqual(checked, [days[2]])
        self.assertEqual(report['days_updated'], 1)

    def test_unchanged_archive_still_checks_the_published_summary(self):
        self.publish({'a' * 40: receipt(FIRST, 1)})
        live = self.latest()
        live['riders'][0]['finish_counts'][0] = 2
        self.store.trees[self.store.head()][dossier.LATEST] = dossier._encode(live)
        directory = Path(__file__).resolve().parents[1]
        pin = directory / 'docs/evidence/2026-11-18/keirin_owner_existing_rsa_public_spki3072.pem'
        with (patch.object(pipeline, 'check_owner_private_key', return_value=pin.read_bytes()),
              patch.object(records, 'fetch_partial_head', return_value='e' * 40),
              patch.object(records, 'discover_days_at', return_value=[FIRST]),
              patch.object(dossier, '_archive_indexes', return_value={FIRST: 'a' * 40}),
              self.assertRaisesRegex(ValueError, 'PREVIOUS_AGGREGATE')):
            dossier.refresh(directory, 'synthetic', b'', store=self.store, clock=lambda: NOW)
        self.assertEqual(self.store.published, 1)


if __name__ == '__main__':
    unittest.main()
