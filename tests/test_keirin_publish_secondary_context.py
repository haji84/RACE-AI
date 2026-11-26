import json
from datetime import datetime
import unittest
from unittest.mock import Mock, patch

from race_ai import keirin_dossier_secondary as secondary
from race_ai import keirin_public_forecasts as public
from scripts import keirin_publish_secondary_context as publisher
from tests.test_keirin_dossier_secondary import (
    CAPTURED, DAY, OFFICIAL_CUTOFF, PUBLISHED, RACE_ID, receipt, roster, saved_card,
)


class PublishSecondaryContextTest(unittest.TestCase):
    def store(self, *, published=True):
        store = Mock()
        store.head.return_value = 'a' * 40
        store.commit.return_value = 'b' * 40
        path = f'rider-context-secondary/{DAY}.json'
        store.run.return_value = (path + '\n').encode()
        files = {}
        if published:
            files[f'starters/{DAY}.json'] = dict(schema=secondary.context.STARTERS_SCHEMA,
                day=DAY, published_at=CAPTURED, races=[roster()])
            files[f'forecasts/{DAY}.json'] = dict(schema=public.SCHEMA, day=DAY, published_at=CAPTURED, races=[
                dict(race_id=RACE_ID, cutoff_at=OFFICIAL_CUTOFF, status='pending', saved_at=None, a=[], b=[])])

        def read(commit, requested):
            if commit == 'b' * 40:
                return store.commit.call_args.args[0][requested]
            return json.dumps(files[requested]).encode() if requested in files else None

        store.read_previous.side_effect = read
        return store, path

    def test_publishes_only_bound_derived_race_data(self):
        store, path = self.store()
        raw = saved_card()
        with patch.object(publisher, '_national_identities') as directory:
            report = publisher.publish_cards(None, DAY, [(RACE_ID, raw, receipt(raw), None)],
                published_at=datetime.fromisoformat(PUBLISHED), published_only=True, store=store)
        self.assertEqual(report['state'], 'PUBLIC_RIDER_CONTEXT_SECONDARY_UPDATED')
        self.assertEqual(report['coverage']['verified_riders'], 5)
        self.assertEqual(report['provider_requests'], 0)
        directory.assert_not_called()
        files = store.commit.call_args.args[0]
        self.assertEqual(list(files), [path])
        decoded = secondary.checked_day(json.loads(files[path]))
        self.assertEqual(public.when(decoded['races'][0]['cutoff_at']), public.when(OFFICIAL_CUTOFF))
        self.assertNotIn('私的記述'.encode(), files[path])

    def test_early_capture_requires_unique_verified_directory_identities(self):
        store, path = self.store(published=False)
        raw = saved_card()
        cards = [(RACE_ID, raw, receipt(raw), DAY + 'T15:10:00+09:00')]
        clock = {'published_at':datetime.fromisoformat(PUBLISHED),'published_only':False,'store':store}
        roster_ids = {publisher._person(row['name']): row['registration'] for row in roster()['riders']}
        with patch.object(publisher, '_national_identities', return_value={}):
            held = publisher.publish_cards(None, DAY, cards, **clock)
        self.assertEqual(held['state'], 'PUBLIC_RIDER_CONTEXT_SECONDARY_NO_QUALIFYING_ROWS')
        store.push.assert_not_called()
        with patch.object(publisher, '_national_identities', return_value=roster_ids):
            report = publisher.publish_cards(None, DAY, cards, **clock)
        self.assertEqual(report['coverage']['verified_riders'], 5)
        row = json.loads(store.commit.call_args.args[0][path])['races'][0]
        self.assertEqual(row['source_cutoff_at'], row['cutoff_at'])
