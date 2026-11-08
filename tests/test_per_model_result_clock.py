"""Invented source receipts: each saved model keeps its own cutoff and clocks."""
from copy import deepcopy
import json,subprocess,unittest
from pathlib import Path
from race_ai import saved_result_sync as S,saved_view_feed as F
from race_ai.boat_saved_model_view import validate_cutoff_reconciliation
from tests.intraday_fixture import packet
from tests.test_boat_sp_settlement import document
from tests.test_racer_result_bridge import saved_view


def fixture():
    view=saved_view();row=view['records'][0];p=row['prediction']
    p.update(generated_at='2026-11-07T09:44:00+09:00',as_of='2026-11-07T09:44:00+09:00',persisted_at='2026-11-07T09:45:00+09:00',prediction_sha256='a'*64,input_sha256='c'*64,odds_independent=True)
    late=deepcopy(p);late.update(stage='P1',model_id='INVENTED_LATER_MODEL',generated_at='2026-11-07T10:04:00+09:00',as_of='2026-11-07T10:04:00+09:00',persisted_at='2026-11-07T10:05:00+09:00',cutoff_at='2026-11-07T10:10:00+09:00',prediction_sha256='b'*64)
    row.update(venue='桐生',offering_status='TRIFECTA_OFFERED',source_provenance='INVENTED_CLOCK_TEST_ONLY',source_sha256='c'*64,cutoff_at=None,saved_cutoff_variants=[p['cutoff_at'],late['cutoff_at']],comparison_predictions=[late],missing_reasons=['SAVED_FORECAST_CUTOFF_CONFLICT'])
    d=document();d['raceheader']['rlinklist'][0]['deadline']='10:10'
    raw,receipt=packet(d,captured='2026-11-07T01:20:00Z')
    return view,(raw,receipt)


def project(view,capture):
    return F.update_view(view,[],captures=[capture],synced_at='2026-11-07T01:21:00Z')


