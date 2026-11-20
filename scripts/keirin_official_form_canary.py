"""The owner's fixed future-race trial, using ordinary official public pages.

Only a trusted main-branch Actions job can capture or settle this one race.
Plain sources and four-arm predictions remain private; Git receives only the
existing owner-key envelopes and bounded hash/count receipts. The repository's
global opt-ins, secrets, branch protection and model are never changed here.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from race_ai import keirin_form_fall_blind_pdca as pdca
from race_ai import keirin_form_fall_shadow as condition
from race_ai import keirin_github_origin_evidence as origin
from race_ai import keirin_github_provider_stop as provider_stop
from race_ai import keirin_nationwide_auto_generator as core
from race_ai import keirin_nationwide_auto_settlement as baseline_decrypt
from race_ai import keirin_nationwide_auto_storage as storage
from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_canary_card as card_source
from race_ai import keirin_official_canary_join as join
from race_ai import keirin_official_form_history as form
from race_ai import keirin_official_reviewed_pdf as payout_unit
from race_ai import keirin_official_run_history as history
from scripts import keirin_capture_official_form_history as history_capture
from scripts import keirin_github_only_ab_day as day_report
from scripts import keirin_official_day_pipeline as day_pipeline

RACE = origin.FORM_CANARY_RACE
CUTOFF = origin.FORM_CANARY_CUTOFF
DAY = '2026-11-20'
PRE_CUTOFF_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_FORM_CANARY_PRE_CUTOFF_V1'
SETTLEMENT_SCHEMA = 'RACE_AI_KEIRIN_OFFICIAL_FORM_CANARY_SETTLEMENT_V1'
COHORT = dict(schema='RACE_AI_KEIRIN_FIXED_FORM_CANARY_COHORT_V1', day_jst=DAY,
              race_ids=[RACE], official_cutoff_at=CUTOFF, max_tickets_per_arm=12)


class CanaryError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise CanaryError(code)


def utc_now():
    return datetime.now(timezone.utc)


def check_runtime(mode, now):
    need(mode in ('capture', 'settle') and isinstance(now, datetime) and
         now.utcoffset() is not None, 'CANARY_MODE_OR_CLOCK_INVALID')
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and
         os.environ.get('GITHUB_REPOSITORY') == origin.FORM_CANARY_POLICY.repository_full_name and
         os.environ.get('GITHUB_REPOSITORY_ID') == str(origin.FORM_CANARY_POLICY.repository_id) and
         os.environ.get('GITHUB_REF') == 'refs/heads/main' and
         os.environ.get('GITHUB_EVENT_NAME') in origin.FORM_CANARY_POLICY.allowed_events and
         archive.RUN.fullmatch(os.environ.get('GITHUB_RUN_ID', '')) is not None and
         archive.COMMIT.fullmatch(os.environ.get('GITHUB_SHA', '')) is not None,
         'MAIN_ONLY_CANARY_RUNTIME_REQUIRED')
    need(origin.form_canary_window(now)[mode], 'FIXED_CANARY_RUNTIME_WINDOW_CLOSED')
    need(os.environ.get('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED') == 'true',
         'SCOPED_CANARY_GIT_STORE_GATE_REQUIRED')


def _report(state='HOLD_CANARY_NOT_STARTED'):
    return dict(schema=day_report.SCHEMA, day_jst=DAY, state=state,
                registered_races=1, new_A_B_sealed=0, new_A_B_git_archived=0,
                new_conditioned_A_B_git_archived=0, new_encrypted_originals=[],
                server_origin_verified=False, paired_comparable_races=0,
                nationwide_expansion_gate_passed=False, source_or_forecast_plaintext_exposed=False)


def _private_root(path):
    return history_capture._private_directory(path)


def _json_bytes(value):
    return core.canonical(value) + b'\n'


def _json_save(path, value):
    history_capture._save_once(path, _json_bytes(value))


def _load_sources(*directories):
    result, total = {}, 0
    for folder in directories:
        for path in sorted(Path(folder).iterdir()):
            if not re.fullmatch(r'[0-9a-f]{64}\.(bin|html|headers)', path.name):
                continue
            need(not path.is_symlink() and path.is_file() and
                 0 < path.stat().st_size <= 8_000_000, 'CANARY_SOURCE_FILE_INVALID')
            raw = path.read_bytes()
            digest = sha256(raw).hexdigest()
            need(path.stem == digest, 'CANARY_SOURCE_BYTES_CHANGED')
            need(digest not in result or result[digest] == raw, 'CANARY_SOURCE_SHA_CONFLICT')
            if digest not in result:
                result[digest] = raw
                total += len(raw)
            need(len(result) <= 400 and total <= 11_000_000, 'CANARY_SOURCE_BUNDLE_TOO_LARGE')
    return result


def _existing_baseline(repo):
    checked_repo = archive._remote(repo, synthetic_local=False)
    head = archive._refresh(checked_repo)
    metadata = archive.read_blob_bytes(checked_repo, head, archive._refs(RACE)[1], max_bytes=16384)
    if metadata is None:
        need(archive.read_blob_bytes(checked_repo, head, archive._refs(RACE)[0]) is None,
             'CANARY_ORPHAN_BASELINE_CIPHER')
        return None
    item = json.loads(metadata)
    archive._read_at(checked_repo, head, RACE, item['cipher_sha256'])
    return item


def _provider_preflight(repo):
    need(provider_stop.read_for_observed_day(repo=repo, day=DAY) is None,
         'CANARY_PERSISTENT_PROVIDER_STOP')


def _persist_denial(repo, clock, *, status=None, challenge=False):
    if status in (401, 403, 407, 429) or challenge:
        provider_stop.record_denial(repo=repo, code=provider_stop.DENIED,
                                   observed_at=clock().isoformat())
        raise CanaryError('CANARY_PROVIDER_DENIED_PERSISTED_NO_RETRY')


def freeze_package(*, inputs, card_manifest, history_manifest, source_bytes_by_sha,
                   private_root, public_pem, generated_at, sealed_at,
                   producer_run_id, producer_commit):
    """Seal four already-defined arms and exact input evidence, never public JSON."""
    snapshot, supplement = inputs['snapshot'], inputs['supplement']
    need(snapshot['race_id'] == RACE and snapshot['published_cutoff_at'] == CUTOFF and
         supplement['race_id'] == RACE, 'FIXED_CANARY_RACE_OR_CUTOFF_REQUIRED')
    need(core.when(generated_at).astimezone(form.JST).date().isoformat() == DAY and
         (core.when(CUTOFF)-core.when(sealed_at)).total_seconds() >= 65,
         'CANARY_NOT_SAVED_BEFORE_CUTOFF')
    need(archive.RUN.fullmatch(producer_run_id) is not None and
         archive.COMMIT.fullmatch(producer_commit) is not None, 'CANARY_PRODUCER_ID_INVALID')
    need(type(source_bytes_by_sha) is dict and all(
        type(k) is str and core.SHA.fullmatch(k) is not None and type(v) is bytes and
        sha256(v).hexdigest() == k for k, v in source_bytes_by_sha.items()),
        'CANARY_ORIGINAL_SOURCE_BYTES_REQUIRED')
    root = _private_root(private_root)
    storage.checked_public_key(public_pem)
    baseline = core.generate_A_B(snapshot, generated_at=generated_at, max_tickets=12)
    conditioned = condition.generate_shadow(snapshot, supplement, baseline=baseline,
                                             generated_at=generated_at)
    base_path, form_path = root/(RACE+'.sealed.json'), root/(RACE+'.form.sealed.json')
    base_seal = storage.seal_once(snapshot=snapshot, prediction=baseline,
        public_key_pem=public_pem, path=base_path, sealed_at=sealed_at)
    form_seal = condition.seal_shadow_once(snapshot=snapshot, supplement=supplement,
        shadow=conditioned, public_key_pem=public_pem, path=form_path, sealed_at=sealed_at)
    report = _report('FOUR_ARMS_SEALED_AWAITING_GITHUB_ARCHIVE_AND_SERVER_PROOF')
    report['new_A_B_sealed'] = 1
    record = dict(race_id=RACE, cipher_sha256=base_seal['cipher_sha256'],
        cohort_sha256=core.digest(COHORT), conditioned_state='PRIVATE_CONDITIONED_SHADOW_SEALED',
        conditioned_cipher_sha256=form_seal['file_sha256'],
        baseline_prediction_sha256=baseline['prediction_sha256'])
    report['new_encrypted_originals'] = [record]
    payload = dict(schema=PRE_CUTOFF_SCHEMA, day_jst=DAY, race_id=RACE,
        cohort=COHORT, cohort_sha256=core.digest(COHORT),
        producer_run_id=producer_run_id, producer_commit=producer_commit,
        baseline_sealed_at=sealed_at, conditioned_sealed_at=sealed_at,
        card_manifest=card_manifest, history_manifest=history_manifest,
        source_bytes_by_sha=source_bytes_by_sha, snapshot=snapshot, supplement=supplement,
        identity_proof=inputs['identity_proof'], availability=inputs['availability'],
        baseline=baseline, conditioned=conditioned,
        baseline_cipher_sha256=base_seal['cipher_sha256'],
        conditioned_cipher_sha256=form_seal['file_sha256'], safe_report=report)
    evidence_cipher = history.seal_evidence(day_pipeline.private_snapshot_json(payload),
                                           public_pem, DAY, sealed_at)
    evidence_path = root/(sha256(evidence_cipher).hexdigest()+'.evidence.sealed.json')
    history_capture._save_once(evidence_path, evidence_cipher)
    return dict(payload=payload, safe_report=report, evidence_cipher=evidence_cipher,
        baseline_cipher=base_path.read_bytes(), conditioned_cipher=form_path.read_bytes(),
        baseline_cipher_sha256=base_seal['cipher_sha256'],
        conditioned_cipher_sha256=form_seal['file_sha256'])


def decrypt_conditioned(raw, *, expected_sha256, owner_private_pem, baseline):
    """Authenticate the original shadow envelope and compare its frozen parent."""
    need(type(raw) is bytes and 0 < len(raw) < 2_000_000 and
         sha256(raw).hexdigest() == expected_sha256, 'CANARY_CONDITIONED_CIPHER_SHA_INVALID')
    doc = baseline_decrypt._json(raw)
    need(doc.get('schema') == condition.SEALED_SCHEMA and doc.get('race_id') == RACE and
         doc.get('original_baseline_sha256') == baseline['prediction_sha256'] and
         doc.get('owner_spki_sha256') == storage.PINNED_OWNER_SPKI_SHA256 and
         doc.get('actual_official_result_included') is False,
         'CANARY_CONDITIONED_PARENT_INVALID')
    key = serialization.load_pem_private_key(owner_private_pem, password=None)
    need(isinstance(key, rsa.RSAPrivateKey) and key.key_size >= 3072,
         'CANARY_OWNER_PRIVATE_RSA_REQUIRED')
    der = key.public_key().public_bytes(serialization.Encoding.DER,
                                       serialization.PublicFormat.SubjectPublicKeyInfo)
    need(sha256(der).hexdigest() == storage.PINNED_OWNER_SPKI_SHA256,
         'CANARY_OWNER_PRIVATE_PIN_MISMATCH')
    aad = ('RACE_AI_FORM_FALL_V1|'+RACE+'|'+baseline['prediction_sha256']).encode()
    need(doc.get('aad_ascii') == aad.decode() and doc.get('generated_at') == baseline['generated_at'] and
         doc.get('cutoff_at') == CUTOFF and
         core.when(doc['generated_at']) <= core.when(doc['sealed_at']) and
         (core.when(CUTOFF)-core.when(doc['sealed_at'])).total_seconds() >= 65,
         'CANARY_CONDITIONED_TIME_OR_AAD_INVALID')
    try:
        aes = key.decrypt(base64.b64decode(doc['rsa_wrapped_aes_key_b64'], validate=True),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                         algorithm=hashes.SHA256(), label=None))
        need(len(aes) == 32, 'CANARY_AES_256_REQUIRED')
        cipher = base64.b64decode(doc['ciphertext_b64'], validate=True)
        need(sha256(cipher).hexdigest() == doc['ciphertext_sha256'], 'CANARY_CONDITIONED_SHA_INVALID')
        zipped = AESGCM(aes).decrypt(base64.b64decode(doc['nonce_b64'], validate=True), cipher, aad)
        decompressor = zlib.decompressobj()
        plain = decompressor.decompress(zipped, 2_000_001)
        need(len(plain) <= 2_000_000 and decompressor.eof and not decompressor.unused_data and
             not decompressor.unconsumed_tail and sha256(plain).hexdigest() == doc['private_shadow_plaintext_sha256'],
             'CANARY_CONDITIONED_PLAINTEXT_INVALID')
    except (ValueError, InvalidTag, zlib.error, KeyError, TypeError):
        raise CanaryError('CANARY_CONDITIONED_DECRYPTION_FAILED') from None
    result = baseline_decrypt._json(plain)
    need(set(result) == {'shadow', 'supplement'} and
         result['shadow'].get('baseline_prediction_sha256') == baseline['prediction_sha256'] and
         result['shadow'].get('sha256') == core.digest({k:v for k,v in result['shadow'].items() if k != 'sha256'}) and
         result['shadow'].get('condition_supplement_sha256') == core.digest(result['supplement']),
         'CANARY_CONDITIONED_DECRYPTED_LINEAGE_INVALID')
    return result


def run_capture(*, repo, private_root, owner_public_pem, clock=utc_now):
    check_runtime('capture', clock())
    root = _private_root(private_root)
    public = Path(owner_public_pem).read_bytes()
    storage.checked_public_key(public)
    prior = _existing_baseline(repo)
    if prior is not None:
        return _report('EXISTING_CANARY_ORIGINAL_PRESERVED_NO_REFORECAST')
    _provider_preflight(repo)
    need((core.when(CUTOFF)-clock()).total_seconds() >= 390, 'CANARY_CAPTURE_START_MARGIN_REQUIRED')
    card_dir, history_dir, sealed_dir = root/'card', root/'history', root/'sealed'
    for path in (card_dir, history_dir, sealed_dir):
        _private_root(path)
    report = card_source.collect_canary_card_http(card_dir, venue_code=81, race_number=5,
                                                 clock=clock, include_prediction_tab=True)
    for status in report.get('status_counts', {}):
        _persist_denial(repo, clock, status=int(status))
    _persist_denial(repo, clock, challenge=report.get('state') == 'HOLD_PUBLIC_FORM_CHALLENGE_REFUSED')
    need(report.get('canary_card_saved') is True and report.get('marks_source_verified') is True,
         'CANARY_OFFICIAL_CARD_OR_MARKS_INCOMPLETE')
    card_file = card_dir/(report['card_sha256']+'.json')
    card_raw = card_file.read_bytes()
    need(sha256(card_raw).hexdigest() == report['card_sha256'], 'CANARY_CARD_MANIFEST_SHA_CHANGED')
    card = json.loads(card_raw)
    need(card['race_id'] == RACE and card['official_cutoff_at'] == CUTOFF,
         'FIXED_CANARY_RACE_OR_CUTOFF_REQUIRED')
    collector = history_capture.OfficialHistoryCapture(history_dir, cutoff_at=CUTOFF,
        target_race_id=RACE, max_requests=150)
    manifest = dict(schema='RACE_AI_KEIRIN_OFFICIAL_FORM_CAPTURE_V1',
                    state='PARTIAL_CAPTURE_IN_PROGRESS', target_race_id=RACE, riders=[])
    try:
        for rider in card['riders']:
            manifest['riders'].append(collector.capture_rider(car=rider['car'],
                                            registration_id=rider['registration_id']))
            checkpoint = dict(manifest, source_receipts=collector.receipts,
                              captured_at=clock().isoformat())
            raw = _json_bytes(checkpoint)
            history_capture._save_once(history_dir/(sha256(raw).hexdigest()+'.checkpoint.json'), raw)
        collector.check()
        manifest.update(state='OFFICIAL_FORM_HISTORY_CAPTURED', source_receipts=collector.receipts,
                        captured_at=clock().isoformat())
        manifest_raw = _json_bytes(manifest)
        history_capture._save_once(history_dir/(sha256(manifest_raw).hexdigest()+'.form-capture.json'), manifest_raw)
    except (ValueError, OSError) as exc:
        _persist_denial(repo, clock, challenge=str(exc) in
                        ('HOLD_PROVIDER_DENIED', 'HOLD_PROVIDER_CHALLENGE'))
        raise
    finally:
        collector.cookie_path.unlink(missing_ok=True)
    sources = _load_sources(card_dir, history_dir)
    now = clock()
    inputs = join.build_inputs(card_manifest=card, history_manifest=manifest,
                               source_bytes_by_sha=sources, now=now)
    package = freeze_package(inputs=inputs, card_manifest=card, history_manifest=manifest,
        source_bytes_by_sha=sources, private_root=sealed_dir, public_pem=public,
        generated_at=now.isoformat(), sealed_at=clock().isoformat(),
        producer_run_id=os.environ['GITHUB_RUN_ID'], producer_commit=os.environ['GITHUB_SHA'])
    check_runtime('capture', clock())
    saved_base = archive.append_once(repo=repo, raw_cipher=package['baseline_cipher'],
        expected_cipher_sha256=package['baseline_cipher_sha256'],
        producer_run_id=os.environ['GITHUB_RUN_ID'], producer_commit=os.environ['GITHUB_SHA'],
        cohort_sha256=core.digest(COHORT))
    need(saved_base['state'] == 'GIT_ORIGINAL_CREATE_ONCE_AND_RESTORED', 'CANARY_BASELINE_NOT_NEWLY_FROZEN')
    saved_condition = archive.append_conditioned_once(repo=repo,
        raw_cipher=package['conditioned_cipher'],
        expected_cipher_sha256=package['conditioned_cipher_sha256'],
        expected_baseline_cipher_sha256=package['baseline_cipher_sha256'],
        expected_baseline_prediction_sha256=package['payload']['baseline']['prediction_sha256'],
        cohort_sha256=core.digest(COHORT), producer_run_id=os.environ['GITHUB_RUN_ID'],
        producer_commit=os.environ['GITHUB_SHA'])
    need(saved_condition['state'] == 'GIT_CONDITIONED_ORIGINAL_CREATE_ONCE_AND_RESTORED',
         'CANARY_CONDITIONED_NOT_NEWLY_FROZEN')
    evidence_saved = history.append_revision(repo=repo, day=DAY,
        raw_cipher=package['evidence_cipher'], safe_report=package['safe_report'])
    check_runtime('capture', clock())
    final = dict(package['safe_report'])
    final.update(state='CANARY_FOUR_ARMS_ARCHIVED_AWAITING_SERVER_READBACK',
                 new_A_B_git_archived=1, new_conditioned_A_B_git_archived=1,
                 source_evidence_cipher_sha256=evidence_saved['cipher_sha256'])
    final['new_encrypted_originals'] = [dict(package['safe_report']['new_encrypted_originals'][0],
        conditioned_state=saved_condition['state'])]
    return final


def collect_final_result(*, repo, private_root, frozen_card, clock=utc_now, request=None):
    """Follow the actual calendar/list result button after the target's cutoff."""
    _provider_preflight(repo)
    root = _private_root(private_root)
    need(frozen_card['race_id'] == RACE and frozen_card['official_cutoff_at'] == CUTOFF and
         clock() > core.when(CUTOFF), 'CANARY_RESULT_BEFORE_FIXED_CUTOFF')
    transport = None
    if request is None:
        transport = card_source._CurlPublicSession(str(root), clock)
        request = transport.request
    sources, receipts = {}, []
    calendar, sp = card_source.calendar, card_source.receipt

    def read(path, fields=None, referer=None):
        # Every route below is a fixed observed public form/script, except the
        # exact organizer guide already present in the reviewed unit registry.
        allowed = {'/sp/raceschedule', '/sp/racelist', '/sp/race',
            '/sp/static/js/SJ0201.js', '/sp/static/js/commonSubmit.js',
            '/sp/static/js/SJ0301_c.js', '/sp/static/js/SJ0301_v.js'}
        need(path in allowed or path == 'https://www.hofukeirin.jp/ticket/',
             'CANARY_RESULT_UNOBSERVED_ROUTE')
        url = 'https://keirin.jp'+path if path.startswith('/') else path
        response = request(url, fields, referer)
        code = response['status']
        _persist_denial(repo, clock, status=code)
        need(type(code) is int and code == 200 and response['url'] == url,
             'CANARY_RESULT_HTTP_OR_REDIRECT_INVALID')
        raw = response['raw']
        need(type(raw) is bytes and 0 < len(raw) <= calendar.MAX_HTML_BYTES,
             'CANARY_RESULT_SOURCE_BYTES_INVALID')
        _persist_denial(repo, clock, challenge=card_source.browser_source._CHALLENGE.search(
            raw.decode('utf-8', 'replace')) is not None)
        at = form._aware(response['observed_at'])
        need(core.when(CUTOFF) < at <= clock(), 'CANARY_RESULT_CAPTURE_CLOCK_INVALID')
        digest = sha256(raw).hexdigest()
        sources[digest] = raw
        history_capture._save_once(root/(digest+'.bin'), raw)
        provenance = dict(source_url=url, method='POST' if fields is not None else 'GET',
            form_fields=fields, bytes_sha256=digest, captured_at=at.isoformat(), http_status=code)
        receipts.append(provenance)
        _json_save(root/(sha256(_json_bytes(provenance)).hexdigest()+'.json'), provenance)
        return dict(raw_bytes=raw, observed_at=at, expected_sha256=digest, receipt=provenance)

    def script(document, path, parts):
        nodes = card_source.browser_source._document(document['raw_bytes']).nodes
        need(any(n.tag == 'script' and n.attrs.get('src') == path for n in nodes),
             'CANARY_RESULT_SCRIPT_NOT_LINKED')
        source = read(path)
        text = re.sub(r'\s+', '', source['raw_bytes'].decode('utf-8', 'strict'))
        need(all(part in text for part in parts), 'CANARY_RESULT_SCRIPT_CHANGED')

    try:
        cal = read('/sp/raceschedule')
        bound = {key: cal[key] for key in ('raw_bytes', 'observed_at', 'expected_sha256')}
        projection = calendar.project_day(calendar.parse_calendar(cal['raw_bytes'],
            source_url=calendar.OFFICIAL_DOCUMENT, body_sha256=cal['expected_sha256'],
            received_at=cal['observed_at'], now=clock(), http_status=200), event_day=DAY)
        candidates = [r for r in projection['calendar_meeting_candidates'] if r['venue_code'] == 81]
        need(len(candidates) == 1, 'CANARY_RESULT_CURRENT_MEETING_UNAVAILABLE')
        script(cal, '/sp/static/js/SJ0201.js', ('params["encp"]=encp;',
            'params["disp"]="SJ0301";', 'commonSubmit.formPost(next,params,null);'))
        script(cal, '/sp/static/js/commonSubmit.js', ('.attr("method","post")',))
        nodes = [n for n in card_source.browser_source._document(cal['raw_bytes']).nodes if n.tag == 'table'
                 and sha256(calendar._attribute(n, 'onclick').encode()).hexdigest() ==
                 candidates[0]['navigation_reference_sha256']]
        need(len(nodes) == 1, 'CANARY_RESULT_CALENDAR_CONTROL_INVALID')
        match = calendar._REFERENCE.fullmatch(calendar._attribute(nodes[0], 'onclick'))
        need(match is not None, 'CANARY_RESULT_CALENDAR_CONTROL_INVALID')
        listed = read('/sp/racelist', [('encp', match[1]), ('disp', 'SJ0301')], calendar.OFFICIAL_DOCUMENT)
        parsed = sp.parse_race_list(listed['raw_bytes'], expected_day=DAY, expected_venue_code=81,
            observed_at=listed['observed_at'], expected_sha256=listed['expected_sha256'], calendar_receipt=bound)
        script(listed, '/sp/static/js/SJ0301_v.js',
            ('raceProgram.strRaceLnk', 'raceProgram.strRaceLnkPrm', 'raceProgram.strRaceLnkKbn'))
        script(listed, '/sp/static/js/SJ0301_c.js',
            ('varaction=$(children[1]).attr("value");', 'params["encp"]=$(children[2]).attr("value");',
             'if(dispDI==2){dispDI="SJ0326";}', 'commonSubmit.formPost(action,params);'))
        rows = [r for r in parsed['race_references'] if r['race_no'] == 5]
        need(len(rows) == 1 and rows[0]['path'] == '/sp/race', 'CANARY_RESULT_REFERENCE_MISSING')
        need(rows[0]['link_kind'] == '2', 'CANARY_OFFICIAL_RESULT_NOT_PUBLISHED_YET')
        token = rows[0]['opaque_reference']
        guide = read('https://www.hofukeirin.jp/ticket/')
        unit_url = guide['receipt']['source_url']
        exact = payout_unit.UNIT_URLS[unit_url]
        need(exact.encode('utf-8') in guide['raw_bytes'], 'CANARY_OFFICIAL_PAYOUT_UNIT_MISSING')
        unit = dict(url=unit_url, source_sha256=guide['expected_sha256'],
                    observed_at=guide['observed_at'].isoformat(), verified_payout_basis_yen=100,
                    exact_excerpt=exact)
        # Keep the guide's actual capture time before the result observation;
        # neither clock is backdated to manufacture monetary eligibility.
        detail = read('/sp/race', [('encp', token), ('disp', 'SJ0326')], 'https://keirin.jp/sp/racelist')
        reference = dict(source_url='https://keirin.jp/sp/race', method='POST', disp='SJ0326',
            token=token, official_cutoff_at=CUTOFF,
            starters=[dict(car=r['car'], registration_id=r['registration_id']) for r in frozen_card['riders']])
        return dict(raw_result=detail['raw_bytes'], observed_at=detail['observed_at'].isoformat(),
            expected_reference=reference, unit_evidence=unit,
            source_bytes_by_sha=sources, source_receipts=receipts)
    finally:
        if transport is not None:
            transport.close()


