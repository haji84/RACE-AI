"""Real GitHub workflow_run completion should restart only authenticated BOAT owner.

Synthetic GitHub event/API fixtures, no provider GET, AES keys or dispatch.
"""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import base64
import io
import json
import os
import tempfile
import unittest

from scripts import boat_recovery_dispatch_gate as launcher
from scripts import boat_main_dispatch_gate as base

NOW = datetime(2030, 4, 1, 2, 35, tzinfo=timezone.utc)
DAY = "2030-04-01"


def source_control():
    run = dict(id=9901, name=base.WORKFLOW, event="workflow_dispatch",
               head_branch=base.RELEASE_REF, head_sha=base.RELEASE_SHA,
               status="completed", conclusion="success",
               created_at="2030-04-01T01:50:00Z")
    control = dict(previous_run_id=9901,day_jst=DAY,
                   prepared_round=None,source_wait=None,
                   previous_halted_reason=None,previous_stop_reason="WORKER_HANDOFF",
                   previous_session_requests=310,completed_round=24,
                   lifetime_requests=310,day_start_lifetime_requests=0,
                   receipt=dict(id=7101,digest="sha256:"+"a"*64,
                                created_at="2030-04-01T02:20:00Z"),
                   source_control_receipt=dict(id=7102,digest="sha256:"+"b"*64,
                                               created_at="2030-04-01T02:20:01Z"))
    return run, control


def event(run):
    return dict(action="completed", workflow_run=dict(run,
        repository=dict(full_name=base.REPO),
        head_repository=dict(full_name=base.REPO)))


class OwnerCompletionTriggerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.run,self.control=source_control()
        self.history=dict(total_count=1,workflow_runs=[deepcopy(self.run)])
        self.eventpath=self.folder/"event.json"
        self.eventpath.write_text(json.dumps(event(self.run)))
        self.env=dict(GITHUB_ACTIONS="true",GITHUB_EVENT_NAME="workflow_run",
                      GITHUB_REPOSITORY=base.REPO,GITHUB_REF="refs/heads/main",
                      GITHUB_EVENT_PATH=str(self.eventpath))

    def trusted(self, doc=None, hist=None, env=None):
        if doc is not None:self.eventpath.write_text(json.dumps(doc))
        return launcher.trusted_owner_completion(
            self.history if hist is None else hist, NOW,
            env=self.env if env is None else env)

    def test_authentic_owner_completion_is_recognized(self):
        self.assertTrue(self.trusted())

    def test_reviewed_previous_release_completion_is_bound_to_the_actual_history(self):
        for previous in ('84128e0ec8bd9fe3da64ad49f74b8511b07e72be',
                         'b491fb21ce58ba085dd8f54bb7326442b840d8f4',
                         'eff296f6d54ad4be297d93e32f1ee0d4592ad9e3',
                         '86b029ae5bddd5d4956497d8b32b2c92b8eec521',
                         'f55351dce855177a51330f72c37d6238ba2c9e3e'):
            with self.subTest(previous=previous):
                actual=dict(self.run,head_sha=previous)
                history=dict(total_count=1,workflow_runs=[actual])
                with patch.object(base,'RELEASE_SHA','e'*40):
                    self.assertTrue(self.trusted(event(actual),hist=history))
                    actual=dict(actual,head_sha='f'*40)
                    self.assertFalse(self.trusted(event(actual),hist=dict(total_count=1,workflow_runs=[actual])))

    def test_exact_eff_completion_selects_new_release_without_rewriting_control(self):
        self._assert_previous_completion_selects_current('eff296f6d54ad4be297d93e32f1ee0d4592ad9e3')

    def test_exact_m2_completion_selects_new_release_without_rewriting_control(self):
        self._assert_previous_completion_selects_current('86b029ae5bddd5d4956497d8b32b2c92b8eec521')

    def test_exact_f553_completion_selects_new_release_without_rewriting_control(self):
        self._assert_previous_completion_selects_current('f55351dce855177a51330f72c37d6238ba2c9e3e')

    def _assert_previous_completion_selects_current(self,previous):
        current=base.RELEASE_SHA
        self.assertNotEqual(current,previous)
        run=dict(self.run,head_sha=previous)
        original=deepcopy(self.control)
        original.update(completed_round=13,previous_session_requests=485,
            lifetime_requests=13503,day_start_lifetime_requests=13017,lifetime_completed_rounds=720)
        args=dict(now=NOW,release=dict(ref='refs/heads/'+base.RELEASE_REF,object=dict(sha=current)),
            owner_doc=dict(encoding='base64',content=base64.b64encode(base.RELEASE_TOKEN.encode()).decode()),
            history=dict(total_count=1,workflow_runs=[run]),continuation_proof=original)
        before=deepcopy(args)
        with patch.object(base,'RELEASE_SHA',current):
            self.assertTrue(self.trusted(event(run),hist=args['history']))
            result=launcher.decide(**args)
            self.assertTrue(result['dispatch_allowed'])
            self.assertEqual(result['release_sha'],current)
            self.assertEqual(args,before)
            for change in (
                dict(release=dict(ref='refs/heads/'+base.RELEASE_REF,object=dict(sha=previous))),
                dict(continuation_proof=None),
                dict(continuation_proof=dict(original,lifetime_requests=0)),
                dict(continuation_proof=dict(original,day_start_lifetime_requests=13504)),
                dict(history=dict(total_count=1,workflow_runs=[dict(run,status='in_progress')])),
                dict(history=dict(total_count=1,workflow_runs=[dict(run,head_sha='f'*40)])),
            ):
                with self.subTest(change=change):
                    self.assertFalse(launcher.decide(**dict(args,**change))['dispatch_allowed'])

    def test_day_handoff_is_not_same_day_continuation_and_next_day_keeps_early_window(self):
        run=dict(self.run,head_sha='86b029ae5bddd5d4956497d8b32b2c92b8eec521')
        control=deepcopy(self.control)
        control.update(completed_round=10,previous_session_requests=304,
            lifetime_requests=13807,day_start_lifetime_requests=13017,
            lifetime_completed_rounds=730,previous_stop_reason='DAY_HANDOFF')
        args=dict(now=NOW,release=dict(ref='refs/heads/'+base.RELEASE_REF,object=dict(sha=base.RELEASE_SHA)),
            owner_doc=dict(encoding='base64',content=base64.b64encode(base.RELEASE_TOKEN.encode()).decode()),
            history=dict(total_count=1,workflow_runs=[run]),continuation_proof=control)
        before=deepcopy(args)
        out=launcher.decide(**args)
        self.assertEqual(out['status'],'HOLD_ALREADY_DISPATCHED_FOR_JST_DAY')
        self.assertFalse(out['dispatch_allowed'])
        midnight=NOW.replace(hour=15,minute=15,second=0,microsecond=0)
        out=launcher.decide(**dict(args,now=midnight))
        self.assertEqual(out['status'],'HOLD_OUTSIDE_OWNER_DAYTIME_WINDOW')
        self.assertFalse(out['dispatch_allowed'])
        active=dict(run,status='in_progress',conclusion=None)
        out=launcher.decide(**dict(args,now=midnight,
            history=dict(total_count=1,workflow_runs=[active])))
        self.assertEqual(out['status'],'HOLD_ACTIVE_OWNER_WORKFLOW')
        self.assertFalse(out['dispatch_allowed'])
        self.assertEqual(args,before)

    def test_existing_release_push_context_is_genuine_and_bound_to_actual_main_sha(self):
        sha='e'*40
        self.eventpath.write_text(json.dumps(dict(ref='refs/heads/main', after=sha,
            repository=dict(id=1416489937,full_name=base.REPO),head_commit=dict(
                id=sha,message='boat-owner-release: single-real-session-20261111 | retained orphan'))))
        env=dict(self.env,GITHUB_EVENT_NAME='push',GITHUB_SHA=sha,
            GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/boat-racer-daily.yml@refs/heads/main')
        self.assertTrue(launcher.trusted_release_push(env=env))
        for change in (dict(GITHUB_EVENT_NAME='workflow_dispatch'),dict(GITHUB_SHA='f'*40),
                       dict(GITHUB_REF='refs/heads/other'),dict(GITHUB_WORKFLOW_REF='other')):
            with self.subTest(change=change):
                self.assertFalse(launcher.trusted_release_push(env=dict(env,**change)))
        document=json.loads(self.eventpath.read_text())
        document['head_commit']['message']='ordinary update'
        self.eventpath.write_text(json.dumps(document))
        self.assertFalse(launcher.trusted_release_push(env=env))

    def test_owner_release_push_requires_both_real_path_filter_and_exact_prefix(self):
        import fnmatch,re
        from types import SimpleNamespace as NS
        source=(Path(__file__).resolve().parents[1]/'.github/workflows/boat-racer-daily.yml').read_text()
        header=source.split('\njobs:\n',1)[0]
        push=header.split('\n  push:\n',1)[1].split('\n  workflow_run:\n',1)[0]
        patterns=[value.strip() for value in re.search(r'paths:\s*\[([^]]+)\]',push)[1].split(',')]
        self.assertIn('branches: [main]',push)
        marker='docs/evidence/owner-pdca-main-trigger.txt'
        self.assertIn(marker,patterns)
        owner=source.split('\n  owner_p0_p1_dispatch:\n',1)[1].split('    runs-on:',1)[0]
        expression=' '.join(owner.split('    if: >-\n',1)[1].split())
        expression=expression.replace('&&',' and ').replace('||',' or ')
        prefix='boat-owner-release: single-real-session-20261111'
        for message,changed,branch,expected in (
            (prefix+' | exact reviewed release',[marker],'main',True),
            (prefix+' | exact reviewed release',['scripts/boat_main_dispatch_gate.py'],'main',False),
            ('racer-intraday-refresh: stage-model-pdca authenticated source handoff',[marker],'main',False),
            ('ordinary update',[marker],'main',False),
            (prefix+' | exact reviewed release',[marker],'other',False),
        ):
            github=NS(repository=base.REPO,ref='refs/heads/'+branch,event_name='push',
                event=NS(head_commit=NS(message=message)))
            admitted=eval(expression,{'__builtins__':{}},
                dict(github=github,startsWith=lambda value,start:value.startswith(start)))
            push_matches=branch=='main' and any(fnmatch.fnmatchcase(path,pattern)
                for path in changed for pattern in patterns)
            with self.subTest(message=message,changed=changed,branch=branch):
                self.assertEqual(bool(push_matches and admitted),expected)

    def test_current_release_is_recorded_in_the_existing_push_trigger_marker(self):
        marker=(Path(__file__).resolve().parents[1]/'docs/evidence/owner-pdca-main-trigger.txt').read_text()
        self.assertTrue(base.RELEASE_SHA in marker,
            'A source pin update must append the actual release to the existing push-filtered marker.')
        self.assertIn('boat-owner-release: single-real-session-20261111',marker)

    def test_untrusted_pr_foreign_head_and_denials_remain_closed(self):
        for field,invalid in (
            ("head_sha","0"*40),("head_branch","main"),
            ("event","pull_request"),("conclusion","cancelled"),
            ("status","in_progress"),("id",1)):
            bad=event(self.run)
            bad["workflow_run"][field]=invalid
            with self.subTest(field=field):
                self.assertFalse(self.trusted(bad))
        for bad in (dict(event(self.run),action="requested"),
                    dict(event(self.run),workflow_run=dict(event(self.run)["workflow_run"],
                          head_repository=dict(full_name="other/repo"))),
                    dict(event(self.run),workflow_run=dict(event(self.run)["workflow_run"],
                          repository=dict(full_name="other/repo")))):
            self.assertFalse(self.trusted(bad))
        self.assertFalse(self.trusted(event(self.run),env=dict(self.env,GITHUB_EVENT_NAME="pull_request")))
        self.assertFalse(self.trusted(event(self.run),env=dict(self.env,GITHUB_ACTIONS="false")))

    def test_live_api_run_must_match_event_exactly_and_be_latest_today(self):
        bad=deepcopy(self.history);bad["workflow_runs"][0]["head_sha"]="0"*40
        self.assertFalse(self.trusted(hist=bad))
        bad=deepcopy(self.history);bad["workflow_runs"][0]["conclusion"]="failure"
        self.assertFalse(self.trusted(hist=bad))
        bad=deepcopy(self.history);bad["workflow_runs"]=[]
        self.assertFalse(self.trusted(hist=bad))
        newer=dict(self.run,id=9902,created_at="2030-04-01T02:22:00Z")
        bad=dict(total_count=2,workflow_runs=[newer,self.run])
        self.assertFalse(self.trusted(hist=bad))

    def test_bad_event_bytes_symlink_and_prior_day_hold(self):
        self.eventpath.write_text("{not json")
        self.assertFalse(self.trusted())
        self.eventpath.write_text("x"*1048577)
        self.assertFalse(self.trusted())
        self.eventpath.unlink()
        self.eventpath.symlink_to(self.folder/"safe.json")
        self.assertFalse(self.trusted())
        self.eventpath.unlink()
        old=dict(self.run,created_at="2030-03-31T14:50:00Z")
        self.assertFalse(self.trusted(event(old)))

    def test_authenticated_workflow_completion_uses_pinned_reader_then_admits_successor(self):
        output=self.folder/"github-output"
        output.write_text("")
        release=self.folder/"release.json"
        release.write_text(json.dumps(dict(ref="refs/heads/"+base.RELEASE_REF,
                                           object=dict(sha=base.RELEASE_SHA))))
        policy=self.folder/"owner.json"
        policy.write_text(json.dumps(dict(encoding="base64",content=base64.b64encode(
            base.RELEASE_TOKEN.encode()).decode())))
        listing=self.folder/"history.json"
        listing.write_text(json.dumps(self.history))
        with patch.dict(os.environ,self.env,clear=True),patch.object(
             launcher,"read_pinned_control",return_value=self.control) as read,redirect_stdout(io.StringIO()) as out:
            code=launcher.main(["--release",str(release),"--owner-doc",str(policy),
                                "--history",str(listing),"--verify-source-handoff",
                                "--github-output",str(output)],now=NOW)
        self.assertEqual(code,0)
        read.assert_called_once()
        self.assertIn("ready=true",output.read_text())
        result=json.loads(out.getvalue())
        self.assertEqual(result["status"],"READY_VERIFIED_SAME_DAY_CONTINUATION")
        self.assertEqual(result["official_source_requests"],0)

    def test_failed_real_owner_event_requests_aes_repair_not_blind_relaunch(self):
        failed=dict(self.run,conclusion="failure")
        recorded=dict(total_count=1,workflow_runs=[failed])
        self.assertTrue(self.trusted(event(failed),hist=recorded))
        decision=launcher.decide(
            now=NOW,release=dict(ref="refs/heads/"+base.RELEASE_REF,
                                 object=dict(sha=base.RELEASE_SHA)),
            owner_doc=dict(encoding="base64",content=base64.b64encode(
                base.RELEASE_TOKEN.encode()).decode()),
            history=recorded,continuation_proof=None)
        self.assertFalse(decision["dispatch_allowed"])
        self.assertTrue(decision["recovery_required"])

    def test_duplicate_api_ids_and_untrusted_main_ref_hold(self):
        duplicate=dict(total_count=2,workflow_runs=[dict(self.run),dict(self.run)])
        self.assertFalse(self.trusted(hist=duplicate))
        self.assertFalse(self.trusted(env=dict(self.env,GITHUB_REF="refs/heads/other")))

    def test_trigger_does_not_admit_successor_without_physical_control(self):
        self.assertTrue(self.trusted())
        # This is the same gate used by the CLI after the trusted event.
        result=launcher.decide(now=NOW,release=dict(ref="refs/heads/"+base.RELEASE_REF,
                                object=dict(sha=base.RELEASE_SHA)),
                               owner_doc=dict(encoding="base64",content=base64.b64encode(
                                   base.RELEASE_TOKEN.encode()).decode()),
                               history=self.history,continuation_proof=None)
        self.assertFalse(result["dispatch_allowed"])

    def test_main_owner_job_listens_to_completed_authentic_producer_only(self):
        source=(Path(__file__).resolve().parents[1]/".github/workflows/boat-racer-daily.yml").read_text()
        job=source.split("  owner_p0_p1_dispatch:\n",1)[1]
        self.assertIn("github.event_name == 'workflow_run'",job)
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'",job)
        self.assertIn("github.event.workflow_run.head_sha == '"+base.RELEASE_SHA+"'",job)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository",job)
        self.assertIn("github.event.workflow_run.conclusion == 'failure'",job)
        self.assertIn("github.event.workflow_run.conclusion == 'success'",job)
        self.assertIn("--verify-source-handoff",job)
        self.assertIn("group: boat-main-launcher-source-free",job)
        self.assertIn('ref: '+base.RELEASE_SHA+'\n          path: boat-owner-reader',job)
        self.assertIn('--expected-head '+base.RELEASE_SHA,job)
        dispatch=job.split('- name: Dispatch only the existing owner P0/P1 workflow',1)[1]
        self.assertIn('--ref production/boat-p0-p1-20261111',dispatch)
        self.assertNotIn('--ref '+base.RELEASE_SHA,dispatch)

    def test_actual_completion_gates_preserve_exact_current_and_eff_sources(self):
        import re
        from types import SimpleNamespace as NS
        source=(Path(__file__).resolve().parents[1]/'.github/workflows/boat-racer-daily.yml').read_text()
        heads={base.RELEASE_SHA,'eff296f6d54ad4be297d93e32f1ee0d4592ad9e3',
               '86b029ae5bddd5d4956497d8b32b2c92b8eec521',
               'f55351dce855177a51330f72c37d6238ba2c9e3e',
               'f1f8ed4ffb2a29e6b702685f49de63918610479d',
               'c979aeb678538d99e277f26726047dccbdc982af'}
        for job in ('original_retention','source_mirror','daily','owner_p0_p1_dispatch'):
            section=source.split('\n  '+job+':\n',1)[1].split('    runs-on:',1)[0]
            expression=' '.join(section.split('    if: >-\n',1)[1].split())
            expression=expression.replace('&&',' and ').replace('||',' or ')
            expression=re.sub(r'!(?!=)',' not ',expression).strip()
            for head in sorted(heads|{'f'*40}):
                github=NS(repository=base.REPO,ref='refs/heads/main',event_name='workflow_run',
                    event=NS(workflow_run=NS(event='workflow_dispatch',name=base.WORKFLOW,
                        head_repository=NS(full_name=base.REPO),head_branch=base.RELEASE_REF,
                        head_sha=head,conclusion='success')))
                needs=NS(original_readback=NS(result='success'),original_reconcile=NS(result='success'),
                         source_mirror=NS(result='success'))
                context=dict(github=github,needs=needs,cancelled=lambda:False,
                    contains=lambda values,value:value in values,fromJSON=json.loads,
                    startsWith=lambda value,prefix:value.startswith(prefix))
                with self.subTest(job=job,head=head):
                    self.assertEqual(bool(eval(expression,{'__builtins__':{}},context)),head in heads)



    @patch.object(base,'RELEASE_SHA','a74f1e940e7fc0852e63938f8138bdb58bd93163')
    def test_actual_protected_a74_is_the_only_current_dispatch_release(self):
        protected='a74f1e940e7fc0852e63938f8138bdb58bd93163'
        run=dict(self.run,head_sha=protected)
        control=deepcopy(self.control)
        control.update(completed_round=13,previous_session_requests=485,
            lifetime_requests=13503,day_start_lifetime_requests=13017,
            lifetime_completed_rounds=720)
        args=dict(now=NOW,release=dict(ref='refs/heads/'+base.RELEASE_REF,
            object=dict(sha=protected)),
            owner_doc=dict(encoding='base64',content=base64.b64encode(
                base.RELEASE_TOKEN.encode()).decode()),
            history=dict(total_count=1,workflow_runs=[run]),continuation_proof=control)
        before=deepcopy(args)
        decision=launcher.decide(**args)
        self.assertTrue(decision['dispatch_allowed'])
        self.assertEqual(decision['release_sha'],protected)
        self.assertEqual(args,before)
        for previous in ('bb49215034b779ea1493b35dd91e5c3ebfc04032','f'*40):
            with self.subTest(release=previous):
                refused=launcher.decide(**dict(args,release=dict(
                    ref='refs/heads/'+base.RELEASE_REF,object=dict(sha=previous))))
                self.assertFalse(refused['dispatch_allowed'])
                self.assertEqual(refused['status'],'HOLD_RELEASE_SHA_MISMATCH')

    def test_exact_bb_completion_selects_new_release_without_rewriting_control(self):
        self._assert_previous_completion_selects_current(
            'bb49215034b779ea1493b35dd91e5c3ebfc04032')

    @patch.object(base,'RELEASE_SHA','a74f1e940e7fc0852e63938f8138bdb58bd93163')
    def test_actual_a74_does_not_bypass_an_active_bb_owner(self):
        run=dict(self.run,head_sha='bb49215034b779ea1493b35dd91e5c3ebfc04032',
                 status='in_progress',conclusion=None)
        args=dict(now=NOW,release=dict(ref='refs/heads/'+base.RELEASE_REF,
            object=dict(sha='a74f1e940e7fc0852e63938f8138bdb58bd93163')),
            owner_doc=dict(encoding='base64',content=base64.b64encode(
                base.RELEASE_TOKEN.encode()).decode()),
            history=dict(total_count=1,workflow_runs=[run]),continuation_proof=None)
        before=deepcopy(args)
        decision=launcher.decide(**args)
        self.assertFalse(decision['dispatch_allowed'])
        self.assertEqual(decision['status'],'HOLD_ACTIVE_OWNER_WORKFLOW')
        self.assertEqual(args,before)

    def test_all_existing_completion_gates_keep_exact_bb_after_the_new_release(self):
        with patch.object(base,'RELEASE_SHA','bb49215034b779ea1493b35dd91e5c3ebfc04032'):
            self.test_actual_completion_gates_preserve_exact_current_and_eff_sources()

    def test_actual_research_cache_merge_is_the_only_current_dispatch_release(self):
        protected='995ef00a2ffb98a0161e1875d7d2a33145367b40'
        run=dict(self.run,head_sha=protected)
        control=deepcopy(self.control)
        control.update(completed_round=13,previous_session_requests=485,
            lifetime_requests=13503,day_start_lifetime_requests=13017,
            lifetime_completed_rounds=720)
        args=dict(now=NOW,release=dict(ref='refs/heads/'+base.RELEASE_REF,
            object=dict(sha=protected)),
            owner_doc=dict(encoding='base64',content=base64.b64encode(
                base.RELEASE_TOKEN.encode()).decode()),
            history=dict(total_count=1,workflow_runs=[run]),continuation_proof=control)
        before=deepcopy(args)
        decision=launcher.decide(**args)
        self.assertTrue(decision['dispatch_allowed'])
        self.assertEqual(decision['release_sha'],protected)
        self.assertEqual(args,before)
        for previous in ('c979aeb678538d99e277f26726047dccbdc982af','f1f8ed4ffb2a29e6b702685f49de63918610479d','a74f1e940e7fc0852e63938f8138bdb58bd93163','bb49215034b779ea1493b35dd91e5c3ebfc04032','f'*40):
            with self.subTest(release=previous):
                refused=launcher.decide(**dict(args,release=dict(
                    ref='refs/heads/'+base.RELEASE_REF,object=dict(sha=previous))))
                self.assertFalse(refused['dispatch_allowed'])
                self.assertEqual(refused['status'],'HOLD_RELEASE_SHA_MISMATCH')

    def test_exact_a74_completion_selects_research_cache_release_without_rewriting_control(self):
        self._assert_previous_completion_selects_current('a74f1e940e7fc0852e63938f8138bdb58bd93163')

    def test_research_cache_release_keeps_active_a74_and_bb_owners_closed(self):
        for owner in ('a74f1e940e7fc0852e63938f8138bdb58bd93163',
                      'bb49215034b779ea1493b35dd91e5c3ebfc04032'):
            with self.subTest(owner=owner):
                run=dict(self.run,head_sha=owner,status='in_progress',conclusion=None)
                args=dict(now=NOW,release=dict(ref='refs/heads/'+base.RELEASE_REF,
                    object=dict(sha='995ef00a2ffb98a0161e1875d7d2a33145367b40')),
                    owner_doc=dict(encoding='base64',content=base64.b64encode(
                        base.RELEASE_TOKEN.encode()).decode()),
                    history=dict(total_count=1,workflow_runs=[run]),continuation_proof=None)
                before=deepcopy(args)
                decision=launcher.decide(**args)
                self.assertFalse(decision['dispatch_allowed'])
                self.assertEqual(decision['status'],'HOLD_ACTIVE_OWNER_WORKFLOW')
                self.assertEqual(args,before)

    def test_all_existing_completion_gates_keep_exact_a74_after_research_cache_release(self):
        with patch.object(base,'RELEASE_SHA','a74f1e940e7fc0852e63938f8138bdb58bd93163'):
            self.test_actual_completion_gates_preserve_exact_current_and_eff_sources()


if __name__=="__main__":
    unittest.main()
