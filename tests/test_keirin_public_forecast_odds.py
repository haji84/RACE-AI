"""Result-independent odds display uses only the dated market and starter set."""
from copy import deepcopy
from datetime import datetime
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
