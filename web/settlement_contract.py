"""Pure current-day Money-compatible projections of checked cloud receipts.

No ledger, money arithmetic, storage, provider or source requests live here.
The API must obtain receipts from the approved storage boundary: canonical
hashes and clocks alone do not establish that caller-supplied data is official.
"""
import copy

if __package__:
    from . import race_contract as facts
    from . import evaluation_contract as receipts
else:
    import race_contract as facts
    import evaluation_contract as receipts


def _build(race_bundle, race, now):
    clock = receipts._clock(now)
    day, closed, _ = facts._program(race)
    facts._require(clock.astimezone(facts.JST).date() == day,
                   'current Japan-local race required for live settlement')
    # Reuse the entire canonical receipt/manifest validator, including other
    # supplied observation kinds, before returning any informative empty state.
    result = receipts._checked_race_bundle(race_bundle, race, clock, day, closed)
    report = dict(schema_version=1, race_id=race['race_id'], date_jst=day.isoformat(),
        as_of=facts.stamp(clock), closed_at=facts.stamp(closed), program_sha256=facts.program_digest(race),
        status='RESULT_NOT_OBTAINED', markets=[], excluded_market_types=sorted(facts.ALL_MARKETS),
        result_proof=receipts._result_proof(result), exclusion_reason='OFFICIAL_RESULT_NOT_OBTAINED')
    if result is None:
        return report
    record = result['record']
    if record['status'] == 'PENDING':
        return dict(report, status='RESULT_PENDING', exclusion_reason='OFFICIAL_RESULT_PENDING')
    data = record['data']
    if data.get('refund_boats') or data.get('refunds') not in ([], None):
        return dict(report, status='SETTLEMENT_UNSUPPORTED', exclusion_reason='OFFICIAL_REFUND_OUTCOME_UNSUPPORTED')
    if data['status'] == 'dead_heat':
        return dict(report, status='SETTLEMENT_UNSUPPORTED', exclusion_reason='OFFICIAL_TIE_COVERAGE_UNSUPPORTED')
    # Validation positively establishes complete winner coverage independently
    # for each market, or explicit confirmed full-race refund disposition.
    verified = set(data['verified_market_types'])
    markets = []
    for kind in sorted(verified):
        payouts = [p for p in data['payouts'] if p['bet_type'] == kind]
        specials = [p for p in data['special_payouts'] if p['bet_type'] == kind]
        status = data['status'] if data['status'] in {'cancelled', 'no_contest', 'postponed'} else (
            'special' if specials else 'settled')
        markets.append(dict(race_id=race['race_id'], status=status, confirmed=True,
            verified_market_types=[kind], payouts=copy.deepcopy(payouts), refunds=[],
            special_payouts=copy.deepcopy(specials)))
    excluded = sorted(facts.ALL_MARKETS - verified)
    if not markets:
        return dict(report, status='SETTLEMENT_UNSUPPORTED', exclusion_reason='OFFICIAL_MARKET_COVERAGE_UNVERIFIED')
    return dict(report, markets=markets, excluded_market_types=excluded,
        status='SETTLEMENT_PARTIAL' if excluded else 'SETTLEMENT_READY',
        exclusion_reason='OFFICIAL_MARKET_COVERAGE_INCOMPLETE' if excluded else None)


def build_settlement_report(race_bundle, race, now):
    """Return verified single-market results, preserving all supplied inputs.

    Missing evidence has an informative empty state. Malformed supplied evidence
    is rejected; incomplete winner coverage can never infer losing purchases.
    """
    try:
        return _build(race_bundle, race, now)
    except (TypeError, KeyError, AttributeError, OverflowError, UnicodeError) as exc:
        raise ValueError('invalid live settlement evidence') from exc
