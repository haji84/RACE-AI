"""Result-independent odds display uses only the dated market and starter set."""
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

DAY = '2026-11-26'
RID = '202611267505'
URL = 'https://keirin.kdreams.jp/matsuyama/racedetail/7520261126010005/'
AT = DAY+'T18:00:15+09:00'
CARS = [1,3,4,6,7]


def page():
    tables = []
    for first in CARS:
        other = [car for car in CARS if car != first]
        headings = ''.join(f'<th class="c{car}">{car}</th>' for car in other)
        data = ''.join(f'<tr><th class="c{third}">{third}</th>'+''.join(
            f'<td>{21.5 if second != third else "–"}</td>' for second in other)+
            f'<th class="c{third}">{third}</th></tr>' for third in other)
        tables.append(f'<table class="bt5"><tr><th><span class="number">{first}</span></th></tr>'
                      f'<tr>{headings}</tr><tr><th>3着</th></tr>{data}</table>')
    return (f'<html><head><link rel="canonical" href="{URL}"></head><body>'
        '<div id="JS_ODDSSTATUS_3rentan"><p class="time">2026/11/26 17:54現在</p></div>'
        '<div id="JS_ODDSCONTENTS_3rentan"><div class="odds_table_wrapper">'+''.join(tables)+
        '</div><div class="oddspop_table_wrapper"><table><tr><td><span class="num">1-3-4</span>'
        '<span class="odds">21.5</span></td></tr></table></div></div>'
        '<div class="result"><span class="odds">4030</span></div></body></html>').encode()


