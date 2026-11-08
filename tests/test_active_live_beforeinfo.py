"""Invented official sources: active live observations require the retained program."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from race_ai import boat_context_store as store, saved_view_feed as feed
from race_ai.boat_active_exhibition import parse_active_beforeinfo
from race_ai.racer_beforeinfo import collect_beforeinfo, project_beforeinfo
from race_ai.racer_intraday import IntradayState
from tests.test_boat_active_exhibition import program, main_table, start_table
from tests.test_boat_observation_context import frame, starts, url, weather
from tests.test_racer_beforeinfo import AT, preview_view


def active_view(lanes=(1, 2, 3, 4, 5), *, source_lanes=(1, 2, 3, 4, 5, 6)):
    withdrawn = tuple(n for n in source_lanes if n not in lanes)
    source = program(lanes=source_lanes, withdrawn=withdrawn)
    view = preview_view()
    row = view['records'][0]
    row['participants'] = [dict(number=n, registration_no=str(4000+n), active=True)
                           for n in lanes]
    row.update(roster_status='OFFICIAL_ACTIVE', withdrawn_lanes=list(withdrawn),
               withdrawn_participants=[dict(number=n, registration_no=str(4000+n), active=False)
                                       for n in withdrawn])
    return view, source


def observation(source, *, missing=(), start_grid=None, captured_at=None):
    raw = frame(main_table(lanes=tuple(p['lane'] for p in source['boats']), missing=missing)
                + (starts(populated=True) if start_grid is None else start_grid) + weather())
    parsed = parse_active_beforeinfo(raw, program=source, source_url=url(),
                                    captured_at=captured_at or AT.isoformat())
    context = dict(schema=store.SCHEMA, race_id=source['race_id'], cutoff_at=source['closed_at'],
                   roster=[dict(lane=p['lane'], registration_number=p['racer_registration_id'])
                           for p in source['boats'] if p['entry_status'] == 'listed'],
                   program=deepcopy(source), beforeinfo=parsed['context'], pitreport=None,
                   entry_history=None, forecast_inputs_used=False)
    return raw, context


class ActiveLiveBeforeinfoTests(unittest.TestCase):
    def test_verified_current_subset_keeps_the_actual_old_six_forecast_immutable(self):
        from race_ai.racer_beforeinfo import project_program_observation
        from race_ai.boat_saved_model_view import merge_saved_views
        old,old_program=active_view(tuple(range(1,7)))
        old['records'][0]['prediction']['prediction_sha256']='a'*64
        old=merge_saved_views(old,[])
        original=deepcopy(old)
        pin,inventory=feed.originals_sha(old),feed.forecast_inventory(old)
        _,source=active_view()
        at=(AT-timedelta(minutes=1)).isoformat()
        source.update(captured_at=at)
        source['source']['captured_at']=at
        for boat in source['boats']:boat['captured_at']=at
        raw,_=observation(source)
        preview=parse_active_beforeinfo(raw,program=source,source_url=url(),captured_at=AT.isoformat())
        row=old['records'][0]
        row['live_boat_observation']=project_program_observation(row,source,preview,checked_at=AT.isoformat())
        old_overlay=deepcopy(original)
        earlier_raw,_=observation(old_program,captured_at=(AT-timedelta(minutes=5)).isoformat())
        earlier=parse_active_beforeinfo(earlier_raw,program=old_program,source_url=url(),
                                       captured_at=(AT-timedelta(minutes=5)).isoformat())
        old_overlay['records'][0]['live_boat_observation']=project_program_observation(
            old_overlay['records'][0],old_program,earlier,checked_at=(AT+timedelta(minutes=1)).isoformat())
        for first,second in ((old,old_overlay),(old_overlay,old)):
            merged=merge_saved_views(first,[second])
            self.assertEqual(merged['records'][0]['participants'],original['records'][0]['participants'])
            self.assertEqual(merged['records'][0]['prediction'],original['records'][0]['prediction'])
            self.assertEqual(feed.originals_sha(merged),pin)
            self.assertEqual(feed.forecast_inventory(merged),inventory)
            self.assertEqual(merged['records'][0]['live_boat_observation']['context']['program'],source)
            state,calls=IntradayState(),[]
            report=collect_beforeinfo(state,merged['records'],now=AT+timedelta(minutes=1),fetch=lambda u:calls.append(u))
            self.assertEqual(report['requests'],0)
            self.assertEqual(calls,[])
            self.assertEqual(len(project_beforeinfo(merged['records'][0],state,
                now=AT+timedelta(minutes=1))['context']['beforeinfo']['participants']),5)
        for mutate in (lambda p:p['boats'][5].update(racer_registration_id='4999'),
                       lambda p:p['boats'].pop(),
                       lambda p:p['boats'][5].update(entry_status='listed'),
                       lambda p:p['boats'][5].update(lane=5)):
            wrong=deepcopy(source);mutate(wrong)
            with self.subTest(mutate=mutate),self.assertRaises((ValueError,KeyError)):
                project_program_observation(row,wrong,preview,checked_at=AT.isoformat())
        with tempfile.TemporaryDirectory() as folder:
            store.save_context(Path(folder),row['live_boat_observation']['context'])
            snapshot=store.read_contexts(Path(folder),day='2030-04-01')
            self.assertIsNotNone(store.attach_contexts(deepcopy(original),snapshot))

    def test_actual_capture_completion_is_recorded_without_backdating_or_future_admission(self):
        view,source=active_view()
        started=AT+timedelta(minutes=6)
        captured=started+timedelta(seconds=1)
        completed=started+timedelta(seconds=2)
        raw,_=observation(source,captured_at=captured.isoformat())
        for end,expected in ((completed,1),(started,0),(started+timedelta(minutes=6),0)):
            state=IntradayState()
            report=collect_beforeinfo(state,view['records'],now=started,
                fetch=lambda _:(raw,captured.isoformat()),programs={source['race_id']:source},
                completion_clock=lambda:end)
            self.assertEqual(report['parsed'],expected)
            if expected:
                live=project_beforeinfo(view['records'][0],state,now=completed)
                self.assertEqual(live['checked_at'],completed.isoformat())
                self.assertEqual(live['context']['beforeinfo']['source']['captured_at'],captured.isoformat())

    def test_later_poll_cannot_restore_a_retired_six_program_from_the_old_live_row(self):
        from race_ai.racer_beforeinfo import project_program_observation
        old,old_program=active_view(tuple(range(1,7)))
        earlier=AT-timedelta(minutes=11)
        old_raw,_=observation(old_program,captured_at=earlier.isoformat())
        parsed=parse_active_beforeinfo(old_raw,program=old_program,source_url=url(),captured_at=earlier.isoformat())
        row=old['records'][0]
        row['live_boat_observation']=project_program_observation(row,old_program,parsed,
            checked_at=(AT-timedelta(minutes=10)).isoformat())
        _,current=active_view()
        at=(AT-timedelta(minutes=1)).isoformat()
        current['captured_at']=current['source']['captured_at']=at
        for person in current['boats']:person['captured_at']=at
        raw,_=observation(current)
        state=IntradayState()
        first=collect_beforeinfo(state,[row],now=AT,fetch=lambda _:(raw,AT.isoformat()),
                                 programs={current['race_id']:current})
        self.assertEqual(first['parsed'],1)
        self.assertEqual(len(project_beforeinfo(row,state,now=AT)['context']['roster']),5)
        later=AT+timedelta(minutes=6)
        second=collect_beforeinfo(state,[row],now=later,fetch=lambda _:(old_raw,later.isoformat()),
                                  completion_clock=lambda:later)
        self.assertEqual(second['parsed'],1)
        self.assertEqual(state.control['beforeinfo_programs'][row['race_id']],current)
        self.assertEqual(len(project_beforeinfo(row,state,now=later)['context']['roster']),5)
        calls=[]
        third=collect_beforeinfo(state,[row],now=later+timedelta(seconds=1),fetch=lambda u:calls.append(u),
                                programs={row['race_id']:old_program})
        self.assertEqual(third['requests'],0)
        self.assertEqual(calls,[])
        self.assertEqual(state.control['beforeinfo_programs'][row['race_id']],current)

    def test_native_projection_seeds_full_program_overlay_without_source_requests(self):
        from race_ai import boat_all_model_cycle as cycle
        from race_ai.boat_saved_model_view import merge_saved_views
        from tests.test_boat_all_model_cycle import AllModelCycleTests, receipt
        fixture = AllModelCycleTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        _, source = active_view()
        raw, context = observation(source)
        current = dict(program=source, beforeinfo=parse_active_beforeinfo(raw, program=source,
                       source_url=url(), captured_at=AT.isoformat()), as_of=AT.isoformat())
        payload = cycle.forecast_round([current], fixture.runtime(), now=AT+timedelta(seconds=10))
        proof = receipt(payload, saved=(AT+timedelta(seconds=20)).isoformat())
        projected = cycle.project_round(payload, proof)
        row = projected['records'][0]
        original = deepcopy(row)
        live = row.get('live_boat_observation')
        self.assertIsNotNone(live, 'verified current_inputs must reach the separate mutable live overlay')
        self.assertEqual(live['context']['program'], source)
        self.assertEqual(live['context']['beforeinfo']['source']['sha256'], context['beforeinfo']['source']['sha256'])
        del original['live_boat_observation']
        self.assertEqual(feed.originals_sha(projected), feed.originals_sha(dict(projected, records=[original])))
        self.assertEqual(feed.forecast_inventory(projected), feed.forecast_inventory(dict(projected, records=[original])))
        calls, state = [], IntradayState()
        report = collect_beforeinfo(state, [row], now=AT+timedelta(seconds=30), fetch=lambda u: calls.append(u))
        self.assertEqual(report['requests'], 0)
        self.assertEqual(calls, [])
        self.assertEqual(project_beforeinfo(row, state, now=AT+timedelta(seconds=30))['context'], live['context'])
        merged = merge_saved_views(projected, [])
        self.assertEqual(merged['records'][0]['live_boat_observation']['context']['program'], source)

    def test_new_active_overlay_survives_an_older_full_six_overlay(self):
        from race_ai.boat_saved_model_view import merge_saved_views
        view, source = active_view()
        _, context = observation(source)
        newer = deepcopy(view)
        newer['records'][0]['live_boat_observation'] = dict(schema='RACE_AI_LIVE_BOAT_OBSERVATION_V1',
            forecast_inputs_used=False, checked_at=AT.isoformat(), state='READY', context=context)
        old, old_source = active_view(tuple(range(1, 7)))
        _, old_context = observation(old_source, captured_at=(AT-timedelta(minutes=5)).isoformat())
        old['records'][0]['live_boat_observation'] = dict(schema='RACE_AI_LIVE_BOAT_OBSERVATION_V1',
            forecast_inputs_used=False, checked_at=(AT+timedelta(minutes=1)).isoformat(), state='READY', context=old_context)
        old['records'][0]['prediction'] = deepcopy(newer['records'][0]['prediction'])
        for part in (old,newer):
            part['records'][0]['prediction']['prediction_sha256']='a'*64
        for first, extra in ((old, newer), (newer, old)):
            result = merge_saved_views(first, [extra])['records'][0]
            self.assertEqual(len(result['participants']), 5)
            self.assertEqual(result['live_boat_observation']['context']['program'], source)
            self.assertEqual(len(result['live_boat_observation']['context']['beforeinfo']['participants']), 5)

    def test_native_overlay_retires_an_older_six_capture_and_wait_without_get(self):
        old, old_program = active_view(tuple(range(1, 7)))
        old_at = AT-timedelta(minutes=6)
        raw, _ = observation(old_program, captured_at=old_at.isoformat())
        state = IntradayState()
        collect_beforeinfo(state, old['records'], now=old_at, fetch=lambda _: (raw, old_at.isoformat()))
        view, source = active_view()
        _, context = observation(source)
        row = view['records'][0]
        row['live_boat_observation'] = dict(schema='RACE_AI_LIVE_BOAT_OBSERVATION_V1',
            forecast_inputs_used=False, checked_at=AT.isoformat(), state='READY', reason=None, context=context)
        before = deepcopy(state.control)
        projected = project_beforeinfo(row, state, now=AT)
        self.assertIsNotNone(projected['context'])
        self.assertEqual(len(projected['context']['beforeinfo']['participants']), 5)
        self.assertEqual(state.control, before, 'projection never rewrites retained observations')
        calls = []
        report = collect_beforeinfo(state, [row], now=AT+timedelta(seconds=30), fetch=lambda u: calls.append(u))
        self.assertEqual(report['requests'], 0)
        self.assertEqual(calls, [])
        self.assertEqual(project_beforeinfo(row, state, now=AT+timedelta(seconds=30))['context'], projected['context'])

    def test_malformed_program_clock_and_overlay_hold_one_race_without_breaking_others(self):
        view, source = active_view()
        for mutate in (lambda r,p: p['source'].update(captured_at=None),
                       lambda r,p: r.update(live_boat_observation='malformed'),
                       lambda r,p: r.update(live_boat_observation=dict(context='malformed'))):
            with self.subTest(mutate=mutate):
                row, card = deepcopy(view['records'][0]), deepcopy(source)
                mutate(row,card)
                calls=[]
                report=collect_beforeinfo(IntradayState(),[row],now=AT,fetch=lambda u:calls.append(u),
                                          programs={source['race_id']:card})
                self.assertEqual(report['requests'],0)
                self.assertEqual(calls,[])

    def test_malformed_rows_cannot_reuse_the_previous_rows_program(self):
        view, source = active_view()
        good = view['records'][0]
        raw, _ = observation(source)
        bad_cutoff = deepcopy(preview_view()['records'][0])
        bad_cutoff.update(race_id='20300401-12-11',cutoff_at='invalid',saved_cutoff_variants=[])
        for rows in ([{},good,bad_cutoff], [bad_cutoff,{},good]):
            with self.subTest(rows=rows):
                state,calls=IntradayState(),[]
                def fetch(request):
                    calls.append(request)
                    return raw,AT.isoformat()
                report=collect_beforeinfo(state,rows,now=AT,fetch=fetch,
                                          programs={source['race_id']:source})
                self.assertEqual(report,dict(requests=1,parsed=1,rejected=0))
                self.assertEqual(len(calls),1)
                self.assertNotIn(bad_cutoff['race_id'],state.control['beforeinfo_checks'])

    def test_verified_current_program_cutoff_gates_refresh_without_rewriting_forecast(self):
        view,source=active_view()
        row=view['records'][0]
        row.update(cutoff_at='2030-04-01T21:30:00+09:00',saved_cutoff_variants=['2030-04-01T21:30:00+09:00'])
        row['prediction']['cutoff_at']=row['cutoff_at']
        pin,inventory=feed.originals_sha(view),feed.forecast_inventory(view)
        raw,_=observation(source)
        state=IntradayState()
        report=collect_beforeinfo(state,[row],now=AT,fetch=lambda _:(raw,AT.isoformat()),
                                 programs={source['race_id']:source})
        self.assertEqual(report['parsed'],1)
        self.assertEqual(project_beforeinfo(row,state,now=AT)['context']['cutoff_at'],source['closed_at'])
        self.assertEqual(feed.originals_sha(view),pin)
        self.assertEqual(feed.forecast_inventory(view),inventory)

    def test_native_five_overlay_reaches_encrypted_feed_on_the_original_six_forecast(self):
        from race_ai.racer_beforeinfo import project_program_observation
        from tests.test_racer_result_bridge import BridgeTests
        from race_ai.racer_result_bridge import SavedResultBridge
        fixture=BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view=preview_view()
        _,source=active_view()
        raw,_=observation(source)
        preview=parse_active_beforeinfo(raw,program=source,source_url=url(),captured_at=AT.isoformat())
        row=view['records'][0]
        row['live_boat_observation']=project_program_observation(row,source,preview,checked_at=AT.isoformat())
        original=deepcopy(view)
        pin,inventory=feed.originals_sha(view),feed.forecast_inventory(view)
        fixture.seed(view)
        bridge=SavedResultBridge(fixture.repo,now=AT,transport=fixture.git,bootstrap=fixture.boot)
        state,calls=IntradayState(),[]
        collect_beforeinfo(state,bridge.rows,now=AT+timedelta(seconds=30),fetch=lambda u:calls.append(u))
        report=bridge.publish(state,now=AT+timedelta(seconds=30))
        _,_,_,readback=feed.current_view(fixture.git,fixture.boot)
        self.assertEqual(calls,[])
        self.assertEqual(readback['records'][0]['participants'],original['records'][0]['participants'])
        self.assertEqual(readback['records'][0]['prediction'],original['records'][0]['prediction'])
        self.assertEqual(len(readback['records'][0]['live_boat_observation']['context']['beforeinfo']['participants']),5)
        self.assertEqual(feed.originals_sha(readback),pin)
        self.assertEqual(feed.forecast_inventory(readback),inventory)

    def test_bound_program_and_raw_capture_survive_authenticated_intraday_restart(self):
        from tests.test_racer_intraday_handoff import JournalTests
        from race_ai.racer_intraday_handoff import load_intraday,save_intraday
        fixture=JournalTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        view,source=active_view((1,3,6))
        raw,_=observation(source)
        loaded=load_intraday(fixture.repo,initialize=True,key=fixture.key,
                            transport=fixture.git,now=AT)
        collect_beforeinfo(loaded['state'],view['records'],now=AT,fetch=lambda _:(raw,AT.isoformat()),
                           programs={source['race_id']:source})
        expected=project_beforeinfo(view['records'][0],loaded['state'],now=AT)
        saved=save_intraday(loaded,catalogue_sha256='a'*64,now=AT,key=fixture.key)
        restored=load_intraday(fixture.repo,key=fixture.key,transport=fixture.git,
                              now=AT+timedelta(minutes=1))['state']
        self.assertEqual(restored.control['beforeinfo_programs'][source['race_id']],source)
        self.assertEqual(project_beforeinfo(view['records'][0],restored,now=AT+timedelta(minutes=1)),expected)
        self.assertEqual(restored.capture(restored.control['beforeinfo_captures'][source['race_id']])[0],raw)
        self.assertNotIn(b'RACE_AI_BOAT_OFFICIAL_PROGRAM_V1',fixture.git.read(
            saved['source_commit'],saved['cipher_path'],1000000))

    def test_direct_three_row_program_keeps_noncontiguous_physical_lanes(self):
        view, source=active_view((1,3,6),source_lanes=(1,3,6))
        raw,_=observation(source,start_grid=start_table(lanes=(1,3,6)))
        state=IntradayState()
        report=collect_beforeinfo(state,view['records'],now=AT,fetch=lambda _:(raw,AT.isoformat()),
                                 programs={source['race_id']:source})
        self.assertEqual(report['parsed'],1)
        self.assertEqual([p['lane'] for p in project_beforeinfo(view['records'][0],state,now=AT)['context']['roster']], [1,3,6])

    def test_unknown_registration_is_allowed_only_for_explicit_program_withdrawal(self):
        from race_ai.racer_beforeinfo import project_program_observation
        view, _ = active_view((1,3,6))
        source = program(withdrawn=(2,4,5),unknown_withdrawn=True)
        for person in view['records'][0]['withdrawn_participants']:
            person['registration_no']=None
        raw,_=observation(source,start_grid=start_table(lanes=(1,3,6)))
        preview=parse_active_beforeinfo(raw,program=source,source_url=url(),captured_at=AT.isoformat())
        live=project_program_observation(view['records'][0],source,preview,checked_at=AT.isoformat())
        self.assertEqual([p['lane'] for p in live['context']['roster']],[1,3,6])
        view['records'][0]['withdrawn_participants'][0]['registration_no']='4999'
        with self.assertRaises(ValueError):
            project_program_observation(view['records'][0],source,preview,checked_at=AT.isoformat())

    def test_two_and_seven_active_inputs_never_reach_sources(self):
        for lanes in ((1,6),tuple(range(1,8))):
            view, source=active_view()
            view['records'][0]['participants']=[dict(number=n,registration_no=str(4000+n)) for n in lanes]
            calls=[]
            report=collect_beforeinfo(IntradayState(),view['records'],now=AT,fetch=lambda u:calls.append(u),
                                     programs={source['race_id']:source})
            self.assertEqual(report['requests'],0)
            self.assertEqual(calls,[])

    def test_retained_full_program_supports_three_to_six_and_preserves_originals(self):
        for lanes in ((1, 3, 6), (1, 2, 4, 6), (1, 2, 3, 4, 5), tuple(range(1, 7))):
            with self.subTest(lanes=lanes):
                view, source = active_view(lanes)
                row = view['records'][0]
                raw, _ = observation(source, missing=tuple(row['withdrawn_lanes']))
                before = deepcopy(view)
                pin, inventory = feed.originals_sha(view), feed.forecast_inventory(view)
                state, calls = IntradayState(), []
                def fetch(request):
                    calls.append(request)
                    return raw, AT.isoformat()
                report = collect_beforeinfo(state, [row], now=AT, fetch=fetch, max_requests=4,
                                            programs={source['race_id']: source})
                self.assertEqual(report, dict(requests=1, parsed=1, rejected=0))
                self.assertEqual(calls, [url().replace('rno=12&jcd=12&hd=20300401',
                                                     'hd=20300401&jcd=12&rno=12')])
                live = project_beforeinfo(row, state, now=AT)
                self.assertEqual(live['state'], 'READY')
                self.assertEqual([p['lane'] for p in live['context']['beforeinfo']['participants']], list(lanes))
                self.assertEqual(live['context']['program'], source)
                self.assertEqual(view, before)
                row['live_boat_observation'] = live
                self.assertEqual(feed.originals_sha(view), pin)
                self.assertEqual(feed.forecast_inventory(view), inventory)
                self.assertEqual(project_beforeinfo(row, state, now=AT)['context'], live['context'])

    def test_missing_active_display_remains_five_and_optional_start_never_blocks_ready(self):
        view, source = active_view()
        row = view['records'][0]
        for missing, expected in (((3, 6), 'AWAITING_EXHIBITION'), ((6,), 'READY')):
            with self.subTest(missing=missing):
                raw, _ = observation(source, missing=missing, start_grid=starts())
                state = IntradayState()
                collect_beforeinfo(state, [row], now=AT, fetch=lambda _: (raw, AT.isoformat()),
                                   programs={source['race_id']: source})
                live = project_beforeinfo(row, state, now=AT)
                self.assertEqual(live['state'], expected)
                self.assertEqual(len(live['context']['beforeinfo']['participants']), 5)
                self.assertTrue(all(p['exhibition_st'] is None for p in live['context']['beforeinfo']['participants']))

    def test_unbound_active_declaration_hash_and_url_do_not_authorize_source_calls(self):
        view, source = active_view()
        row = view['records'][0]
        row['source_provenance'] = dict(program_sha256=source['source_sha256'], program_url=source['source_url'])
        calls, state = [], IntradayState()
        report = collect_beforeinfo(state, [row], now=AT, fetch=lambda u: calls.append(u))
        self.assertEqual(report['requests'], 0)
        self.assertEqual(calls, [])
        live = project_beforeinfo(row, state, now=AT)
        self.assertIsNone(live['context'])
        self.assertEqual(live['state'], 'SOURCE_ERROR')
        self.assertEqual(live['reason'], 'BEFOREINFO_ACTIVE_PROGRAM_REQUIRED')

    def test_program_roster_identity_date_and_clock_contradictions_hold_before_fetch(self):
        view, source = active_view()
        cases = [lambda r, p: r['participants'].pop(),
                 lambda r, p: r['participants'][1].update(number=1),
                 lambda r, p: r['participants'][1].update(registration_no='4999'),
                 lambda r, p: r.update(event_date_jst='2030-04-02'),
                 lambda r, p: p.update(captured_at=(AT+timedelta(minutes=1)).isoformat()),
                 lambda r, p: p.update(race_id='20300401-12-11'),
                 lambda r, p: p['boats'][5].update(entry_status='listed'),
                 lambda r, p: p.update(active_lanes=[1, 2, 3, 4]),
                 lambda r, p: r['participants'][0].update(number=True)]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                row, card = deepcopy(view['records'][0]), deepcopy(source)
                mutate(row, card)
                calls = []
                report = collect_beforeinfo(IntradayState(), [row], now=AT,
                    fetch=lambda u: calls.append(u), programs={source['race_id']: card})
                self.assertEqual(report['requests'], 0)
                self.assertEqual(calls, [])

    def test_active_source_identity_mismatch_is_rejected_and_capture_is_retained(self):
        view, source = active_view()
        raw, _ = observation(source)
        for body in (raw.replace(b'toban=4003', b'toban=4999'),
                     raw.replace(b'hd=20300401', b'hd=20300402')):
            state = IntradayState()
            report = collect_beforeinfo(state, view['records'], now=AT,
                fetch=lambda _: (body, AT.isoformat()), programs={source['race_id']: source})
            self.assertEqual(report, dict(requests=1, parsed=0, rejected=1))
            self.assertTrue(any(p['kind'] == 'BEFOREINFO_REJECTED' for p in state.new_captures.values()))
            self.assertIsNone(project_beforeinfo(view['records'][0], state, now=AT)['context'])

    def test_context_store_accepts_only_full_program_bound_active_rosters(self):
        for lanes in ((1, 3, 6), (1, 2, 3, 4, 5), tuple(range(1, 7))):
            with self.subTest(lanes=lanes), tempfile.TemporaryDirectory() as folder:
                view, source = active_view(lanes)
                _, context = observation(source)
                before = deepcopy(context)
                ident = store.save_context(Path(folder), context)
                self.assertEqual(len(ident), 64)
                snapshot = store.read_contexts(Path(folder), day='2030-04-01')
                self.assertEqual(snapshot['contexts'][source['race_id']]['program'], source)
                self.assertIsNotNone(store.attach_contexts(view, snapshot))
                self.assertEqual(context, before)
                self.assertIsNotNone(view['records'][0].get('boat_observation_context'))
                if len(lanes) < 6:
                    del context['program']
                    with self.assertRaises(ValueError):
                        store.save_context(Path(folder), context)

    def test_context_store_rejects_program_and_observation_contradictions(self):
        _, source = active_view()
        _, context = observation(source)
        cases = [lambda c: c['roster'].pop(),
                 lambda c: c['beforeinfo']['participants'].pop(),
                 lambda c: c['program']['boats'][0].update(racer_registration_id='4999'),
                 lambda c: c['program']['source'].update(sha256='b'*64),
                 lambda c: c['program'].update(captured_at=(AT+timedelta(seconds=1)).isoformat()),
                 lambda c: c['program'].update(closed_at='2030-04-01T20:31:00+09:00'),
                 lambda c: c['beforeinfo'].update(source_cutoff_at='2030-04-01T20:31:00+09:00')]
        for mutate in cases:
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as folder:
                bad = deepcopy(context)
                mutate(bad)
                with self.assertRaises(ValueError):
                    store.save_context(Path(folder), bad)

    def test_context_store_anchors_the_current_program_before_a_stale_six_capture(self):
        _,old_program=active_view(tuple(range(1,7)))
        _,old_context=observation(old_program,captured_at=(AT+timedelta(minutes=1)).isoformat())
        _,source=active_view()
        at=(AT-timedelta(minutes=1)).isoformat()
        source['captured_at']=source['source']['captured_at']=at
        for person in source['boats']:person['captured_at']=at
        _,current=observation(source)
        with tempfile.TemporaryDirectory() as folder:
            for context in (current,old_context):store.save_context(Path(folder),context)
            selected=store.read_contexts(Path(folder),day='2030-04-01')['contexts'][source['race_id']]
            self.assertEqual(selected['program'],source)
            self.assertEqual(len(selected['beforeinfo']['participants']),5)


if __name__ == '__main__':
    unittest.main()
