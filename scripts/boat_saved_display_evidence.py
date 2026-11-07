"""Require actual successful count reports, not just a tee pipeline exit code."""
import json
import os
from pathlib import Path
import re

def verified(site, audit, *, expected_plan_sha256, site_outcome, audit_outcome):
    if site_outcome != 'success' or audit_outcome != 'success':
        return False
    if not isinstance(site, dict) or not isinstance(audit, dict):
        return False
    if not isinstance(expected_plan_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_plan_sha256):
        return False
    flags = ('participant_names', 'editable_daily_budget', 'per_race_1000_simulation',
             'hit_miss_rate_roi_and_settled_pending_net_visible', 'removed_seller_hidden')
    return (site.get('schema') == 'RACE_AI_LIVE_SITE_CHECK_COUNTS_V1'
        and site.get('status') == 'LIVE_OWNER_SITE_VERIFIED'
        and type(site.get('active_model_families')) is int and site['active_model_families'] == 15
        and type(site.get('widths_checked')) is int and site['widths_checked'] >= 2
        and all(site.get(name) is True for name in flags)
        and site.get('key_in_requests_or_storage') is False
        and type(site.get('blocked_external_requests')) is int and site['blocked_external_requests'] == 0
        and site.get('plaintext_published') is False
        and audit.get('status') == 'SETTLED'
        and audit.get('plan_sha256') == expected_plan_sha256
        and audit.get('frozen_plan_reallocated') is False
        and audit.get('forecasting_performed') is False
        and audit.get('actual_purchases') is False
        and audit.get('promotion_allowed') is False)

def main():
    good = False
    try:
        root = Path(os.environ['RUNNER_TEMP'])
        def read(name):
            path = root / name
            if not path.is_file() or not 0 < path.stat().st_size <= 4 * 1024 * 1024:
                raise ValueError('COUNT_REPORT_UNAVAILABLE')
            return json.loads(path.read_bytes())
        plan = json.loads(Path('docs/evidence/2026-11-07/prospective-evaluation-plan.json').read_bytes())
        good = verified(read('boat-live-site-check-counts.json'), read('boat-prospective-audit-display.json'),
            expected_plan_sha256=plan['plan_sha256'],
            site_outcome=os.environ.get('SITE_CHECK_OUTCOME'),
            audit_outcome=os.environ.get('AUDIT_OUTCOME'))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    print(json.dumps({'status': 'DISPLAY_EVIDENCE_VERIFIED' if good else 'DISPLAY_EVIDENCE_REJECTED'}))
    return 0 if good else 2

if __name__ == '__main__':
    raise SystemExit(main())
