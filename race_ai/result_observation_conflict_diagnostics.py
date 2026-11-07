"""Pure fixed-vocabulary counts for a rejected pair; never reconcile evidence."""
from collections import Counter
import json

FIELDS = frozenset('''schema sport race_id captured_at closed_at source_sha256 source_url
body_identity_verified status data missing_reason reason source_kind source_format verified_official'''.split())
DATA_FIELDS = frozenset('''status confirmed finish_confirmed confirmed_scope results payouts top3
dead_heat refund_boats refunds settlement_ready special_payouts available_market_types
verified_market_types refund_policy_status'''.split())
FINISH_FIELDS = frozenset('''race_id lane racer_registration_id name finish finish_status
verified_official race_time race_time_seconds actual_st actual_raw_st'''.split())


def result_conflict_counts(left, right):
    wire = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False)
    def changes(first, second, allowed):
        counts = Counter()
        for key in set(first) | set(second):
            if (key in first) != (key in second) or wire(first.get(key)) != wire(second.get(key)):
                counts[key if key in allowed else 'OTHER'] += 1
        return counts
    data = Counter(); finishes = Counter()
    first, second = left.get('data'), right.get('data')
    if type(first) is dict and type(second) is dict:
        data = changes(first, second, DATA_FIELDS)
        def lanes(value):
            rows = value.get('results')
            if type(rows) is not list or any(type(row) is not dict or type(row.get('lane')) is not int for row in rows):
                return {}
            return {row['lane']: row for row in rows} if len({row['lane'] for row in rows}) == len(rows) else {}
        first, second = lanes(first), lanes(second)
        for lane in set(first) & set(second):
            finishes.update(changes(first[lane], second[lane], FINISH_FIELDS))
    a, b = left.get('source_sha256'), right.get('source_sha256')
    return dict(same_source_bytes=a == b if type(a) is str and type(b) is str else None,
                differing_fields=dict(changes(left, right, FIELDS)), differing_data_fields=dict(data),
                differing_finish_fields=dict(finishes), observations_reconciled=0, originals_changed=False)
