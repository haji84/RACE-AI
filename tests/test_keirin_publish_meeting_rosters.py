from datetime import datetime
import json
import unittest
from unittest.mock import Mock

from race_ai import keirin_public_forecasts as public
from scripts import keirin_publish_meeting_rosters as publication
from tests.test_keirin_daily_rider_update import PublicStore


DAY = '2026-11-29'
AT = DAY + 'T09:00:00+09:00'
RACE = '202611293501'


def reference():
    return dict(schema=publication.source.SCHEMA,day=DAY,published_at=AT,races=[
        dict(race_id=RACE, source_url='https://keirin.kdreams.jp/hiratsuka/racecard/35202611270300/',
             source_sha256='a'*64, source_at=AT, riders=[
                 dict(number=n,name=f'選手{n}',region='東京',cohort=100+n,style='逃',
                      registration='012300' if n==1 else None) for n in range(1,5)])])


def directory():
    return dict(schema=publication.DIRECTORY_SCHEMA,source_sha256=publication.BASE_SHA256,as_of='2026-11-25',
                riders=[dict(name=f'選手{n}',region='東京都',registration=f'01230{n}') for n in range(1,5)])


class MeetingRosterPublicationTests(unittest.TestCase):
    def test_publication_keeps_exact_id_and_uses_only_unambiguous_directory_matches(self):
        storage = PublicStore()
        lookup = directory()
        lookup['riders'].append(dict(name='選手3',region='大阪府',registration='012309'))
        commit = publication.publish(storage,[reference()],lookup)
        path = f'reference-starters/{DAY}.json'
        rows = json.loads(storage.read_previous(commit,path))['races'][0]['riders']
        self.assertEqual([rider['registration'] for rider in rows],['012300','012302',None,'012304'])
        self.assertNotIn('registration_basis',rows[0])
        self.assertEqual(rows[1]['registration_basis'],publication.DIRECTORY_BASIS)
        self.assertEqual(commit,publication.publish(storage,[reference()],lookup))

    def test_complete_rosters_do_not_call_any_provider_again(self):
        storage = PublicStore()
        head = publication.publish(storage,[reference()],directory())
        snapshot = dict(schema=public.SCHEMA,day=DAY,published_at=AT,races=[
            dict(race_id=RACE,cutoff_at=None,status='pending',saved_at=None,a=[],b=[])])
        storage.trees[head][f'forecasts/{DAY}.json'] = public.canonical(snapshot)
        collect = Mock()
        report = publication.refresh(None,DAY,now=datetime.fromisoformat(AT),collect=collect,store=storage)
        self.assertEqual(report['state'],'ROSTERS_ALREADY_PUBLISHED')
        collect.assert_not_called()

    def test_source_race_must_have_the_same_day_and_venue_as_the_page(self):
        packet = reference()
        packet['races'][0]['source_url'] = 'https://keirin.kdreams.jp/hiratsuka/racecard/35202611270200/'
        with self.assertRaisesRegex(ValueError,'RACE_SOURCE'):
            publication.checked_packet(packet)
