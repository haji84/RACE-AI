"""Synthetic manifests exercise evidence consistency, not genuine running services."""
import unittest
from datetime import datetime, timezone, timedelta
from race_ai.boat_day_acceptance import assess

D='2030-11-03'; H='a'*64; S='b'*64

def stamp(minutes):
    return (datetime(2030,11,3,8,tzinfo=timezone(timedelta(hours=9)))+timedelta(minutes=minutes)).isoformat()

def fixture():
    sched={f'20301103-17-{i+1:02}':stamp(10+10*i) for i in range(12)}
    rows=[]
    def f(role,sha,rid,at):
        versions={'A':'boat-display-rating-PL-reference-v1-UNVALIDATED','B':'boat-course-motor-shadow-v0.1-UNTRAINED','K_TACTICAL':'boat-course-entry-method-scenarios-v0.1-UNTRAINED'}
        return {'model':role,'race_id':rid,'saved':at,'generated':at,'sha':sha,'observation':H,'receipt':S,'version':versions[role]}
    for i,rid in enumerate(sched):
        at=stamp(6+10*i); k=f('K_TACTICAL','c'*64,rid,at)
        k.update(history=H,history_captured=stamp(-20),last_k_day='2030-11-02',comparison={'A':H,'B':S,'K':'c'*64,'result':S,'receipt':S})
        rows.append({'id':rid,'exhibition_at':stamp(5+10*i),'exhibition_sha':H,'reason':None,'attempts':[],'result':{'at':stamp(13+10*i),'state':'SETTLED','sha':S,'race_id':rid},'ab':[f('A',H,rid,at),f('B',S,rid,at)],'k':k})
    return {'date':D,'venues':['17'],'schedule':sched,'schedule_receipt':H,'first_exhibition':stamp(0),'first_exhibition_receipt':S,'start':stamp(-1),'stop':stamp(125),'trigger':'AUTOMATIC','trace_receipt':H,'heartbeats':[stamp(i) for i in range(-1,126)],'manual_restarts':0,'rows':rows,'close_sha':H,'replay':{'ran_at':'2030-11-04T07:00:00+09:00','private_readback_sha':S,'archive_sha':S,'report_sha':H,'receipt':H,'owner_only':True}}

class Gate(unittest.TestCase):
    def test_consistent(self): self.assertEqual(assess(fixture())['status'],'EVIDENCE_CONSISTENT')
    def test_no_late_start_manual_restart_or_heartbeat_gap(self):
        for change in [lambda x:x.update(start=stamp(3)),lambda x:x.update(manual_restarts=1),lambda x:x.update(heartbeats=[stamp(-1),stamp(125)]),lambda x:x.update(stop=stamp(110))]:
            x=fixture();change(x);self.assertNotEqual(assess(x)['status'],'EVIDENCE_CONSISTENT')
    def test_explained_miss_differs_from_perfect_coverage(self):
        x=fixture();r=x['rows'][4];r.update(ab=[],k=None,reason='SOURCE_UNAVAILABLE',attempts=[{'at':stamp(48),'reason':'SOURCE_UNAVAILABLE','receipt':H}]);o=assess(x);self.assertEqual(o['status'],'EVIDENCE_CONSISTENT');self.assertFalse(o['all_normal_forecasted']);r['attempts']=[];self.assertNotEqual(assess(x)['status'],'EVIDENCE_CONSISTENT')
    def test_k_late_mixed_or_leaked_is_not_k(self):
        for change in [lambda k:k.update(saved=stamp(15)),lambda k:k.update(model='C_LITE'),lambda k:k.update(last_k_day=D),lambda k:k.update(history_captured=stamp(9))]:
            x=fixture();change(x['rows'][0]['k']);self.assertNotEqual(assess(x)['status'],'EVIDENCE_CONSISTENT')
    def test_each_forecast_follows_its_own_exhibition(self):
        x=fixture();x['rows'][1]['exhibition_at']=stamp(19);self.assertFalse(assess(x)['operations_ok'])
    def test_k_comparison_cannot_point_at_other_forecast(self):
        x=fixture();x['rows'][0]['k']['comparison']['K']=S;self.assertFalse(assess(x)['k_comparison_ok'])
    def test_same_day_replay_mismatch_and_pending(self):
        x=fixture();x['replay']['ran_at']=stamp(140);self.assertFalse(assess(x)['next_day_ok']);x=fixture();x['replay']['report_sha']=S;self.assertFalse(assess(x)['next_day_ok']);x=fixture();x['rows'][0]['result']['state']='PENDING';self.assertFalse(assess(x)['operations_ok'])
    def test_no_partial_comparison_or_duplicate_slot(self):
        x=fixture();x['rows'][1]['ab'].pop();self.assertFalse(assess(x)['operations_ok']);x=fixture();x['rows'][-1]=x['rows'][0];self.assertNotEqual(assess(x)['status'],'EVIDENCE_CONSISTENT')
