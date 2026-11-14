"""No private originals/picks in fixtures; research records cannot become formal."""
import copy,unittest
from race_ai.actions_contract import digest
try:
    from race_ai import external_research_registry as registry
except ImportError:
    registry=None

def sample():
    source=dict(race_id='autorace:2030-04-01:sanyo:1',race_no=1,venue='山陽',
                captured_at_jst='2030-04-01T10:00:00+09:00',cutoff_at_jst='2030-04-01T11:00:00+09:00')
    row=dict(schema='RACE_AI_AUTORACE_ASSISTANT_SINGLE_RUN_RESEARCH_FORECAST_V1',
             model_id='autorace-personal-observed-baseline-v1',model_version='0.1.0-HEURISTIC-UNTRAINED',
             race_id=source['race_id'],race_no=1,venue='山陽',phase='A_PRE_TRIAL_INPUT_NO_SAME_DAY_TRIAL_USED',
             generated_at_jst=source['captured_at_jst'],cutoff_at_jst=source['cutoff_at_jst'],
             source=source,input_sha256=digest(source),formal_hit_at_8_eligible=False,
             external_pre_cutoff_receipt=None,official_prediction=False,bet_placed=False,
             ordered_top8=[[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1],[1,2,4],[1,4,2]])
    row['prediction_sha256']=digest(row)
    return row

class ExternalResearchRegistryTests(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(registry,'Evidence-separated research registry is missing')
    def test_redacted_projection_does_not_publish_picks_or_claim_receipt(self):
        original=sample();before=copy.deepcopy(original)
        manifest=registry.build_manifest([original],day='2030-04-01')
        self.assertEqual(original,before)
        self.assertNotIn('ordered_top8',str(manifest));self.assertNotIn('source_url',str(manifest))
        self.assertEqual(manifest['entries'][0]['original_prediction_sha256'],original['prediction_sha256'])
        self.assertFalse(manifest['entries'][0]['formal_hit_at_8_eligible'])
        report=registry.summarize(manifest,day='2030-04-01')
        self.assertEqual(report['research_forecast_count'],1)
        self.assertEqual(report['formal_forecast_count'],0)
        self.assertIsNone(report['formal_hit_rate'])
    def test_repeat_import_is_idempotent_conflicting_original_is_rejected(self):
        s=sample(); m=registry.build_manifest([s,s],day='2030-04-01')
        self.assertEqual(len(m['entries']),1)
        another=copy.deepcopy(s);another['ordered_top8'].reverse();another['prediction_sha256']=digest({k:v for k,v in another.items() if k!='prediction_sha256'})
        with self.assertRaises(ValueError):registry.build_manifest([s,another],day='2030-04-01')
    def test_tamper_wrong_day_and_fake_promotion_rejected(self):
        for change in ('source','model','promotion','receipt','day'):
            s=sample();day='2030-04-01'
            if change=='source':s['source']['venue']='別会場'
            if change=='model':s['model_id']='invented-model'
            if change=='promotion':s['formal_hit_at_8_eligible']=True
            if change=='receipt':s['external_pre_cutoff_receipt']={'claimed':True}
            if change=='day':day='2030-04-02'
            with self.subTest(change=change),self.assertRaises(ValueError):registry.build_manifest([s],day=day)
    def test_manifest_tamper_and_true_flag_rejected(self):
        m=registry.build_manifest([sample()],day='2030-04-01')
        m['entries'][0]['formal_hit_at_8_eligible']=True
        m['manifest_sha256']=digest({k:v for k,v in m.items() if k!='manifest_sha256'})
        with self.assertRaises(ValueError):registry.summarize(m,day='2030-04-01')

class ReportEvidenceSeparationTests(unittest.TestCase):
    def test_report_attachment_does_not_inflate_frozen_or_scored_counts(self):
        self.assertTrue(hasattr(registry,'attach_to_report'),'research summary is not connected to the existing report')
        report=dict(forecast_count=312,scored_forecasts=20,scoreboard=[{'stage':'P0','model_id':'unchanged'}],
                    model_coverage={'models':[]})
        before=copy.deepcopy(report)
        manifest=registry.build_manifest([sample()],day='2030-04-01')
        registry.attach_to_report(report,manifest,day='2030-04-01')
        self.assertEqual(report['forecast_count'],before['forecast_count'])
        self.assertEqual(report['scored_forecasts'],before['scored_forecasts'])
        self.assertEqual(report['scoreboard'],before['scoreboard'])
        self.assertEqual(report['external_research']['research_forecast_count'],1)
        registry.attach_to_report(report,manifest,day='2030-04-01')
        self.assertEqual(report['external_research']['research_forecast_count'],1)

class ResearchClockTests(unittest.TestCase):
    def test_wrong_cutoff_day_even_with_consistent_hash_is_rejected(self):
        s=sample();s['source']['cutoff_at_jst']='2030-04-02T11:00:00+09:00'
        s['cutoff_at_jst']=s['source']['cutoff_at_jst'];s['input_sha256']=digest(s['source'])
        s['prediction_sha256']=digest({k:v for k,v in s.items() if k!='prediction_sha256'})
        with self.assertRaises(ValueError):registry.build_manifest([s],day='2030-04-01')