def _load_original_bundle(repo, private_pem):
    found, settled = [], []
    for saved in history.read_revisions(repo=repo, day=DAY):
        payload = day_pipeline.restore_private_snapshot_json(
            history.decrypt_evidence(saved['raw_cipher'], private_pem))
        if payload.get('schema') == PRE_CUTOFF_SCHEMA:
            need(payload.get('day_jst') == DAY and payload.get('race_id') == RACE and
                 payload.get('producer_run_id') == saved['receipt'].get('producer_run_id'),
                 'CANARY_FROZEN_EVIDENCE_PRODUCER_INVALID')
            found.append((payload, saved['receipt']))
        elif payload.get('schema') == SETTLEMENT_SCHEMA:
            need(payload.get('day_jst') == DAY and payload.get('race_id') == RACE,
                 'CANARY_SAVED_SETTLEMENT_SCOPE_INVALID')
            settled.append((payload, saved['receipt']))
    need(len(found) == 1, 'CANARY_ONE_AUTHENTICATED_FROZEN_BUNDLE_REQUIRED')
    return found[0][0], found[0][1], settled


def _archived_pair(repo, payload):
    checked_repo = archive._remote(repo, synthetic_local=False)
    head = archive._refresh(checked_repo)
    base_receipt = archive._read_at(checked_repo, head, RACE, payload['baseline_cipher_sha256'])
    need(base_receipt is not None and base_receipt['producer_run_id'] == payload['producer_run_id'] and
         base_receipt['producer_commit'] == payload['producer_commit'] and
         base_receipt.get('cohort_sha256') == payload['cohort_sha256'] == core.digest(COHORT),
         'CANARY_ARCHIVED_BASELINE_LINEAGE_INVALID')
    archive._read_conditioned_at(checked_repo, head, RACE, payload['conditioned_cipher_sha256'],
        payload['baseline_cipher_sha256'], payload['baseline']['prediction_sha256'], payload['cohort_sha256'])
    base = archive.read_blob_bytes(checked_repo, head, archive._refs(RACE)[0])
    conditioned = archive.read_blob_bytes(checked_repo, head, archive._form_refs(RACE)[0])
    need(base is not None and conditioned is not None, 'CANARY_ARCHIVED_PAIR_MISSING')
    return base, conditioned, base_receipt


