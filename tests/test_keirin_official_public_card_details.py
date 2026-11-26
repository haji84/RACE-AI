"""Public details are bound to synthetic frozen originals and checked Git receipts."""

from copy import deepcopy
from datetime import timedelta
import importlib
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from race_ai import keirin_confidence as confidence
from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_public_forecast_details as details
from race_ai import keirin_public_forecasts as public
from race_ai.keirin_note_view import canonical
from tests.test_keirin_nationwide_auto_generator import fixture
from tests.test_keirin_nationwide_forecast_view import DAY, NOW, RACE, nationwide_document


def five_starter_day():
    doc = nationwide_document()
    row = doc['races'][0]
    original = row['original']
    old = original['baseline']
    snapshot = fixture(5)
    snapshot.update(race_id=RACE, as_of=old['source_as_of'],
                    published_cutoff_at=old['published_cutoff_at'], line_groups=[[1, 2, 3], [4, 5]])
    snapshot['cutoff_source']['captured_at'] = snapshot['as_of']
    for source in snapshot['source_pages']:
        source['captured_at'] = snapshot['as_of']
    original['facts'] = {name: deepcopy(snapshot[name]) for name in ('competition', 'line_groups', 'riders')}
    original['baseline'] = model.generate_A_B(snapshot, generated_at=old['generated_at'])
    original['confidence_assessment'] = confidence.assess_baseline(snapshot, original['baseline'],
        assessed_at=original['baseline_sealed_at'])
    return doc


def prior_detail(race_id):
    return dict(race_id=race_id, b=None, a=dict(tickets=[[1, 2, 3]], grade=details.GRADE,
        reasons=['既存の参考予想。'], scenarios=[dict(ticket=[1, 2, 3], orders=[None] * 6)]))


class OfficialPublicCardDetailsTests(unittest.TestCase):
    def api(self):
        return importlib.import_module('race_ai.keirin_official_public_card_details')

    def test_five_starter_detail_copies_exact_saved_shortlist_and_B_phases(self):
        doc = five_starter_day()
        before = deepcopy(doc)
        shortlist = public.project(doc, published_at=NOW)
        original = doc['races'][0]['original']
        with (patch.object(model, 'generate_A_B', side_effect=AssertionError('regenerated forecast')),
              patch.object(model, 'generate_evidence_analysis', side_effect=AssertionError('new simulation')),
              patch.object(confidence, 'assess_baseline', side_effect=AssertionError('new assessment'))):
            body = self.api().project(doc, shortlist, published_at=NOW)
        self.assertEqual(details.checked(body), body)
        self.assertEqual(len(body['races']), 1)
        row = body['races'][0]
        self.assertEqual(set(row), {'race_id', 'saved_at', 'a', 'b'})
        self.assertEqual(row['saved_at'], original['baseline_sealed_at'])
        for arm in ('a', 'b'):
            self.assertEqual(row[arm]['tickets'], shortlist['races'][0][arm])
            self.assertEqual(row[arm]['grade'], '未校正')
            self.assertTrue(row[arm]['reasons'])
        self.assertTrue(all(scene['orders'] == [None] * 6 for scene in row['a']['scenarios']))
        for scene in row['b']['scenarios']:
            stored = [s for s in original['baseline']['B']['six_phase_scenarios']
                      if s['projected_3ren_tan'] == scene['ticket']]
            expected_orders = [[phase['projected_order'] for phase in s['six_phases']] for s in stored]
            self.assertIn(scene['orders'], expected_orders)
            self.assertTrue(all(sorted(order) == [1, 2, 3, 4, 5] for order in scene['orders']))
        self.assertEqual(row['b']['coherence_grade'], original['confidence_assessment']['evaluations']['B']['grade'])
        serialized = json.dumps(body)
        for field in ('athlete_id', 'baseline_cipher_sha256', 'source_facts_sha256', 'relative_research_weight', 'conditioned'):
            self.assertNotIn(field, serialized)
        self.assertEqual(doc, before)

    def test_current_shortlist_must_match_original_ticket_order_and_seal(self):
        doc = five_starter_day()
        for field in ('a', 'b', 'saved_at', 'cutoff_at'):
            with self.subTest(field=field):
                shortlist = public.project(doc, published_at=NOW)
                row = shortlist['races'][0]
                if field in ('a', 'b'):
                    row[field].reverse()
                else:
                    row[field] = (model.when(row[field]) + timedelta(seconds=1)).isoformat()
                body = self.api().project(doc, shortlist, published_at=NOW)
                self.assertEqual(body['races'], [])

    def test_publish_replaces_only_matched_rows_and_preserves_research(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repo, remote = root / 'repo', root / 'remote.git'

            def git(*args, cwd=None):
                return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.DEVNULL)

            git('init', '--bare', str(remote))
            git('init', str(repo))
            git('remote', 'add', 'origin', str(remote), cwd=repo)

            class LocalStore(public.PublicForecastGit):
                def _remote(self):
                    return 'origin'

            doc = five_starter_day()
            store = LocalStore(repo)
            shortlist = public.project(doc, published_at=NOW)
            shortlist_receipt = public.publish(repo, shortlist, store=store)
            research_row = prior_detail(doc['races'][1]['race_id'])
            previous = dict(schema=details.SCHEMA, day=DAY, published_at=NOW.isoformat(),
                            races=[prior_detail(RACE), research_row])
            path = f'details/{DAY}.json'
            parent = store.head()
            store.push(store.commit({path: canonical(details.checked(previous)) + b'\n'}, parent), parent)
            concurrent_row = prior_detail(doc['races'][2]['race_id'])
            concurrent_body = details.checked(dict(previous, races=[*previous['races'], concurrent_row]))
            push = store.push
            first_attempt = True

            def publish_research_before_first_official_write(commit, parent):
                nonlocal first_attempt
                if first_attempt:
                    first_attempt = False
                    research_commit = store.commit({path: canonical(concurrent_body) + b'\n'}, parent)
                    push(research_commit, parent)
                return push(commit, parent)

            with patch.object(store, 'push', side_effect=publish_research_before_first_official_write):
                receipt = self.api().publish(repo, doc, published_at=NOW, store=store)
            self.assertEqual(receipt['state'], 'PUBLIC_OFFICIAL_DETAILS_UPDATED')
            self.assertEqual(receipt['matched_official_races'], 1)
            head = store.head()
            body = details.checked(json.loads(store.read_previous(head, path)))
            self.assertEqual(body['races'][1:], [research_row, concurrent_row])
            self.assertNotIn('saved_at', body['races'][1])
            self.assertEqual(body['races'][0]['saved_at'], shortlist['races'][0]['saved_at'])
            self.assertEqual(body['races'][0]['b']['tickets'], shortlist['races'][0]['b'])
            forecast_path = f'forecasts/{DAY}.json'
            self.assertEqual(store.read_previous(head, forecast_path),
                             store.read_previous(shortlist_receipt['commit'], forecast_path))
            self.assertEqual(self.api().publish(repo, doc, published_at=NOW, store=store)['state'],
                             'PUBLIC_OFFICIAL_DETAILS_CURRENT')
            self.assertEqual(store.head(), head)


if __name__ == '__main__':
    unittest.main()
