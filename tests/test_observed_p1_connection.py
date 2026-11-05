"""Fictional observed inputs; no live source or historical performance claims."""
import copy, hashlib, io, json, unittest, zipfile
from race_ai.actions_contract import digest
from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
from race_ai.boat_observed_pairwise_models import MODEL_IDS, predict_pair
from race_ai.frozen_day_cycle import read_p1
from race_ai.first_receipt_continuity import first_receipt_rows
try:
    from race_ai import observed_p1_connection as bridge
except ImportError:
    bridge = None

AT = '2030-04-01T10:40:00+09:00'
PROGRAM_AT = '2030-04-01T10:39:00+09:00'
PREVIEW_AT = '2030-04-01T10:39:30+09:00'

def inputs():
    base = dict(race_id='20300401-01-01', cutoff_at='2030-04-01T10:59:00+09:00', captured_at=PREVIEW_AT,
                program_source_sha256='a'*64, beforeinfo_source_sha256='b'*64,
                boats=[dict(lane=i, racer_id=str(4000+i), national_win_rate=5+i/10,
                            exhibition_time_seconds=6.5+i/100, motor_two_place_rate_percent=30+i)
                       for i in range(1,7)])
    extra = dict(race_id=base['race_id'], observed_at=PREVIEW_AT,
                 source_sha256=hashlib.sha256(('a'*64+'b'*64).encode()).hexdigest(),
                 participants=[dict(lane=i, racer_id=str(4000+i), local_win_rate=5., average_st=.15,
                                    exhibition_st=.1+i/100, exhibition_st_status='OK') for i in range(1,7)])
    provenance = dict(program_url='https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd=01&hd=20300401',
                      preview_url='https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno=1&jcd=01&hd=20300401',
                      program_captured_at=PROGRAM_AT, preview_captured_at=PREVIEW_AT)
    return base, extra, provenance

def archive(doc, saved='2030-04-01T01:41:00Z'):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z: z.writestr('national.json',json.dumps(doc))
    raw=out.getvalue()
    return raw,dict(id=123, name='boat-national-cutoff-99', expired=False, created_at=saved,
                    digest='sha256:'+hashlib.sha256(raw).hexdigest(),
                    workflow_run=dict(id=99, head_repository_id=1416489937))

class ObservedP1ConnectionTests(unittest.TestCase):
    def setUp(self): self.assertIsNotNone(bridge,'P1 observed-model connection is missing')
    def bundle(self):
        base,extra,proof=inputs()
        return bridge.build_bundle(base,extra,AT,**proof,owner_reviewed=True)
    def test_same_input_unchanged_models_and_missing_history(self):
        base,extra,proof=inputs(); before=copy.deepcopy((base,extra))
        bundle=bridge.build_bundle(base,extra,AT,**proof,owner_reviewed=True)
        snap=bundle['snapshot']; suite=bundle['suite']
        self.assertEqual((base,extra),before)
        self.assertEqual(tuple(suite['models']),MODEL_IDS)
        self.assertEqual(suite,predict_pair(snap,allow_source=lambda *_:True))
        self.assertEqual(snap['stage'],'P1'); self.assertFalse(suite['official_prediction'])
        for row in snap['participants']:
            self.assertEqual(len(row['features']),4)
            self.assertEqual(row['missing']['recent_mean_st'],'NO_PRIOR_SAMPLES')
            self.assertEqual(row['features']['exhibition_start_seconds']['value'],extra['participants'][row['lane']-1]['exhibition_st'])
        self.assertEqual(bundle['http_provenance'][0]['request_url'],proof['program_url'])
        self.assertEqual(snap['sources'][0]['captured_at'],PROGRAM_AT)
    def test_f_l_pending_start_never_becomes_zero(self):
        for status in ('F','L','PENDING'):
            b,e,p=inputs(); e['participants'][0].update(exhibition_st_status=status,exhibition_st=None)
            x=bridge.build_bundle(b,e,AT,**p,owner_reviewed=True)['snapshot']['participants'][0]
            self.assertNotIn('exhibition_start_seconds',x['features'])
            self.assertEqual(x['missing']['exhibition_start_seconds'],status if status!='PENDING' else 'NOT_YET_PUBLISHED')
    def test_source_identity_time_permission_fail_closed(self):
        for change in ('racer','url','future','late','unreviewed'):
            b,e,p=inputs(); clock=AT; permission=True
            if change=='racer':e['participants'][0]['racer_id']='9999'
            if change=='url':p['preview_url']=p['preview_url'].replace('rno=1','rno=2')
            if change=='future':p['program_captured_at']='2030-04-01T10:50:00+09:00'
            if change=='late':clock=b['cutoff_at']
            if change=='unreviewed':permission=False
            with self.subTest(change=change),self.assertRaises(ValueError):
                bridge.build_bundle(b,e,clock,**p,owner_reviewed=permission)
    def test_same_artifact_five_models_and_legacy_unchanged(self):
        b,e,p=inputs(); pair=build_pair(b,AT); shadow=build_live_feature_shadow(b,e,AT)
        old=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',paired_forecasts=[pair],additional_official_feature_shadows=[shadow])
        _,legacy=read_p1(*archive(old))
        new=copy.deepcopy(old); new['observed_pairwise_p1_bundles']=[self.bundle()]
        _,rows=read_p1(*archive(new))
        self.assertEqual(len(legacy),3); self.assertEqual(len(rows),5)
        for x,y in zip(legacy,rows[:3]):
            self.assertEqual({k:v for k,v in x.items() if k!='original_json_sha256'},
                             {k:v for k,v in y.items() if k!='original_json_sha256'})
        self.assertEqual(len(first_receipt_rows(rows+rows)[0]),5)
    def test_observed_archive_tampering_cross_race_and_late_rejected(self):
        for change in ('tamper','race','late','duplicate'):
            bundle=self.bundle()
            doc=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',paired_forecasts=[],observed_pairwise_p1_bundles=[bundle])
            saved='2030-04-01T01:41:00Z'
            if change=='tamper':bundle['suite']['models'][MODEL_IDS[0]]['ordered_top8'][0].reverse()
            if change=='race':bundle['snapshot']['race_id']='boat:2030-04-01:boatrace-jcd-01:2'
            if change=='late':saved='2030-04-01T02:00:00Z'
            if change=='duplicate':doc['observed_pairwise_p1_bundles'].append(copy.deepcopy(bundle))
            with self.subTest(change=change),self.assertRaises(ValueError):read_p1(*archive(doc,saved))

