import copy
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo
from model import VERSION, generate, purchase_tickets, settle, commit_digest

JST = ZoneInfo('Asia/Tokyo')


def fixtures(day='2026-11-04', count=8):
    d = day.replace('-', '')
    cards, waku = {}, {}
    for race in range(1, count + 1):
        key = f'{d}18{race:02}'
        a = {'レースコード': key}
        w = {'レースコード': key}
        for i in range(1, 7):
            p = f'艇{i}_'
            a[p+'全国勝率'] = str(6.5 if i == 1 else 5.8 - 0.35*(i-2))
            a[p+'級別'] = 'A1' if i == 1 else 'B1'
            w[p+'枠番別勝率'] = str(8.0 + race*.10 if i == 1 else 6.8 - .5*(i-2))
        cards[key], waku[key] = a, w
    return cards, waku


class SellerShadowTest(unittest.TestCase):
    def test_five_limited_and_unique(self):
        c, w = fixtures()
        f = generate(c, w, date(2026,11,4), datetime(2026,11,4,3,30,tzinfo=JST))
        self.assertEqual(f['discovered'], 8)
        self.assertEqual(f['forecasted'], 5)
        for r in f['rows']:
            if 'tickets' not in r: continue
            three = r['tickets']['three']
            five = r['tickets']['five']
            self.assertEqual(sum(x['yen'] for x in three), 10000)
            self.assertEqual(sum(x['yen'] for x in five), 10000)
            self.assertEqual(len({x['ticket'] for x in five}),5)
            self.assertEqual([x['ticket'] for x in three], [x['ticket'] for x in five][:3])
    def test_deadline_blocks_backdating(self):
        c,w=fixtures(count=1)
        with self.assertRaises(ValueError):
            generate(c,w,date(2026,11,4),datetime(2026,11,4,7,0,tzinfo=JST))
        f = generate(c,w,date(2026,11,4),datetime(2026,11,4,7,0,tzinfo=JST),dry_run=True)
        self.assertEqual(f['status'],'DRY_RUN_NOT_PROSPECTIVE')
    def test_no_data_no_forecast(self):
        c,w=fixtures(count=1)
        w.pop(next(iter(w)))
        with self.assertRaises(ValueError):
            generate(c,{},date(2026,11,4),datetime(2026,11,4,4,tzinfo=JST))
    def test_result_does_not_change_forecast(self):
        c,w=fixtures(count=1)
        f=generate(c,w,date(2026,11,4),datetime(2026,11,4,4,tzinfo=JST))
        original=copy.deepcopy(f)
        ticket=f['rows'][0]['tickets']['three'][0]['ticket']
        race=next(iter(c))
        p={race: {'3連単_組番':ticket,'3連単_払戻金':'1000'}}
        rt={race: {f'{i}コース_F':'' for i in range(1,7)}}
        s=settle(f,p,rt)
        self.assertEqual(s['rows'][0]['series']['three']['return_yen'],50000)
        self.assertTrue(s['rows'][0]['series']['three']['hit'])
        self.assertEqual(f,original)
    def test_f_refund_partial_and_return(self):
        c,w=fixtures(count=1)
        f=generate(c,w,date(2026,11,4),datetime(2026,11,4,4,tzinfo=JST))
        race=next(iter(c)); t=f['rows'][0]['tickets']['three']
        returned=5000 if '1' in t[0]['ticket'].split('-') else 0
        p={race:{'3連単_組番':'4-5-6','3連単_払戻金':'15000'}}
        rt={race:{'1コース_F':'F','1コース_艇番':'1'}}
        s=settle(f,p,rt)
        self.assertEqual(s['rows'][0]['series']['three']['return_yen'],10000)
        self.assertFalse(s['rows'][0]['series']['three']['hit'])
    def test_digest_deterministic(self):
        c,w=fixtures(count=1)
        x=generate(c,w,date(2026,11,4),datetime(2026,11,4,4,tzinfo=JST))
        self.assertEqual(commit_digest(x),commit_digest(copy.deepcopy(x)))

if __name__=='__main__':
    unittest.main(verbosity=2)