"""Public chat revisions use only invented racecards and a local Git remote."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest

from race_ai import keirin_public_forecasts as official

DAY = '2026-11-26'
RACE = '202611267505'
CUTOFF = DAY+'T17:35:00+09:00'
AT = DAY+'T18:20:00+09:00'
LATER = DAY+'T18:21:00+09:00'
CARS = [1, 2, 3, 4, 5]


def manual(tickets, at=AT):
    return dict(kind='chat', registered_at=at, tickets=tickets)


def contested(hypotheses, at=AT):
    return dict(kind='contested_lineup', registered_at=at, hypotheses=hypotheses)


def packet(a=None, b=None, *, at=AT):
    return dict(schema='RACE_AI_KEIRIN_PUBLIC_FORECAST_UPDATES_V1', day=DAY, published_at=at,
                races=[dict(race_id=RACE, cutoff_at=CUTOFF, starter_cars=CARS, a=a, b=b)])


class PublicForecastUpdatesTests(unittest.TestCase):
    def test_chat_arguments_support_japanese_separators_and_use_the_verified_roster(self):
        from scripts.keirin_chat_forecast import _body, _roster, tickets

        state = {'forecasts':{'races':[dict(race_id=RACE,cutoff_at=CUTOFF)]},'research':None,'updates':None}
        schedule = {RACE:dict(official_cutoff_at=CUTOFF,starters=[{'car':car} for car in CARS])}
        cutoff, cars = _roster(RACE, state, schedule)
        row = dict(race_id=RACE, cutoff_at=cutoff, starter_cars=cars,
                   a=manual(tickets('１－２－３、 ５ → ４ → １')), b=None)
        self.assertEqual(_body(DAY,[row],AT)['races'][0]['a']['tickets'], [[1,2,3],[5,4,1]])
        with self.assertRaisesRegex(ValueError, 'UPDATE_CHAT_TICKETS'):
            _body(DAY,[dict(row, a=manual(tickets('6-4-1')))],AT)

    def test_validates_actual_five_car_roster_and_keeps_contest_conditions_explicit(self):
        from race_ai import keirin_public_forecast_updates as edits

        body = packet(manual([[1,2,3]]), contested([dict(cars=[2],tickets=[[2,1,3]]),
                                                   dict(cars=[4],tickets=[])]))
        self.assertEqual(edits.checked(body), body)
        for change in (
            lambda row: row.__setitem__('starter_cars', [1,2,3,4,4]),
            lambda row: row['a'].__setitem__('tickets', [[1,2,6]]),
            lambda row: row['a'].__setitem__('registered_at', LATER),
            lambda row: row['a'].__setitem__('raw_input', 'held'),
            lambda row: row['b']['hypotheses'][1].__setitem__('cars', [2]),
            lambda row: row['b']['hypotheses'][0].__setitem__('tickets', []),
            lambda row: row.__setitem__('a', row['b']),
        ):
            invalid = deepcopy(body)
            change(invalid['races'][0])
            with self.assertRaises(ValueError):
                edits.checked(invalid)

    def test_chat_edit_is_versioned_and_preserves_baseline_and_other_arm(self):
        from race_ai import keirin_public_forecast_updates as edits

        class LocalStore(official.PublicForecastGit):
            def _remote(self):
                return 'origin'

        with TemporaryDirectory() as folder:
            repo, remote = Path(folder)/'repo', Path(folder)/'remote.git'
            for args, cwd in [(['init','--bare',str(remote)],None), (['init',str(repo)],None),
                              (['remote','add','origin',str(remote)],repo)]:
                subprocess.check_output(['git',*args], cwd=cwd, stderr=subprocess.DEVNULL)
            store = LocalStore(repo)
            path = f'forecasts/{DAY}.json'
            original = official.publish(repo, dict(schema=official.SCHEMA,day=DAY,published_at=AT,
                races=[dict(race_id=RACE,cutoff_at=CUTOFF,status='saved',saved_at=DAY+'T16:50:00+09:00',
                            a=[[1,2,3]],b=[[3,2,1]])]),store=store)['commit']
            first = edits.publish(repo, packet(manual([[2,3,4]]), manual([[5,4,3]])),
                                  store=store, expected_head=original)
            draft = packet(manual([[1,3,5]],LATER), at=LATER)
            with self.assertRaisesRegex(ValueError, 'UPDATE_HEAD_CHANGED'):
                edits.publish(repo, draft, store=store, expected_head=original)
            second = edits.publish(repo, draft, store=store, expected_head=first['commit'])
            same = edits.publish(repo, draft, store=store)
            self.assertEqual(same['commit'], second['commit'])
            first_row = json.loads(store.read_previous(first['commit'], f'updates/{DAY}.json'))['races'][0]
            latest = json.loads(store.read_previous(second['commit'], f'updates/{DAY}.json'))['races'][0]
            self.assertEqual(first_row['a']['tickets'], [[2,3,4]])
            self.assertEqual(latest['a']['tickets'], [[1,3,5]])
            self.assertEqual(latest['b'], first_row['b'])
            self.assertEqual(store.read_previous(original,path), store.read_previous(second['commit'],path))
