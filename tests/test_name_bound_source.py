"""Real source parsers, memory store and bounded transport seams; no GET."""
import copy
from datetime import timedelta
import importlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError
from tests.test_name_bound_inputs import fixture, bodies, NOW
from race_ai import official_observation_store as memory
from race_ai.tokuyama_day_worker import FetchResponse

ROOT=Path(__file__).resolve().parents[1]
def reviews():
    values = (json.loads((ROOT/'config/operator-official-facts.json').read_text(encoding='utf-8')),
        json.loads((ROOT/'config/operator-exhibition-media.json').read_text(encoding='utf-8')))
    for value in values:value['reviewed_at']=(NOW-timedelta(hours=1)).isoformat()
    return values

class SourceTests(unittest.TestCase):
    def setUp(self):
        try:self.c=importlib.import_module('race_ai.name_bound_exhibition_source')
        except ModuleNotFoundError:self.c=None
        self.assertIsNotNone(self.c,'bounded name-bound source worker required')
        self.race,self.base,self.binding=fixture();self.calls=[]
    def collect(self,raws=None,clocks=None,failure=None,execute=True,**kw):
        raw,first,second=raws or bodies();ticks=iter(clocks) if clocks else None
        def transport(url,**options):
            self.calls.append((url,options))
            if failure:raise failure
            body=raw if 'beforeinfo' in url else first if '/txt/' in url else second
            return FetchResponse(body,url,200,'text/html' if 'beforeinfo' in url else 'text/plain')
        facts,media=reviews()
        with patch.object(memory,'utc_now',return_value=kw.pop('saved_at',NOW)):
            return self.c.collect_name_bound_inputs(self.race,self.base,self.binding,parents_read_at=kw.pop('parents_read_at',NOW-timedelta(seconds=60)),facts_review=kw.pop('facts_review',facts),media_review=kw.pop('media_review',media),execute=execute,transport_update=transport,transport_original=transport,clock=(lambda:next(ticks)) if ticks else (lambda:NOW),**kw)
    def test_dry_run_has_no_requests(self):
        self.assertEqual(self.collect(execute=False),dict(status='DRY_RUN',official_source_requests=0));self.assertEqual(self.calls,[])
    def test_three_exact_requests_capture_after_response_and_preserve_raw_b(self):
        old=copy.deepcopy((self.race,self.base,self.binding))
        ticks=[NOW+timedelta(milliseconds=n*100) for n in range(20)]
        result=self.collect(clocks=ticks,saved_at=NOW+timedelta(milliseconds=250))
        self.assertEqual(result['status'],'COLLECTED');self.assertEqual(result['official_source_requests'],3)
        self.assertEqual([x[1] for x in self.calls],[dict(timeout=10,max_bytes=1048576),dict(timeout=15,max_bytes=1048576),dict(timeout=15,max_bytes=1048576)])
        packet=result['snapshot'];self.assertGreater(packet['beforeinfo_record']['captured_at'],self.c.facts.stamp(NOW))
        self.assertEqual(packet['beforeinfo_record']['saved_at'],self.c.facts.stamp(NOW+timedelta(milliseconds=250)))
        self.assertEqual((self.race,self.base,self.binding),old);self.assertNotIn('<html',repr(result));self.assertNotIn('data=\n',repr(result))
    def test_missing_display_stops_after_one_get(self):
        raw,first,second=bodies();raw=raw.replace(b'<td>6.92</td>',b'<td>-</td>')
        result=self.collect(raws=(raw,first,second))
        self.assertEqual(result,dict(status='DISPLAY_PENDING',official_source_requests=1));self.assertEqual(len(self.calls),1)
    def test_rights_parent_day_margin_and_proof_fail_before_get(self):
        facts,media=reviews()
        for args,status in [(dict(facts_review={}), 'RIGHTS_BLOCKED'),(dict(media_review={}), 'RIGHTS_BLOCKED'),(dict(parents_read_at=NOW+timedelta(seconds=1)),'INPUT_INVALID'),(dict(clocks=[NOW+timedelta(days=1)]),'DAY_INVALID'),(dict(clocks=[self.c.facts._time(self.race['closed_at'])-timedelta(seconds=120)]),'CUTOFF_PASSED')]:
            self.calls=[];result=self.collect(**args)
            with self.subTest(args=args):self.assertEqual(result,dict(status=status,official_source_requests=0));self.assertEqual(self.calls,[])
        self.binding['finalization']['receipt_sha256']='0'*64
        self.assertEqual(self.collect()['status'],'INPUT_INVALID');self.assertEqual(self.calls,[])
    def test_transport_and_body_failures_are_safe_and_not_retried(self):
        for failure,status in [(URLError('PRIVATE'), 'SOURCE_UNAVAILABLE'),(ValueError('PRIVATE'),'SOURCE_INVALID')]:
            self.calls=[];result=self.collect(failure=failure)
            self.assertEqual(result,dict(status=status,official_source_requests=1));self.assertEqual(len(self.calls),1)
        raw,first,second=bodies()
        for bad in [raw.replace(b'4001',b'4999'),raw.replace(b'08:43',b'08:44'),raw.replace(b'20261015',b'20261014'),b'x'*1048577]:
            self.calls=[];result=self.collect(raws=(bad,first,second))
            self.assertEqual(result['status'],'SOURCE_INVALID');self.assertEqual(result['official_source_requests'],1)
    def test_original_incomplete_conflicting_names_and_display_fail_after_three(self):
        raw,first,second=bodies()
        for raws,status in [((raw,first.replace(b'36.42',b'-',1),second),'ORIGINAL_INCOMPLETE'),((raw,first,second.replace(b'6.92',b'6.91')),'SOURCE_INVALID'),((raw,first.replace('松田 大志郎'.encode(),'松田大志'.encode()),second),'SOURCE_INVALID')]:
            self.calls=[];result=self.collect(raws=raws)
            with self.subTest(status=status):self.assertEqual(result,dict(status=status,official_source_requests=3))
    def test_response_crossing_cutoff_next_day_and_reverse_clock_stops_before_tsv(self):
        for ticks,status in [([NOW,NOW,self.c.facts._time(self.race['closed_at'])],'CUTOFF_PASSED'),([NOW,NOW,NOW+timedelta(days=1)],'DAY_INVALID'),([NOW,NOW,NOW-timedelta(seconds=1)],'SOURCE_INVALID')]:
            self.calls=[];self.assertEqual(self.collect(clocks=ticks),dict(status=status,official_source_requests=1))
    def test_margin_is_rechecked_after_parent_validation_before_first_get(self):
        close=self.c.facts._time(self.race['closed_at'])
        result=self.collect(clocks=[NOW,close-timedelta(seconds=120)])
        self.assertEqual(result,dict(status='CUTOFF_PASSED',official_source_requests=0))
        self.assertEqual(self.calls,[])

    def test_unrecognized_facts_reference_stops_before_get(self):
        review,_=reviews();review['evidence_reference']='another-owner-reference'
        self.assertEqual(self.collect(facts_review=review),dict(status='RIGHTS_BLOCKED',official_source_requests=0))

    def test_generation_clock_is_read_after_original_parse(self):
        tick=[NOW]
        real=self.c.parse_original
        def parse(*a,**k):
            value=real(*a,**k);tick[0]=NOW+timedelta(seconds=1);return value
        facts_review,media_review=reviews()
        raw,first,second=bodies()
        def transport(url,**kw):return FetchResponse(raw if 'beforeinfo' in url else first if '/txt/' in url else second,url,200,'text/html' if 'beforeinfo' in url else 'text/plain')
        with patch.object(memory,'utc_now',return_value=NOW),patch.object(self.c,'parse_original',side_effect=parse):
            result=self.c.collect_name_bound_inputs(self.race,self.base,self.binding,parents_read_at=NOW-timedelta(seconds=60),facts_review=facts_review,media_review=media_review,execute=True,transport_update=transport,transport_original=transport,clock=lambda:tick[0])
        self.assertEqual(result['snapshot']['generated_at'],self.c.facts.stamp(NOW+timedelta(seconds=1)))

    def test_response_envelopes_and_second_request_failure_keep_exact_attempt_counts(self):
        facts_review,media_review=reviews();raw,first,second=bodies()
        for variant in ('redirect','mime','status','not_bytes','empty','second_failure'):
            calls=[]
            def transport(url,**kw):
                calls.append(url)
                if variant=='second_failure' and len(calls)==2:raise URLError('PRIVATE_TSV')
                return FetchResponse('text' if variant=='not_bytes' else b'' if variant=='empty' else raw,
                    url+'#redirect' if variant=='redirect' else url,
                    302 if variant=='status' else 200,'application/json' if variant=='mime' else 'text/html')
            # The second-failure branch needs a valid beforeinfo response.
            with patch.object(memory,'utc_now',return_value=NOW):
                result=self.c.collect_name_bound_inputs(self.race,self.base,self.binding,parents_read_at=NOW-timedelta(seconds=60),facts_review=facts_review,media_review=media_review,execute=True,transport_update=transport,transport_original=transport,clock=lambda:NOW)
            with self.subTest(variant=variant):
                self.assertEqual(result,dict(status='SOURCE_UNAVAILABLE' if variant=='second_failure' else 'SOURCE_INVALID',official_source_requests=2 if variant=='second_failure' else 1))
                self.assertNotIn('PRIVATE_TSV',repr(result))

    def test_caller_budget_exception_propagates_without_becoming_a_source_failure(self):
        class BudgetExhausted(RuntimeError):pass
        with self.assertRaises(BudgetExhausted):self.collect(failure=BudgetExhausted('budget'))

    def test_memory_clock_remains_independent_and_cannot_be_backdated(self):
        result=self.collect(saved_at=NOW+timedelta(seconds=1))
        self.assertEqual(result['status'],'SOURCE_INVALID')

if __name__=='__main__':unittest.main()