def _verify_origins(payload, raw_base, raw_conditioned, packets):
    common = dict(race_id=RACE, official_cutoff_at=CUTOFF,
        expected_producer_run_id=payload['producer_run_id'],
        expected_producer_commit=payload['producer_commit'],
        producer=packets['producer'], readback=packets['readback'], policy=origin.FORM_CANARY_POLICY)
    base = origin.verify_origin_evidence(raw_cipher=raw_base,
        expected_cipher_sha256=payload['baseline_cipher_sha256'], **common)
    conditioned = origin.verify_conditioned_origin_evidence(raw_baseline_cipher=raw_base,
        expected_baseline_cipher_sha256=payload['baseline_cipher_sha256'],
        raw_conditioned_cipher=raw_conditioned,
        expected_conditioned_cipher_sha256=payload['conditioned_cipher_sha256'],
        expected_baseline_prediction_sha256=payload['baseline']['prediction_sha256'],
        cohort_sha256=payload['cohort_sha256'], **common)
    return base, conditioned


def compare_frozen(*, payload, raw_baseline, raw_conditioned, owner_private_pem,
                   packets, final_capture):
    """Score authenticated frozen predictions; result data never enters a model."""
    need(payload.get('schema') == PRE_CUTOFF_SCHEMA and payload.get('race_id') == RACE and
         payload.get('day_jst') == DAY and payload.get('cohort') == COHORT and
         payload.get('cohort_sha256') == core.digest(COHORT), 'CANARY_FROZEN_BUNDLE_SCOPE_INVALID')
    inputs = join.build_inputs(card_manifest=payload['card_manifest'],
        history_manifest=payload['history_manifest'], source_bytes_by_sha=payload['source_bytes_by_sha'],
        now=payload['baseline']['generated_at'])
    need(all(inputs[key] == payload[key] for key in ('snapshot', 'supplement', 'identity_proof', 'availability')),
         'CANARY_FROZEN_SOURCE_REPARSE_CHANGED')
    base_envelope, baseline, starters = baseline_decrypt.decrypt_original_pair(
        raw_cipher=raw_baseline, expected_cipher_sha256=payload['baseline_cipher_sha256'],
        owner_private_pem=owner_private_pem)
    adjusted = decrypt_conditioned(raw_conditioned,
        expected_sha256=payload['conditioned_cipher_sha256'], owner_private_pem=owner_private_pem,
        baseline=baseline)
    need(baseline == payload['baseline'] and adjusted['shadow'] == payload['conditioned'] and
         adjusted['supplement'] == payload['supplement'] and
         baseline['source_facts_sha256'] == base_envelope['original_source_sha256'] == core.digest(inputs['snapshot']) and
         base_envelope['sealed_at'] == payload['baseline_sealed_at'] and
         json.loads(raw_conditioned)['sealed_at'] == payload['conditioned_sealed_at'],
         'CANARY_AUTHENTICATED_ORIGINALS_DIFFER_FROM_BUNDLE')
    base_origin, conditioned_origin = _verify_origins(payload, raw_baseline, raw_conditioned, packets)

    def reparse_final():
        return form.parse_final_result(final_capture['raw_result'], expected_race_id=RACE,
            observed_at=final_capture['observed_at'], expected_reference=final_capture['expected_reference'],
            verified_unit_evidence=final_capture['unit_evidence'],
            source_bytes_by_sha=final_capture['source_bytes_by_sha'])

    final = reparse_final()
    original_ids = {r['car']:r['athlete_id'] for r in inputs['snapshot']['riders']}
    need(final['monetary_comparison_eligible'] is True and
         {r['car'] for r in final['starters']} == starters and
         {r['car']:r['registration_id'] for r in final['starters']} == original_ids,
         'CANARY_MONETARY_OR_REGISTERED_ROSTER_COMPARISON_UNVERIFIED')
    official_receipt = dict(race_id=RACE, source_sha256=final['source_sha256'],
        observed_at=final['observed_at'], payout_unit_source_sha256=final['payout_unit_evidence']['source_sha256'])
    row = dict(baseline=baseline, conditioned=adjusted['shadow'], result=final,
        starters=sorted(starters), baseline_sealed_at=payload['baseline_sealed_at'],
        conditioned_sealed_at=payload['conditioned_sealed_at'],
        verified_receipts=dict(baseline_origin=base_origin, condition_origin=conditioned_origin,
                               official_final=official_receipt))

    def verify_base(rid, joined, witness):
        return (rid == RACE and joined is row and witness == base_origin and
                _verify_origins(payload, raw_baseline, raw_conditioned, packets)[0] == witness)

    def verify_condition(rid, joined, witness):
        return (rid == RACE and joined is row and witness == conditioned_origin and
                _verify_origins(payload, raw_baseline, raw_conditioned, packets)[1] == witness)

    def verify_final(rid, joined, witness):
        return (rid == RACE and joined is row and witness == official_receipt and
                reparse_final() == final and final['source_sha256'] == sha256(final_capture['raw_result']).hexdigest())

    comparison = pdca.compare_cohort(registered_race_ids=[RACE], joined_private_rows={RACE:row},
        independently_verify=dict(baseline_origin=verify_base, condition_origin=verify_condition,
                                  official_final=verify_final))
    need(comparison['paired_comparable_races'] == 1, 'CANARY_FOUR_ARM_COMPARISON_NOT_QUALIFIED')
    return dict(comparison=comparison, official_result=final,
                origin_receipts=row['verified_receipts'])