class PublicForecastOddsTests(unittest.TestCase):
    def test_five_car_trifecta_quotes_are_timed_and_bound_to_an_ordinary_racecard(self):
        from race_ai import keirin_public_forecast_odds as odds

        row = odds.parse_racecard(page(), race_id=RID, url=URL, starters=CARS, observed_at=AT,
                                  wanted={'1-3-4','4-7-1','1-2-3'})
        self.assertEqual(row['quotes'], {'1-3-4':21.5,'4-7-1':21.5})
        self.assertEqual(row['source_at'], DAY+'T17:54:00+09:00')
        self.assertEqual(row['observed_at'], AT)
        body = dict(schema=odds.SCHEMA, day=DAY, published_at=AT, races=[row])
        self.assertEqual(odds.checked(body), body)
        invalid = deepcopy(body)
        invalid['races'][0]['source_at'] = DAY+'T18:01:00+09:00'
        with self.assertRaises(ValueError):
            odds.checked(invalid)
        for raw, roster, source in ((page(),[1,2,3,4,5],URL), (page(),CARS,URL+'?x=1'),
            (page().replace(b'2026/11/26 17:54',b'2026/11/25 17:54'),CARS,URL),
            (page().replace(b'<th class="c3">3</th></tr>', b'<th class="c3">2</th></tr>', 1),CARS,URL),
            (page().replace(b'class="odds">21.5',b'class="odds">999.5'),CARS,URL)):
            with self.assertRaises(ValueError):
                odds.parse_racecard(raw,race_id=RID,url=source,starters=roster,observed_at=AT,wanted={'1-3-4'})

    def test_daily_handoff_reuses_exact_already_admitted_card_and_holds_mismatched_starters(self):
        from race_ai import keirin_public_forecasts as public
        from scripts import keirin_publish_forecast_odds as publisher

        captured = datetime.fromisoformat(AT)
        saved = (captured + timedelta(seconds=1)).isoformat()
        cutoff = DAY + 'T18:10:00+09:00'
        raw = page()
        digest = sha256(raw).hexdigest()
        receipt = dict(url=URL, bytes_sha256=digest, bytes=len(raw), status=200, captured_at=AT)
        ref = dict(input=dict(race_id=RID, riders=[dict(car=car) for car in CARS], published_cutoff_at=cutoff,
                              cutoff_source={key: receipt[key] for key in ('url', 'bytes_sha256', 'captured_at')}))
        source_manifest = dict(races=[dict(race_id=RID, kdreams_url=URL)])

        def note_file(value):
            value_bytes = public.canonical(value)
            return dict(text=value_bytes.decode(), bytes=len(value_bytes), sha256=sha256(value_bytes).hexdigest())

        note = dict(dates=[DAY], files={
            f'data/{DAY}/reference_AB.json': note_file([ref]),
            f'data/{DAY}/manifest.json': note_file(dict(source_manifest=source_manifest, source_receipts=[receipt])),
        })
        entry = dict(kind='research', days=[DAY], captured_race_ids=[RID], created_at=saved,
                     source_content_sha256=sha256(public.canonical(note)).hexdigest())
        state = dict(forecasts=dict(day=DAY, races=[dict(race_id=RID, a=[], b=[])]), research=None, updates=None,
                     references=dict(races=[dict(race_id=RID, a=[[1,3,4]], b=[[4,7,1]])]))
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / 'capture'
            target = root / 'handoff'
            for path in (source, source / 'raw', target):
                path.mkdir(mode=0o700)
            (source / 'raw' / (digest + '.html')).write_bytes(raw)
            staged = publisher.stage_reference_handoff(source, note, entry, target)
            self.assertEqual(staged['staged_races'], 1)
            body, receipt_summary = publisher.prepare_handoff(target, state, now=captured + timedelta(minutes=2))
            self.assertEqual(receipt_summary['quotes'], 2)
            self.assertEqual(body['races'][0]['quotes'], {'1-3-4': 21.5, '4-7-1': 21.5})
            self.assertEqual(body['races'][0]['observed_at'], AT)

            from race_ai import keirin_public_forecast_updates as updates

            class LocalStore(public.PublicForecastGit):
                def _remote(self):
                    return 'origin'

            repo, remote = root/'repo', root/'remote.git'
            for args, cwd in [(['init','--bare',str(remote)],None), (['init',str(repo)],None),
                              (['remote','add','origin',str(remote)],repo)]:
                subprocess.check_output(['git',*args], cwd=cwd, stderr=subprocess.DEVNULL)
            store = LocalStore(repo)
            frozen = dict(race_id=RID, cutoff_at=cutoff, saved_at=saved, status='saved', a=[[1,3,4]], b=[[4,7,1]])
            public.publish(repo, dict(schema=public.SCHEMA, day=DAY, published_at=saved,races=[frozen]),store=store)
            head, state = updates.day_state(store, DAY)
            body, _ = publisher.prepare_handoff(target, state, now=captured + timedelta(minutes=2))
            commit = publisher.publish(store, head, body)
            self.assertEqual(store.head(), commit)
            self.assertEqual(public._json(store.read_previous(commit, f'odds/{DAY}.json')), body)
            self.assertEqual(store.read_previous(head, f'forecasts/{DAY}.json'),
                             store.read_previous(commit, f'forecasts/{DAY}.json'))
            self.assertEqual(publisher.publish(store, commit, body), commit)

            mismatched = dict(state, research=dict(races=[dict(race_id=RID, starter_cars=[1,2,3,4,6,7], a=[], b=[])]))
            withheld, summary = publisher.prepare_handoff(target, mismatched, now=captured + timedelta(minutes=2))
            self.assertIsNone(withheld)
            self.assertEqual(summary['held'], {'ODDS_PUBLISHED_STARTER_MISMATCH': 1})

            receipt_file = target / 'raw' / (digest + '.html')
            receipt_file.write_bytes(raw + b'x')
            withheld, summary = publisher.prepare_handoff(target, state, now=captured + timedelta(minutes=2))
            self.assertIsNone(withheld)
            self.assertEqual(summary['held'], {'KEIRIN_PUBLIC_RESEARCH_SOURCE_SHA': 1})
