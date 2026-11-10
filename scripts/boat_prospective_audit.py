"""Actions-only count audit of an existing frozen plan and authenticated feed.

The owner key is checked before private I/O and stays out of Node environments.
This reader uses the already restored runtime; it never repairs missing state,
requests original artifacts, generates forecasts, or changes a frozen plan.
"""
import argparse
import base64
from datetime import date
import hashlib
import math
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import boat_all_model_cycle as CLI
from scripts.boat_registered_policy import staged_registered_policy
from scripts import boat_private_original_vault as VCLI
from race_ai import saved_view_feed as F
from race_ai.boat_history_store import wire
from race_ai.saved_pages import _read

SCHEMA = 'RACE_AI_PROSPECTIVE_SAVED_AUDIT_V1'
MAX_PLAN = 16*1024*1024
MAX_VIEW = 64*1024*1024
MAX_NODE_STDOUT = 8*1024*1024
MAX_NODE_STDERR = 64*1024
NODE_TIMEOUT_SECONDS = 60
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_SAFE_KEYS = frozenset('''schema status day plan_sha256 scenarios actual_purchases alternative_scenarios
hypothetical_budget_returns independent_pre_cutoff_receipt_verified accuracy_improvement_proven promotion_allowed reason
diagnostic_stage diagnostic_class diagnostic_module diagnostic_line
diagnostic_caller_module diagnostic_caller_line diagnostic_origin_module diagnostic_origin_line
id model_group_index budget race_budget bought spent settledStake pendingStake settledCount payout refund net roi
hits misses void pending review partialRefund hitDenominator hitRate coverage races forecasts result_states final
unsupported missing days groups model_id scope sport stage variant saved_version_ref source_code_commit issued
ambiguous_originals observed available noForecast simulations budgetPerDay raceBudget budgetTotal reserved held unspent
skippedBudget balance settledNet comparison boughtComparison hypothetical paired_comparisons baseline_group challenger_group
axis paired_races both_hit baseline_only challenger_only both_miss baseline_hits challenger_hits baseline_hit_rate
challenger_hit_rate hit_rate_difference exact_discordance_p_value uncertainty method discordant_pairs baseline_hit_rate_95
challenger_hit_rate_95 exploratory_multiple_comparisons excluded missing_or_ambiguous condition_mismatch plan_ineligible
duplicate_pair daily_budget identical_selected_races baseline challenger evidence_scope independent_receipts_verified
prospective_allocation_verified models_are_alternative_scenarios conclusion'''.split())
_ENUMS = {
    'schema': {'RACE_AI_FROZEN_BUDGET_PLAN_SETTLEMENT_V1', 'RACE_AI_SAVED_PERFORMANCE_AGGREGATES_V1'},
    'status': {'HOLD', 'PENDING', 'REVIEW', 'SETTLED'},
    'scope': {'official', 'research', 'synthetic'},
    'sport': {'boat', 'keirin', 'autorace', 'horse'},
    'stage': {'P0', 'P1', 'UNKNOWN', 'A_PRE_TRIAL', 'B_POST_TRIAL'},
    'variant': {'HISTORY_BASELINE', 'HISTORY_ADDED', 'LEARNED_SHADOW', 'LEARNED_VIDEO_EXPERIMENTAL', 'OTHER_SAVED_VARIANT'},
    'axis': {'HISTORY_INPUT_ADDITION', 'LEARNED_WEIGHT_VERSION'},
    'method': {'EXACT_TWO_SIDED_DISCORDANCE_BINOMIAL_AND_WILSON_95'},
    'evidence_scope': {'DESCRIPTIVE_SAVED_ORIGINAL_COMPARISON'},
    'diagnostic_stage': {'PRE_INPUT', 'PLAN_INPUT', 'SAVED_VIEW_INPUT', 'REGISTRATION_INPUT', 'REGISTERED_VERIFY', 'SETTLEMENT_CALCULATION'},
    'diagnostic_class': {'TypeError', 'RangeError', 'SyntaxError', 'ReferenceError', 'Error', 'Other'},
    'diagnostic_module': {'PRODUCT_DATA', 'SAVED_PERFORMANCE', 'FORECAST_AUDIT', 'FROZEN_SETTLEMENT', 'UNRESOLVED'},
    'diagnostic_caller_module': {'PRODUCT_DATA', 'SAVED_PERFORMANCE', 'FORECAST_AUDIT', 'FROZEN_SETTLEMENT', 'UNRESOLVED'},
    'diagnostic_origin_module': {'PRODUCT_DATA', 'SAVED_PERFORMANCE', 'FORECAST_AUDIT', 'FROZEN_SETTLEMENT', 'UNRESOLVED'},
    'conclusion': {'DESCRIPTIVE_COMPARISON_ONLY_PROSPECTIVE_IMPROVEMENT_NOT_DEMONSTRATED'},
}


def _need(ok, reason):
    if not ok:
        raise ValueError('PROSPECTIVE_AUDIT_'+reason)


