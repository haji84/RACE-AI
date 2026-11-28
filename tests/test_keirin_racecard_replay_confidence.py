import json
import unittest
from copy import deepcopy
from hashlib import sha256
from itertools import permutations
from unittest.mock import Mock

from race_ai import keirin_public_forecasts as public
from race_ai import keirin_racecard_replay_confidence as replay
from race_ai.keirin_paired_measurement import _wilson


DAY = '2026-11-28'
RACE = '202611283101'
GENERATED = DAY + 'T10:00:00+09:00'
CUTOFF = DAY + 'T15:00:00+09:00'
ASSESSED = DAY + 'T11:00:00+09:00'
PARENT = 'a' * 40
NEXT = 'b' * 40
PATH = f'measurements/replay-confidence-{DAY}.json'
RESEARCH_PATH = f'research/{DAY}.json'
TICKETS = [list(ticket) for ticket in list(permutations(range(1, 8), 3))[:8]]


def _fixture():
    research = dict(schema=public.RESEARCH_SCHEMA, day=DAY, published_at=GENERATED,
                    races=[dict(race_id=RACE, cutoff_at=CUTOFF, generated_at=GENERATED,
                                starter_cars=list(range(1, 8)), a=deepcopy(TICKETS), b=[])])
    body = dict(schema='RACE_AI_KEIRIN_PUBLIC_RACECARD_REPLAY_V1', scope='RETROSPECTIVE_REPLAY',
                day=DAY, assessed_at=ASSESSED, forecast_commit=PARENT, forecast_published_at=GENERATED, tree_sha256='d' * 64,
                archive_sha256='e' * 64, replay_window=['2026-11-17', '2026-11-25'],
                bins=[dict(lower=.15, upper=.25, n=100, hits=20, days=9,
                           mean_probability=.20, ci95=list(_wilson(20, 100, 1.959963984540054)))],
                races=[dict(race_id=RACE, points=8, probability=.205,
                            ticket_sha256=sha256(public.canonical(TICKETS)).hexdigest())])
    return body, research


def _store(research, *, existing=None):
    objects = {(PARENT, RESEARCH_PATH): public.canonical(research)}
    if existing is not None:
        objects[(PARENT, PATH)] = public.canonical(existing) + b'\n'
    store = Mock()
    store.head.return_value = PARENT
    store.read_previous.side_effect = lambda head, path: objects.get((head, path))
    store.commit.return_value = NEXT
    store.run.side_effect = lambda args: (PATH + '\n').encode() if args[0] == 'diff-tree' else b''

    def retain(commit, parent):
        updates, actual_parent = store.commit.call_args.args
        if (commit, parent, actual_parent) != (NEXT, PARENT, PARENT):
            raise AssertionError('Unexpected append lineage')
        objects.update({(NEXT, path): raw for path, raw in updates.items()})

    store.push.side_effect = retain
    return store


class KeirinRacecardReplayConfidenceTests(unittest.TestCase):
    def test_checked_requires_supported_positive_replay_bin(self):
        body, _ = _fixture()
        self.assertEqual(replay.checked(body), body)
        for field, value in [('lower', .1), ('upper', .6), ('n', 29), ('days', 2), ('hits', 0),
                             ('mean_probability', .34), ('ci95', [.0, 1.0])]:
            with self.subTest(field=field, value=value):
                altered = deepcopy(body)
                altered['bins'][0][field] = value
                with self.assertRaises(ValueError):
                    replay.checked(altered)
        for field, value in [('probability', .50), ('probability', True), ('points', 7),
                             ('race_id', '202611273101')]:
            with self.subTest(field=field, value=value):
                altered = deepcopy(body)
                altered['races'][0][field] = value
                with self.assertRaises(ValueError):
                    replay.checked(altered)
        for dates in ([DAY, DAY], ['2026-11-25', '2026-11-17']):
            with self.subTest(window=dates):
                with self.assertRaises(ValueError):
                    replay.checked(dict(body, replay_window=dates))
        with self.assertRaises(ValueError):
            replay.checked(dict(body, forecast_published_at=CUTOFF))

    def test_append_writes_only_one_new_path_and_reads_it_back(self):
        body, research = _fixture()
        store = _store(research)
        replay.publish(None, body, store=store)
        files, parent = store.commit.call_args.args
        self.assertEqual(parent, PARENT)
        self.assertEqual(set(files), {PATH})
        self.assertEqual(json.loads(files[PATH]), body)
        store.push.assert_called_once_with(NEXT, PARENT)
        store.read_previous.assert_any_call(NEXT, PATH)

    def test_rejects_other_order_or_forecast_past_cutoff(self):
        body, research = _fixture()
        for alteration in ('ticket_order', 'late', 'late_publication', 'missing'):
            with self.subTest(alteration=alteration):
                changed = deepcopy(research)
                if alteration == 'ticket_order':
                    changed['races'][0]['a'].reverse()
                elif alteration == 'late':
                    changed['races'][0]['cutoff_at'] = GENERATED
                elif alteration == 'late_publication':
                    changed['published_at'] = CUTOFF
                else:
                    changed['races'] = []
                store = _store(changed)
                with self.assertRaises(ValueError):
                    replay.publish(None, body, store=store)
                store.commit.assert_not_called()
                store.push.assert_not_called()

    def test_measured_artifact_cannot_be_replaced(self):
        body, research = _fixture()
        store = _store(research, existing=body)
        replay.publish(None, body, store=store)
        incoming = deepcopy(body)
        incoming['races'][0]['probability'] = .22
        with self.assertRaises(ValueError):
            replay.publish(None, incoming, store=store)
        store.commit.assert_not_called()
        store.push.assert_not_called()
