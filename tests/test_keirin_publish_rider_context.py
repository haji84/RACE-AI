import json
from copy import deepcopy
from unittest.mock import Mock

from race_ai import keirin_dossier_race_context as context
from race_ai import keirin_public_forecasts as public
from scripts import keirin_publish_rider_context as publisher
from tests import test_keirin_dossier_race_context as fixture


class PublishRiderContextTests(fixture.DossierRaceContextTests):
    def store(self, *, prior=None):
        store = Mock()
        store.head.return_value = 'a' * 40
        row = context.project_sp_context(self.payload, self.admitted)
        day = self.starters['day']
        registry = dict(schema=public.SCHEMA, day=day, published_at=self.at.isoformat(), races=[
            dict(race_id=race['race_id'], cutoff_at=row['cutoff_at'], status='pending', saved_at=None, a=[], b=[])
            for race in self.starters['races']])
        starters = deepcopy(self.starters)
        for race in starters['races']:
            for rider in race['riders']:
                rider['name'] = f"テスト {rider['number']}"
        files = {f'forecasts/{day}.json': registry, f'starters/{day}.json': starters}
        path = f'rider-context/{day}.json'
        if prior is not None:
            files[path] = prior

        def read(head, name):
            if head == 'b' * 40:
                return store.commit.call_args.args[0][name]
            if name in files:
                return json.dumps(files[name]).encode()
            return None

        store.read_previous.side_effect = read
        store.commit.return_value = 'b' * 40
        store.run.return_value = (path + '\n').encode()
        return store, row

    def test_writes_only_the_roster_bound_day_and_reads_back(self):
        store, row = self.store()
        report = publisher.publish_day(None, self.starters['day'], [row],
                                       published_at=self.at, store=store)
        self.assertEqual(report['state'], 'PUBLIC_RIDER_CONTEXT_UPDATED')
        self.assertEqual(report['coverage']['verified_riders'], 7)
        self.assertEqual(report['registered_calendar_races'], 2)
        path = f"rider-context/{self.starters['day']}.json"
        outputs = store.commit.call_args.args[0]
        self.assertEqual(list(outputs), [path])
        self.assertEqual(context.checked_day(json.loads(outputs[path]))['races'], [row])
        store.push.assert_called_once_with('b' * 40, 'a' * 40)

    def test_retry_preserves_previous_verified_races(self):
        row = context.project_sp_context(self.payload, self.admitted)
        prior = context.build_day(self.starters, [row], published_at=self.at)
        store, _ = self.store(prior=prior)
        report = publisher.publish_day(None, self.starters['day'], [],
                                       published_at=self.at, store=store)
        self.assertEqual(report['state'], 'PUBLIC_RIDER_CONTEXT_CURRENT')
        self.assertEqual(report['coverage'], prior['coverage'])
        store.commit.assert_not_called()
        store.push.assert_not_called()

    def test_cutoff_change_fails_before_writing(self):
        store, row = self.store()
        row['cutoff_at'] = self.at.isoformat()
        with self.assertRaisesRegex(ValueError, 'DOSSIER_REGISTRY_CUTOFF'):
            publisher.publish_day(None, self.starters['day'], [row], published_at=self.at, store=store)
        store.commit.assert_not_called()
