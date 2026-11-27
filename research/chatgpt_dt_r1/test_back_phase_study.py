import copy
import unittest
import tempfile
import io
from contextlib import redirect_stderr
from unittest.mock import patch
import numpy as np
from research.chatgpt_dt_r1.back_phase_study import back_label,prepare,scenario_row,fit_leader,leader_prob,mixture,score
from research.chatgpt_dt_r1.model import RankModel
from research.chatgpt_dt_r1.test_agari import records

class BackStudyTests(unittest.TestCase):
    def test_cli_refuses_unretained_training_before_source_download(self):
        from research.chatgpt_dt_r1 import back_phase_study
        with tempfile.TemporaryDirectory() as private:
            with patch('sys.argv',['back-study',private]),redirect_stderr(io.StringIO()):
                with patch.object(back_phase_study.subprocess,'run',side_effect=lambda *a,**k:self.fail('Missing retention must stop before download')):
                    with self.assertRaises(SystemExit) as stopped:back_phase_study.main()
        self.assertEqual(stopped.exception.code,2)

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

    def test_held_prediction_stays_in_finish_and_back_target_denominators(self):
        row=prepare([self.fixture()])[0]
        held=copy.deepcopy(row);held['race_id']='held';held['feature_status']='MISSING_INPUT'
        from research.chatgpt_dt_r1.features import _bind_feature_input
        held=_bind_feature_input(held)
        leader={'feature_names':list(row['feature_names']),'mean':[0.]*len(row['feature_names']),
                'scale':[1.]*len(row['feature_names']),'weights':[0.]*len(row['feature_names'])}
        conditional=RankModel.zero(scenario_row(row,1)['feature_names'])
        direct=RankModel.zero(row['feature_names'])
        result=score([row,held],leader,conditional,direct)
        self.assertEqual(result['finish_evaluable'],2)
        self.assertEqual(result['finish_predicted_evaluable'],1)
        self.assertEqual(result['B_evaluable'],2)
        self.assertEqual(result['B_predicted_evaluable'],1)
        self.assertEqual(result['B_top1_hits'],1)
        self.assertEqual(result['B_top1_rate'],.5)
        self.assertEqual(result['finish']['direct']['trifecta_hits']['1'],1)
        self.assertEqual(result['finish']['direct']['trifecta_rates']['1'],.5)
        self.assertEqual(result['finish']['direct']['proper_score_n'],1)
        self.assertEqual(result['holds'],{'MISSING_INPUT':1})

if __name__=='__main__':unittest.main()
