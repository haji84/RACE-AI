"""Offline archive history: frozen source membership, no live accuracy claim."""
import copy
import hashlib
import io
import json
import unittest
import zipfile
from race_ai.actions_contract import digest
from tests.test_observed_p1_connection import inputs, AT


def observation(rid='20300331-01-01', captured='2030-03-31T03:00:00Z'):
    url='https://www.boatrace.jp/owpc/pc/race/raceresult?rno='+str(int(rid[-2:]))+'&jcd='+rid[9:11]+'&hd='+rid[:8]
    return dict(race_id=rid,kind='raceresult',information_phase='official_result',
        status='AVAILABLE',body_identity_verified=True,closed_at='2030-03-31T02:00:00Z',
        available_at=captured,captured_at=captured,source_url=url,source_sha256='c'*64,
        data=dict(status='settled',confirmed=True,finish_confirmed=True,results=[
            dict(race_id=rid,lane=i,racer_registration_id=str(4000+i),finish=i,finish_status='FINISHED',
                actual_st=.1+i/100,actual_st_status='OK',actual_course=None,verified_official=True,
                source_url=url,captured_at=captured) for i in range(1,7)]))


def archived(observations):
    report=dict(day_jst='2030-03-31',result_observation_versions=len(observations))
    report['report_sha256']=digest(report)
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        z.writestr(zipfile.ZipInfo('official-result-observations.json',(2026,1,1,0,0,0)),json.dumps(observations))
        z.writestr(zipfile.ZipInfo('status.json',(2026,1,1,0,0,0)),json.dumps(report))
    raw=b.getvalue()
    return raw,dict(id=88,name='race-existing-cycle-9',expired=False,created_at='2030-03-31T04:00:00Z',
        digest='sha256:'+hashlib.sha256(raw).hexdigest(),workflow_run=dict(id=9,head_repository_id=1416489937))


def roster():return [dict(lane=i,registration_no=str(4000+i)) for i in range(1,7)]


def reseal(doc,field):doc[field]=digest({k:v for k,v in doc.items() if k!=field})


