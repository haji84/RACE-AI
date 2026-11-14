"""Published alternatives share the already verified S16 source; no acquisition."""
from copy import deepcopy
import json,unittest
from race_ai import keirin_future_selector as selector
from tests.test_keirin_future_selector import wire_fixture,html,CASE,NOW


class SelectorAlternativeTests(unittest.TestCase):
    def select(self,**options):
        journal,evidence=wire_fixture()
        return selector.selector_metadata(journal,evidence,probe_case=CASE,now=NOW,**options)
    def test_opt_in_keeps_primary_and_exports_later_published_metadata_only(self):
        old=self.select();new=self.select(include_alternatives=True)
        self.assertEqual(old['schema'],selector.SCHEMA)
        self.assertNotIn('published_alternatives',old)
        self.assertEqual(new['case'],old['case']);self.assertEqual(new['source'],old['source'])
        self.assertEqual(new['schema'],'RACE_AI_KEIRIN_FUTURE_SELECTOR_METADATA_V2')
        self.assertEqual(new['published_alternatives'][0]['case']['race_no'],6)
        self.assertEqual(new['published_alternatives'][0]['case']['cutoff_at'],'2030-01-15T16:00:00+09:00')
        self.assertEqual(new['published_alternatives'][0]['published_start_at'],'2030-01-15T16:03:00+09:00')
        self.assertIs(selector.validate_metadata(new),new)
        for secret in ('DO_NOT_EXPORT','sInfo','senNo','raw_base64','AUTHORED_OPAQUE'):
            self.assertNotIn(secret,json.dumps(new))
    def test_wrong_source_context_duplicate_order_and_raw_fields_reject(self):
        for change in ('date','venue','ui','duplicate','order','raw','bound'):
            value=self.select(include_alternatives=True);alt=value['published_alternatives'][0]
            if change=='date':alt['case']['expected_date']='2030-01-16'
            elif change=='venue':alt['case']['venue']='keirin-jyo-12'
            elif change=='ui':alt['case']['ui_entry_url']='https://www.keirin.jp/pc/top'
            elif change=='duplicate':alt['case']=deepcopy(value['case']);alt.pop('published_start_at',None)
            elif change=='order':value['case'],alt['case']=alt['case'],value['case'];value.pop('published_start_at',None);alt.pop('published_start_at',None)
            elif change=='raw':alt['source_body']='DO_NOT_EXPORT'
            else:value['published_alternatives']*=12
            with self.subTest(change=change),self.assertRaises(ValueError):selector.validate_metadata(value)
    def test_absent_selector_stays_exact_v1_when_opted_in(self):
        journal,evidence=wire_fixture(listing=html(day='20300114'))
        a=selector.selector_metadata(journal,evidence,probe_case=CASE,now=NOW)
        b=selector.selector_metadata(journal,evidence,probe_case=CASE,now=NOW,include_alternatives=True)
        self.assertEqual(a,b);self.assertEqual(b['schema'],selector.SCHEMA)
    def test_real_admitted_eight_preparation_outputs_bounded_alternatives(self):
        from tests.test_keirin_future_selector import _admitted_current_list_fixture
        from tests.official_result_prepare_fixtures import KEY
        from race_ai import all_existing_model_official_prepare as prepare
        value,data,ctx,now=deepcopy(_admitted_current_list_fixture())
        result=prepare.prepare_from_evidence(value,data,context=ctx,run_id=601,head_sha='7'*40,now=now,key=KEY)
        metadata=result['counts']['future_selector']
        self.assertEqual(metadata['schema'],'RACE_AI_KEIRIN_FUTURE_SELECTOR_METADATA_V2')
        self.assertGreaterEqual(len(metadata['published_alternatives']),1)
        self.assertEqual(result['counts']['source_requests'],0)


if __name__=='__main__':unittest.main()