def reuse_completed(*, payload, bundle_receipt, settled, raw_baseline,
                   raw_conditioned, owner_private_pem):
    """Revalidate a completed encrypted trial; no source requests or new writes."""
    if not settled:
        return None
    saved, receipt = settled[-1]
    need(saved.get('schema') == SETTLEMENT_SCHEMA and saved.get('day_jst') == DAY and
         saved.get('race_id') == RACE and
         saved.get('pre_cutoff_evidence_plaintext_sha256') == bundle_receipt['evidence_plaintext_sha256'] and
         saved.get('baseline_cipher_sha256') == payload['baseline_cipher_sha256'] and
         saved.get('conditioned_cipher_sha256') == payload['conditioned_cipher_sha256'] and
         saved.get('producer_run_id') == payload['producer_run_id'] and
         saved.get('producer_commit') == payload['producer_commit'] and
         saved.get('settler_run_id') == receipt.get('producer_run_id') and
         archive.RUN.fullmatch(saved.get('settler_run_id', '')) is not None and
         archive.COMMIT.fullmatch(saved.get('settler_commit', '')) is not None,
         'CANARY_COMPLETED_REVISION_LINEAGE_INVALID')
    scored = compare_frozen(payload=payload, raw_baseline=raw_baseline,
        raw_conditioned=raw_conditioned, owner_private_pem=owner_private_pem,
        packets=saved['origin_packets'], final_capture=saved['final_capture'])
    need(all(saved.get(key) == scored[key] for key in
             ('comparison', 'official_result', 'origin_receipts')) and
         saved.get('safe_report', {}).get('paired_comparable_races') == 1 and
         saved['safe_report'].get('nationwide_expansion_gate_passed') is True,
         'CANARY_COMPLETED_COMPARISON_NOT_REPRODUCIBLE')
    report = dict(saved['safe_report'])
    report.update(state='EXISTING_VERIFIED_CANARY_COMPARISON_REUSED',
                  settlement_evidence_cipher_sha256=receipt['cipher_sha256'],
                  restored_complete_evidence=True, new_official_source_requests=0,
                  new_evidence_revisions=0)
    return report


