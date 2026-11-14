"""Synthetic round budgets and authenticated source-control projections only."""
from copy import deepcopy
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from race_ai import boat_source_control as control
from race_ai import cycle_recovery as recovery
from race_ai import repeated_cycle as repeat
from tests import test_boat_source_control as fixtures
from tests import test_continuity_checkpoint as continuity

NOW=fixtures.NOW


def row(number,*,stage='P0',cutoff=None):
    return dict(race_id=f'20300401-{number//12+1:02d}-{number%12+1:02d}',stage=stage,
                cutoff_at=(cutoff or NOW-timedelta(minutes=10)).isoformat())


class BoundedResultAuditPriorityTests(unittest.TestCase):
    def safe_fixture(self,wait=None,reason='ROUND_SOURCE_BUDGET_EXHAUSTED'):
        helper=fixtures.SafeSourceControlTests(methodName='runTest')
        return helper.fixture(requests_used=45,lifetime_requests=49,halted_reason=reason,source_wait=wait)

    def test_raw_round_budget_stop_with_no_wait_does_not_manufacture_source_review(self):
        _,raw,meta,summary,public,public_meta=self.safe_fixture()
        self.assertIsNone(summary['control']['source_wait'])
        projected=control.read_summary(public,public_meta,raw,meta,run_id=7,head_sha=fixtures.HEAD)
        self.assertIsNone(projected['source_wait']);self.assertIsNone(projected['previous_halted_reason'])
        self.assertEqual(projected['previous_stop_reason'],'ROUND_SOURCE_BUDGET_EXHAUSTED')
        self.assertEqual((projected['previous_session_requests'],projected['lifetime_requests']),(45,49))

    def test_legacy_recovery_agrees_without_rewriting_original_control_bytes(self):
        payload=continuity.session(requests_used=45,completed_round=1,prepared_round=None,
            lifetime_requests=445,lifetime_completed_rounds=56,halted_reason='ROUND_SOURCE_BUDGET_EXHAUSTED',source_wait=None)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:archive.writestr('repeat-session.json',payload)
        raw=output.getvalue();metadata=fixtures.metadata(raw,'race-cycle-continuity-7',70);before=bytes(raw)
        value=recovery.authenticated_source_control(raw,metadata,expected_run=7,now=NOW)
        self.assertIsNone(value['source_wait']);self.assertIsNone(value['previous_halted_reason'])
        self.assertEqual(value['previous_stop_reason'],'ROUND_SOURCE_BUDGET_EXHAUSTED');self.assertEqual(raw,before)

    def test_actual_denials_retry_after_and_review_waits_survive_round_stop(self):
        waits=[repeat.plan_http_wait(403,{},NOW),repeat.plan_http_wait(429,{'Retry-After':'600'},NOW),
               dict(state='SOURCE_REVIEW_WAIT',reason='SOURCE_VERIFICATION_REQUIRED',retry_at=None,http_status=None,attempts=2)]
        for wait in waits:
            _,raw,meta,_,public,public_meta=self.safe_fixture(wait)
            with self.subTest(wait=wait):
                out=control.read_summary(public,public_meta,raw,meta,run_id=7,head_sha=fixtures.HEAD)
                self.assertEqual(out['source_wait'],wait);self.assertTrue(repeat.wait_active(out['source_wait'],NOW))

    def test_due_priority_never_advances_cutoffs_cooldowns_or_settled_rechecks(self):
        old=row(3);target=row(4,stage='P1',cutoff=NOW-timedelta(minutes=3));future=row(5,stage='P1',cutoff=NOW+timedelta(minutes=2))
        rows=[old,target,future,deepcopy(target)];before=deepcopy(rows)
        priority={target['race_id'],future['race_id']}
        due=recovery.due_rows(rows,[],NOW,priority_races=priority)
        self.assertEqual([x['race_id'] for x in due],[target['race_id'],old['race_id']]);self.assertEqual(rows,before)
        observed=dict(race_id=target['race_id'],captured_at=(NOW-timedelta(minutes=1)).isoformat(),data=None)
        self.assertEqual([r['race_id'] for r in recovery.due_rows(rows,[observed],NOW,priority_races=priority)],[old['race_id']])
        observed.update(captured_at=(NOW-timedelta(hours=7)).isoformat(),data=dict(confirmed=True,status='settled'))
        self.assertEqual([r['race_id'] for r in recovery.due_rows(rows,[observed],NOW,priority_races=priority)],[old['race_id'],target['race_id']])

    def test_nineteen_plus_one_plus_twentyfive_completes_and_next_round_polls_new_due_p1_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'session.json';moment=[NOW]
            repeat.start(path,day='2030-04-01',run_id=77,now=NOW);repeat.prepare(path,1,now=NOW)
            guard=repeat.SourceGuard(path,clock=lambda:moment[0])
            for _ in range(20):guard.charge('forecast')
            backlog=[row(n+12) for n in range(60)]
            targets=[row(0,stage='P1',cutoff=NOW+timedelta(minutes=5)),row(1,stage='P1',cutoff=NOW+timedelta(minutes=11))]
            rows=backlog+targets;priority={r['race_id'] for r in targets}
            budget=recovery.result_request_budget(repeat.load(path),NOW)
            due=recovery.due_rows(rows,[],NOW,priority_races=priority,limit=budget)
            self.assertEqual((budget,len(due)),(25,25))
            for _ in due:guard.charge('result')
            state=repeat.load(path);self.assertEqual(state['requests_used'],45);self.assertIsNone(state['halted_reason'])
            repeat.complete(path,1,now=NOW,forecast_artifact=101,result_artifact=102)
            moment[0]=NOW+timedelta(minutes=20)
            self.assertTrue(repeat.prepare(path,2,now=moment[0])['active'])
            state=repeat.load(path);budget=recovery.result_request_budget(state,moment[0]);self.assertEqual(budget,45)
            due=recovery.due_rows(rows,[],moment[0],priority_races=priority,limit=budget)
            self.assertEqual([r['race_id'] for r in due[:2]],[r['race_id'] for r in targets])
            for _ in due:guard.charge('result')
            self.assertEqual(repeat.load(path)['requests_used'],90)

    def test_budget_preserves_exhausted_sessions_real_waits_and_total_ceiling(self):
        state=dict(requests_used=239,round_started_requests=235,prepared_round=1,halted_reason=None,source_wait=None)
        before=deepcopy(state);self.assertEqual(recovery.result_request_budget(state,NOW),1);self.assertEqual(state,before)
        for change in (dict(requests_used=240),dict(halted_reason='ROUND_SOURCE_BUDGET_EXHAUSTED'),
                       dict(source_wait=repeat.plan_http_wait(403,{},NOW))):
            with self.subTest(change=change):self.assertEqual(recovery.result_request_budget(dict(state,**change),NOW),0)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.json';repeat.start(path,day='2030-04-01',run_id=77,now=NOW);repeat.prepare(path,1,now=NOW)
            guard=repeat.SourceGuard(path,clock=lambda:NOW)
            for _ in range(45):guard.charge('result')
            with self.assertRaisesRegex(ValueError,'ROUND_SOURCE_BUDGET_EXHAUSTED'):guard.charge('result')
            original=path.read_bytes();self.assertEqual(recovery.result_request_budget(repeat.load(path),NOW),0)
            self.assertFalse(repeat.prepare(path,2,now=NOW+timedelta(minutes=5))['active']);self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
