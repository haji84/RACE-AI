import copy
import unittest
from datetime import datetime,timedelta,timezone
from math import fsum, factorial
from keirin_chat_dt_r1 import forecast, fit

def snapshot(n=7):
    return {'race_id':'synthetic','as_of':'2026-11-01T08:00:00+00:00','published_cutoff_at':'2026-11-01T09:00:00+00:00','competition':'S','line_groups':[list(range(1,n+1))], 'riders':[dict(car=i,competition_points=105-i,recent_form_score=.5,h_count=5,b_count=6,style='MAKURI') for i in range(1,n+1)]}
AT='2026-11-01T08:30:00+00:00'
class TestDT(unittest.TestCase):
    def test_fields(self):
        for n in range(3,10):
            s=snapshot(n); r=forecast(s,AT)
            self.assertEqual(len(r['trifecta']),factorial(n)//factorial(n-3)); self.assertEqual(len(r['exacta']),n*(n-1))
            self.assertAlmostEqual(fsum(x['probability'] for x in r['trifecta']),1)
            self.assertAlmostEqual(fsum(x['probability'] for x in r['exacta']),1)
            self.assertTrue(all(x['probability']>0 for x in r['trifecta']))
            for x in r['exacta']:
                self.assertAlmostEqual(x['probability'],fsum(y['probability'] for y in r['trifecta'] if y['order'][:2]==x['order']))
            self.assertEqual(r['confidence'],'HOLD');self.assertEqual(len(r['branches'][0]['phases']),6)
    def test_determinism(self):
        s=snapshot(); self.assertEqual(forecast(s,AT),forecast(copy.deepcopy(s),AT))
    def test_cutoff(self):
        with self.assertRaises(ValueError):forecast(snapshot(),'2026-11-01T08:46:00+00:00')
    def test_lines(self):
        s=snapshot();s['line_groups']=[[1,2],[2,3]]
        with self.assertRaises(ValueError):forecast(s,AT)
    def test_girls(self):
        s=snapshot();s['competition']='GIRLS'
        with self.assertRaises(ValueError):forecast(s,AT)
        s['line_groups']=[[i] for i in range(1,8)]; self.assertEqual(len(forecast(s,AT)['branches']),7)
    def test_fit(self):
        rows=[]
        for i in range(30):
            s=snapshot(5);s['race_id']=str(i);rows.append(dict(snapshot=s,prediction_at=AT,official_top3=[1,2,3],result_at='2026-11-01T10:00:00+00:00'))
        with self.assertRaises(ValueError):fit(rows,AT)
        model=fit(rows,'2026-11-02T00:00:00+00:00')
        self.assertEqual(model['n'],30)
        with self.assertRaises(ValueError):forecast(snapshot(),AT,model)
        s=snapshot();s['as_of']='2026-11-03T08:00:00+00:00';s['published_cutoff_at']='2026-11-03T09:00:00+00:00'
        r=forecast(s,'2026-11-03T08:30:00+00:00',model)
        self.assertEqual(r['status'],'UNVALIDATED_FITTED');self.assertEqual(r['confidence'],'HOLD')
    def test_duplicate_training(self):
        row=dict(snapshot=snapshot(),prediction_at=AT,official_top3=[1,2,3],result_at='2026-11-01T10:00:00+00:00')
        with self.assertRaises(ValueError):fit([row]*30,'2026-11-02T00:00:00+00:00')
if __name__=='__main__':unittest.main()