def _safe_aggregate(value, field=None, depth=0):
    """Only the two readers' numeric, public-enum and hash vocabulary escapes."""
    _need(depth <= 32, 'NODE_AGGREGATE_INVALID')
    if value is None:
        return
    if type(value) is bool:
        if field in ('independent_pre_cutoff_receipt_verified', 'independent_receipts_verified',
                     'accuracy_improvement_proven', 'prospective_allocation_verified', 'promotion_allowed', 'actual_purchases'):
            _need(value is False, 'NODE_AGGREGATE_INVALID')
        return
    if type(value) in (int, float):
        _need(math.isfinite(value) and abs(value) <= 9007199254740991, 'NODE_AGGREGATE_INVALID')
        return
    if type(value) is list:
        for child in value:
            _safe_aggregate(child, field, depth+1)
        return
    if type(value) is dict:
        _need(set(value) <= _SAFE_KEYS, 'NODE_AGGREGATE_INVALID')
        for name, child in value.items():
            _safe_aggregate(child, name, depth+1)
        return
    _need(type(value) is str, 'NODE_AGGREGATE_INVALID')
    if field in _ENUMS:
        ok = value in _ENUMS[field]
    elif field == 'day':
        try:
            ok = date.fromisoformat(value).isoformat() == value
        except ValueError:
            ok = False
    elif field in ('plan_sha256', 'saved_version_ref'):
        ok = _SHA.fullmatch(value) is not None
    elif field == 'source_code_commit':
        ok = re.fullmatch(r'[a-f0-9]{40}', value) is not None
    elif field == 'reason':
        ok = re.fullmatch(r'[A-Z][A-Z0-9_]{1,100}', value) is not None
    elif field == 'model_id':
        from race_ai.existing_model_coverage import catalog
        ok = value == 'UNLISTED_MODEL' or value in {item['model_id'] for item in catalog()}
    else:
        ok = False
    _need(ok, 'NODE_AGGREGATE_INVALID')


def _run_node(script, arguments, *, module_root=None):
    _need(script in ('boat_frozen_plan_settlement.cjs', 'saved_performance_report.cjs'), 'NODE_SCRIPT_INVALID')
    child_environment = {'PATH': os.environ.get('PATH', ''), 'LANG': 'C.UTF-8', 'TZ': 'UTC'}
    process = None
    try:
        runtime_root = Path(module_root).resolve() if module_root is not None else ROOT
        _need(module_root is None or script == 'boat_frozen_plan_settlement.cjs', 'REGISTERED_POLICY_SCRIPT_SCOPE_INVALID')
        process = subprocess.Popen(['node', str(runtime_root/'scripts'/script), *arguments], cwd=runtime_root,
            env=child_environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        deadline = time.monotonic()+NODE_TIMEOUT_SECONDS
        with selectors.DefaultSelector() as selected:
            selected.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selected.register(process.stderr, selectors.EVENT_READ, 'stderr')
            while selected.get_map():
                remaining = deadline-time.monotonic()
                _need(remaining > 0, 'NODE_TIMEOUT')
                for item, _ in selected.select(min(remaining, 1)):
                    block = os.read(item.fd, 65536)
                    if not block:
                        selected.unregister(item.fileobj)
                        continue
                    buffers[item.data].extend(block)
                    maximum = MAX_NODE_STDOUT if item.data == 'stdout' else MAX_NODE_STDERR
                    _need(len(buffers[item.data]) <= maximum, 'NODE_OUTPUT_BOUND_INVALID')
        remaining = deadline-time.monotonic()
        _need(remaining > 0, 'NODE_TIMEOUT')
        code = process.wait(timeout=remaining)
        _need(code in ((0, 2) if script == 'boat_frozen_plan_settlement.cjs' else (0,)), 'NODE_READER_REJECTED')
        result = VCLI.V._json(bytes(buffers['stdout']), MAX_NODE_STDOUT)
        _need(type(result) is dict, 'NODE_AGGREGATE_INVALID')
        _safe_aggregate(result)
        return code, result
    except subprocess.TimeoutExpired:
        raise ValueError('PROSPECTIVE_AUDIT_NODE_TIMEOUT') from None
    except OSError:
        raise ValueError('PROSPECTIVE_AUDIT_NODE_EXECUTION_REJECTED') from None
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdout, process.stderr):
                if stream:
                    stream.close()


