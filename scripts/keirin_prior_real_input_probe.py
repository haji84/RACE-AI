"""Actual prior results -> existing PR71 partial inputs; public counts only.

Only ordinary owner-approved WINTICKET pages. No internal API, guessed input,
late prediction, plaintext public source or changed model. Matched finishing
percentiles enter only B's existing finishing input, never A's acceleration.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import argparse
import json

from race_ai.keirin_owner_public_page_fetch import network_page_once, PublicPageFetchError
from race_ai.keirin_winticket_ex_connection import racecard_with_observed_ex as racecard_from_public_html
from race_ai.keirin_winticket_prior_events import (
    documents_from_html, history_references, normalize_result_event,
    observed_prior_candidates, safe_prior_counts, PriorSourceError,
)
from race_ai.keirin_prior_private_stage import (
    private_research_packet, stage_owner_private_prior_research,
)
from race_ai.keirin_prior_input_connection import (
    attach_prior_finishing_input, stage_connected_prior_input,
)
from race_ai.keirin_real_source_gap_report import inspect_source_gaps


def select_references(reference, documents):
    """Keep observed matching categories and balance home/away samples."""
    from race_ai.keirin_winticket_prior_events import canonical_id
    categories = {}
    target_category = reference['target']['race_category']
    for doc in documents:
        for record in doc.get('records', []) if type(doc.get('records')) is list else []:
            if type(record) is not dict or record.get('playerId') not in reference['rider_ids']:
                continue
            for name in ('latestCupResults', 'latestVenueResults'):
                for cup in record.get(name, []) if type(record.get(name)) is list else []:
                    if type(cup) is not dict or type(cup.get('raceResults')) is not list:
                        continue
                    for row in cup['raceResults']:
                        if type(row) is not dict or type(row.get('raceType3')) is not str:
                            continue
                        try:
                            rid = canonical_id(row.get('raceId'))
                        except (ValueError, TypeError):
                            continue
                        categories.setdefault(rid, set()).add(row['raceType3'])
    eligible = [r for r in reference['references'] if
                not categories.get(r['race_id']) or categories[r['race_id']] == {target_category}]
    by_rider = {}
    for rider in reference['rider_ids']:
        rows = [r for r in eligible if rider in r['rider_ids']]
        rows.sort(key=lambda r: (bool(categories.get(r['race_id'])), r['race_id']), reverse=True)
        same = [r for r in rows if r['race_id'][8:10] == reference['target']['venue']]
        other = [r for r in rows if r['race_id'][8:10] != reference['target']['venue']]
        balanced = []
        for i in range(max(len(same), len(other))):
            if i < len(same):
                balanced.append(same[i])
            if i < len(other):
                balanced.append(other[i])
        by_rider[rider] = balanced
    chosen = []
    seen = set()
    for n in range(max((len(v) for v in by_rider.values()), default=0)):
        for rider in reference['rider_ids']:
            rows = by_rider[rider]
            if n < len(rows) and rows[n]['race_id'] not in seen:
                seen.add(rows[n]['race_id'])
                chosen.append(rows[n])
    return chosen, len(reference['references']) - len(eligible)


def probe(*, race_id, racecard_url, max_pages=32, fetch=None, clock=None,
          private_evidence_dir=None):
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError('PRIOR_PAGE_BUDGET_INVALID')
    if fetch is None:
        fetch = network_page_once
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    requests = 1
    body = fetch(racecard_url)
    captured = clock().isoformat()
    validated = racecard_from_public_html(body, url=racecard_url,
        race_id=race_id, captured_at=captured)
    requests += 1
    index = fetch('https://www.winticket.jp/keirin/odds/' + race_id[:8])
    documents = documents_from_html(body)
    reference = history_references(documents, target_race_id=race_id,
        target_url=racecard_url, captured_at=captured,
        venue_documents=documents_from_html(index))
    if set(reference['rider_ids']) != {str(r['source_player_id']) for r in validated['riders']}:
        raise ValueError('PRIOR_TARGET_ROSTER_MISMATCH')
    chosen, category_excluded = select_references(reference, documents)
    events = []
    failures = Counter()
    stopped = False
    attempted = 0
    for ref in chosen[:max_pages]:
        attempted += 1
        try:
            requests += 1
            raw = fetch(ref['url'])
            event = normalize_result_event(documents_from_html(raw),
                source_url=ref['url'], expected_race_id=ref['race_id'],
                source_sha256=sha256(raw).hexdigest(), captured_at=clock().isoformat(),
                target_cutoff_at=reference['target']['cutoff'])
            events.append(event)
        except PublicPageFetchError as exc:
            reason = str(exc)
            failures[reason if reason.startswith('PUBLIC_PAGE_') else 'SOURCE_UNAVAILABLE'] += 1
            if 'BLOCKED' in reason or 'RATE_LIMITED' in reason:
                stopped = True
                break
        except PriorSourceError as exc:
            failures[str(exc)] += 1
        except (ValueError, TypeError, KeyError, OSError):
            failures['PRIOR_RESULT_SCHEMA_OR_TIME_NOT_VERIFIED'] += 1
    as_of = clock().isoformat()
    derived = observed_prior_candidates(reference, events, as_of=as_of)
    private_packet = private_research_packet(reference, events, derived,
        racecard_sha256=sha256(body).hexdigest(),
        day_index_sha256=sha256(index).hexdigest(), as_of=as_of)
    # Joining a reproducible derivative is not a full live-source admission.
    # Existing A gets no bogus acceleration. B gets only actual finishing
    # values with the original formula, rider identity, sample count and SHA.
    connected = attach_prior_finishing_input(validated, private_packet)
    gap_before = inspect_source_gaps(validated)
    gap_after = inspect_source_gaps(connected)
    retained = staged = None
    if private_evidence_dir is not None:
        retained = stage_owner_private_prior_research(private_evidence_dir, private_packet)
        staged = stage_connected_prior_input(private_evidence_dir, validated, private_packet)
    counts = safe_prior_counts(reference, events)
    features = ('finishing_power', 'bank_fit', 'line_coordination', 'sprint_acceleration')
    return {
        **counts, 'race_id': race_id, 'observed_at': as_of,
        'racecard_sha256': sha256(body).hexdigest(),
        'source_packet_sha256': derived['source_packet_sha256'],
        'candidate_riders_by_existing_feature': {
            name: sum(r['features'][name]['candidate_value'] is not None
                      for r in derived['riders'].values()) for name in features},
        'matched_prior_event_counts': sorted(r['matched_prior_events'] for r in derived['riders'].values()),
        'unfetched_prior_references': max(0, len(chosen) - attempted),
        'request_count': requests, 'host_denial_stopped': stopped,
        'source_failures': dict(failures), 'formula_version': derived['formula_version'],
        'prior_category_mismatches_excluded': category_excluded,
        'eligible_prior_references': len(chosen),
        'model_coefficients_changed': False, 'actual_four_model_forecast_saved': False,
        'private_candidate_packet_saved': retained is not None,
        'private_candidate_packet_sha256': retained['private_packet_sha256'] if retained else None,
        'private_candidate_replay_verified': retained is not None,
        'private_candidate_encrypted_git_archived': False,
        'existing_private_partial_input_staged': staged is not None,
        'connected_partial_input_sha256': staged['connected_input_sha256'] if staged else None,
        'derived_finishing_B_slots_connected': len(connected['prior_finishing_input_evidence']),
        'observed_or_derived_model_A_slots': gap_after['model_A_source_coverage']['source_observed_required_slots'],
        'observed_or_derived_model_B_slots': gap_after['model_B_source_coverage']['source_observed_required_slots'],
        'remaining_model_A_slots': gap_after['model_A_source_coverage']['source_unobserved_required_slots'],
        'remaining_model_B_slots': gap_after['model_B_source_coverage']['source_unobserved_required_slots'],
        'before_history_model_B_slots': gap_before['model_B_source_coverage']['source_observed_required_slots'],
        'required_model_slots': gap_after['model_B_source_coverage']['required_model_input_slots'],
        'full_model_input_admitted': False,
        'status': 'REAL_PRIOR_SOURCE_CHECKED_NOT_FULL_MODEL_ADMISSION',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--race-id', required=True)
    parser.add_argument('--racecard-url', required=True)
    parser.add_argument('--max-pages', type=int, default=32)
    parser.add_argument('--private-evidence-dir', help='existing private directory outside checkout')
    args = parser.parse_args()
    try:
        report = probe(race_id=args.race_id, racecard_url=args.racecard_url,
            max_pages=args.max_pages, private_evidence_dir=args.private_evidence_dir)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report = {'status': 'REAL_PRIOR_INPUT_UNAVAILABLE_NO_INVENTED_VALUES',
                  'model_input_admitted': False, 'actual_four_model_forecast_saved': False,
                  'reason': str(exc) if isinstance(exc, PriorSourceError) else type(exc).__name__}
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
