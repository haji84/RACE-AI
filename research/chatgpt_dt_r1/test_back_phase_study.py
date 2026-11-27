import copy
import unittest
import numpy as np
from research.chatgpt_dt_r1.back_phase_study import back_label,prepare,scenario_row,fit_leader,leader_prob,mixture
from research.chatgpt_dt_r1.model import RankModel
from research.chatgpt_dt_r1.test_agari import records

class BackStudyTests(unittest.TestCase):
    def fixture(self):
        rows=records()
        target=rows[-1]
        target.update(result_status='COMPLETE',top3=[1,2,3],finish=[1,2,3],
            result_rows=[{'car':1,'rank':1,'sb_mark':'ＳＢ'}, {'car':2,'rank':2,'sb_mark':''},
                         {'car':3,'rank':3,'sb_mark':None}])
        return target
    def test_label_requires_unique_explicit_back_and_roster(self):
        r=self.fixture()
        self.assertEqual(back_label(r),(1,'UNIQUE_ARCHIVED_B'))
        r['result_rows'][1]['sb_mark']='B'
        self.assertEqual(back_label(r),(None,'AMBIGUOUS_B'))
        r['result_rows'].pop()
        self.assertEqual(back_label(r),(None,'RESULT_ROSTER_INCOMPLETE'))
    def test_mixture_normalized_and_independent_of_target_result(self):
        row=prepare([self.fixture()])[0]
        leader={'feature_names':list(row['feature_names']),'mean':[0.]*len(row['feature_names']),
                'scale':[1.]*len(row['feature_names']),'weights':[0.]*len(row['feature_names'])}
        conditional=RankModel.zero(scenario_row(row,1)['feature_names'])
        a=mixture(leader,conditional,row)
        self.assertAlmostEqual(sum(t['probability'] for t in a['trifectas']),1.)
        self.assertAlmostEqual(sum(t['probability'] for t in a['exactas']),1.)
        self.assertAlmostEqual(sum(a['back_leader'].values()),1.)
        changed=copy.deepcopy(row);changed['result_rows'][0]['sb_mark']=''
        changed['result_rows'][2]['sb_mark']='B';changed['top3']=[3,2,1]
        self.assertEqual(a,mixture(leader,conditional,changed))
        expected=sum(t['scenario_probability']*t['conditional_loss_probability'] for t in a['favorite_loss_by_back_leader'])
        self.assertAlmostEqual(expected,1-sum(t['probability'] for t in a['trifectas'] if t['cars'][0]==a['favorite_car']))
    def test_training_time_guard_and_fit(self):
        rows=[]
        for i in range(30):
            r=self.fixture();r['race_id']=str(i);rows.append(r)
        featured=prepare(rows)
        model=fit_leader(featured,'2026-07-12')
        self.assertAlmostEqual(sum(leader_prob(model,featured[0]).values()),1.)
        with self.assertRaises(ValueError):fit_leader(featured,featured[0]['day'])
    def test_scenario_unknown_line_is_not_inferred(self):
        r=self.fixture();r['lines_known']=False
        row=prepare([r])[0];s=scenario_row(row,1)
        self.assertTrue(np.all(s['features'][:,-1]==1.))
        self.assertTrue(np.all(s['features'][:,-5:-1]==0.))

if __name__=='__main__':unittest.main()