class HistoryTests(unittest.TestCase):
    def setUp(self):
        try:
            from race_ai import observed_result_history as history
        except ImportError:
            history=None
        self.assertIsNotNone(history, "archive-backed history adapter is missing")
        self.h=history
    def context(self,obs=None):
        return self.h.context_from_result_archive(*archived([observation()] if obs is None else obs),verified_at='2030-03-31T04:01:00Z')
    def prepared(self,context=None,participants=None):
        return self.h.prepare_history(context or self.context(),race_id='20300401-01-01',participants=participants or roster(),as_of=AT)
    def test_captured_prior_finish_and_st_are_real_samples_with_no_course(self):
        p=self.prepared();r=p['participants'][0]
        self.assertEqual(r['features']['recent_mean_finish']['value'],1)
        self.assertEqual(r['features']['recent_mean_st']['value'],.11)
        self.assertEqual(r['features']['recent_mean_st']['sample_n'],1)
        self.assertEqual(r['missing'],dict(course_mean_finish='NO_VERIFIED_COURSE',course_mean_st='NO_VERIFIED_COURSE'))
        self.assertEqual(p['source']['source_sha256'],self.context()['receipt']['digest'][7:])
        self.assertEqual(p['source']['source_url'],'https://api.github.com/repos/haji84/RACE-AI/actions/artifacts/88/zip')
        self.assertIsNone(p['source']['published_at'])
        self.assertEqual(p,self.h.verify_history_evidence(p['evidence'],race_id='20300401-01-01',participants=roster(),as_of=AT))
        self.h.validate_history_proofs(p['evidence'],{'88':self.h.history_proof(self.context())})
    def test_latest_unknown_revision_blocks_old_positive_and_fl_counts_remain(self):
        old=observation();new=observation(captured='2030-03-31T03:30:00Z')
        new['data']['results'][0].update(finish=None,finish_status='F',actual_st=None,actual_st_status='F')
        new['data']['results'][1].update(actual_st=None,actual_st_status='L')
        other=observation('20300331-01-02',captured='2030-03-31T03:40:00Z')
        r=self.prepared(self.context([old,new,other]))['participants'][0]
        self.assertNotIn('recent_mean_finish',r['features'])
        self.assertEqual(r['features']['recent_mean_st']['value'],.11)
        self.assertEqual(r['features']['recent_mean_st']['history']['f_n'],1)
        self.assertEqual(r['features']['recent_mean_st']['history']['total_n'],2)
        self.assertEqual(r['features']['recent_mean_st']['sample_n'],1)
    def test_target_future_and_unavailable_versions_cannot_supply_history(self):
        for change in ('target','future_capture','future_available','future_cutoff','unknown_latest'):
            o=observation()
            if change=='target':o['race_id']='20300401-01-01'
            if change=='future_capture':o['captured_at']='2030-04-01T03:00:00Z'
            if change=='future_available':o['available_at']='2030-04-01T03:00:00Z'
            if change=='future_cutoff':o['closed_at']='2030-04-01T03:00:00Z'
            if change=='unknown_latest':o.update(status='PENDING',data=None)
            # Target has its own archive day, so directly evaluate a valid context of that day.
            raw,meta=archived([o])
            if change=='target':
                b=io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(raw)) as z,zipfile.ZipFile(b,'w') as out:
                    report=json.loads(z.read('status.json'));report['day_jst']='2030-04-01';reseal(report,'report_sha256')
                    out.writestr('status.json',json.dumps(report));out.writestr('official-result-observations.json',json.dumps([o]))
                raw=b.getvalue();meta['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
            c=self.h.context_from_result_archive(raw,meta,verified_at='2030-03-31T04:01:00Z')
            with self.subTest(change=change):self.assertEqual(self.prepared(c)['participants'][0]['features'],{})
    def test_empty_history_and_roster_mismatch_fail_closed(self):
        p=self.prepared(self.context([]))
        self.assertEqual(p['participants'][0]['features'],{})
        self.assertEqual(p['participants'][0]['missing']['recent_mean_finish'],'NO_PRIOR_SAMPLES')
        bad=roster();bad[1]['registration_no']=bad[0]['registration_no']
        with self.assertRaises(ValueError):self.prepared(participants=bad)
    def test_conflicting_same_instant_versions_rejected(self):
        o=observation();v=copy.deepcopy(o);v['captured_at']='2030-03-31T12:00:00+09:00';v['status']='PENDING'
        with self.assertRaises(ValueError):self.prepared(self.context([o,v]))
    def test_forged_context_and_parent_receipt_membership_rejected(self):
        c=self.context();c['observations'][0]['data']['results'][0]['finish']=6
        with self.assertRaises(ValueError):self.prepared(c)
        p=self.prepared();proof=self.h.history_proof(self.context())
        for change in ('empty','digest','created_at','membership'):
            q=copy.deepcopy(proof)
            if change=='digest':q['digest']='sha256:'+'f'*64
            if change=='created_at':q['created_at']='2030-03-31T03:00:00Z'
            if change=='membership':q['observation_sha256s']=[]
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.h.validate_history_proofs(p['evidence'],{} if change=='empty' else {'88':q})
    def test_parent_verification_time_is_checked_and_not_publication_time(self):
        raw,meta=archived([observation()])
        for at in ('2030-03-31T03:00:00Z','2030-03-31T04:01:00','2030-04-01T03:00:00Z'):
            with self.subTest(at=at),self.assertRaises(ValueError):
                c=self.h.context_from_result_archive(raw,meta,verified_at=at);self.prepared(c)
    def test_only_ten_latest_unique_race_opportunities_are_counted(self):
        obs=[observation('20300331-01-'+str(i).zfill(2),captured='2030-03-31T03:'+str(i).zfill(2)+':00Z') for i in range(1,13)]
        obs+=copy.deepcopy(obs)
        p=self.prepared(self.context(obs));f=p['participants'][0]['features']['recent_mean_finish']
        self.assertEqual(f['sample_n'],10)
        self.assertEqual(f['history']['total_n'],10)
    def test_missing_official_flags_and_row_identity_never_make_numeric_features(self):
        for change in ('body','row','race','url','registration','finish','st'):
            o=observation();row=o['data']['results'][0]
            if change=='body':o['body_identity_verified']=False
            if change=='row':row['verified_official']=False
            if change=='race':row['race_id']='20300331-01-02'
            if change=='url':row['source_url']='https://example.com'
            if change=='registration':row['racer_registration_id']='9999'
            if change=='finish':row['finish']=True
            if change=='st':row['actual_st_status']='UNKNOWN'
            with self.subTest(change=change):
                p=self.prepared(self.context([o]));features=p['participants'][0]['features']
                self.assertNotIn('recent_mean_st' if change=='st' else 'recent_mean_finish',features)

class HistoryIntegrationTests(unittest.TestCase):
    def context(self):
        from race_ai.observed_result_history import context_from_result_archive
        return context_from_result_archive(*archived([observation()]),verified_at='2030-03-31T04:01:00Z')
    def bundle(self):
        from race_ai.observed_p1_connection import build_bundle
        b,e,p=inputs()
        try:return build_bundle(b,e,AT,**p,owner_reviewed=True,history_context=self.context())
        except TypeError as exc:self.fail('optional archive history input is missing: '+str(exc))
    def test_history_bundle_adds_only_existing_features_and_exact_eight_tickets(self):
        from race_ai.observed_p1_connection import verified_rows
        b=self.bundle();snap=b['snapshot']
        self.assertEqual(len(snap['sources']),3)
        self.assertEqual(snap['participants'][0]['features']['recent_mean_finish']['value'],1)
        self.assertEqual(len(b['http_provenance']),3)
        self.assertIn('history_evidence',b)
        rows=verified_rows(b,dict(id=99,created_at='2030-04-01T01:41:00Z'),'d'*64)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(len(r['top8'])==8 for r in rows))
    def test_resealed_feature_alteration_and_arbitrary_extra_source_rejected(self):
        from race_ai.observed_p1_connection import verified_rows
        from race_ai.boat_observed_pairwise_models import predict_pair
        for change in ('feature','source','raw_provenance','course','roster','omitted_latest'):
            b=self.bundle();snap=b['snapshot']
            if change=='feature':snap['participants'][0]['features']['recent_mean_finish']['value']=6
            if change=='source':snap['sources'][2]['source_sha256']='f'*64
            if change=='raw_provenance':b['http_provenance'][2]['request_url']='https://example.com'
            if change=='course':
                f=copy.deepcopy(snap['participants'][0]['features']['recent_mean_finish'])
                f['transform_id']='strict_numeric_finish_mean_v1'
                snap['participants'][0]['features']['course_mean_finish']=f
                del snap['participants'][0]['missing']['course_mean_finish']
            if change=='roster':snap['participants'][0]['registration_no']='9999'
            if change=='omitted_latest':b['history_evidence']['observations']=[];reseal(b['history_evidence'],'evidence_sha256')
            b['suite']=predict_pair(snap,allow_source=lambda *_:True);reseal(b,'bundle_sha256')
            with self.subTest(change=change),self.assertRaises(ValueError):
                verified_rows(b,dict(id=99,created_at='2030-04-01T01:41:00Z'),'d'*64)
    def test_rehashed_history_downgrade_cannot_use_legacy_sources_without_evidence(self):
        from race_ai.observed_p1_connection import verified_rows
        from race_ai.boat_observed_pairwise_models import predict_pair,FEATURE_TRANSFORMS,HISTORY_FIELDS
        for name in sorted(HISTORY_FIELDS):
            b=self.bundle();snap=b['snapshot']
            del b['history_evidence'];snap['sources']=snap['sources'][:2];b['http_provenance']=b['http_provenance'][:2]
            for row in snap['participants']:
                original=copy.deepcopy(row['features']['recent_mean_finish' if name.endswith('finish') else 'recent_mean_st'])
                for key in HISTORY_FIELDS:
                    row['features'].pop(key,None);row['missing'][key]='NO_PRIOR_SAMPLES'
                original.update(source_id=snap['sources'][0]['source_id'],transform_id=FEATURE_TRANSFORMS[name])
                row['features'][name]=original;del row['missing'][name]
            b['suite']=predict_pair(snap,allow_source=lambda *_:True);reseal(b,'bundle_sha256')
            with self.subTest(feature=name),self.assertRaisesRegex(ValueError,'history'):
                verified_rows(b,dict(id=99,created_at='2030-04-01T01:41:00Z'),'d'*64)
    def test_same_parent_reread_at_later_actual_verification_time_authenticates(self):
        from race_ai.observed_result_history import context_from_result_archive,history_proof,validate_history_proofs
        evidence=self.bundle()['history_evidence']
        reread=context_from_result_archive(*archived([observation()]),verified_at='2030-04-02T00:00:00Z')
        validate_history_proofs(evidence,{'88':history_proof(reread)})

