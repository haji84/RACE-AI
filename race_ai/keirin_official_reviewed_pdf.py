"""Finite, explicitly reviewed official PDF evidence for historical acceptance.

This is not an unattended PDF parser and is not the KEIRIN.JP JSON contract.
The private review is pinned after two assistant visual reads of the actual
PDF pages. Exact source bytes, the complete official schedule, all starter
cars, and external official payout-unit evidence must accompany it. New PDFs
or altered transcriptions need a new reviewed pin; a caller cannot opt in an
arbitrary result with a boolean. First publication times remain unknown.

No network, filesystem, source acquisition, or private plaintext output here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from hashlib import sha256
import json

from . import keirin_official_public_source as official

SCHEMA = 'RACE_AI_KEIRIN_KNOWN_PDF_VISUAL_REVIEW_V1'
RESULT_SCHEMA = 'RACE_AI_KEIRIN_REVIEWED_VENUE_PDF_RESULT_V1'
APPROVED_REVIEW_SHA256 = frozenset({
    '9ba18bc253dd27910387e1d32bc7072a536ace7d9cf385d3359cb01340f5d6c9'})
PDF_URLS = {
    'https://utsunomiya-keirin.jp/data/racelist/racelist.pdf': '24',
    'https://www.kochi-keirin.jp/shussohyo/today.pdf': '74',
    'https://www.keirin-saitama.jp/seibuen/wp-content/uploads/pdf/page.pdf': '26',
}
UNIT_URLS = {
    'https://www.hofukeirin.jp/ticket/': '払戻金額は100円あたりの金額で発表され',
    'https://www.shonanbank.com/beginner/': '100円あたりの払い戻し金額が発表されます',
}


class ReviewedPdfError(ValueError):
    pass


def _need(condition, code):
    if not condition:
        raise ReviewedPdfError(code)


def _bytes(sources, digest):
    raw = sources.get(digest)
    _need(type(raw) is bytes and 0 < len(raw) <= 4_000_000 and
          sha256(raw).hexdigest() == digest, 'REVIEWED_PDF_SOURCE_BYTES_MISSING_OR_CHANGED')
    return raw


def verify_reviewed_pdf_results(*, review_raw, source_bytes_by_sha, schedule):
    """Admit only a recorded review of exact private source documents."""
    _need(type(review_raw) is bytes and 0 < len(review_raw) <= 200_000 and
          sha256(review_raw).hexdigest() in APPROVED_REVIEW_SHA256,
          'PDF_REVIEW_NOT_APPROVED')
    _need(type(source_bytes_by_sha) is dict, 'REVIEWED_PDF_SOURCE_BYTES_REQUIRED')
    _need(official.reparse_day_schedule(schedule), 'REVIEWED_PDF_SCHEDULE_INVALID')
    doc = json.loads(review_raw)
    _need(doc.get('schema') == SCHEMA and doc.get('race_day') == schedule['day_jst'] and
          doc.get('review_method') == 'TWO_ASSISTANT_VISUAL_READS_OF_SAME_OFFICIAL_PDF' and
          type(doc.get('sources')) is dict and bool(doc['sources']) and
          type(doc.get('unit_basis')) is list and bool(doc['unit_basis']) and
          type(doc.get('rows')) is list and bool(doc['rows']), 'REVIEWED_PDF_SCHEMA_INVALID')
    reviewed = official._aware(doc['reviewed_at'])
    for source in doc['sources'].values():
        _need(source.get('url') in PDF_URLS and
              source.get('source_published_at') is None and
              source.get('publication_time_basis') == 'UNKNOWN' and
              source.get('source_available_no_later_than') == source.get('observed_at') and
              source.get('result_table_day') == doc['race_day'] and
              date.fromisoformat(source['document_issue_day']) >= date.fromisoformat(doc['race_day']) and
              type(source.get('result_table_page_1based')) is int and
              1 <= source['result_table_page_1based'] <= 20,
              'REVIEWED_PDF_SOURCE_IDENTITY_OR_TIME_INVALID')
        _need(_bytes(source_bytes_by_sha, source['source_sha256']).startswith(b'%PDF-'),
              'REVIEWED_PDF_SOURCE_BYTES_NOT_PDF')
        _need(reviewed >= official._aware(source['observed_at']),
              'REVIEWED_PDF_OBSERVATION_ORDER_INVALID')
    unit_refs = []
    for unit in doc['unit_basis']:
        raw = _bytes(source_bytes_by_sha, unit['source_sha256'])
        _need(unit.get('url') in UNIT_URLS and unit.get('verified_payout_basis_yen') == 100 and
              unit.get('exact_excerpt') == UNIT_URLS[unit['url']] and
              unit['exact_excerpt'].encode('utf-8') in raw and
              reviewed >= official._aware(unit['observed_at']),
              'REVIEWED_PDF_PAYOUT_UNIT_NOT_SUPPORTED')
        unit_refs.append({key: unit[key] for key in ('url', 'source_sha256', 'observed_at')})
    races = {row['race_id']: row for row in schedule['races']}
    results = {}
    for row in doc['rows']:
        rid = row['race_id']
        _need(rid in races and rid not in results and row.get('race_day') == doc['race_day'] and
              row.get('race_no') == int(rid[-2:]) and row.get('source_id') in doc['sources'],
              'REVIEWED_PDF_RACE_IDENTITY_OR_DUPLICATE')
        source = doc['sources'][row['source_id']]
        _need(PDF_URLS[source['url']] == rid[8:10] and
              row['source_page_1based'] == source['result_table_page_1based'],
              'REVIEWED_PDF_VENUE_OR_PAGE_MISMATCH')
        cutoff = races[rid]['official_cutoff_at']
        _need(cutoff is not None and row['official_cutoff_at_from_saved_schedule'] == cutoff,
              'REVIEWED_PDF_OFFICIAL_CUTOFF_MISMATCH')
        _need(official._aware(source['observed_at']) > official._aware(cutoff),
              'REVIEWED_PDF_OBSERVATION_ORDER_INVALID')
        cars = {item['car'] for item in races[rid]['starters']}
        finishes = row['finish_rows_displayed']
        _need(type(finishes) is list and len(finishes) == len(cars) and
              sorted(row['scheduled_starters']) == sorted(cars) and
              all(type(item) is dict and type(item.get('car')) is int for item in finishes) and
              {item['car'] for item in finishes} == cars,
              'REVIEWED_PDF_FINISH_STARTERS_MISMATCH')
        ranks = {}
        for item in finishes:
            rank, status = item['rank'], item['status_label']
            _need((type(rank) is int and 1 <= rank <= len(cars) and status is None) or
                  (rank is None and status == '失'), 'REVIEWED_PDF_FINISH_STATUS_UNKNOWN')
            if rank is not None:
                _need(rank not in ranks, 'REVIEWED_PDF_FINISH_TIE_NEEDS_SEPARATE_REVIEW')
                ranks[rank] = item['car']
        triple = row['winning_triple_displayed']
        _need(type(triple) is list and len(triple) == 3 and
              triple == [ranks.get(i) for i in (1, 2, 3)] and
              all(type(car) is int and car in cars for car in triple) and len(set(triple)) == 3,
              'REVIEWED_PDF_WINNER_FINISH_MISMATCH')
        yen = row['payout_yen_displayed']
        _need(type(yen) is int and 100 <= yen <= 10**9 and row.get('payout_basis_yen') == 100 and
              row.get('payout_basis_kind') == 'EXTERNAL_OFFICIAL_VENUE_GUIDES',
              'REVIEWED_PDF_PAYOUT_INVALID')
        results[rid] = {
            'schema': RESULT_SCHEMA, 'race_id': rid, 'status': 'FINAL_NORMAL',
            'refund_status': 'NONE', 'official_cutoff_at': cutoff,
            'source_published_at': None, 'publication_time_basis': 'UNKNOWN',
            'observed_at': source['observed_at'],
            'source_available_no_later_than': source['observed_at'],
            'source_url': source['url'], 'source_sha256': source['source_sha256'],
            'provider_revision_ref': 'review-sha256:' + sha256(review_raw).hexdigest(),
            'source_page_1based': source['result_table_page_1based'],
            'winning_triples': [deepcopy(triple)], 'payouts_100yen': [{'triple': deepcopy(triple), 'yen': yen}],
            'payout_basis_kind': 'EXTERNAL_OFFICIAL_VENUE_GUIDES', 'unit_basis_sources': unit_refs,
            'verification_method': 'PINNED_VISUAL_PDF_REVIEW', 'automated_result_parser': False,
        }
    return {'results_by_race': results, 'review_sha256': sha256(review_raw).hexdigest(),
            'reviewed_races': len(results), 'automated_result_parser': False}


def settle_known_evening_with_pdf(*, schedule, batches, generator_source_bytes,
                                 review_raw, source_bytes_by_sha, owner_private_pem,
                                 baseline_inputs=None):
    """Replay actual pinned batches, then join their reviewed official PDFs.

    The ordinary JSON pipeline independently validates any baseline races.
    PDF/manual and JSON/automatic counts remain separate in the combined view.
    A failed batch/review stops this historical replay rather than creating a
    partially trusted aggregate. It never alters a pre-cutoff original.
    """
    from . import keirin_legacy_evening_replay as legacy
    from . import keirin_nationwide_auto_settlement as settlement
    from . import keirin_nationwide_AB_results as totals
    from . import keirin_available_prediction_audit as audit
    from . import keirin_official_cohort as cohort
    from . import keirin_nationwide_auto_generator as model
    from scripts import keirin_official_day_pipeline as pipeline

    registry = cohort.build_registry(schedule)
    baseline = baseline_inputs or {'originals_by_race': {}, 'official_records_by_race': {},
                                   'origin_packets_by_race': {}}
    report, rows, proofs = pipeline.settle_collected(
        schedule=schedule, owner_private_pem=owner_private_pem, **baseline)
    verified = verify_reviewed_pdf_results(review_raw=review_raw,
        source_bytes_by_sha=source_bytes_by_sha, schedule=schedule)
    final = verified['results_by_race']
    cutoffs = {r['race_id']: r['official_cutoff_at'] for r in schedule['races']}
    _need(type(batches) is list and 1 <= len(batches) <= 2, 'REVIEWED_PDF_BATCHES_REQUIRED')
    originals, counts = {}, {}
    for batch in batches:
        checked = legacy.verify_known_batch(**batch, official_cutoffs_by_race=cutoffs,
                                            generator_source_bytes=generator_source_bytes)
        _need(not (set(checked['originals_by_race']) &
                   (set(originals) | set(proofs) | set(baseline['originals_by_race']))),
              'REVIEWED_PDF_DUPLICATE_ORIGINAL')
        originals.update(checked['originals_by_race'])
        proofs.update(checked['proofs_by_race'])
        counts.update(checked['ticket_counts_by_race'])
    _need(set(originals) == set(final), 'REVIEWED_PDF_RESULT_AND_ORIGINAL_SCOPE_DIFFER')
    owner = {r['race_id']: r for r in rows}
    accepted = {}
    for receipt in report['result_receipts']:
        if receipt['state'] == 'AB_SETTLED_FROM_INDEPENDENT_RECEIPTS':
            accepted[receipt['race_id']] = {
                'schema': audit.AUDIT_SCHEMA, 'race_id': receipt['race_id'],
                'state': 'A_B_RESEARCH_SETTLED', 'ab_evaluable': True, 'abc_evaluable': False,
                'A_existing': receipt['A_existing'], 'B_six_phase': receipt['B_six_phase'],
                'C_six_phase_plus_line': None}
    for rid, original in originals.items():
        manifest, forecast, starters = legacy.decrypt_legacy_original_pair(
            raw_cipher=original['raw_cipher'], expected_cipher_sha256=original['cipher_sha256'],
            owner_private_pem=owner_private_pem, generator_source_bytes=generator_source_bytes)
        result = final[rid]
        _need(manifest['race_id'] == rid and
              (model.when(cutoffs[rid])-model.when(manifest['sealed_at'])).total_seconds() >= 65 and
              starters == {r['car'] for r in next(r for r in schedule['races'] if r['race_id']==rid)['starters']} and
              all(len(forecast[role]['ranked_tickets']) == counts[rid][role] for role in ('A','B')),
              'REVIEWED_PDF_ORIGINAL_CUTOFF_STARTERS_OR_COUNTS_INVALID')
        paid = {tuple(p['triple']): p['yen'] for p in result['payouts_100yen']}
        a, b = [settlement._score(forecast[role]['ranked_tickets'], paid) for role in ('A','B')]
        state = 'AB_SETTLED_FROM_INDEPENDENT_RECEIPTS'
        accepted[rid] = {'schema': audit.AUDIT_SCHEMA, 'race_id': rid,
            'state': 'A_B_RESEARCH_SETTLED', 'ab_evaluable': True, 'abc_evaluable': False,
            'A_existing': a, 'B_six_phase': b, 'C_six_phase_plus_line': None}
        owner[rid].update(state=state, A=forecast['A'], B=forecast['B'], result=result)
        report['result_receipts'].append({'race_id': rid, 'state': state,
            'cipher_file_sha256': original['cipher_sha256'],
            'result_revision_sha256': model.digest(result), 'source_sha256': result['source_sha256'],
            'result_verification_method': 'PINNED_VISUAL_PDF_REVIEW', 'source_published_at': None,
            'A_existing': a, 'B_six_phase': b})
        report['official_result_states'][rid] = 'OFFICIAL_PDF_VISUALLY_REVIEWED'
        report['original_proof_states'][rid] = proofs[rid]['state']
    scorecard = totals.summarize(registry=registry, paired_reports=list(accepted.values()),
        independently_verify_settled_report=lambda rid, item: accepted.get(rid) is item)
    initial_count = report['originals_present']
    report.update(scorecard=scorecard, paired_A_B_scored=len(accepted),
        statuses=[{'race_id': r['race_id'], 'state': r['state']} for r in rows],
        originals_present=initial_count+len(originals),
        originals_server_verified_before_cutoff=len(proofs),
        missing_originals=len(rows)-initial_count-len(originals),
        originals_not_loaded_for_audit=len(rows)-initial_count-len(originals),
        json_official_results_verified=report['official_final_results_verified'],
        reviewed_pdf_official_results_verified=len(final),
        official_final_results_verified=report['official_final_results_verified']+len(final),
        reviewed_pdf_sha256=verified['review_sha256'],
        historical_replay_not_live_autonomous_acceptance=True,
        evidence_scope_note='締切前の暗号原本と公式結果を照合しています。追加16レースは公式会場の結果PDFを画像で確認した履歴検証で、自動運転の通し試験には含めていません。PDF結果の最初の公表時刻は不明です。原本未読込のレースを外れには数えていません。')
    return report, rows, proofs, originals
