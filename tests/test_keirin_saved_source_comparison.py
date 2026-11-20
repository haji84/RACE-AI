"""Retained-summary corroboration only; no provider or official-status upgrade."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest
from unittest.mock import patch

from race_ai import keirin_saved_source_comparison as saved
from race_ai import keirin_secondary_result_consensus as consensus
from race_ai import keirin_result_updates as updates
from race_ai import keirin_official_public_source as official
from tests.test_keirin_official_public_source import fixtures, transport, DAY, RACE, NOW


def archive_record(*, triple=(1, 2, 3), yen=1230, observed='2026-10-02T08:00:00+00:00'):
    receipts = []
    for provider, url in (
        ('Kdreams', 'https://keirin.kdreams.jp/seibuen/racedetail/2620261002010001/?pageType=result'),
        ('netkeirin', 'https://keirin.netkeiba.com/race/result/?race_id=' + RACE),
    ):
        receipts.append(dict(provider=provider, source_url=url,
            source_bytes_sha256=sha256(provider.encode()).hexdigest(), observed_at=observed))
    doc = dict(schema=consensus.SCHEMA, race_id=RACE,
        state='SECONDARY_TWO_SOURCES_MATCH_NOT_OFFICIAL', winning_triple=list(triple),
        payout_per_100yen=yen, provider_receipts=receipts,
        official_primary_result_authenticated=False, actual_organizer_cutoff_authenticated=False,
        qualifies_for_formal_settlement=False)
    return encode(doc)


def encode(doc):
    raw = (json.dumps(doc, sort_keys=True, separators=(',', ':')) + '\n').encode()
    return dict(sha256=sha256(raw).hexdigest(), raw=raw)


class SavedSourceComparisonTests(unittest.TestCase):
    def row(self):
        get = transport(fixtures())
        schedule = official.fetch_day_schedule(DAY, fetcher=get, clock=lambda: NOW)
        record = official.fetch_race_result(RACE, schedule=schedule, fetcher=get, clock=lambda: NOW)
        return updates.from_official_records({RACE: record}, {})['races'][0]

    def compare(self, records, row=None):
        row = row or self.row()
        return saved.retained_source_comparisons('/unused', [row], clock=lambda: NOW,
            reader=lambda repo, ids: {RACE: records})[RACE]

    def test_matching_retained_summaries_add_comparison_without_touching_official_decisions(self):
        row = self.row(); original = deepcopy(row)
        compared = self.compare([archive_record()], row)
        self.assertEqual(compared, [
            {'source_id': 'official_json', 'state': 'matched'},
            {'source_id': 'kdreams', 'state': 'matched'},
            {'source_id': 'netkeirin', 'state': 'matched'}])
        self.assertEqual(row, original)
        self.assertEqual(row['authority'], 'official')
        self.assertEqual(row['arms']['A']['state'], 'unverifiable')

    def test_different_secondary_value_does_not_override_official_result(self):
        row = self.row(); original = deepcopy(row)
        result = self.compare([archive_record(triple=(2, 1, 3))], row)
        self.assertEqual([r['state'] for r in result], ['matched', 'different', 'different'])
        self.assertEqual(row, original)

    def test_payout_comparison_requires_confirmed_official_unit(self):
        different = archive_record(yen=4560)
        self.assertEqual(self.compare([different])[-1]['state'], 'different')
        row = self.row(); row['payout_status'] = 'pending'; row['payouts_100yen'] = {}
        self.assertEqual(self.compare([different], row)[-1]['state'], 'matched')
        self.assertEqual(row['payout_status'], 'pending')

    def test_latest_unambiguous_retained_revision_controls_comparison(self):
        old = archive_record(triple=(2, 1, 3), observed='2026-10-02T07:00:00+00:00')
        newer = archive_record(observed='2026-10-02T07:01:00+00:00')
        self.assertEqual(self.compare([newer, old])[-1]['state'], 'matched')
        self.assertEqual(self.compare([old, newer])[-1]['state'], 'matched')

    def test_tied_latest_observation_with_conflicting_values_stays_unverified(self):
        result = self.compare([archive_record(), archive_record(triple=(2, 1, 3))])
        self.assertEqual([r['state'] for r in result], ['matched', 'unverified', 'unverified'])

    def test_missing_is_unavailable_and_corrupt_is_unverified(self):
        self.assertEqual(self.compare([])[-1]['state'], 'unavailable')
        item = archive_record(); item['sha256'] = '0' * 64
        self.assertEqual(self.compare([item])[-1]['state'], 'unverified')
        self.assertEqual(self.compare(None)[-1]['state'], 'unverified')

    def test_claimed_official_or_wrong_race_or_missing_provider_receipt_is_not_accepted(self):
        base = json.loads(archive_record()['raw'])
        cases = []
        changed = deepcopy(base); changed['qualifies_for_formal_settlement'] = True; cases.append(changed)
        changed = deepcopy(base); changed['race_id'] = '202610022602'; cases.append(changed)
        changed = deepcopy(base); changed['provider_receipts'].pop(); cases.append(changed)
        changed = deepcopy(base); changed['provider_receipts'][0]['source_url'] = 'https://example.invalid/?secret=private'; cases.append(changed)
        changed = deepcopy(base); changed['provider_receipts'][0]['observed_at'] = '2099-01-01T00:00:00+00:00'; cases.append(changed)
        changed = deepcopy(base); changed['provider_receipts'][0]['observed_at'] = '2026-10-02T08:00:00'; cases.append(changed)
        changed = deepcopy(base); changed['provider_receipts'][0]['source_bytes_sha256'] = 'invalid'; cases.append(changed)
        for doc in cases:
            with self.subTest(doc=doc):
                self.assertEqual(self.compare([encode(doc)])[-1]['state'], 'unverified')

    def test_duplicate_json_fields_cannot_hide_false_authority_flags(self):
        item = archive_record()
        raw = item['raw'].replace(b'"qualifies_for_formal_settlement":false',
            b'"qualifies_for_formal_settlement":true,"qualifies_for_formal_settlement":false')
        item = dict(raw=raw, sha256=sha256(raw).hexdigest())
        self.assertEqual(self.compare([item])[-1]['state'], 'unverified')

    def test_source_read_failure_does_not_erase_official_result_or_leak_error(self):
        row = self.row(); original = deepcopy(row)

        def broken(*_):
            raise OSError('SECRET_GIT_CONTEXT')

        result = saved.retained_source_comparisons('/unused', [row], clock=lambda: NOW, reader=broken)
        self.assertEqual(row, original)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertEqual(result[RACE][-1]['state'], 'unverified')

    def test_empty_or_secondary_only_rows_do_not_open_git_or_create_officiality(self):
        secondary = self.row(); secondary['authority'] = 'secondary'
        for rows in ([], [secondary]):
            with patch.object(saved, 'read_retained_records') as reader:
                result = saved.retained_source_comparisons('/unused', rows, clock=lambda: NOW)
            reader.assert_not_called()
            self.assertEqual(result, {})
        self.assertEqual(secondary['authority'], 'secondary')

    def test_default_reader_uses_one_pinned_git_head_and_selected_race_directory(self):
        item = archive_record(); head = 'a' * 40
        directory = saved.ROOT + '/' + DAY + '/' + RACE
        path = directory + '/' + item['sha256'] + '.json'
        tree = '100644 blob ' + 'b' * 40 + '\t' + item['sha256'] + '.json\0'
        commands = []

        def command(repo, *args, **kw):
            commands.append(args)
            if args[1:3] == ('cat-file', '-t'): return 0, 'tree'
            if args[1:3] == ('cat-file', '-s'): return 0, '200'
            if args[1] == 'ls-tree': return 0, tree
            self.fail('Unexpected Git operation')

        with patch.object(saved.archive, '_remote', return_value='/unused'), \
                patch.object(saved.archive, '_refresh', return_value=head) as refresh, \
                patch.object(saved.archive, '_cmd', side_effect=command), \
                patch.object(saved.archive, 'read_blob_bytes', return_value=item['raw']) as read:
            records = saved.read_retained_records('/unused', [RACE])
        refresh.assert_called_once()
        self.assertEqual(records[RACE], [item])
        read.assert_called_once_with('/unused', head, path, max_bytes=saved.MAX_RECORD_BYTES)
        self.assertTrue(all(directory in ' '.join(map(str, command)) for command in commands))

    def test_nested_race_tree_is_rejected_without_recursive_expansion(self):
        commands = []

        def command(repo, *args, **kw):
            commands.append(args)
            if args[1:3] == ('cat-file', '-t'): return 0, 'tree'
            if args[1:3] == ('cat-file', '-s'): return 0, '100'
            if args[1] == 'ls-tree':
                return 0, '040000 tree ' + 'b' * 40 + '\tnested\0'
            self.fail('Unexpected Git operation')

        with patch.object(saved.archive, '_remote', return_value='/unused'), \
                patch.object(saved.archive, '_refresh', return_value='a' * 40), \
                patch.object(saved.archive, '_cmd', side_effect=command), \
                patch.object(saved.archive, 'read_blob_bytes') as read:
            records = saved.read_retained_records('/unused', [RACE])
        self.assertIsNone(records[RACE])
        read.assert_not_called()
        listed = [command for command in commands if command[1] == 'ls-tree']
        self.assertEqual(len(listed), 1)
        self.assertNotIn('-r', listed[0])
        self.assertIn('a' * 40 + ':' + saved.ROOT + '/' + DAY + '/' + RACE, listed[0])

    def test_corrupt_blob_reads_consume_batch_read_budget(self):
        races = [RACE[:10] + suffix for suffix in ('01', '02', '03')]

        def command(repo, *args, **kw):
            if args[1:3] == ('cat-file', '-t'): return 0, 'tree'
            if args[1:3] == ('cat-file', '-s'): return 0, '200'
            if args[1] == 'ls-tree':
                # Current and former listing formats are accepted by this fake;
                # the assertion concerns how many invalid blobs are read.
                prefix = args[-1] if '-r' in args else ''
                return 0, '100644 blob ' + 'b' * 40 + '\t' + prefix + '0' * 64 + '.json\0'
            self.fail('Unexpected Git operation')

        for limit, value, expected_reads in (('MAX_RECORDS', 2, 2), ('MAX_TOTAL_BYTES', 7, 1)):
            with self.subTest(limit=limit), patch.object(saved, limit, value), \
                    patch.object(saved.archive, '_remote', return_value='/unused'), \
                    patch.object(saved.archive, '_refresh', return_value='a' * 40), \
                    patch.object(saved.archive, '_cmd', side_effect=command), \
                    patch.object(saved.archive, 'read_blob_bytes', return_value=b'invalid') as read:
                records = saved.read_retained_records('/unused', races)
                self.assertTrue(all(records[rid] is None for rid in races))
                self.assertEqual(read.call_count, expected_reads)

    def test_oversized_race_directory_is_not_listed_or_read(self):
        def command(repo, *args, **kw):
            if args[1:3] == ('cat-file', '-t'): return 0, 'tree'
            if args[1:3] == ('cat-file', '-s'): return 0, str(saved.MAX_TREE_BYTES + 1)
            self.fail('Over-budget tree was listed')

        with patch.object(saved.archive, '_remote', return_value='/unused'), \
                patch.object(saved.archive, '_refresh', return_value='a' * 40), \
                patch.object(saved.archive, '_cmd', side_effect=command), \
                patch.object(saved.archive, 'read_blob_bytes') as read:
            records = saved.read_retained_records('/unused', [RACE])
        self.assertIsNone(records[RACE])
        read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
