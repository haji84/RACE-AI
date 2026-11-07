"""Saved model completeness gates fresh capture without regenerating originals."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

from race_ai.boat_ab_shadow import MODEL_IDS as AB
from race_ai.boat_live_feature_shadow import MODEL_ID as CLITE
from race_ai.boat_observed_pairwise_models import MODEL_IDS as OBSERVED
from race_ai.existing_model_dispatch import catalog
from tests.test_boat_official_program import page
from tests.test_boat_active_exhibition import main_table, start_table
from tests.test_boat_all_model_cycle import source_context

DAY = date(2030, 4, 1)
RID = '20300401-12-12'
NOW = datetime.fromisoformat('2030-04-01T20:20:00+09:00')
BASELINES = set(AB) | {CLITE} | set(OBSERVED)
ALL = {s['model_id'] for s in catalog() if 'boat' in s['applicable_sports']
       and s['model_id'] != 'seller-shadow-v1-20261104'}
HEAD = 'a'*40


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


def cached_schedule():
    captured = (NOW-timedelta(minutes=1)).isoformat()
    return dict(official_day_source=dict(url='https://www.boatrace.jp/owpc/pc/race/index?hd=20300401',
        source_sha256='a'*64, captured_at=captured), verified_active_venues=['12'],
        official_race_registry=[dict(race_id=RID, cutoff_at='2030-04-01T20:30:00+09:00',
            schedule_captured_at=captured, source_sha256='b'*64)])


def raw_sources():
    options = {n:dict(name=f'選手 {n}') for n in range(1,7)}
    program = page(venue='12', race_no=12, row_options=options)
    preview = page(venue='12', race_no=12, content=main_table()+start_table()).replace(
        b'/owpc/pc/race/racelist?rno=', b'/owpc/pc/race/beforeinfo?rno=')
    return program, preview


class CollectorCompletionTests(unittest.TestCase):
    def collect(self, issued, *, frozen=True, sink_error=False, forbid_models=False):
        from scripts import boat_nationwide_ab_pilot as pilot
        program, preview = raw_sources()
        requests, retained = [], []
        def get(url, **kwargs):
            requests.append(url)
            if '/racelist?' in url: raw=program
            elif '/beforeinfo?' in url: raw=preview
            else: raise pilot.SourceError('FICTIONAL_OPTIONAL_ODDS_UNAVAILABLE')
            return raw,NOW,sha256(raw).hexdigest()
        def sink(program,beforeinfo,as_of):
            if sink_error: raise ValueError('/private/never-show-this-input')
            retained.append(deepcopy((program,beforeinfo,as_of)))
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(pilot,'OUTPUT',Path(temporary)), patch.object(pilot,'datetime',Clock), \
                 patch.object(pilot,'_clock',return_value=NOW), patch.object(pilot,'get',side_effect=get), \
                 patch.object(pilot,'observed_timestamp',return_value=NOW.isoformat()), \
                 patch.object(pilot,'ISSUED_MODELS',issued,create=True), patch.object(pilot,'MODEL_INPUT_SINK',sink), \
                 patch.object(pilot,'load_original_race_ids',return_value=frozenset({RID}) if frozen else frozenset()), \
                 patch.object(pilot,'collect_pitreport',return_value=None), patch.object(pilot,'collect_entry_history',return_value=None), \
                 patch.dict(os.environ,{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true'}), redirect_stdout(io.StringIO()):
                if forbid_models:
                    with patch.object(pilot.model,'build_pair',side_effect=AssertionError('saved A/B regeneration')), \
                         patch.object(pilot,'build_live_feature_shadow',side_effect=AssertionError('saved C-lite regeneration')), \
                         patch.object(pilot,'build_observed_p1',side_effect=AssertionError('saved observed regeneration')):
                        result=pilot.run(schedule_snapshot=cached_schedule())
                else:
                    result=pilot.run(schedule_snapshot=cached_schedule())
        return result,requests,retained

    def test_saved_five_baselines_still_capture_missing_applicable_family(self):
        self.assertEqual(len(ALL),14)
        result,requests,retained=self.collect({RID:sorted(BASELINES)},forbid_models=True)
        self.assertEqual(len(retained),1)
        self.assertEqual(len(requests),2)
        self.assertEqual(result['paired_forecasts'],[])
        self.assertEqual(result['additional_official_feature_shadows'],[])
        self.assertEqual(result['observed_pairwise_p1_bundles'],[])
        self.assertEqual(result['reason'],'ADDITIONAL_MODEL_INPUTS_RETAINED')
        self.assertEqual(next(r['state'] for r in result['candidate_attempts'] if r['race_id']==RID),
                         'SOURCE_READY_ADDITIONAL_MODELS')
        self.assertEqual(retained[0][0]['race_id'],RID)
        self.assertEqual(retained[0][1]['source_sha256'],sha256(raw_sources()[1]).hexdigest())

    def test_only_one_missing_family_is_enough_and_complete_matrix_skips_sources(self):
        result,requests,retained=self.collect({RID:sorted(ALL-{'boat-comprehensive-v1'})},forbid_models=True)
        self.assertEqual((len(requests),len(retained)),(2,1))
        result,requests,retained=self.collect({RID:sorted(ALL)},forbid_models=True)
        self.assertEqual((requests,retained),([],[]))
        self.assertEqual(result['paired_forecasts'],[])

    def test_canonical_original_is_never_regenerated_when_matrix_has_no_baseline_entry(self):
        result,requests,retained=self.collect({},forbid_models=True)
        self.assertEqual((len(requests),len(retained)),(2,1))
        self.assertEqual(result['paired_forecasts'],[])

    def test_retention_failure_isolated_from_unissued_legacy_baselines(self):
        result,requests,retained=self.collect({},frozen=False,sink_error=True)
        self.assertEqual(len(result['paired_forecasts']),1)
        self.assertEqual(len(result['additional_official_feature_shadows']),1)
        self.assertEqual(len(result['observed_pairwise_p1_bundles']),1)
        self.assertEqual((len(requests),retained),(3,[]))
        self.assertNotIn('never-show-this-input',json.dumps(result))

    def test_failed_additional_capture_preserves_all_saved_baselines(self):
        result,requests,retained=self.collect({RID:sorted(BASELINES)},sink_error=True,forbid_models=True)
        self.assertEqual((len(requests),retained),(2,[]))
        self.assertEqual(result['paired_forecasts'],[])
        self.assertEqual(next(r['state'] for r in result['candidate_attempts'] if r['race_id']==RID),
                         'ADDITIONAL_MODEL_INPUT_REJECTED')
        self.assertNotIn('never-show-this-input',json.dumps(result))


class CollectorRuntimeWiringTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name)
        self.root=self.base/'checkout'; self.root.mkdir()
        (self.root/'cycle_recovery_output').mkdir()
        self.output=self.root/'out'; self.output.mkdir()
        self.index=self.root/'index.json'; self.index.write_text('{"entries":[]}')
        self.private=self.base/'private'; self.private.mkdir(mode=0o700)
        self.runtime=self.private/'boat-all-model-runtime'; self.runtime.mkdir(mode=0o700)
        self.issued={RID:sorted(BASELINES)}
    def ready(self):
        raw=(json.dumps(self.issued,sort_keys=True,separators=(',',':'))+'\n').encode()
        (self.runtime/'issued-models.json').write_bytes(raw)
        (self.runtime/'issued-models.json').chmod(0o600)
        for name in ('history.sqlite','metadata.json'):
            (self.runtime/name).write_bytes(b'fictional-runtime'); (self.runtime/name).chmod(0o600)
        flags=dict(verified_runtime=True,history_identity_verified=True,owner_reviewed=True)
        marker=dict(schema='RACE_AI_BOAT_ALL_MODEL_RUNTIME_READY_V1',ready=True,round_no=3,
            **flags,source_code_commit=HEAD,run_id='42',pointer_sha256='b'*64,metadata_sha256='c'*64,
            issued_models_sha256=sha256(raw).hexdigest(),runtime_files=dict(**flags,source_code_commit=HEAD,run_id='42',
                **{n:str(self.runtime/n) for n in ('history.sqlite','metadata.json')}))
        path=self.runtime/'runtime-ready.json'; path.write_text(json.dumps(marker)); path.chmod(0o600)
        return marker
    def invoke(self,*,round_no=3,callback=None):
        from scripts import github_existing_cycle as runner
        from scripts import boat_nationwide_ab_pilot as pilot
        state=dict(index_entries=[])
        def run(**kwargs):
            if callback: callback(pilot)
            return dict(observed_pairwise_p1_bundles=[],baseline_marker='PRESERVED')
        with patch.object(runner,'ROOT',self.root), patch.object(runner,'load_state',return_value=state), \
             patch.object(pilot,'FROZEN_INDEX',self.index),patch.object(pilot,'OUTPUT',self.output), \
             patch.object(pilot,'MODEL_INPUT_SINK',None),patch.object(pilot,'ISSUED_MODELS',None,create=True), \
             patch.object(pilot,'run',side_effect=run), patch.object(runner,'gh',side_effect=AssertionError('new API read')), \
             patch.dict(os.environ,{'RUNNER_TEMP':str(self.private),'GITHUB_RUN_ID':'42','GITHUB_SHA':HEAD}):
            runner.forecast(DAY.isoformat(),round_no=round_no)
            self.assertIsNone(pilot.MODEL_INPUT_SINK)
            self.assertIsNone(pilot.ISSUED_MODELS)
        return json.loads((self.output/'national.json').read_text())

    def test_verified_current_round_captures_first_input_outside_git(self):
        self.ready()
        ctx=source_context()
        def run(pilot):
            self.assertEqual(pilot.ISSUED_MODELS,self.issued)
            self.assertTrue(callable(pilot.MODEL_INPUT_SINK))
            pilot.MODEL_INPUT_SINK(ctx['program'],ctx['beforeinfo'],ctx['as_of'])
        result=self.invoke(callback=run)
        target=self.private/'boat-all-model-inputs/cycle-3'/f'{RID}.json'
        self.assertTrue(target.is_file())
        self.assertEqual(target.stat().st_mode&0o077,0)
        self.assertEqual(json.loads(target.read_text())['program'],ctx['program'])
        self.assertEqual(result['baseline_marker'],'PRESERVED')

    def test_missing_or_rejected_runtime_preserves_baseline_capture(self):
        for mutation in ('absent','round','head','run','hash','flags','boolean_round'):
            for path in self.runtime.iterdir():path.unlink()
            if mutation!='absent':
                marker=self.ready()
                if mutation=='round': marker['round_no']=2
                if mutation=='head': marker['source_code_commit']='d'*40
                if mutation=='run': marker['run_id']='43'
                if mutation=='hash': marker['issued_models_sha256']='d'*64
                if mutation=='flags': marker['verified_runtime']=False
                if mutation=='boolean_round': marker['round_no']=True
                (self.runtime/'runtime-ready.json').write_text(json.dumps(marker))
            def run(pilot):
                self.assertIsNone(pilot.MODEL_INPUT_SINK)
                self.assertIsNone(pilot.ISSUED_MODELS)
            with self.subTest(mutation=mutation):
                self.assertEqual(self.invoke(callback=run,round_no=1 if mutation=='boolean_round' else 3)['baseline_marker'],'PRESERVED')


if __name__=='__main__':
    unittest.main()