class HistoryAdditionalRegressions(unittest.TestCase):
    setUp=HistoryTests.setUp
    context=HistoryTests.context
    prepared=HistoryTests.prepared
    def test_st_fl_missing_counts_and_finish_unknowns_are_not_filled(self):
        obs=[]
        for i,status in enumerate(('OK','F','L','MISSING'),1):
            o=observation('20300331-01-'+str(i).zfill(2),captured='2030-03-31T03:0'+str(i)+':00Z')
            if status!='OK':o['data']['results'][0].update(actual_st=None,actual_st_status=status)
            obs.append(o)
        f=self.prepared(self.context(obs))['participants'][0]['features']['recent_mean_st']
        self.assertEqual(f['history'],dict(window_id=f['history']['window_id'],total_n=4,ok_n=1,f_n=1,l_n=1,missing_n=1,unresolved_n=0))
        self.assertEqual(f['sample_n'],1)
        self.assertAlmostEqual(f['value'],.11)
    def test_latest_pending_capture_never_falls_back_to_old_positive(self):
        old=observation();new=observation(captured='2030-03-31T03:30:00Z');new.update(status='PENDING',data=None)
        self.assertEqual(self.prepared(self.context([old,new]))['participants'][0]['features'],{})
    def test_rehashed_membership_forgery_cannot_pass_independent_parent_proof(self):
        c=self.context();proof=self.h.history_proof(c)
        c['observations'][0]['data']['results'][0]['finish']=6
        c['journal_index'][0]['observation_sha256']=digest(c['observations'][0]);c['journal_sha256']=digest(c['observations'])
        c['context_sha256']=digest({k:v for k,v in c.items() if k not in ('observations','context_sha256')})
        forged=self.prepared(c)
        with self.assertRaises(ValueError):self.h.validate_history_proofs(forged['evidence'],{'88':proof})
    def test_report_seal_and_journal_count_mismatch_fail_closed(self):
        for change in ('seal','count'):
            raw,meta=archived([observation()]);b=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(raw)) as z,zipfile.ZipFile(b,'w') as out:
                report=json.loads(z.read('status.json'));report['result_observation_versions']=2
                if change=='count':reseal(report,'report_sha256')
                out.writestr('status.json',json.dumps(report));out.writestr('official-result-observations.json',z.read('official-result-observations.json'))
            raw=b.getvalue();meta['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.h.context_from_result_archive(raw,meta,verified_at='2030-03-31T04:01:00Z')
    def test_optional_none_keeps_old_bundle_bytes(self):
        from race_ai.observed_p1_connection import build_bundle
        b,e,p=inputs()
        old=build_bundle(b,e,AT,**p,owner_reviewed=True)
        explicit=build_bundle(b,e,AT,**p,owner_reviewed=True,history_context=None)
        self.assertEqual(old,explicit)
        self.assertEqual(digest(old),'41e6e8c73bd93bb77c5abe8db7f5e053703a70de4bf46a0866833eedd55f80d9')


class LegacyHistoryArchiveTests(unittest.TestCase):
    def test_sealed_legacy_report_without_day_count_keeps_authenticated_journal(self):
        from race_ai.observed_result_history import context_from_result_archive,prepare_history
        raw,meta=archived([observation()]);b=io.BytesIO();report=dict(automatic_learning={});reseal(report,'report_sha256')
        with zipfile.ZipFile(io.BytesIO(raw)) as z,zipfile.ZipFile(b,'w') as out:
            out.writestr('status.json',json.dumps(report));out.writestr('official-result-observations.json',z.read('official-result-observations.json'))
        raw=b.getvalue();meta['digest']='sha256:'+hashlib.sha256(raw).hexdigest()
        context=context_from_result_archive(raw,meta,verified_at='2030-03-31T04:01:00Z')
        p=prepare_history(context,race_id='20300401-01-01',participants=roster(),as_of=AT)
        self.assertEqual(p['participants'][0]['features']['recent_mean_finish']['value'],1)
    def test_non_ascii_registration_is_not_a_verified_registration(self):
        from race_ai.observed_result_history import context_from_result_archive,prepare_history
        c=context_from_result_archive(*archived([]),verified_at='2030-03-31T04:01:00Z')
        participants=roster();participants[0]['registration_no']='٤٠٠١'
        with self.assertRaises(ValueError):prepare_history(c,race_id='20300401-01-01',participants=participants,as_of=AT)
