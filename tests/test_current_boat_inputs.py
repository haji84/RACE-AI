"""Current-source collection contracts; all transport bytes/races are fictional.

The LZH extractor is replaced only to supply a strict B text fixture. These
tests do not claim that their placeholder archive is a real official archive.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from hashlib import sha256
import importlib
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from tests.test_program_race_isolation import fixture

try:
    provider = importlib.import_module("race_ai.current_boat_inputs")
except ModuleNotFoundError:
    provider = None

AT = datetime.fromisoformat("2030-04-01T08:00:00+09:00")
ARCHIVE = b"\x17\x00-lh0-" + bytes(32)


class Response:
    status = 200
    def __init__(self, url, body=ARCHIVE, *, final_url=None, content_type="application/octet-stream"):
        self.url, self.body = final_url or url, body
        self.headers = {"Content-Type": content_type}
    def geturl(self): return self.url
    def read(self, limit): return self.body[:limit]
    def __enter__(self): return self
    def __exit__(self, *args): pass


class CurrentBoatInputsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(provider, "current BOAT source provider is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.root = self.parent / "sources"
        self.calls = []
        self.now = AT
        self.extract = patch.object(provider, "extract_daily_lzh", return_value=fixture()).start()
        self.addCleanup(patch.stopall)
    def opener(self, request, *, timeout):
        self.calls.append(request.full_url)
        return Response(request.full_url)
    def collect(self, **kwargs):
        return provider.CurrentBoatInputs(self.root, clock=lambda:self.now, opener=self.opener).collect(**kwargs)

    def test_current_program_supplies_actual_native_p0_inputs_without_inference(self):
        with patch("race_ai.boat_observed_pairwise_models.predict_pair", side_effect=AssertionError("provider inferred")):
            result = self.collect()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(result["schedule"]), 12)
        self.assertEqual(len(result["inputs"]), 12)
        self.assertEqual(result["source_report"]["request_count"], 1)
        self.assertFalse(result["source_report"]["independent_source_verified"])
        for row in result["schedule"]:
            self.assertEqual(row["sport"], "boat")
            self.assertEqual(row["stage"], "P0")
            snap = result["inputs"][row["race_id"]]["P0"]["boat_observed"]["snapshot"]
            self.assertEqual(snap["sales_cutoff_at"], row["cutoff_at"])
            self.assertEqual(snap["scope"], "OPERATOR_SUPPLIED_RESEARCH")
            self.assertIsNone(snap["sources"][0]["published_at"])
            self.assertEqual(snap["sources"][0]["captured_at"], AT.isoformat())
            self.assertIn("recent_mean_finish", snap["participants"][0]["missing"])
        originals = list(self.root.rglob("*.lzh"))
        self.assertEqual(len(originals), 1)
        self.assertEqual(originals[0].read_bytes(), ARCHIVE)
        for p in self.root.rglob("*"):
            self.assertEqual(p.stat().st_mode & 0o777, 0o700 if p.is_dir() else 0o600)

    def test_restart_reuses_exact_cached_archive_without_another_get(self):
        first = self.collect()
        before = {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob("*.lzh")}
        with patch.object(provider, "_default_open", side_effect=AssertionError("cache caused network")):
            second = provider.CurrentBoatInputs(self.root, clock=lambda:AT).collect()
        self.assertEqual(second["inputs"], first["inputs"])
        self.assertEqual(second["source_report"]["request_count"], 1)
        self.assertEqual(before, {str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob("*.lzh")})

    def test_restart_recovers_already_captured_B_before_final_parse_pin(self):
        first=self.collect();p=next(self.root.rglob('state.json'))
        state=json.loads(p.read_text());state['p0_capture']=None;p.write_text(json.dumps(state))
        second=self.collect()
        self.assertEqual(second['inputs'],first['inputs'])
        self.assertEqual(len(self.calls),1,'captured source must not be fetched twice after interrupted parse')

    def test_parallel_collects_share_one_source_get(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _:self.collect(), range(2)))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(results[0]["inputs"], results[1]["inputs"])

    def test_deadline_rows_remain_in_schedule_without_backdated_inputs(self):
        self.now = datetime.fromisoformat("2030-04-01T10:29:00+09:00")
        result = self.collect()
        self.assertEqual(len(result["schedule"]), 12)
        self.assertEqual(result["inputs"], {})
        self.assertEqual({x["reason"] for x in result["blocked_races"]}, {"CUTOFF_BUFFER"})

    def test_bad_race_is_retained_as_blocked_without_fabricating_its_inputs(self):
        self.extract.return_value = fixture(3)
        result = self.collect()
        self.assertEqual(len(result["schedule"]), 12)
        self.assertEqual(len(result["inputs"]), 11)
        self.assertNotIn("20300401-18-03", result["inputs"])

    def test_wrong_day_program_is_preserved_but_halts_without_retry_on_restart(self):
        self.extract.return_value = fixture().replace("２０３０年４月１日".encode("cp932"), "２０３０年４月２日".encode("cp932"))
        with self.assertRaises(provider.CurrentBoatInputError): self.collect()
        self.assertEqual(next(self.root.rglob("*.lzh")).read_bytes(), ARCHIVE)
        with self.assertRaises(provider.CurrentBoatInputError): self.collect()
        self.assertEqual(len(self.calls), 1)

    def test_http_429_is_charged_and_persistently_stops_requests(self):
        def rejected(request, *, timeout):
            self.calls.append(request.full_url)
            raise HTTPError(request.full_url, 429, "fictional rate limit", {}, None)
        source = provider.CurrentBoatInputs(self.root, clock=lambda:AT, opener=rejected)
        with self.assertRaises(provider.CurrentBoatInputError): source.collect()
        with self.assertRaises(provider.CurrentBoatInputError): source.collect()
        state = json.loads(next(self.root.rglob("state.json")).read_text())
        self.assertEqual(state["request_count"], 1)
        self.assertTrue(state["halted_reason"])
        self.assertEqual(len(self.calls), 1)

    def test_redirect_or_oversize_response_cannot_be_accepted_as_official_source(self):
        def foreign(request, *, timeout):
            self.calls.append(request.full_url)
            return Response(request.full_url, final_url="https://unapproved.invalid/fake.lzh")
        with self.assertRaises(provider.CurrentBoatInputError):
            provider.CurrentBoatInputs(self.root, clock=lambda:AT, opener=foreign).collect()
        self.assertEqual(len(self.calls), 1)

    def test_budget_does_not_reset_when_provider_restarts(self):
        self.collect()
        state_path = next(self.root.rglob("state.json"))
        state = json.loads(state_path.read_text()); state["request_count"] = 240
        state_path.write_text(json.dumps(state))
        result = self.collect()
        self.assertEqual(result["source_report"]["request_count"], 240)
        self.assertEqual(len(self.calls), 1, "cache reads must retain the existing request count")
        self.assertIsNone(result["source_report"]["request_limit"], "the owner requested no numeric GET ceiling")

    def test_cached_archive_tampering_and_hardlinks_are_rejected(self):
        self.collect(); raw = next(self.root.rglob("*.lzh")); raw.write_bytes(b"tampered")
        with self.assertRaises(provider.CurrentBoatInputError): self.collect()
        raw.write_bytes(ARCHIVE); os.link(raw, self.parent/"linked-raw")
        with self.assertRaises(provider.CurrentBoatInputError): self.collect()

    def test_git_or_symlink_output_is_rejected_before_source_access(self):
        (self.parent/".git").mkdir()
        with self.assertRaises(provider.CurrentBoatInputError): self.collect()
        (self.parent/".git").rmdir(); self.root.mkdir(mode=0o700)
        link = self.parent/"symlink";link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(provider.CurrentBoatInputError):
            provider.CurrentBoatInputs(link, clock=lambda:AT, opener=self.opener).collect()
        self.assertEqual(self.calls, [])

    def test_client_cannot_select_a_historical_day_or_unsupported_stage(self):
        with self.assertRaises(provider.CurrentBoatInputError): self.collect(stage="P2")
        with self.assertRaises(TypeError): self.collect(day="2026-11-04")
        self.assertEqual(self.calls, [])

    def test_declared_capabilities_and_sport_are_explicit(self):
        source = provider.CurrentBoatInputs(self.root, clock=lambda:AT, opener=self.opener)
        self.assertIsNotNone(getattr(source,"capabilities",None), "provider capabilities are missing")
        self.assertTrue(source.capabilities["boat"]["P0"])
        self.assertTrue(source.capabilities["boat"]["P1"])
        for sport in ("keirin", "autorace", "horse"):
            self.assertFalse(source.capabilities[sport]["P0"])
            with self.assertRaises(provider.CurrentBoatInputError): source.collect(sport=sport)
        result = source.collect(sport="boat")
        for row in result["schedule"]:
            self.assertEqual(row["venue"], "boatrace-jcd-18")
            self.assertEqual(row["participants"][0]["registration_no"], "4001")
            self.assertTrue(row["participants"][0]["name"])

    def p1_parsers(self, *, pending=False):
        """Replace strict external HTML parsers with explicit fictional facts."""
        from race_ai import official_racelist_adapter as cards, official_race_updates as updates
        from scripts import boat_ab_future_pilot
        def card(raw, *, day, venue, race_no, source_url, captured_at):
            return dict(race_id=f'{day:%Y%m%d}-{venue}-{race_no:02}',closed_at='2030-04-01T10:30:00+09:00',
                boats=[dict(lane=i,racer_registration_id=str(4000+i),entry_status='listed',motor_no=10+i,
                    national_win_rate=5+i/10,local_win_rate=4+i/10,average_st=.15) for i in range(1,7)])
        def preview(raw, **kwargs):
            if pending: return dict(status='PENDING',body_identity_verified=True,data=None)
            return dict(status='AVAILABLE',body_identity_verified=True,data=dict(boats=[
                dict(lane=i,racer_registration_id=str(4000+i),display_time=6.5+i/100,
                    preview_st=.1+i/100,preview_st_status='OK') for i in range(1,7)]))
        patch.object(cards,'parse_official_racelist',side_effect=card).start()
        patch.object(updates,'parse_update',side_effect=preview).start()
        patch.object(boat_ab_future_pilot,'motor_top2',return_value={i:30+i for i in range(1,7)}).start()
        def opener(req, *, timeout):
            self.calls.append(req.full_url)
            if req.full_url.endswith('.lzh'):return Response(req.full_url)
            return Response(req.full_url,body=('<fictional>'+req.full_url+'</fictional>').encode(),content_type='text/html')
        return provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=opener)

    def test_p1_inputs_execute_only_the_five_existing_models_after_collection(self):
        source=self.p1_parsers()
        with patch('race_ai.boat_observed_pairwise_models.predict_pair',side_effect=AssertionError('provider inferred')):
            result=source.collect(stage='P1')
        self.assertEqual(len(result['schedule']),12)
        self.assertEqual(len(result['inputs']),3)
        self.assertEqual(len(self.calls),7)
        self.assertEqual(result['source_report']['request_count'],7)
        refs={(x['source_ref'],x['source_rights_ref']) for x in result['source_references']}
        from race_ai.existing_model_dispatch import dispatch
        report=dispatch(result['schedule'],result['inputs'],now=AT,
            allow_source=lambda ref,rights,purpose:(ref,rights) in refs and purpose=='analysis')
        generated=[s for s in report['slots'] if s['status']=='GENERATED_UNATTESTED']
        self.assertEqual(len(generated),15,'three races, five existing models each')
        self.assertTrue(all(s['scope']=='OPERATOR_SUPPLIED_RESEARCH' for s in generated))
        self.assertFalse(report['external_receipts_created'])

    def test_p1_later_calls_advance_other_races_and_preserve_ready_sources(self):
        source=self.p1_parsers();first=source.collect(stage='P1')
        pins={str(p.relative_to(self.root)):sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*.html')}
        second=source.collect(stage='P1')
        self.assertEqual(len(second['inputs']),6,'ready first3 cannot starve the next3')
        self.assertTrue(set(first['inputs'])<set(second['inputs']))
        self.assertEqual(len(self.calls),13)
        for name,digest in pins.items():self.assertEqual(sha256((self.root/name).read_bytes()).hexdigest(),digest)

    def test_p1_pending_exhibition_stays_missing_and_cooldown_advances_other_races(self):
        source=self.p1_parsers(pending=True)
        first=source.collect(stage='P1');second=source.collect(stage='P1')
        self.assertEqual(first['inputs'],{})
        self.assertEqual(second['inputs'],{})
        self.assertEqual(len(self.calls),13,'second request considers next3 instead of refetching cooled-down first3')
        self.assertIn('EXHIBITION_NOT_FULLY_PUBLISHED',{x['reason'] for x in first['blocked_races']})

    def test_p1_continues_above_legacy_240_counter_without_resetting_it(self):
        source=self.p1_parsers();source.collect(stage='P0')
        p=next(self.root.rglob('state.json'));state=json.loads(p.read_text());state['request_count']=240;p.write_text(json.dumps(state))
        try: result=source.collect(stage='P1')
        except provider.CurrentBoatInputError as exc:self.fail('legacy request count still blocks valid inputs: '+str(exc))
        self.assertEqual(result['source_report']['request_count'],246)
        self.assertIsNone(result['source_report']['request_limit'])
        self.assertEqual(len(result['inputs']),3,'removing a GET ceiling must retain the bounded fresh-race batch')
        self.assertEqual(len(self.calls),7)
        restarted=provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=self.opener)
        self.assertEqual(restarted.status(),{'day_jst':'2030-04-01','requests_used':246,'halted_reason':None})
        restarted.collect(stage='P0')
        self.assertEqual(restarted.status()['requests_used'],246)
        self.assertEqual(len(self.calls),7)

    def test_more_than_45_mock_source_requests_in_one_call_have_no_numeric_ceiling(self):
        source=provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=self.opener)
        calls=[0]
        try:
            with source._locked_day('2030-04-01') as folder:
                state=source._state(folder,'2030-04-01')
                for _ in range(50):
                    source._fetch(folder,state,'https://www1.mbrace.or.jp/od2/B/203004/b300401.lzh','B',calls)
        except provider.CurrentBoatInputError as exc:self.fail('legacy per-call GET limit still blocks collection: '+str(exc))
        self.assertEqual(calls,[50])
        self.assertEqual(len(self.calls),50)
        self.assertEqual(source.status(),{'day_jst':'2030-04-01','requests_used':50,'halted_reason':None})
        self.assertEqual(len(list(self.root.rglob('*.lzh'))),50)
        self.assertIsNone(provider.REQUEST_LIMIT)
        self.assertIsNone(provider.CALL_REQUEST_LIMIT)

    def test_existing_http_halt_above_240_is_read_and_never_cleared(self):
        self.collect();p=next(self.root.rglob('state.json'));state=json.loads(p.read_text())
        state.update(request_count=241,halted_reason='SOURCE_HTTP_4XX_STOP');p.write_text(json.dumps(state))
        source=provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=self.opener)
        try: status=source.status()
        except provider.CurrentBoatInputError as exc:self.fail('saved nonnegative counter was rejected: '+str(exc))
        self.assertEqual(status,{'day_jst':'2030-04-01','requests_used':241,'halted_reason':'SOURCE_HTTP_4XX_STOP'})
        with self.assertRaisesRegex(provider.CurrentBoatInputError,'SOURCE_SESSION_HALTED'):source.collect(stage='P1')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(source.status(),status)

    def test_p1_does_not_request_preview_after_rejected_program_identity(self):
        source=self.p1_parsers()
        with patch('race_ai.official_racelist_adapter.parse_official_racelist',side_effect=ValueError('fictional bad identity')):
            with self.assertRaises(provider.CurrentBoatInputError):source.collect(stage='P1')
        self.assertEqual(len(self.calls),2,'B plus racelist only; rejected identity must stop before preview GET')
        self.assertFalse(any('/beforeinfo?' in url for url in self.calls))
        with self.assertRaises(provider.CurrentBoatInputError):source.collect(stage='P1')
        self.assertEqual(len(self.calls),2)

    def test_503_has_no_automatic_retry_but_next_explicit_call_keeps_attempt_budget(self):
        def temporary(req, *, timeout):
            self.calls.append(req.full_url)
            if len(self.calls)==1:raise HTTPError(req.full_url,503,'fictional temporary error',{},None)
            return Response(req.full_url)
        source=provider.CurrentBoatInputs(self.root,clock=lambda:AT,opener=temporary)
        with self.assertRaises(provider.CurrentBoatInputError):source.collect()
        self.assertEqual(len(self.calls),1)
        state=json.loads(next(self.root.rglob('state.json')).read_text())
        self.assertIsNone(state['halted_reason'])
        result=source.collect()
        self.assertEqual(result['source_report']['request_count'],2)
        self.assertEqual(len(self.calls),2)

    def test_oversized_source_halts_before_parsing_or_model_input(self):
        def too_big(req, *, timeout):
            self.calls.append(req.full_url)
            return Response(req.full_url,body=b'x'*(provider.MAX_ARCHIVE_BYTES+1))
        source=provider.CurrentBoatInputs(self.root,clock=lambda:AT,opener=too_big)
        with self.assertRaises(provider.CurrentBoatInputError):source.collect()
        with self.assertRaises(provider.CurrentBoatInputError):source.collect()
        self.assertEqual(len(self.calls),1)
        self.extract.assert_not_called()

    def automatic_collect(self, source, **kwargs):
        self.assertIn('due_only',inspect.signature(source.collect).parameters,
                      'automatic deadline-window input selection is missing')
        return source.collect(stage='P1',due_only=True,**kwargs)

    def test_automatic_p1_before_window_keeps_whole_schedule_without_source_gets(self):
        self.collect();source=self.p1_parsers()
        result=self.automatic_collect(source)
        self.assertEqual(len(result['schedule']),12)
        self.assertEqual(result['inputs'],{})
        self.assertEqual(len(self.calls),1,'only the earlier cached B capture is allowed')
        self.assertEqual(result['source_report']['source_requests'],0)
        self.assertEqual({x['reason'] for x in result['blocked_races']},{'NOT_IN_CAPTURE_WINDOW'})

    def test_automatic_p1_selects_due_three_and_advances_other_due_races(self):
        self.collect();self.now=datetime.fromisoformat('2030-04-01T10:10:00+09:00')
        source=self.p1_parsers();first=self.automatic_collect(source);second=self.automatic_collect(source)
        self.assertEqual(len(first['schedule']),12)
        self.assertEqual(len(first['inputs']),3)
        self.assertEqual(len(second['inputs']),6)
        self.assertEqual(len(self.calls),13)
        self.assertEqual(first['source_report']['due_only'],True)

    def test_automatic_p1_ready_cache_outside_window_uses_no_new_gets(self):
        self.collect();source=self.p1_parsers();self.now=datetime.fromisoformat('2030-04-01T09:00:00+09:00')
        ready=source.collect(stage='P1');calls=len(self.calls)
        automatic=self.automatic_collect(source)
        self.assertEqual(set(automatic['inputs']),set(ready['inputs']))
        self.assertEqual(len(automatic['schedule']),12)
        self.assertEqual(len(self.calls),calls)
        self.assertEqual(automatic['source_report']['source_requests'],0)

    def test_automatic_p1_rechecks_buffer_before_preview_and_each_later_race(self):
        self.collect();source=self.p1_parsers();self.now=datetime.fromisoformat('2030-04-01T10:10:00+09:00')
        original=source.opener
        def advances(req,*,timeout):
            response=original(req,timeout=timeout)
            if '/racelist?' in req.full_url:self.now=datetime.fromisoformat('2030-04-01T10:27:00+09:00')
            return response
        source.opener=advances
        result=self.automatic_collect(source)
        self.assertEqual(result['inputs'],{})
        self.assertEqual(len(self.calls),2,'B and first racelist only; remaining210s buffer was consumed')
        self.assertFalse(any('/beforeinfo?' in url for url in self.calls))
        self.assertEqual(len(result['schedule']),12)

    def test_automatic_p1_boundary_and_future_source_capture_do_not_fetch(self):
        self.collect();source=self.p1_parsers();self.now=datetime.fromisoformat('2030-04-01T10:26:30+09:00')
        result=self.automatic_collect(source)
        self.assertEqual(result['inputs'],{})
        self.assertEqual(len(self.calls),1)
        self.now=datetime.fromisoformat('2030-04-01T07:59:00+09:00')
        with self.assertRaises(provider.CurrentBoatInputError):self.automatic_collect(source)
        self.assertEqual(len(self.calls),1)
        state=json.loads(next(self.root.rglob('state.json')).read_text())
        self.assertTrue(state['halted_reason'])

    def test_status_has_no_get_no_state_creation_and_preserves_budget_and_halt(self):
        source=provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=self.opener)
        self.assertIsNotNone(getattr(source,'status',None),'read-only source budget status is missing')
        self.assertEqual(list(self.root.iterdir()),[])
        self.assertEqual(source.status(),{'day_jst':'2030-04-01','requests_used':0,'halted_reason':None})
        self.assertEqual(list(self.root.iterdir()),[])
        self.assertEqual(self.calls,[])
        source.collect()
        p=next(self.root.rglob('state.json'));state=json.loads(p.read_text());state['request_count']=239
        state['halted_reason']='SOURCE_HTTP_4XX_STOP';p.write_text(json.dumps(state))
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        again=provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=self.opener).status()
        self.assertEqual(again,{'day_jst':'2030-04-01','requests_used':239,'halted_reason':'SOURCE_HTTP_4XX_STOP'})
        self.assertEqual(len(self.calls),1)
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_missing_prior_budget_is_rejected_instead_of_resetting_requests(self):
        self.collect();p=next(self.root.rglob('state.json'));p.unlink()
        source=provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=self.opener)
        self.assertIsNotNone(getattr(source,'status',None),'read-only source budget status is missing')
        with self.assertRaises(provider.CurrentBoatInputError):source.status()
        with self.assertRaises(provider.CurrentBoatInputError):source.collect()
        self.assertEqual(len(self.calls),1)

    def test_status_does_not_report_zero_when_existing_source_lock_is_missing(self):
        self.collect();(self.root/'source.lock').unlink()
        source=provider.CurrentBoatInputs(self.root,clock=lambda:self.now,opener=self.opener)
        with self.assertRaises(provider.CurrentBoatInputError):source.status()
        self.assertEqual(len(self.calls),1)
        self.assertFalse((self.root/'source.lock').exists(),'read-only status cannot recreate a missing protocol lock')

    def collect_until(self,source,stop,**kwargs):
        self.assertIn('automatic_stop_at',inspect.signature(source.collect).parameters,
                      'trusted automatic session end is missing')
        return source.collect(automatic_stop_at=stop,**kwargs)

    def test_automatic_deadline_crossed_during_B_get_keeps_original_without_next_get(self):
        source=self.p1_parsers();original=source.opener
        def crosses(req,*,timeout):
            response=original(req,timeout=timeout)
            self.now=datetime.fromisoformat('2030-04-01T08:02:00+09:00')
            return response
        source.opener=crosses
        with self.assertRaisesRegex(provider.CurrentBoatInputError,'AUTOMATIC_SESSION_END'):
            self.collect_until(source,'2030-04-01T08:01:00+09:00',stage='P1')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(next(self.root.rglob('*.lzh')).read_bytes(),ARCHIVE)
        state=json.loads(next(self.root.rglob('state.json')).read_text())
        self.assertEqual(state['request_count'],1)
        self.assertIsNone(state['halted_reason'],'session end must not poison the whole-day source identity')
        result=source.collect(stage='P0')
        self.assertEqual(len(result['inputs']),12)
        self.assertEqual(len(self.calls),1,'manual collection may reuse the valid original without another GET')

    def test_automatic_deadline_crossed_during_card_get_never_charges_preview(self):
        self.collect();source=self.p1_parsers();original=source.opener
        def crosses(req,*,timeout):
            response=original(req,timeout=timeout)
            if '/racelist?' in req.full_url:self.now=datetime.fromisoformat('2030-04-01T08:02:00+09:00')
            return response
        source.opener=crosses
        with self.assertRaisesRegex(provider.CurrentBoatInputError,'AUTOMATIC_SESSION_END'):
            self.collect_until(source,'2030-04-01T08:01:00+09:00',stage='P1')
        self.assertEqual(len(self.calls),2,'cached B plus only the first P1 source GET')
        self.assertFalse(any('/beforeinfo?' in url for url in self.calls))
        self.assertEqual(len(list(self.root.rglob('*.html'))),1,'inflight original remains preserved')
        self.assertEqual(source.status(),{'day_jst':'2030-04-01','requests_used':2,'halted_reason':None})

    def test_automatic_deadline_is_aware_day_bound_and_does_not_mutate_budget(self):
        self.collect();source=self.p1_parsers();p=next(self.root.rglob('state.json'));before=p.read_bytes()
        for stop in ('2030-04-01T07:59:00+09:00','2030-04-01T08:01:00','2030-04-02T08:01:00+09:00'):
            with self.subTest(stop=stop),self.assertRaises(provider.CurrentBoatInputError):
                self.collect_until(source,stop,stage='P1')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(p.read_bytes(),before)

    def test_automatic_midnight_inflight_original_is_preserved_without_identity_latch(self):
        self.now=datetime.fromisoformat('2030-04-01T23:59:59+09:00')
        source=self.p1_parsers();original=source.opener
        def midnight(req,*,timeout):
            response=original(req,timeout=timeout)
            self.now=datetime.fromisoformat('2030-04-02T00:00:10+09:00')
            return response
        source.opener=midnight
        with self.assertRaisesRegex(provider.CurrentBoatInputError,'AUTOMATIC_SESSION_END'):
            self.collect_until(source,'2030-04-02T00:00:00+09:00',stage='P0')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(next(self.root.rglob('*.lzh')).read_bytes(),ARCHIVE)
        state=json.loads((self.root/'2030-04-01/state.json').read_text())
        self.assertEqual(state['request_count'],1)
        self.assertIsNone(state['halted_reason'])
        self.assertEqual(state['captures'][0]['captured_at'],'2030-04-02T00:00:10+09:00')
