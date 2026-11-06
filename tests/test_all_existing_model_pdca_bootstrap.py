"""Actual synthetic encrypted archives: source-only is never a forecast/loss."""
from copy import deepcopy
from datetime import timedelta
import contextlib
import io
import json
import os
from unittest.mock import patch
import unittest

from tests import test_all_existing_model_input_bootstrap as bootstrap
from race_ai.all_existing_model_pdca import score_private_pairs_artifact


class AllModelBootstrapPDCATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):bootstrap.NativeInputBootstrapTests.setUpClass()

    def setUp(self):
        self.case=bootstrap.NativeInputBootstrapTests();self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fixture=self.case.fixture

    def generate(self, *, mixed):
        requests=[self.case.request('horse')]
        if mixed:requests.insert(0,dict(cell_key=self.fixture.cell,native_payload=self.fixture.native()))
        self.case.generate(requests)
        raw,_=self.fixture.archive();meta=self.fixture.metadata(raw)
        return raw,meta

    def result(self):
        pair=next(record['pair'] for record in self.case.payloads() if 'pair' in record)
        return dict(race_id=pair['race_id'],sport=pair['sport'],status='settled',
            ordered_top3=deepcopy(pair['baseline_normalized']['top'][0]),
            roster=deepcopy(pair['baseline_normalized']['roster']),
            captured_at=(bootstrap.FORECAST_NOW+timedelta(minutes=21)).isoformat(),source_sha256='b'*64,
            identity_verified=True,payout_per_100_yen=1230,refund_numbers=[])

    def score(self,raw,meta,results):
        return score_private_pairs_artifact(raw,meta,results,self.fixture.root/'pdca',
            now=bootstrap.FORECAST_NOW+timedelta(hours=1),expected_run_id=99,expected_head_sha='a'*40)

    def test_source_only_archive_produces_zero_forecasts_or_losses(self):
        raw,meta=self.generate(mixed=False);report=self.score(raw,meta,[])
        self.assertEqual(report['state'],'FROZEN_NATIVE_INPUTS_NO_FORECASTS')
        for field in ('paired_forecasts','baseline_forecast_count','learned_forecast_count','partition_count'):
            self.assertEqual(report[field],0)
        self.assertEqual(report['scoreboard'],{})
        self.assertEqual({p.name for p in (self.fixture.root/'pdca').iterdir()},{'summary.json'})

    def test_mixed_archive_scores_only_the_actual_pair(self):
        raw,meta=self.generate(mixed=True);report=self.score(raw,meta,[self.result()])
        self.assertEqual(report['paired_forecasts'],1)
        self.assertEqual(report['partition_count'],1)
        self.assertEqual(set(report['scoreboard']),{self.fixture.cell})

    def test_cycle_filters_other_settled_day_races_after_authenticating_archive(self):
        from scripts import github_existing_cycle as runner
        raw,meta=self.generate(mixed=True);result=self.result()
        unrelated=deepcopy(result);unrelated['race_id']='boat:2030-04-01:boatrace-jcd-24:11'
        repo=self.fixture.root/'repo';(repo/'existing_cycle_output').mkdir(parents=True)
        (repo/'existing_cycle_output/official-result-observations.json').write_text('[]')
        ref=dict(artifact_id=meta['id'],run_id=99,head_sha='a'*40,digest=meta['digest'])
        with patch.object(runner,'ROOT',repo),patch.object(runner,'load_state',return_value={
                 'venue_research_artifact_refs':[ref]}), \
             patch.object(runner,'latest_result_observations',return_value=([result,unrelated],[])), \
             patch.object(runner,'gh',side_effect=[json.dumps(meta).encode(),raw]), \
             patch.dict(os.environ,RUNNER_TEMP=str(self.fixture.root)), \
             patch.object(runner,'datetime') as clock,contextlib.redirect_stdout(io.StringIO()):
            clock.now.return_value=bootstrap.FORECAST_NOW+timedelta(hours=1)
            report=runner.venue_research_pdca('2030-04-01',2)
        self.assertEqual(report['archives_processed'],1)
        self.assertEqual(report['rejected_archives'],0)
        self.assertEqual(report['paired_forecasts'],1)


if __name__=='__main__':unittest.main()
