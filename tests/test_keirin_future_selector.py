"""Authored retained UI wires; no live source, key lookup or forecast."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from functools import lru_cache

from race_ai.actions_contract import digest
from scripts import all_existing_model_official_result_collect as C

JST = timezone(timedelta(hours=9))
NOW = datetime(2030, 1, 15, 9, tzinfo=JST)
CASE = dict(sport='keirin', race_id='keirin:2030-01-14:keirin-jyo-48:2',
            route=dict(kind='NORMAL_UI', ui_entry_url='https://keirin.jp/pc/top', ui_venue_name='四日市'))


def html(day='20300115', venue='48', rows=None, *, selected=1, hidden=None):
    if rows is None:
        rows = [dict(raceNo=1, denTime='11:00', stTime='11:03'),
                dict(raceNo=5, denTime='15:10', stTime='15:13', sInfo=[{'senNo': 'DO_NOT_EXPORT'}]),
                dict(raceNo=6, denTime='16:00', stTime='16:03')]
    data = dict(PC0201=dict(C0201data=dict(selKaisai=day, selKjyoCd=venue, selRaceNo=selected)),
                PJ0305=dict(kaisaihi=day, keirinCd=venue, rInfo=rows))
    inputs = '' if hidden is None else ''.join('<input id="'+k+'" value="'+v+'">' for k, v in hidden.items())
    return ('<html>'+inputs+'<script>var jsonData={};'+''.join(
        'jsonData['+json.dumps(k)+']='+json.dumps(v)+';' for k, v in data.items())+'</script></html>').encode()


def wire_fixture(*, listing=None, request=b'disp=PJ0305&encp=AUTHORED_OPAQUE', event=True):
    start = NOW-timedelta(minutes=10)
    end = start+timedelta(seconds=15)
    values = [('https://keirin.jp/pc/top', b'<html>published venue list</html>', None),
              ('https://keirin.jp/pc/racelist', html() if listing is None else listing, request),
              ('https://keirin.jp/pc/racelist', html(day='20300114'), b'disp=PJ0305&encp=OLD_DAY')]
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); root.chmod(0o700)
        responses = []
        for number, (url, raw, post) in enumerate(values, 1):
            at = start+timedelta(seconds=number*2)
            headers = at+timedelta(milliseconds=100)
            completed = at+timedelta(milliseconds=500)
            entry = dict(sequence=number, url=url, method='GET' if post is None else 'POST',
                resource_type='document', status=200, content_type='text/html;charset=UTF-8', byte_count=len(raw),
                source_sha256=sha256(raw).hexdigest(), request_started_at=at.isoformat(),
                headers_received_at=headers.isoformat(), response_received_at=completed.isoformat(),
                body_captured_at=completed.isoformat(), body_file=f'response-{number}.body', metadata_file=f'response-{number}.json')
            meta = dict(source_url=url, final_url=url, method=entry['method'], http_method=entry['method'],
                resource_type='document', status=200, byte_count=len(raw), source_sha256=entry['source_sha256'],
                fetched_at=entry['request_started_at'], response_received_at=entry['body_captured_at'],
                headers={'content-type': entry['content_type']})
            if post is not None:
                entry.update(request_body_file=f'request-{number}.body', request_body_sha256=sha256(post).hexdigest(),
                             request_content_type='application/x-www-form-urlencoded')
                meta.update(**{k: entry[k] for k in ('request_body_file', 'request_body_sha256', 'request_content_type')})
                C._write(root/entry['request_body_file'], post)
            C._write(root/entry['body_file'], raw); C._write(root/entry['metadata_file'], C.future.wire(meta))
            responses.append(entry)
        ledger = deepcopy(responses[:2])
        if event:
            ledger.append(dict(event='NORMAL_SEMANTIC_UI_CLICK', label='出走表\n一覧', before=values[0][0],
                after=values[1][0], at=(start+timedelta(seconds=5)).isoformat()))
        ledger.append(deepcopy(responses[2]))
        case = dict(sport=CASE['sport'], race_id=CASE['race_id'], state='HOLD_RESULT_SOURCE_UNAVAILABLE', responses=[])
        index = dict(schema='RACE_AI_OFFICIAL_RESULT_BROWSER_CAPTURE_V1', started_at=start.isoformat(), completed_at=end.isoformat(),
            actual_request_count=3, maximum_requests=16, minimum_spacing_ms=825, request_timeout_ms=12000,
            maximum_elapsed_ms=85000, normal_ui_only=True, manual_api_requests=0, stop_reason='FINISHED',
            stopped_host=False, responses=responses, ledger=ledger, cases=[case])
        C._write(root/'capture-index.json', C.future.wire(index))
        planned = [dict(sport=CASE['sport'], race_id=CASE['race_id'])]
        found, states, originals = C.browser_sources(index, root, planned, started=start, now=end, remaining=16)
        journal = dict(execution_day='2030-01-15', epoch_started_at=start.isoformat(), maximum_requests=16,
            attempts=[], captures=[r[2] for r in found], cases=states, browser_captures=originals,
            browser_attempt=dict(state='COMPLETE', reserved_request_limit=16, actual_request_count=3,
                started_at=start.isoformat(), completed_at=end.isoformat()),
            browser_index=C._index_diagnostic(index, planned), browser_quarantine=C._browser_quarantine(index, root, maximum_json=12*1024*1024))
    metadata = dict(created_at=(end+timedelta(seconds=1)).isoformat())
    evidence = dict(pin=dict(id=100, digest='sha256:'+'a'*64, run_id=200, head_sha='b'*40),
        artifact_metadata=metadata, cipher_sha256='c'*64, payload_sha256=digest(journal))
    return journal, evidence


def change_index(journal,change):
    from tests.test_all_existing_model_prior_static_cache import update_file
    item=next(f for f in journal['browser_quarantine']['files'] if f['file']=='capture-index.json')
    index=json.loads(base64.b64decode(item['raw_base64']));change(index)
    for name in ('capture-index.json','returned-index.canonical.json'):update_file(journal,name,C.future.wire(index))
    journal['browser_quarantine']['returned_index_sha256']=digest(index)
    journal['browser_index']=C._index_diagnostic(index,journal['cases'])


@lru_cache(maxsize=1)
def _admitted_current_list_fixture():
    """Add authored current-day originals BEFORE sealing the real S16 codec."""
    from tests import official_result_prepare_fixtures as fixtures
    from tests import test_all_existing_model_official_probe16_continuation as sixteen
    from race_ai.boat_all_model_store import open_forecasts
    value,data,context,now=fixtures.eight_fixture();key=fixtures.KEY
    journal_item=data['groups']['prior_journal_artifacts'][-1]
    journal=open_forecasts(C._journal_cipher(journal_item['raw']),key=key)
    start=C.stamp(journal['epoch_started_at']);end=C.stamp(journal['browser_attempt']['completed_at'])
    files={f['file']:base64.b64decode(f['raw_base64']) for f in journal['browser_quarantine']['files']}
    index=json.loads(files['capture-index.json']);old_rows={e['sequence']:e for e in index['ledger'] if 'sequence' in e}
    responses=[]
    day=journal['execution_day'].replace('-','')
    new=[('https://keirin.jp/pc/top',b'<html>authored published current venue</html>',None),
         ('https://keirin.jp/pc/racelist',html(day=day,rows=[dict(raceNo=1,denTime='11:00',stTime='11:03'),
            dict(raceNo=5,denTime='15:20',stTime='15:23'),dict(raceNo=6,denTime='16:00',stTime='16:03')]),
          b'disp=PJ0305&encp=AUTHORED_CURRENT')]
    for sequence,(url,raw,post) in enumerate(new,1):
        at=start+timedelta(seconds=sequence);completed=at+timedelta(milliseconds=300)
        entry=dict(sequence=sequence,url=url,method='GET' if post is None else 'POST',resource_type='document',status=200,
            content_type='text/html;charset=UTF-8',byte_count=len(raw),source_sha256=sha256(raw).hexdigest(),
            request_started_at=at.isoformat(),headers_received_at=(at+timedelta(milliseconds=100)).isoformat(),
            response_received_at=completed.isoformat(),body_captured_at=completed.isoformat(),
            body_file=f'initial-{sequence}.body',metadata_file=f'initial-{sequence}.json')
        meta=dict(source_url=url,final_url=url,method=entry['method'],http_method=entry['method'],resource_type='document',
            status=200,byte_count=len(raw),source_sha256=entry['source_sha256'],fetched_at=entry['request_started_at'],
            response_received_at=entry['body_captured_at'],headers={'content-type':entry['content_type']})
        if post is not None:
            entry.update(request_body_file='initial-request.body',request_body_sha256=sha256(post).hexdigest(),
                request_content_type='application/x-www-form-urlencoded')
            meta.update(**{k:entry[k] for k in ('request_body_file','request_body_sha256','request_content_type')})
            files[entry['request_body_file']]=post
        files[entry['body_file']]=raw;files[entry['metadata_file']]=C.future.wire(meta);responses.append(entry)
    historical=[]
    for old in index['responses']:
        entry=dict(old_rows[old['sequence']],**{k:old[k] for k in ('body_file','metadata_file')})
        entry['sequence']+=2;meta=json.loads(files[entry['metadata_file']]);at=start+timedelta(seconds=entry['sequence']*3)
        completed=at+timedelta(milliseconds=500)
        entry.update(method=meta['method'],resource_type=meta['resource_type'],status=meta['status'],byte_count=meta['byte_count'],
            content_type=meta['headers']['content-type'],source_sha256=meta['source_sha256'],request_started_at=at.isoformat(),
            headers_received_at=(at+timedelta(milliseconds=100)).isoformat(),response_received_at=completed.isoformat(),body_captured_at=completed.isoformat())
        meta.update(fetched_at=entry['request_started_at'],response_received_at=entry['body_captured_at'])
        files[entry['metadata_file']]=C.future.wire(meta);responses.append(entry);historical.append(entry)
    click=dict(event='NORMAL_SEMANTIC_UI_CLICK',label='出走表一覧',before=new[0][0],after=new[1][0],at=(start+timedelta(seconds=4)).isoformat())
    events=[dict(e,at=(start+timedelta(seconds=14)).isoformat()) for e in index['ledger'] if 'sequence' not in e]
    index.update(actual_request_count=4,responses=responses,ledger=deepcopy(responses[:2])+[click]+deepcopy(historical)+events)
    for case in index['cases']:
        for ref in case['responses']:ref['sequence']+=2
        browser=case['browser_metadata'];browser.update(started_at=start.isoformat(),captured_at=(end-timedelta(seconds=1)).isoformat(),
            actual_request_count=4,ledger=deepcopy(historical)+deepcopy(events))
        case['rendered_dom']['captured_at']=browser['captured_at']
    planned=[dict(sport='keirin',race_id=index['cases'][0]['race_id'])]
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);root.chmod(0o700)
        for name,raw in files.items():
            if name in ('capture-index.json','returned-index.canonical.json'):continue
            path=root/name;path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);C._write(path,raw)
        C._write(root/'capture-index.json',C.future.wire(index))
        found,_,originals=C.browser_sources(index,root,planned,started=start,now=end,remaining=16)
        journal.update(captures=[r[2] for r in found],browser_captures=originals)
        journal['browser_attempt']['actual_request_count']=4
        sixteen._refresh_wire_projection(journal,index,root)
    original=open_forecasts(data['old_plan_raw'],key=key);natives=[]
    for sport,(_,_,template,_,_) in fixtures.pairs.templates().items():
        for case in original['cases']:
            if case['sport']==sport:
                native=deepcopy(template);native['snapshot']['race']['race_id']=case['race_id'];native['adapter_lineage']['race_id']=case['race_id'];natives.append(native)
    result=fixtures._result(journal,natives,390002,600,'6'*40,end,original['execution_day'])
    retained=fixtures._journal(journal,390001,600,'6'*40,end+timedelta(seconds=2))
    data['groups']['prior_journal_artifacts'][-1]=retained;data['groups']['checkpoint_artifacts'][-1]=result
    value['previous_source'].update(journal_artifact=fixtures.seed.pin(retained['metadata']),result_artifact=fixtures.seed.pin(result['metadata']))
    context['previous_source']=deepcopy(value['previous_source'])
    return value,data,context,now


class KeirinFutureSelectorTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('race_ai.keirin_future_selector'), 'selector helper is missing')
        return importlib.import_module('race_ai.keirin_future_selector')

    def select(self, *, listing=None, **options):
        journal, evidence = wire_fixture(listing=listing, **options)
        before = deepcopy(journal)
        result = self.api().selector_metadata(journal, evidence, probe_case=CASE, now=NOW)
        self.assertEqual(journal, before)
        return result, journal

    def test_earliest_afternoon_uses_full_list_not_default_selected_race_or_later_old_day(self):
        result, journal = self.select()
        self.assertEqual(result['state'], 'published_selector')
        self.assertEqual((result['case']['race_no'], result['case']['cutoff_at']), (5, '2030-01-15T15:10:00+09:00'))
        self.assertEqual(result['source']['sequence'], 2)
        self.assertEqual(result['source']['body_captured_at'], journal['browser_index']['responses'][1]['body_captured_at'])
        self.assertTrue(result['selector_only']); self.assertFalse(result['fresh_future_input'])
        self.assertTrue(result['fresh_post_f30_capture_required'])
        text = json.dumps(result)
        for forbidden in ('DO_NOT_EXPORT', 'AUTHORED_OPAQUE', 'raw_base64', 'request_body_base64', 'sInfo', 'senNo'):
            self.assertNotIn(forbidden, text)
        self.assertIs(self.api().validate_metadata(result), result)

    def test_start_is_optional_and_legitimate_body_venue_is_not_teacher_case_join(self):
        result, _ = self.select(listing=html(venue='12', rows=[dict(raceNo=8, denTime='15:00', stTime='')]))
        self.assertEqual((result['case']['venue'], result['case']['race_no']), ('keirin-jyo-12', 8))
        self.assertNotIn('published_start_at', result)
        self.assertNotIn('ui_venue_name', result['case'])

    def test_equal_cutoffs_use_race_order_and_default_cancel_does_not_cancel_other_races(self):
        rows=[dict(raceNo=6,denTime='15:00'),dict(raceNo=5,denTime='15:00')]
        raw=html(rows=rows).replace(b'"selRaceNo": 1',b'"selRaceNo": 1,"flgRaceCancel": true')
        result,_=self.select(listing=raw)
        self.assertEqual(result['case']['race_no'],5)
        rows[1]['flgRaceCancel']=True
        result,_=self.select(listing=html(rows=rows))
        self.assertEqual(result['case']['race_no'],6)

    def test_ambiguous_global_click_is_absent_and_case_only_click_cannot_replace_global_evidence(self):
        journal,evidence=wire_fixture()
        change_index(journal,lambda index:index['ledger'].insert(3,deepcopy(index['ledger'][2])))
        evidence['payload_sha256']=digest(journal)
        result=self.api().selector_metadata(journal,evidence,probe_case=CASE,now=NOW)
        self.assertEqual(result['state'],'selector_absent')
        self.assertEqual(result['reason'],'AMBIGUOUS_INITIAL_LIST')
        journal,evidence=wire_fixture(event=False)
        change_index(journal,lambda index:index['cases'][0].update(browser_metadata=dict(ledger=[dict(
            event='NORMAL_SEMANTIC_UI_CLICK',label='出走表一覧',before='https://keirin.jp/pc/top',
            after='https://keirin.jp/pc/racelist',at=NOW.isoformat())])))
        evidence['payload_sha256']=digest(journal)
        result=self.api().selector_metadata(journal,evidence,probe_case=CASE,now=NOW)
        self.assertEqual(result['state'],'selector_absent')

    def test_absent_current_list_or_late_clock_never_fabricates_selector(self):
        for body in (html(day='20300114'), html(rows=[dict(raceNo=1, denTime='', stTime='')]),
                     html(rows=[dict(raceNo=2, denTime='14:59', stTime='15:02')])):
            with self.subTest(body=sha256(body).hexdigest()):
                result, _ = self.select(listing=body)
                self.assertEqual(result['state'], 'selector_absent'); self.assertNotIn('case', result)
        result, _ = self.select(event=False)
        self.assertEqual(result['state'], 'selector_absent')

    def test_malformed_json_identity_clock_duplicate_rows_and_request_scope_reject(self):
        cases = [html().replace(b'"kaisaihi": "20300115"', b'"kaisaihi": "20300114"'),
                 html().replace(b'"keirinCd": "48"', b'"keirinCd": "12"'),
                 html(rows=[dict(raceNo=5, denTime='25:00', stTime='25:03')]),
                 html(rows=[dict(raceNo=5, denTime='15:00', stTime='14:59')]),
                 html(rows=[dict(raceNo=5, denTime='15:00'), dict(raceNo=5, denTime='16:00')]),
                 html(hidden={'hhSelK': '20300114', 'hhSelJ': '48'}),
                 html().replace(b'"selKaisai":', b'"selKaisai":"20300115","selKaisai":')]
        for raw in cases:
            with self.subTest(raw=sha256(raw).hexdigest()), self.assertRaises(ValueError): self.select(listing=raw)
        for post in (b'disp=PJ0306&encp=AUTHORED_OPAQUE', b'disp=PJ0305&disp=PJ0305&encp=AUTHORED_OPAQUE'):
            with self.subTest(post=post), self.assertRaises(ValueError): self.select(request=post)

    def test_transport_hash_inventory_unknown_denial_and_dynamic_replay_reject(self):
        for change in ('body', 'inventory', 'unknown', 'denial', 'payload', 'replay'):
            journal, evidence = wire_fixture()
            if change == 'body': journal['browser_quarantine']['files'][0]['raw_base64'] = base64.b64encode(b'bad').decode()
            elif change == 'inventory': journal['browser_quarantine']['inventory_sha256'] = '0'*64
            elif change == 'unknown': journal['browser_attempt']['actual_request_count'] = None
            elif change == 'denial': journal['browser_index']['ledger'][0]['status'] = 403
            elif change == 'replay': journal['initial_document_replayed'] = True
            else: evidence['payload_sha256'] = '0'*64
            if change != 'payload': evidence['payload_sha256'] = digest(journal)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.api().selector_metadata(journal, evidence, probe_case=CASE, now=NOW)

    def test_nested_output_allowlist_blocks_raw_ids_or_false_future_claim(self):
        result, _ = self.select()
        for change in ('raw', 'ids', 'claim', 'opaque'):
            value = deepcopy(result)
            if change == 'raw': value['raw_base64'] = 'FORBIDDEN'
            elif change == 'ids': value['case']['roster'] = ['123456']
            elif change == 'opaque': value['source']['request_body'] = 'encp=FORBIDDEN'
            else: value['fresh_future_input'] = True
            with self.subTest(change=change), self.assertRaises(ValueError): self.api().validate_metadata(value)

    def test_real_mac_eight_preparation_exports_only_current_list_metadata_in_three_files(self):
        from race_ai import all_existing_model_official_prepare as prepare
        from race_ai.boat_all_model_store import open_forecasts
        from scripts import all_existing_model_official_result_prepare as writer
        from tests.official_result_prepare_fixtures import KEY
        value,data,context,now=deepcopy(_admitted_current_list_fixture())
        before=deepcopy(data)
        result=prepare.prepare_from_evidence(value,data,context=context,run_id=601,head_sha='7'*40,now=now,key=KEY)
        metadata=result['counts']['future_selector']
        self.assertEqual(metadata['state'],'published_selector')
        self.assertEqual(metadata['case']['race_no'],5)
        self.assertEqual(metadata['case']['cutoff_at'],'2030-01-16T15:20:00+09:00')
        self.assertEqual((result['counts']['case_count'],result['counts']['maximum_new_requests']),(8,32))
        self.assertEqual(result['counts']['previous_normal_observation_count'],1)
        self.assertEqual(data,before)
        plan=open_forecasts(result['plan_cipher'],key=KEY)
        self.assertEqual(plan['cases'],open_forecasts(data['old_plan_raw'],key=KEY)['cases'][8:16])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'out';writer.write_outputs(root,result)
            self.assertEqual({p.name for p in root.iterdir()},{'sealedplan.enc','request.json','counts.json'})
        for mutate in ('raw','wrong_pin','single'):
            altered=deepcopy(result)
            if mutate=='raw':altered['counts']['future_selector']['raw_base64']='FORBIDDEN'
            elif mutate=='wrong_pin':altered['counts']['future_selector']['source_journal']['id']+=1
            else:altered['counts']['kind']=prepare.SINGLE
            with self.subTest(mutate=mutate),tempfile.TemporaryDirectory() as directory,self.assertRaises(ValueError):
                writer.write_outputs(Path(directory)/'out',altered)


if __name__ == '__main__': unittest.main()