class LivePilotWiringTests(unittest.TestCase):
    def test_existing_make_pair_calls_existing_observed_models(self):
        from unittest.mock import patch
        from datetime import date,datetime
        import race_ai
        from pathlib import Path
        race_ai.__path__.append(str(Path(__file__).resolve().parents[1]/"pr64-reference/race_ai"))
        from scripts import boat_nationwide_ab_pilot as pilot
        b,e,p=inputs()
        program=dict(race_id=b['race_id'],closed_at=b['cutoff_at'],boats=[
            dict(lane=r['lane'],racer_registration_id=r['racer_id'],national_win_rate=r['national_win_rate'],
                 entry_status='listed',local_win_rate=5.,average_st=.15) for r in b['boats']])
        preview=dict(status='AVAILABLE',data=dict(boats=[
            dict(lane=r['lane'],racer_registration_id=r['racer_id'],display_time=r['exhibition_time_seconds'],
                 preview_st=e['participants'][r['lane']-1]['exhibition_st'],preview_st_status='OK') for r in b['boats']]))
        captures=[(b'program',datetime.fromisoformat(PROGRAM_AT),'a'*64),
                  (b'preview',datetime.fromisoformat(PREVIEW_AT),'b'*64),
                  pilot.SourceError('FICTIONAL_ODDS_NOT_AVAILABLE')]
        with patch.object(pilot,'get',side_effect=captures),patch.object(pilot,'parse_official_racelist',return_value=program), \
             patch.object(pilot,'parse_update',return_value=preview),patch.object(pilot,'motor_top2',return_value={r['lane']:r['motor_two_place_rate_percent'] for r in b['boats']}), \
             patch.object(pilot,'observed_timestamp',return_value=AT),patch.object(pilot,'requests_used',45), \
             patch.dict('os.environ',{'RACE_AI_NATIONWIDE_OWNER_SOURCE_REVIEWED':'true'}):
            output=pilot.make_pair(date(2030,4,1),dict(race_id=b['race_id'],cutoff_at=b['cutoff_at']))
        self.assertEqual(len(output),5,'existing runner still returns only A/B/C-lite, no observed P1 bundle')
        self.assertEqual(tuple(output[4]['suite']['models']),MODEL_IDS)
        self.assertEqual(output[3].get('failure_class'),'SourceError',
                         'optional pre-close odds must not be skipped at the former GET count')

class ProvenanceBindingTests(unittest.TestCase):
    def test_pair_and_observed_source_must_match_in_same_archive(self):
        b,e,p=inputs();pair=build_pair(b,AT);bundle=bridge.build_bundle(b,e,AT,**p,owner_reviewed=True)
        bundle['base_source_sha256']='f'*64
        bundle['bundle_sha256']=digest({k:v for k,v in bundle.items() if k!='bundle_sha256'})
        doc=dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',paired_forecasts=[pair],
                 additional_official_feature_shadows=[build_live_feature_shadow(b,e,AT)],observed_pairwise_p1_bundles=[bundle])
        with self.assertRaisesRegex(ValueError,'source'):read_p1(*archive(doc))
