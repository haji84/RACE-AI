from copy import deepcopy
from datetime import date
import gzip
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import keirin_public_site_rosters as rosters
from scripts.keirin_capture_public_two_sources import SourceCaptureError


SITE = 'https://keirin-20261119-race-note.chankuma.chatgpt.site/'
DAY = '2026-11-23'
NEXT_DAY = '2026-11-24'


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False) + '\n').encode()


def detail(day, race_no):
    return f'https://keirin.kdreams.jp/hiroshima/racedetail/62{day.replace("-", "")}0100{race_no:02d}/'


def forecast(day, version, race_no=1):
    stamp = day.replace('-', '')
    race_id = f'{stamp}62{race_no:02d}'
    cutoff = day + 'T10:00:00+09:00'
    riders = [{'number': n, 'name': f'選手{n}'} for n in range(1, 5)]
    row = {'race_id': race_id, 'venue': '広島', 'race_title': f'第{race_no}レース'}
    markets = {'3t': [[1, 2, 3]], '2t': [[1, 2]]}
    if version == 'legacy':
        model = {'state': 'GENERATED_RESEARCH_ONLY', 'ranked_tickets': markets['3t'],
                 'ranked_2ren_tan': markets['2t'], 'markets': {
                     k: {'tickets': tickets, 'point_count': len(tickets)}
                     for k, tickets in markets.items()}}
        row.update(date=day, venue_code='62', race_no=race_no, published_cutoff_at=cutoff,
                   observed_riders=riders, source_url=detail(day, race_no), A=model, B=deepcopy(model))
        schema = 'KEIRIN_RESULT_UNREAD_DAY_RESEARCH_V1'
        suffix = 'reference'
    else:
        schema = 'KEIRIN_PUBLISHED_LINE_RANK_V' + str(version)
        suffix = 'ranked' if version == 1 else f'ranked_v{version}'
        row.update(cutoff_at=cutoff, riders=riders, predictions=markets, lines=[[1, 2], [3, 4]],
                   source_url='https://keirin.netkeiba.com/race/entry/?race_id=' + race_id)
        if version == 3:
            row['quote'] = {'source_url': detail(day, race_no)}
    packet = {'schema': schema, 'date': day, 'generated_at': day + 'T08:00:00+09:00',
              'races': [row]}
    return f'/data/keirin_{stamp}_{suffix}_public.json', packet


def index_html(day, urls, *, today=False):
    canonical = 'https://keirin.kdreams.jp/raceresult/' + day.replace('-', '/') + '/'
    dt = date.fromisoformat(day)
    today_badge = '<span class="today">本日</span>' if today else ''
    anchors = ''.join(f'<li><a href="{url}?pageType=showResult">{int(url.split("/")[-2][-2:])}R</a></li>'
                      for url in urls)
    return (f'<html><head><link rel="canonical" href="{canonical}">'
            f'<title>競輪 レース結果（{dt.year}年{dt.month}月{dt.day}日）</title></head>'
            f'<body><h2 class="raceinfo_contents-title">{today_badge}'
            f'<span class="text">{dt:%Y年%m月%d日} レース結果一覧</span></h2>'
            f'<div class="raceinfo_table"><table><tr><td>広島競輪</td>'
            f'<td></td><td></td><td><ul class="raceinfo_table-list cf">{anchors}</ul></td>'
            '</tr></table></div></body></html>').encode()


class PublicForecastDiscoveryTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.assets = {}
        self.calendars = {}

    def run_discovery(self, *entries, calendar_fetch=None, site_fetch=None):
        paths = []
        for path, packet in entries:
            self.assets[SITE.rstrip('/') + path] = json_bytes(packet)
            paths.append(path)
        page = (f'<main id="daily-root" data-public-reference-source="{paths[0]}" '
                f'data-published-history-sources="{" ".join(paths[1:])}"></main>')
        self.assets[SITE] = page.encode()
        return rosters.discover(self.root, site_fetch=site_fetch or self.assets.__getitem__,
                                calendar_fetch=calendar_fetch or self.calendars.__getitem__)

    def add_index(self, day, urls, *, today=False):
        self.calendars['https://keirin.kdreams.jp/raceresult/' + day.replace('-', '/') + '/'] = index_html(day, urls, today=today)

    def roster_path(self, day=DAY):
        return self.root / 'rosters' / (day + '.json')

    def test_register_all_published_schema_generations_using_only_roster_fields(self):
        days = ['2026-11-21', '2026-11-22', DAY, NEXT_DAY]
        versions = ['legacy', 1, 2, 3]
        entries = [forecast(day, version, 2) for day, version in zip(days, versions)]
        for day in days:
            self.add_index(day, [detail(day, 2)])
        result = self.run_discovery(*entries)
        self.assertEqual(result['errors'], {})
        self.assertCountEqual(result['created'], days)
        for day, (path, asset) in zip(days, entries):
            roster = json.loads(self.roster_path(day).read_bytes())
            self.assertEqual(roster['date'], day)
            self.assertEqual(roster['generated_at'], asset['generated_at'])
            self.assertEqual(roster['forecast_asset_sha256'], sha256(json_bytes(asset)).hexdigest())
            self.assertEqual(roster['races'], [{
                'race_id': day.replace('-', '') + '6202', 'date': day, 'venue': '広島',
                'race_no': 2, 'source_url': detail(day, 2),
                'published_cutoff_at': day + 'T10:00:00+09:00',
                'observed_riders': [{'number': n} for n in range(1, 5)]}])

    def test_existing_ranked_roster_is_idempotent_but_revised_bets_are_reported(self):
        item = forecast(DAY, 3)
        self.add_index(DAY, [detail(DAY, 1)])
        self.assertEqual(self.run_discovery(item)['created'], [DAY])
        before = self.roster_path().read_bytes()
        self.assertEqual(self.run_discovery(item)['existing'], [DAY])
        item[1]['races'][0]['predictions']['3t'][0] = [3, 2, 1]
        self.assertIn(DAY, self.run_discovery(item)['errors'])
        self.assertEqual(self.roster_path().read_bytes(), before)

    def test_later_published_revision_adds_previously_unpredicted_races_and_preserves_original(self):
        initial = forecast(DAY, 1)
        unpredicted = forecast(DAY, 1, 2)[1]['races'][0]
        unpredicted.update(lines=None, predictions=None)
        initial[1]['races'].append(unpredicted)
        self.add_index(DAY, [detail(DAY, 1), detail(DAY, 2)])
        self.assertEqual(self.run_discovery(initial)['created'], [DAY])
        old_bytes = self.roster_path().read_bytes()
        old = json.loads(old_bytes)
        self.assertEqual([r['race_no'] for r in old['races']], [1])

        later = forecast(DAY, 2)
        later[1]['generated_at'] = DAY + 'T08:15:00+09:00'
        later[1]['races'].append(forecast(DAY, 2, 2)[1]['races'][0])
        result = self.run_discovery(later)
        self.assertEqual(result['errors'], {})
        self.assertEqual(result['updated'], [DAY])
        new_bytes = self.roster_path().read_bytes()
        new = json.loads(new_bytes)
        self.assertEqual([r['race_no'] for r in new['races']], [1, 2])
        history = self.root / 'rosters' / 'revisions' / DAY
        saved = history / (old['forecast_asset_sha256'] + '.json')
        self.assertEqual(saved.read_bytes(), old_bytes)

        self.assertEqual(self.run_discovery(later)['existing'], [DAY])
        self.assertEqual(self.roster_path().read_bytes(), new_bytes)
        self.assertIn(DAY, self.run_discovery(initial)['errors'])
        self.assertEqual(self.roster_path().read_bytes(), new_bytes)
        self.assertEqual(list(history.glob('*.json')), [saved])

    def test_a_stale_poll_cannot_overwrite_a_newer_revision_committed_during_fetch(self):
        original = forecast(DAY, 3)
        self.assertEqual(self.run_discovery(original)['created'], [DAY])
        stale = deepcopy(original)
        stale[1]['generated_at'] = DAY + 'T08:10:00+09:00'
        newer = deepcopy(original)
        newer[1]['generated_at'] = DAY + 'T08:20:00+09:00'
        newer[1]['races'].append(forecast(DAY, 3, 2)[1]['races'][0])

        def fetch_during_concurrent_update(url):
            if url == SITE:
                return self.assets[SITE]
            self.assertEqual(self.run_discovery(newer)['updated'], [DAY])
            return json_bytes(stale[1])

        stale_result = self.run_discovery(stale, site_fetch=fetch_during_concurrent_update)
        self.assertIn(DAY, stale_result['errors'])
        self.assertEqual(self.run_discovery(newer)['existing'], [DAY])
        latest = json.loads(self.roster_path().read_bytes())
        self.assertEqual(latest['forecast_asset_sha256'], sha256(json_bytes(newer[1])).hexdigest())
        self.assertEqual(len(latest['races']), 2)

    def test_newer_revision_rejects_changed_identities_or_shrinking_coverage(self):
        first = forecast(DAY, 3)
        first[1]['races'].append(forecast(DAY, 3, 2)[1]['races'][0])
        self.add_index(DAY, [detail(DAY, 1), detail(DAY, 2)])
        self.assertEqual(self.run_discovery(first)['created'], [DAY])
        existing = self.roster_path().read_bytes()
        for change in ('cutoff', 'rider', 'venue', 'missing_race'):
            with self.subTest(change=change):
                updated = deepcopy(first)
                updated[1]['generated_at'] = DAY + 'T08:20:00+09:00'
                row = updated[1]['races'][0]
                if change == 'cutoff':
                    row['cutoff_at'] = DAY + 'T10:05:00+09:00'
                elif change == 'rider':
                    row['riders'].pop()
                elif change == 'venue':
                    row['venue'] = '別の会場'
                else:
                    updated[1]['races'].pop()
                self.assertIn(DAY, self.run_discovery(updated)['errors'])
                self.assertEqual(self.roster_path().read_bytes(), existing)

    def test_legacy_compressed_sha_is_preserved_and_identities_are_checked(self):
        item = forecast(DAY, 'legacy')
        self.add_index(DAY, [detail(DAY, 1)])
        self.assertEqual(self.run_discovery(item)['created'], [DAY])
        old = json.loads(self.roster_path().read_bytes())
        old['forecast_asset_sha256'] = sha256(gzip.compress(json_bytes(item[1]), mtime=0)).hexdigest()
        self.roster_path().write_bytes(json_bytes(old))
        self.assertEqual(self.run_discovery(item)['existing'], [DAY])
        self.assertEqual(self.roster_path().read_bytes(), json_bytes(old))
        old['races'][0]['observed_riders'][-1]['number'] = 7
        self.roster_path().write_bytes(json_bytes(old))
        self.assertIn(DAY, self.run_discovery(item)['errors'])
        self.assertEqual(self.roster_path().read_bytes(), json_bytes(old))

    def test_incomplete_day_does_not_block_registration_of_other_day(self):
        incomplete = forecast(DAY, 2)
        incomplete[1]['races'].append(forecast(DAY, 2, 2)[1]['races'][0])
        self.add_index(DAY, [detail(DAY, 1)])
        self.add_index(NEXT_DAY, [detail(NEXT_DAY, 1)])
        other = forecast(NEXT_DAY, 3)
        result = self.run_discovery(incomplete, other)
        self.assertIn(DAY, result['errors'])
        self.assertEqual(result['created'], [NEXT_DAY])
        self.assertFalse(self.roster_path().exists())
        self.add_index(DAY, [detail(DAY, 1), detail(DAY, 2)])
        retry = self.run_discovery(incomplete, other)
        self.assertEqual(retry['created'], [DAY])
        self.assertEqual(retry['existing'], [NEXT_DAY])
        self.assertEqual(retry['errors'], {})

    def test_mismatched_ids_and_cutoffs_never_enter_roster(self):
        for key, value in [('race_id', '202611226201'),
                           ('source_url', 'https://keirin.netkeiba.com/race/entry/?race_id=202611236202'),
                           ('cutoff_at', DAY + 'T10:00:00')]:
            with self.subTest(field=key):
                entry = forecast(DAY, 3)
                entry[1]['races'][0][key] = value
                self.add_index(DAY, [detail(DAY, 1)])
                self.assertIn(DAY, self.run_discovery(entry)['errors'])
                self.assertFalse(self.roster_path().exists())

    def test_page_never_follows_personal_links_or_external_assets(self):
        path, packet = forecast(DAY, 3)
        advertised = 'https://example.invalid' + path
        owner_path = '/api/private/owner'
        homepage = (f'<main id="daily-root" data-public-reference-source="{path}" '
                    f'data-published-history-sources="{advertised} {owner_path}">'
                    f'<a href="{owner_path}">本人用</a></main>').encode()
        self.assets.update({SITE: homepage, SITE.rstrip('/') + path: json_bytes(packet)})
        self.add_index(DAY, [detail(DAY, 1)])
        requests = []

        def fetch(url):
            requests.append(url)
            return self.assets[url]

        rosters.discover(self.root, site_fetch=fetch, calendar_fetch=self.calendars.__getitem__)
        self.assertNotIn(advertised, requests)
        self.assertNotIn(SITE.rstrip('/') + owner_path, requests)
        self.assertNotIn(owner_path, requests)

    def test_calendar_preserves_event_start_and_ordinal_in_matching_link(self):
        # The November 23 race takes place on day two of a meeting that began on the 22nd.
        target = 'https://keirin.kdreams.jp/hiroshima/racedetail/6220261122020001/'
        self.add_index(DAY, [target])
        self.assertEqual(self.run_discovery(forecast(DAY, 2))['created'], [DAY])
        self.assertEqual(json.loads(self.roster_path().read_bytes())['races'][0]['source_url'], target)

    def test_not_yet_settled_race_uses_the_actual_dated_racecard_link(self):
        entry = forecast(DAY, 2)
        entry[1]['races'].append(forecast(DAY, 2, 2)[1]['races'][0])
        self.add_index(DAY, [detail(DAY, 1)], today=True)
        meeting = 'https://keirin.kdreams.jp/hiroshima/racecard/62202611220200/'
        second = 'https://keirin.kdreams.jp/hiroshima/racedetail/6220261122020002/'
        self.calendars['https://keirin.kdreams.jp/kaisai/2026/11/23/'] = (
            f'<html><body><a href="{meeting}">広島 2日目</a></body></html>').encode()
        self.calendars[meeting] = f'<html><body><a href="{second}">2R</a></body></html>'.encode()
        self.assertEqual(self.run_discovery(entry)['created'], [DAY])
        sources = {r['race_id']: r['source_url']
                   for r in json.loads(self.roster_path().read_bytes())['races']}
        self.assertEqual(sources, {'202611236201': detail(DAY, 1), '202611236202': second})

    def test_missing_results_index_uses_schedule_while_denial_stops(self):
        result_page = 'https://keirin.kdreams.jp/raceresult/2026/11/23/'
        schedule = 'https://keirin.kdreams.jp/kaisai/2026/11/23/'
        meeting = 'https://keirin.kdreams.jp/hiroshima/racecard/62202611220200/'
        first = 'https://keirin.kdreams.jp/hiroshima/racedetail/6220261122020001/'
        pages = {schedule: f'<a href="{meeting}">広島</a>'.encode(),
                 meeting: f'<a href="{first}">1R</a>'.encode()}
        for status in (403, 404):
            with self.subTest(status=status):
                calls = []

                def fetch(url):
                    calls.append(url)
                    if url == result_page:
                        raise SourceCaptureError('PUBLIC_PROVIDER_HTTP_ERROR_STOP', http_status=status)
                    return pages[url]

                result = self.run_discovery(forecast(DAY, 2), calendar_fetch=fetch)
                if status == 403:
                    self.assertIn(DAY, result['errors'])
                    self.assertEqual(calls, [result_page])
                    self.assertFalse(self.roster_path().exists())
                else:
                    self.assertEqual(result['created'], [DAY])
                    self.assertEqual(calls, [result_page, schedule, meeting])

    def test_wrong_date_calendar_cannot_supply_missing_detail_links(self):
        calendar = 'https://keirin.kdreams.jp/raceresult/2026/11/23/'
        self.calendars[calendar] = index_html(NEXT_DAY, [detail(DAY, 1)])
        self.assertIn(DAY, self.run_discovery(forecast(DAY, 2))['errors'])
        self.assertFalse(self.roster_path().exists())

    def test_two_different_forecasts_for_same_date_are_not_arbitrarily_selected(self):
        self.add_index(DAY, [detail(DAY, 1)])
        result = self.run_discovery(forecast(DAY, 2), forecast(DAY, 3))
        self.assertIn(DAY, result['errors'])
        self.assertFalse(self.roster_path().exists())


if __name__ == '__main__':
    unittest.main()
