"""Invented source fixtures. These tests never establish a live acceptance."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import importlib
import json
import unittest

from tests import test_keirin_official_canary_card as card_tests
from tests.test_keirin_official_form_history import profile, result
from race_ai import keirin_official_canary_card as card_parser
from race_ai import keirin_official_form_history as history_parser


def fixture():
    args, scripts, tab_raw = card_tests.CanaryCardTests().prediction_fixture()
    args['detail_raw'] = args['detail_raw'].replace(b'201.25', b'51.25')
    args['detail_sha256'] = sha256(args['detail_raw']).hexdigest()
    now = args['now'] + timedelta(seconds=10)
    card = card_parser.parse_canary_card(**args)
    request = card_parser.derive_prediction_tab_request(args['detail_raw'], scripts)
    card['sources'].append(dict(kind='PREDICTION_TAB', url=request['url'],
        bytes_sha256=sha256(tab_raw).hexdigest(), captured_at=now.isoformat(), method='GET'))
    raw = {args['calendar_receipt']['expected_sha256']: args['calendar_receipt']['raw_bytes'],
           args['list_sha256']: args['list_raw'], args['detail_sha256']: args['detail_raw'],
           sha256(tab_raw).hexdigest(): tab_raw}
    card['navigation_script_receipts'] = []
    for path, body in scripts.items():
        digest = sha256(body).hexdigest()
        raw[digest] = body
        card['navigation_script_receipts'].append(dict(url='https://keirin.jp'+path,
            bytes_sha256=digest, observed_at=now.isoformat(), status=200, method='GET'))
    manifest = dict(schema='RACE_AI_KEIRIN_OFFICIAL_FORM_CAPTURE_V1',
        state='OFFICIAL_FORM_HISTORY_CAPTURED', target_race_id=card['race_id'],
        captured_at=now.isoformat(), riders=[], source_receipts=[])
    # Six exact result pages, shared by seven invented entrants.
    results = []
    for number in range(1, 7):
        body = result(state='', place='1').decode().replace('2026', '2029')
        for n in range(1, 8):
            body = body.replace(f'00000{n}', f'99{n:04d}')
        body = body.replace('"tyaku": "1", "kojinStateItemSubData": []',
                            '"tyaku": "1", "kojinStateItemSubData": []', 1)
        # Result helper gave the other riders ranks n-1; use distinct n.
        doc = history_parser.receipt._embedded(history_parser._document(body.encode()))
        doc['SC0201']['C0201data']['selRaceNo'] = number
        doc['SJ0326']['digestUrl'] = f'https://wm.st.keirin.jp/wm-keirin81/20291110-81-02-{number:02d}-01-00.mp4'
        for n, row in enumerate(doc['SJ0326']['tyakujyunItemSubData'], 1):
            row['tyaku'] = str(n)
        body = ('<html><body><script>var jsonData = {};'+''.join(
            "jsonData['"+k+"'] = "+json.dumps(v)+';' for k,v in doc.items())+'</script></body></html>').encode()
        digest = sha256(body).hexdigest(); raw[digest] = body
        token = chr(64+number)*43
        manifest['source_receipts'].append(dict(source_url='https://keirin.jp/sp/race',
            method='POST', form_fields={'encp': token, 'disp':'SJ0326'}, http_status=200,
            captured_at=now.isoformat(), bytes_sha256=digest, kind='PROGRAM'))
        results.append((token, digest))
    for rider in card['riders']:
        registration, car = rider['registration_id'], rider['car']
        body = profile(registration).decode().replace('2026/11/20', '2030/01/15')
        body = body.replace('試験選手', rider['name']).replace('51.00', rider['score_raw'])
        body = body.replace('id="UNQ_orlabel_18">3<',
                            'id="UNQ_orlabel_18">'+rider['statistics_raw']['backCnt']+'<')
        old = '<span onclick="btnResultClick(\''+'A'*43+'\')"><img alt="落" src="/sp/static/img/icon/print/setP-normal-raku.png" /></span>'
        new = ''.join('<span onclick="btnResultClick(\''+token+'\')"><img alt="'+str(car)+'" '
                      'src="/sp/static/img/icon/print/setP-normal-raku.png" /></span>' for token,_ in results)
        assert old in body
        body = body.replace(old, new).encode(); digest = sha256(body).hexdigest(); raw[digest] = body
        manifest['source_receipts'].append(dict(source_url='https://keirin.jp/sp/racerracentrecord?snum='+registration,
            method='GET', form_fields=None, http_status=200, captured_at=now.isoformat(),
            bytes_sha256=digest, kind='PROGRAM'))
        parsed = history_parser.parse_profile(body, expected_registration_id=registration, observed_at=now)
        manifest['riders'].append(dict(car=car, registration_id=registration, profile=parsed,
            results=[dict(source_sha256=d, reference_token_sha256=sha256(t.encode()).hexdigest()) for t,d in results]))
    return dict(card_manifest=card, history_manifest=manifest, source_bytes_by_sha=raw, now=now)


def with_newest_result(data, *, fall):
    """Add a seventh published result for one synthetic rider, then capture it."""
    captured = data['history_manifest']['riders'][0]
    sources, raw = data['history_manifest']['source_receipts'], data['source_bytes_by_sha']
    token = 'G'*43
    body = raw[captured['results'][-1]['source_sha256']]
    doc = history_parser.receipt._embedded(history_parser._document(body))
    doc['SC0201']['C0201data']['selRaceNo'] = 7
    doc['SJ0326']['digestUrl'] = 'https://wm.st.keirin.jp/wm-keirin81/20291110-81-02-07-01-00.mp4'
    if fall:
        rows = doc['SJ0326']['tyakujyunItemSubData']
        rows[0].update(tyaku='', kojinStateItemSubData=[dict(kojinState='落車棄権', tyakuNote='')])
        for rank, row in enumerate(rows[1:], 1):
            row['tyaku'] = str(rank)
    body = ('<html><body><script>var jsonData = {};'+''.join(
        "jsonData['"+k+"'] = "+json.dumps(v)+';' for k,v in doc.items())+'</script></body></html>').encode()
    digest = sha256(body).hexdigest(); raw[digest] = body
    sources.append(dict(source_url='https://keirin.jp/sp/race', method='POST',
        form_fields={'encp':token, 'disp':'SJ0326'}, http_status=200,
        captured_at=data['now'].isoformat(), bytes_sha256=digest, kind='PROGRAM'))
    captured['results'].append(dict(source_sha256=digest, reference_token_sha256=sha256(token.encode()).hexdigest()))
    old_sha = captured['profile']['source_sha256']
    profile_raw = raw[old_sha].decode()
    end = '</td></tr></table></td></tr><tr id="RaceResults_2">'
    addition = ('<span onclick="btnResultClick(\''+token+'\')"><img alt="'+('落' if fall else '1')+
                '" src="/sp/static/img/icon/print/setP-normal-raku.png" /></span>')
    assert end in profile_raw
    profile_raw = profile_raw.replace(end, addition+end).encode()
    new_sha = sha256(profile_raw).hexdigest(); raw[new_sha] = profile_raw
    next(r for r in sources if r['bytes_sha256']==old_sha)['bytes_sha256'] = new_sha
    captured['profile'] = history_parser.parse_profile(profile_raw,
        expected_registration_id=captured['registration_id'], observed_at=data['now'])
    return data


class OfficialCanaryJoinTests(unittest.TestCase):
    def join(self, data):
        api = importlib.import_module('race_ai.keirin_official_canary_join')
        return api.build_inputs(**data)

    def test_reparse_all_registration_sources_and_observed_marks(self):
        out = self.join(fixture())
        self.assertEqual(len(out['snapshot']['riders']), 7)
        self.assertEqual(out['snapshot']['riders'][4]['mark_rank'], 'UNMARKED')
        self.assertEqual(out['identity_proof']['verified_riders'], 7)
        self.assertEqual(out['identity_proof']['verified_rider_results'], 42)
        self.assertEqual(len(out['supplement']['condition_evidence']['riders'][0]['results']), 6)
        self.assertFalse(out['identity_proof']['independent_origin_attested'])

    def test_normalized_profile_stats_and_result_claims_are_not_trusted(self):
        data = fixture()
        data['history_manifest']['riders'][0]['profile']['stats']['win_rate_percent'] = 99.9
        data['history_manifest']['riders'][0]['results'][0]['place'] = 7
        out = self.join(data)
        self.assertEqual(out['snapshot']['riders'][0]['recent_form_score'], .285)
        self.assertEqual(out['supplement']['condition_evidence']['riders'][0]['results'][0]['place'], 1)

    def test_normalized_comment_claim_is_rebuilt_from_registered_official_tab(self):
        data = fixture()
        data['card_manifest']['riders'][0]['comment_raw'] = 'fabricated recovery claim'
        out = self.join(data)
        comments = out['supplement']['condition_evidence']['riders'][0]['comments']
        self.assertEqual(comments[0]['text'], '架空コメント')
        self.assertEqual(comments[0]['speaker'], 'MEDIA')
        self.assertEqual(comments[0]['source_sha256'], out['identity_proof']['bindings'][0]['marks_sha256'])

    def test_raw_profile_stat_disagreement_with_card_is_rejected_even_with_valid_sha(self):
        data = fixture()
        captured = data['history_manifest']['riders'][0]
        old_sha = captured['profile']['source_sha256']
        raw = data['source_bytes_by_sha'][old_sha]
        changed = raw.replace(b'id="UNQ_orlabel_19">51.25<', b'id="UNQ_orlabel_19">50.25<')
        self.assertNotEqual(raw, changed)
        digest = sha256(changed).hexdigest()
        data['source_bytes_by_sha'][digest] = changed
        captured['profile']['source_sha256'] = digest
        next(r for r in data['history_manifest']['source_receipts']
             if r['bytes_sha256']==old_sha)['bytes_sha256'] = digest
        with self.assertRaisesRegex(ValueError, 'STATISTICS_DISAGREE'):
            self.join(data)

    def test_car_only_or_other_registration_join_is_rejected(self):
        for changed in (None, '999999'):
            data = fixture(); data['history_manifest']['riders'][0]['registration_id'] = changed
            with self.assertRaisesRegex(ValueError, 'REGISTRATION'):
                self.join(data)

    def test_actual_source_mutation_is_rejected(self):
        data = fixture(); digest = data['history_manifest']['riders'][0]['profile']['source_sha256']
        data['source_bytes_by_sha'][digest] += b'changed'
        with self.assertRaisesRegex(ValueError, 'SHA'):
            self.join(data)

    def test_unpublished_history_token_is_rejected(self):
        data = fixture(); data['history_manifest']['riders'][0]['results'][0]['reference_token_sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'REFERENCE'):
            self.join(data)

    def test_receipt_after_forecast_is_rejected(self):
        data = fixture(); data['history_manifest']['source_receipts'][0]['captured_at'] = (data['now']+timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ValueError, 'CAPTURE'):
            self.join(data)

    def test_absence_duration_unknown_is_preserved_and_not_invented(self):
        out = self.join(fixture())
        self.assertEqual(out['supplement']['condition_evidence']['riders'][0]['absences'], [])
        self.assertGreater(out['availability']['absence_records_without_verified_period'], 0)

    def test_missing_sixth_result_holds_the_complete_canary(self):
        data = fixture(); data['history_manifest']['riders'][0]['results'].pop()
        with self.assertRaisesRegex(ValueError, 'SIX'):
            self.join(data)

    def test_manifest_cannot_remove_published_fall_even_with_six_normal_finishes(self):
        data = with_newest_result(fixture(), fall=True)
        self.assertEqual(self.join(data)['identity_proof']['verified_rider_results'], 43)
        data['history_manifest']['riders'][0]['results'].pop()
        with self.assertRaisesRegex(ValueError, 'SELECTION_OMITS_PUBLISHED_RESULT'):
            self.join(data)

    def test_manifest_cannot_substitute_older_finishes_for_published_latest_result(self):
        data = with_newest_result(fixture(), fall=False)
        self.assertEqual(self.join(data)['identity_proof']['verified_rider_results'], 43)
        data['history_manifest']['riders'][0]['results'].pop()
        with self.assertRaisesRegex(ValueError, 'SELECTION_OMITS_PUBLISHED_RESULT'):
            self.join(data)


if __name__ == '__main__':
    unittest.main()
