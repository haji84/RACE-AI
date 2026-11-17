"""Source-free tests: all riders and results in fixtures are fictional."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest

from race_ai.keirin_manual_result_sync import (
    SOURCE_SCHEMA, ManualSyncError, canonical, read_forecast, read_categories,
    read_result_candidates, evaluate, public_counters, render_html,
)
from scripts.keirin_manual_result_sync_cli import run

DAY = '2026-11-17'


def fixture(base):
    old = {'date':DAY,'ranked_races':[]}
    rows = []
    for x in range(71):
        code = 11 + x//12
        race = x%12 + 1
        rid = f'{code:02d}-{race:02d}'
        start='08:50' if x == 0 else '23:30'
        picks = [[1,2,3],[2,1,3],[3,2,1]]
        old['ranked_races'].append({'id':rid,'venue':f'架空会場{code}',
                    'start':start,'ranked_picks':[{'cars':c} for c in picks[:2]]})
        rows.append({'id':rid,'venue':f'架空会場{code}', 'start':start,'race':race,
                     'baseline_first':[1,2,3],
                     'prior_research_first':[1,2,3],
                     'v2_count':2,'v3_count':3,
                     'new_candidate_ranks':[3],
                     'ranked_picks':[{'rank':j,'cars':c} for j,c in
                                     enumerate(picks,1)]})
    old_path=base/'v2.json';old_path.write_text(json.dumps(old),encoding='utf-8')
    new={'date':DAY,'timezone':'Asia/Tokyo',
         'baseline_v2_sha256':sha256(old_path.read_bytes()).hexdigest(),
         'original_pre_race_snapshot_time':'2026-11-17T07:52:51+09:00',
         'baseline_v2_publication_time':'2026-11-17T08:42:31+09:00',
         'generated_at':'2026-11-17T09:06:03+09:00',
         'pre_race_rank_1_changed':False,'races':rows}
    new_path=base/'v3.json';new_path.write_text(json.dumps(new),encoding='utf-8')
    return new, old_path,new_path,sha256(new_path.read_bytes()).hexdigest()


def make_result(folder, code='11', race='02', win=(3,2,1),pay=4000,
                revision='rev1',status='FINAL_NORMAL',refund='NONE',
                observed='2026-11-17T11:00:00+09:00'):
    triple=list(win)
    obj={'schema':SOURCE_SCHEMA,'race_id':f'20261117{code}{race}',
         'source_url':'https://provider.example/authorized-export',
         'rights_ref':'external-testing-only',
         'source_published_at':'2026-11-17T10:59:00+09:00',
         'observed_at':observed,'provider_revision_ref':revision,
         'status':status,'refund_status':refund,
         'winning_triples':[triple] if status=='FINAL_NORMAL' else [],
         'payouts_100yen':[{'triple':triple,'yen':pay}] if status=='FINAL_NORMAL' else []}
    digest=sha256(canonical(obj)).hexdigest()
    p=folder/(digest+'.json');p.write_bytes(canonical(obj))
    return p


class Manual71SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.data,self.base,self.forecast,self.digest=fixture(self.root)
        self.result_dir=self.root/'admitted';self.result_dir.mkdir()

    def load(self):
        return read_forecast(self.forecast,expected_file_sha256=self.digest,
                             baseline_file=self.base)

    def test_71_frozen_and_hash_link(self):
        d=self.load()
        self.assertEqual(len(d['races']),71)
        self.assertEqual(d['races'][0]['ranked_picks'][0]['cars'],[1,2,3])
        self.forecast.write_text(self.forecast.read_text()+' ')
        with self.assertRaisesRegex(ManualSyncError,'FORECAST_SOURCE_SHA_MISMATCH'):
            self.load()

    def test_tampered_v2_refused(self):
        self.base.write_text(self.base.read_text()+' ')
        with self.assertRaisesRegex(ManualSyncError,'BASELINE_V2_SHA_MISMATCH'):
            self.load()

    def test_prior_metadata_conflict_does_not_override_real_v2_picks(self):
        new=deepcopy(self.data)
        new['races'][1]['prior_research_first']=[7,8,9]
        self.forecast.write_text(json.dumps(new))
        self.digest=sha256(self.forecast.read_bytes()).hexdigest()
        self.assertEqual(self.load()['races'][1]['ranked_picks'][0]['cars'],[1,2,3])

    def test_pending_not_zero_hit_rate(self):
        report=evaluate(self.load(),{})
        self.assertEqual(report['all_races'],71)
        self.assertEqual(report['summary']['all']['paired'],0)
        self.assertEqual(public_counters(report)['formal_hit_at_1'],None)
        self.assertFalse(report['official_results_authenticated'])

    def test_first_hit_and_expansion_pre_start_gate(self):
        make_result(self.result_dir,code='11',race='01',win=(3,2,1))
        make_result(self.result_dir,code='11',race='02',win=(3,2,1))
        obs=read_result_candidates(self.result_dir,as_of='2026-11-17T11:01:00+09:00')
        out=evaluate(self.load(),obs)
        first=out['rows'][0]
        self.assertEqual(first['late_added_candidates_excluded'],1)
        self.assertEqual(first['new_count'],2)
        self.assertIsNotNone(first['reference_comparison'])
        self.assertEqual(first['reference_comparison']['expanded']['stake_yen'],200)
        second=out['rows'][1]
        self.assertTrue(second['reference_comparison']['expanded']['hit_any'])
        self.assertFalse(second['reference_comparison']['baseline']['hit_any'])
        self.assertEqual(second['reference_comparison']['expanded']['payout_yen'],4000)
        self.assertEqual(second['reference_comparison']['expanded']['stake_yen'],300)
        self.assertEqual(out['summary']['all']['paired'],2)
        self.assertFalse(out['official_results_authenticated'])

    def test_result_revision_same_key_conflict_rejected(self):
        make_result(self.result_dir,win=(1,2,3),revision='rev1')
        make_result(self.result_dir,win=(3,2,1),revision='rev1')
        with self.assertRaisesRegex(ManualSyncError,'SAME_REVISION_CONTENT_CHANGED'):
            read_result_candidates(self.result_dir,as_of='2026-11-17T11:01:00+09:00')

    def test_refunds_and_pending_are_not_losses(self):
        make_result(self.result_dir,refund='FULL')
        obs=read_result_candidates(self.result_dir,as_of='2026-11-17T11:01:00+09:00')
        result=evaluate(self.load(),obs)
        self.assertEqual(result['rows'][1]['result_state'],'RESULT_UNSETTLED_OR_REFUND')
        self.assertEqual(result['summary']['all']['paired'],0)

    def test_categories_and_html_card_preserved_without_js(self):
        html='<html><head></head><body>'+''.join(
            f'<article id="r{r["id"]}" data-kind="solid">予想</article>'
            for r in self.data['races'])+'</body></html>'
        template=self.root/'source.html'; template.write_text(html)
        cats=read_categories(template,self.load())
        self.assertEqual(len(cats),71)
        result=evaluate(self.load(),{},categories=cats)
        output=render_html(result,self.load(),template_text=html)
        self.assertEqual(output.count('class="keirin-auto-result"'),71)
        self.assertEqual(output.count('<article'),71)
        self.assertIn('結果待ち',output)
        self.assertIn('会場別の照合状況を見る',output)
        self.assertIn('信頼度高め',output)

    def test_cli_offline_private_artifact(self):
        html='<html><head></head><body>'+''.join(
            f'<article id="r{r["id"]}">予想</article>' for r in self.data['races'])+'</body></html>'
        template=self.root/'view.html';template.write_text(html)
        report=self.root/'out'/'audit.json'
        view=self.root/'out'/'view.html'
        counters=run(forecast=self.forecast,baseline=self.base,
            forecast_sha256=self.digest,categories=None,template=template,
            result_dir=self.result_dir,out_report=report,out_html=view,
            now='2026-11-17T12:00:00+09:00')
        self.assertEqual(counters['total_races'],71)
        self.assertEqual(os.stat(report).st_mode & 0o777,0o600)
        self.assertIn('結果待ち',view.read_text())
        with self.assertRaises(FileExistsError):
            run(forecast=self.forecast,baseline=self.base,
                forecast_sha256=self.digest,categories=None,template=template,
                result_dir=self.result_dir,out_report=report,out_html=None,
                now='2026-11-17T12:00:00+09:00')

    def test_no_network_and_no_claimed_official(self):
        make_result(self.result_dir,win=(1,2,3))
        obs=read_result_candidates(self.result_dir,as_of='2026-11-17T11:01:00+09:00')
        view=evaluate(self.load(),obs)
        self.assertFalse(view['official_results_authenticated'])
        self.assertFalse(view['official_cutoffs_verified'])
        self.assertEqual(public_counters(view)['formal_roi'],None)
        # The observer can be a licensed-packet candidate, not an official signature.


if __name__ == '__main__':
    unittest.main()