def run_settle(*, repo, private_root, owner_public_pem, owner_private_pem, clock=utc_now):
    check_runtime('settle', clock())
    root = _private_root(private_root)
    public = Path(owner_public_pem).read_bytes()
    storage.checked_public_key(public)
    need(type(owner_private_pem) is bytes and 0 < len(owner_private_pem) <= 20_000,
         'CANARY_EXISTING_OWNER_PRIVATE_KEY_REQUIRED')
    payload, bundle_receipt, settled = _load_original_bundle(repo, owner_private_pem)
    raw_base, raw_conditioned, base_receipt = _archived_pair(repo, payload)
    reused = reuse_completed(payload=payload, bundle_receipt=bundle_receipt, settled=settled,
        raw_baseline=raw_base, raw_conditioned=raw_conditioned, owner_private_pem=owner_private_pem)
    if reused is not None:
        return reused
    from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
    packets = GitHubEvidenceClient().read_run_bundle(base_receipt['producer_run_id'],
                                                     policy=origin.FORM_CANARY_POLICY)
    # Verify successful, distinct server-timed jobs before calling a provider.
    _verify_origins(payload, raw_base, raw_conditioned, packets)
    result_dir = _private_root(root/'result')
    final_capture = collect_final_result(repo=repo, private_root=result_dir,
                                         frozen_card=payload['card_manifest'], clock=clock)
    scored = compare_frozen(payload=payload, raw_baseline=raw_base,
        raw_conditioned=raw_conditioned, owner_private_pem=owner_private_pem,
        packets=packets, final_capture=final_capture)
    report = _report('REAL_FUTURE_CANARY_FOUR_ARMS_COMPARISON_COMPLETE')
    report.update(server_origin_verified=True, paired_comparable_races=1,
                  nationwide_expansion_gate_passed=True, actual_official_result_verified=True,
                  exact_frozen_originals_authenticated=True,
                  same_conditions_all_four_arms=True, monetary_basis_yen=100)
    revision = dict(schema=SETTLEMENT_SCHEMA, day_jst=DAY, race_id=RACE,
        pre_cutoff_evidence_plaintext_sha256=bundle_receipt['evidence_plaintext_sha256'],
        baseline_cipher_sha256=payload['baseline_cipher_sha256'],
        conditioned_cipher_sha256=payload['conditioned_cipher_sha256'],
        producer_run_id=payload['producer_run_id'], producer_commit=payload['producer_commit'],
        settler_run_id=os.environ['GITHUB_RUN_ID'], settler_commit=os.environ['GITHUB_SHA'],
        origin_packets=packets, final_capture=final_capture, **scored, safe_report=report)
    sealed = history.seal_evidence(day_pipeline.private_snapshot_json(revision), public, DAY,
                                   clock().isoformat())
    history_capture._save_once(root/(sha256(sealed).hexdigest()+'.settlement.sealed.json'), sealed)
    saved = history.append_revision(repo=repo, day=DAY, raw_cipher=sealed, safe_report=report)
    report['settlement_evidence_cipher_sha256'] = saved['cipher_sha256']
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('capture', 'settle'))
    parser.add_argument('--repo', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--owner-public-pem', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    result, code = _report(), 0
    try:
        root = _private_root(args.private_root)
        report_path = Path(args.report).absolute()
        need(report_path == root/'safe'/'summary.json', 'CANARY_SAFE_REPORT_PATH_REQUIRED')
        _private_root(report_path.parent)
        if args.mode == 'capture':
            result = run_capture(repo=args.repo, private_root=root, owner_public_pem=args.owner_public_pem)
        else:
            private_pem = os.environ.get('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode('utf-8')
            result = run_settle(repo=args.repo, private_root=root, owner_public_pem=args.owner_public_pem,
                                owner_private_pem=private_pem)
    except Exception as exc:
        reason = str(exc)
        if re.fullmatch(r'[A-Z][A-Z0-9_]{4,140}', reason) is None:
            reason = 'CANARY_LOCAL_OR_CONTRACT_FAILURE'
        result['state'] = reason if reason.startswith('HOLD_') else 'HOLD_'+reason
        code = 0 if reason == 'CANARY_OFFICIAL_RESULT_NOT_PUBLISHED_YET' else 2
    try:
        # No source, prediction or key is ever placed in this public artifact.
        report_path = Path(args.report).absolute()
        root = _private_root(args.private_root)
        need(report_path == root/'safe'/'summary.json', 'CANARY_SAFE_REPORT_PATH_REQUIRED')
        _private_root(report_path.parent)
        _json_save(report_path, result)
    except Exception:
        print(json.dumps(_report('HOLD_CANARY_SAFE_REPORT_WRITE_FAILED'), sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