def _owner_view(day):
    config = VCLI.V._json(_read(ROOT/'audit/state/boat-saved-view-input.json', 8192), 8192)
    _need(type(config) is dict and config.get('schema') == 'RACE_AI_SAVED_VIEW_INPUT_V1', 'BOOTSTRAP_CONFIG_INVALID')
    raw = base64.b64decode(config['bootstrap'], validate=True)
    _need(hashlib.sha256(raw).hexdigest() == config['bootstrap_sha256'], 'BOOTSTRAP_HASH_MISMATCH')
    bootstrap = F.open_bootstrap(raw)
    _, _, generation, view = F.current_view(F.FeedRepository(ROOT), bootstrap, day=day)
    _need(type(generation) is int and generation >= 0 and type(view) is dict and type(view.get('records')) is list,
          'OWNER_VIEW_INVALID')
    # V4 returns multiple days. Both readers receive this identical target-day
    # view, preserving every retained prediction dictionary byte-for-byte at
    # the JSON-value level. The V5 reader already selects the requested day.
    filtered = dict(view, event_date_jst=day, records=[row for row in view['records'] if row.get('event_date_jst') == day])
    return generation, filtered


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        repo = VCLI._environment(ROOT)
        output = VCLI._private_path(args.output, repo, exists=False)
        marker = CLI.restore_ready()  # Strict existing cache; no recovery or fallback.
        _need(type(marker) is dict and type(marker.get('runtime_files')) is dict, 'RUNTIME_MARKER_INVALID')
        plan_file = marker['runtime_files'].get('prospective-budget-plan.json')
        if plan_file is None:
            print(wire(dict(schema=SCHEMA, status='PROSPECTIVE_PLAN_NOT_CONFIGURED', source_requests=0)))
            return 0
        plan_raw = VCLI._read_private(plan_file, repo, MAX_PLAN)
        plan = VCLI.V._json(plan_raw, MAX_PLAN)
        _need(type(plan) is dict and plan.get('schema') == 'RACE_AI_PRE_OUTCOME_BUDGET_PLAN_V1'
              and type(plan.get('day')) is str and date.fromisoformat(plan['day']).isoformat() == plan['day'], 'PLAN_SCHEMA_INVALID')
        day = plan['day']
        registration_file = ROOT/'docs/evidence'/day/'prospective-evaluation-plan.json'
        registration = VCLI.V._json(_read(registration_file, 512*1024), 512*1024)
        _need(type(registration) is dict and registration.get('schema') == 'RACE_AI_PROSPECTIVE_EVALUATION_REGISTRATION_V1'
              and registration.get('day') == day and type(registration.get('plan_sha256')) is str
              and _SHA.fullmatch(registration['plan_sha256']), 'REGISTRATION_INVALID')
        _need(plan_raw == wire(plan).encode() and hashlib.sha256(plan_raw).hexdigest() == registration['plan_sha256'], 'PLAN_HASH_MISMATCH')
        generation, view = _owner_view(day)
        view_raw = wire(view).encode()
        _need(0 < len(view_raw) <= MAX_VIEW, 'OWNER_VIEW_BOUND_INVALID')
        view_file = VCLI._private_path(output.with_name(output.stem+'.saved-view-'+uuid.uuid4().hex+'.json'), repo, exists=False)
        VCLI._write(view_file, view_raw)
        # Settle the immutable November 7 plan with the registered code, not
        # with later UI/official cutoff-reference enhancements.
        with staged_registered_policy(registration, repository=ROOT,
                                      temporary=os.environ['RUNNER_TEMP']) as registered_root:
            code, settlement = _run_node('boat_frozen_plan_settlement.cjs',
                ['--plan', str(plan_file), '--view', str(view_file), '--registration', str(registration_file)],
                module_root=registered_root)
        _need(settlement.get('schema') == 'RACE_AI_FROZEN_BUDGET_PLAN_SETTLEMENT_V1'
              and settlement.get('status') in ('HOLD', 'PENDING', 'REVIEW', 'SETTLED')
              and settlement.get('day') == day and settlement.get('plan_sha256') == registration['plan_sha256']
              and type(settlement.get('scenarios')) is list
              and (code == 2) == (settlement['status'] == 'HOLD')
              and len(settlement['scenarios']) == (0 if code == 2 else registration['scenarios']), 'NODE_SETTLEMENT_SCHEMA_INVALID')
        _, descriptive = _run_node('saved_performance_report.cjs', ['--input', str(view_file)])
        _need(descriptive.get('schema') == 'RACE_AI_SAVED_PERFORMANCE_AGGREGATES_V1'
              and type(descriptive.get('coverage')) is dict and type(descriptive.get('groups')) is list
              and type(descriptive.get('paired_comparisons')) is list, 'NODE_DESCRIPTIVE_SCHEMA_INVALID')
        report = dict(schema=SCHEMA, status=settlement['status'], day=day, plan_sha256=registration['plan_sha256'],
            feed_generation=generation, frozen_settlement=settlement, descriptive=descriptive,
            frozen_plan_reallocated=False, forecasting_performed=False, official_source_requests=0, source_requests=0,
            independent_pre_cutoff_receipt_verified=False, accuracy_improvement_proven=False, promotion_allowed=False, actual_purchases=False)
        raw = (wire(report)+'\n').encode()
        VCLI._write(output, raw)
        print(raw.decode().rstrip('\n'))
        return 2 if settlement['status'] == 'HOLD' else 0
    except Exception as exc:
        reason = str(exc) if type(exc) in (ValueError, RuntimeError) and re.fullmatch(
            r'(?:PROSPECTIVE_AUDIT|REGISTERED_POLICY|GITHUB|FEED|ALL_MODEL_CLI|MODEL_RUNTIME|HISTORY|VAULT|STATE)_[A-Z0-9_]{1,100}', str(exc)) else 'PROSPECTIVE_AUDIT_REJECTED'
        print(wire(dict(schema=SCHEMA, status='PROSPECTIVE_AUDIT_REJECTED', reason=reason, source_requests=0)))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