class ClockTests(unittest.TestCase):
    def test_later_model_before_own_and_official_cutoffs_is_not_compared_to_another_model_cutoff(self):
        view,capture=fixture();pin=F.originals_sha(view);out=project(view,capture);row=out['records'][0]
        self.assertEqual(row['result']['status'],'final')
        self.assertEqual(row['result']['winning_combinations'],[[1,2,3]])
        self.assertIsNone(row['cutoff_at']);self.assertEqual(F.originals_sha(out),pin)
        self.assertEqual(row['result']['cutoff_reconciliation']['basis'],'RAW_OFFICIAL_SP_RESULT_PER_SAVED_MODEL_CUTOFF')
        self.assertTrue(validate_cutoff_reconciliation(row,row['result']))

    def test_retained_available_observation_without_new_header_metadata_is_preserved(self):
        view,capture=fixture();row=view['records'][0];old=S.parse_capture(*capture);old.pop('schedule_binding')
        row['result_observations']=[old];row['result']=dict(status='unsupported',winning_combinations=[],confirmed_at=None,observed_at=old['captured_at'],source_sha256=old['source_sha256'],official=False)
        before=deepcopy(old);pin=F.originals_sha(view)
        out=F.update_view(view,[old],captures=[capture],synced_at='2026-11-07T01:21:00Z');r=out['records'][0]
        self.assertEqual(r['result']['status'],'final')
        self.assertEqual(r['result_observations'],[before]);self.assertEqual(F.originals_sha(out),pin)
        self.assertTrue(validate_cutoff_reconciliation(r,r['result']))

    def test_saved_schedule_revisions_must_bind_to_the_existing_model_cutoffs(self):
        view,capture=fixture();row=view['records'][0]
        row['saved_schedule_cutoff_variants']=list(row['saved_cutoff_variants'])
        row['missing_reasons'].append('SAVED_SCHEDULE_CUTOFF_CONFLICT')
        original=deepcopy(row);pin=F.originals_sha(view)
        out=project(view,capture);matched=out['records'][0]
        self.assertEqual(matched['result']['status'],'final')
        self.assertEqual(F.originals_sha(out),pin)
        self.assertEqual(matched['saved_schedule_cutoff_variants'],original['saved_schedule_cutoff_variants'])
        self.assertIn('SAVED_SCHEDULE_CUTOFF_CONFLICT',matched['missing_reasons'])
        self.assertTrue(validate_cutoff_reconciliation(matched,matched['result']))
        rejected=[]
        for field,values in [('saved_schedule_cutoff_variants',['2026-11-07T10:09:00+09:00']),('saved_schedule_cutoff_variants',[row['saved_cutoff_variants'][0]]),('saved_observation_cutoff_variants',[row['saved_cutoff_variants'][0]])]:
            bad=deepcopy(view);bad['records'][0][field]=values
            self.assertEqual(project(bad,capture)['records'][0]['result']['status'],'unsupported')
            bad=deepcopy(matched);bad[field]=values;rejected.append(bad)
            with self.assertRaises(ValueError):validate_cutoff_reconciliation(bad,bad['result'])
        legacy=deepcopy(matched);legacy['result']['cutoff_reconciliation']['basis']='RAW_OFFICIAL_RESULT_PER_ORIGINAL_CUTOFF'
        with self.assertRaises(ValueError):validate_cutoff_reconciliation(legacy,legacy['result'])
        rejected.append(legacy)
        code="""const assert=require('node:assert/strict'),M=require('./web/product-data.js');let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const x=JSON.parse(s);assert.equal(M.parse(x.view).records[0].result.status,'final');for(const r of x.bad)assert.throws(()=>M.parse({...x.view,records:[r]}));});"""
        result=subprocess.run(['node','-e',code],cwd=Path(__file__).resolve().parents[1],input=json.dumps({'view':out,'bad':rejected}),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_a_model_saved_after_its_own_or_the_official_cutoff_still_cannot_be_settled(self):
        for field,value in [('cutoff_at','2026-11-07T10:04:00+09:00'),('persisted_at','2026-11-07T10:11:00+09:00'),('generated_at','2026-11-07T10:11:00+09:00')]:
            view,capture=fixture();p=view['records'][0]['comparison_predictions'][0];p[field]=value
            if field=='cutoff_at':view['records'][0]['saved_cutoff_variants'][1]=value
            with self.subTest(field=field):self.assertEqual(project(view,capture)['records'][0]['result']['status'],'unsupported')

    def test_unbound_or_non_sp_evidence_does_not_relax_the_legacy_minute_limit(self):
        view,capture=fixture();row=view['records'][0];o=S.parse_capture(*capture);row['result_observations']=[o]
        for raw_bound,sp in [(False,True),(True,False)]:
            selected=deepcopy(o)
            if not sp:selected.pop('schedule_binding')
            with self.subTest(raw_bound=raw_bound,sp=sp),self.assertRaises(ValueError):S.project_observation(selected,row,freeze_at=row['prediction']['persisted_at'],raw_bound=raw_bound)

    def test_wrong_registration_and_changed_winner_cannot_be_reconciled(self):
        for change in ('registration','winner'):
            view,_=fixture();d=document();d['raceheader']['rlinklist'][0]['deadline']='10:10'
            if change=='registration':d['maindata']['teiinfolist'][0]['registno']='4999'
            else:d['maindata']['infolist3t'][0]['winno']='3-2-1'
            capture=packet(d,captured='2026-11-07T01:20:00Z')
            with self.subTest(change=change):self.assertEqual(project(view,capture)['records'][0]['result']['status'],'unsupported')

    def test_python_and_browser_validate_source_binding_and_chronology_without_changing_cash_policy(self):
        view,capture=fixture();out=project(view,capture);row=out['records'][0]
        self.assertEqual(row['result']['status'],'final')
        bad=[]
        for mutate in [lambda r:r['result']['cutoff_reconciliation'].update(source_cutoff_at='2026-11-07T10:09:00+09:00'),lambda r:(r['result_observations'][0].pop('schedule_binding'),r['result']['cutoff_reconciliation'].pop('source_schedule_binding',None)),lambda r:r['comparison_predictions'][0].update(persisted_at='2026-11-07T10:11:00+09:00')]:
            r=deepcopy(row);mutate(r);bad.append(r)
            with self.subTest(),self.assertRaises(ValueError):validate_cutoff_reconciliation(r,r['result'])
        for url in [row['result_observations'][0]['source_url'].replace('www.boatrace.jp','user:pass@www.boatrace.jp'),row['result_observations'][0]['source_url'].replace('www.boatrace.jp','www.boatrace.jp:443'),row['result_observations'][0]['source_url'].replace('www.boatrace.jp','WWW.BOATRACE.JP')]:
            r=deepcopy(row);r['result_observations'][0]['source_url']=url;bad.append(r)
            with self.subTest(),self.assertRaises(ValueError):validate_cutoff_reconciliation(r,r['result'])
        r=deepcopy(row);r['result']['cutoff_reconciliation']['source_schedule_binding']=None;bad.append(r)
        with self.assertRaises(ValueError):validate_cutoff_reconciliation(r,r['result'])
        code="""const assert=require('node:assert/strict'),M=require('./web/product-data.js'),P=require('./web/saved-performance.js');let s='';process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const x=JSON.parse(s),v=M.parse(x.view),r=v.records[0];assert.equal(r.result.status,'final');for(const p of [r.prediction,...r.comparison_predictions])assert.equal(P.compare(r,p).status,'HIT');assert.equal(M.summary(v.records).overall.evaluable,0);for(const b of x.bad)assert.throws(()=>M.parse({...x.view,records:[b]}));});"""
        result=subprocess.run(['node','-e',code],cwd=Path(__file__).resolve().parents[1],input=json.dumps({'view':out,'bad':bad}),text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
