"""Manual, source-free desktop Safari proof using existing authenticated saved views.

Application assets are verified against the deployed Pages manifest. Latest-P1
private transport and exact-original-seed browser AES are separate checks.
Only the independent viewer capability enters Safari, in a private fragment;
owner state keys and GitHub tokens remain in Actions. Screenshots are possible
only in a separate synthetic-only invocation, after real sessions have closed.
"""
import argparse
import base64
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPException
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request


PAGES_SHA = 'f60308ef7443ca13b5ca23c4896e15ffc67b0427'
SOURCE_SHA = 'eff296f6d54ad4be297d93e32f1ee0d4592ad9e3'
CANDIDATE_SHA = 'b55242230e93ec3975a5a49bf3dd5f46632ff794'
CANDIDATE_WEB_TREE = '5cbbfe05a2971485b5c32a84a8ddf7b2539604cc'
CANDIDATE_ASSET_SHA256 = {
    'index.html': 'ebe5c116ca645e47aa9b4da29307eddd354463c3c21a3cc02141a6f43b9319e2',
    'app.js': 'c5c172f39e7592b44885e8b4a4bb80fc29af5ddef652512eb522e342644a3ca5',
    'style.css': 'cf67f3e93763bb816be5c2a4aeeddbd35b5a6e8b50c9d3e4a3331e1e7e599d08'}
CSP = ("default-src 'none';script-src 'self';style-src 'self';"
       "img-src 'self' data:;connect-src 'self';font-src 'none';"
       "form-action 'none';object-src 'none';base-uri 'none';frame-src 'none'")
MAX_ASSET = 16 * 1024 * 1024
SYNTHETIC_PATH = 'data/example-synthetic-forecast-audit.json'
SYNTHETIC_SHA = 'b49654f4cbf5527131b38971e3504a52d5d9431ff62aa1c2dde4bc9bf96da00a'
SYNTHETIC_IDS = tuple('synthetic:2030-01-01:' + sport + ':1'
                      for sport in ('autorace', 'boat', 'horse', 'keirin'))
# Exact invented fixture from f723f0e8b94a87a6d6a7b414b1bb30954541925e,
# tests/reference_scenarios_browser.cjs::fixture (factory SHA256
# 3e209a92f0073c1d64a112186d96680d1c705519ccdc1332824edea225abd03f).
# Participants, dates, forecasts and results are public inventions, never evidence of real races.
REFERENCE_SYNTHETIC_PATH = Path(__file__).resolve().parents[1] / 'tests/fixtures/boat_native_safari_reference_synthetic.json'
REFERENCE_SYNTHETIC_SHA = 'ef3a81f4c026267063a96d37333c9708a0049342e9a094c8061a11b92bb7feea'
REFERENCE_SYNTHETIC_COUNTS = (('boat', 2, 6), ('keirin', 1, 7), ('autorace', 1, 8), ('horse', 1, 12))
VISUAL_PAGES = ('home', 'races', 'detail', 'picks', 'results', 'research', 'settings')
VISUAL_WIDTHS = (320, 390, 1440, 1920)
DRIVER_OPERATIONS = frozenset(('start_driver', 'wait_for_driver', 'new_session', 'delete_session',
    'navigate', 'execute_script', 'get_window_rect', 'set_window_rect', 'element_click',
    'element_send_keys', 'actions', 'screenshot', 'unknown_command'))
W3C_ERRORS = frozenset(('session not created', 'invalid session id', 'unknown error', 'unknown command',
    'unknown method', 'invalid argument', 'invalid element state', 'unsupported operation', 'timeout', 'script timeout',
    'no such window', 'no such element', 'stale element reference', 'element click intercepted',
    'element not interactable', 'javascript error', 'unexpected alert open', 'invalid selector',
    'move target out of bounds', 'unable to capture screen', 'insecure certificate'))
DRIVER_RESPONSE_LIMIT = 2 * 1024 * 1024
DRIVER_ERROR_LIMIT = 64 * 1024
REASONS = frozenset('''ASSET_HASH_MISMATCH ASSET_FILE_REJECTED ASSET_PATH_REJECTED
ASSET_MANIFEST_INVALID ASSET_INDEX_INVALID LIVE_PAGES_BYTES_DIFFER NATIVE_MACOS_REQUIRED
SAFARIDRIVER_REQUIRED SAFARIDRIVER_UNAVAILABLE SAFARI_CAPABILITIES_INVALID
SAFARI_WEBDRIVER_FAILED SAFARI_OPERATION_FAILED SAVED_CONTEXT_INVALID
MODEL_ORIGINAL_MISMATCH PRIVATE_NETWORK_BOUNDARY_FAILED SAVED_VIEW_UNAVAILABLE
APP_UI_CHECK_FAILED SOURCE_REVISION_MISMATCH VIEWPORT_INVALID NATIVE_BUDGET_INPUT_NOT_APPLIED
ENCRYPTED_SEED_INVALID ENCRYPTED_SEED_REFUSAL_FAILED SYNTHETIC_FIXTURE_INVALID
SYNTHETIC_SCREENSHOT_REJECTED SYNTHETIC_OUTPUT_REJECTED SAFARI_SESSION_CLEANUP_FAILED
NATIVE_SELECT_PRECONDITION_FAILED CURRENT_V5_REPLAY_INVALID CURRENT_V5_EVIDENCE_INVALID'''.split())


class SafariHold(ValueError):
    """A fixed public failure code, never a driver error or private value."""


class DriverHold(SafariHold):
    def __init__(self, reason='SAFARI_WEBDRIVER_FAILED', *, operation='unknown_command',
                 http_status=None, w3c_error=None, remote_automation_disabled=False):
        super().__init__(reason)
        self.operation, self.http_status = operation, http_status
        self.w3c_error = w3c_error
        self.remote_automation_disabled = remote_automation_disabled


class BudgetHold(SafariHold):
    def __init__(self, target, probe):
        super().__init__('NATIVE_BUDGET_INPUT_NOT_APPLIED')
        self.target, self.probe = target, probe


class AppHold(SafariHold):
    def __init__(self, probe):
        super().__init__('APP_UI_CHECK_FAILED')
        self.probe = probe


class SelectHold(SafariHold):
    def __init__(self, probe):
        super().__init__('NATIVE_SELECT_PRECONDITION_FAILED')
        self.probe = select_diagnostic(probe)


class SyntheticEnvironmentHold(SafariHold):
    def __init__(self, unexpected_count, known_os_keys):
        super().__init__('SYNTHETIC_SCREENSHOT_REJECTED')
        self.unexpected_count, self.known_os_keys = unexpected_count, known_os_keys


PUBLIC_UI_MODULES = frozenset(('app.js', 'product-data.js', 'ui-model.js',
    'saved-performance.js', 'forecast-audit-model.js', 'saved-view-crypto.js'))
UI_STAGES = frozenset(('latest_p1_private_transport', 'encrypted_seed_refusal', 'encrypted_seed_valid', 'synthetic_capture'))
UI_ACTIONS = frozenset(('load_saved_view', 'set_viewport', 'select_saved_day', 'open_native_race',
    'select_native_history', 'open_comparison_race', 'open_outlook', 'select_comparison_history',
    'select_comparison_model', 'open_research', 'return_from_research', 'open_results',
    'set_simulation_budget', 'select_simulation_mode', 'load_missing_key', 'load_wrong_key',
    'load_wrong_view', 'load_modified_cipher', 'load_valid_seed', 'open_seed_probe', 'select_seed_history',
    'prepare_synthetic_tickets', 'verify_synthetic_sports', 'open_synthetic_page', 'capture_synthetic_page'))
CHECKER_FUNCTIONS = frozenset(('main', 'read_authenticated_view', 'app_checks', 'budget', 'select', '_select_probe',
    'click', '_click_visible_element', 'element', 'wait', 'command', 'open_race', 'select_day', 'click_page',
    'open_saved_race', 'select_saved_day', 'click_saved_page', 'encrypted_seed_checks', 'synthetic_visual_checks',
    'apple_driver', 'new_session', 'call', 'native_identity', 'verify_model_choice', 'verify_private_boundary',
    'load_public_assets', 'verify_live_assets', 'require_synthetic_environment'))
SELECT_BOOLEANS = ('control_is_select', 'control_connected', 'control_enabled', 'control_visible',
    'target_connected', 'target_enabled', 'target_visible', 'selected_target', 'control_in_view', 'hit_target', 'focused', 'same_control')
SELECT_COUNTS = ('control_count', 'option_count', 'target_count')
SYNTHETIC_ENVIRONMENT_KEYS = frozenset(('PATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR'))
SYNTHETIC_OS_ENVIRONMENT_KEYS = ('__CF_USER_TEXT_ENCODING', '__CFBundleIdentifier', '__PYVENV_LAUNCHER__',
    'VERSIONER_PYTHON_VERSION', 'VERSIONER_PYTHON_PREFER_32_BIT', 'PYTHONEXECUTABLE')


def need(value, reason):
    if not value:
        raise SafariHold(reason)


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def select_diagnostic(probe):
    probe = probe if type(probe) is dict else {}
    def bounded(name, minimum, maximum):
        value = probe.get(name)
        return value if type(value) is int and minimum <= value <= maximum else None
    module, visibility = probe.get('error_module'), probe.get('document_visibility')
    module = module if type(module) is str and module in PUBLIC_UI_MODULES else None
    supported, opened = probe.get('picker_open_supported'), probe.get('picker_open')
    supported = supported if type(supported) is bool else None
    return {**{key: probe.get(key) if type(probe.get(key)) is bool else None for key in SELECT_BOOLEANS},
            **{key: probe.get(key) if type(probe.get(key)) is int and 0 <= probe[key] <= 10000 else None
               for key in SELECT_COUNTS},
            'document_focused': probe.get('document_focused') if type(probe.get('document_focused')) is bool else None,
            'document_visibility': visibility if type(visibility) is str and visibility in ('visible', 'hidden') else None,
            'viewport_width': bounded('viewport_width', 1, 16384),
            'viewport_height': bounded('viewport_height', 1, 16384),
            'page_errors': bounded('page_errors', 0, 1000000),
            'error_module': module, 'error_line': bounded('error_line', 0, 99999) if module is not None else None,
            'picker_open_supported': supported,
            'picker_open': opened if supported is True and type(opened) is bool else None}


def failure_native_browser(capabilities):
    """Project public numeric Safari identity only; never coerce driver values."""
    if type(capabilities) is not dict:
        return None
    browser, version, system = (capabilities.get(key) for key in ('browserName', 'browserVersion', 'platformName'))
    if not (type(browser) is str and browser == 'Safari' and type(system) is str and system == 'macOS'
            and type(version) is str and re.fullmatch(r'[0-9]{1,3}(?:\.[0-9]{1,6}){0,3}', version)):
        return None
    return {'browserName': browser, 'browserVersion': version, 'platformName': system}


def startup_diagnostic(operation, observed):
    """Project startup structure only; neither driver text nor session values."""
    phases = {'start_driver': 'process_launch', 'wait_for_driver': 'tcp_connect',
              'new_session': 'new_session'}
    if type(operation) is not str or operation not in phases:
        return None
    observed = observed if type(observed) is dict else {}
    result = {'phase': phases[operation]}
    for name in ('tcp_connected', 'process_running_before_connect', 'process_running_after_failure',
                 'response_session_id_field_present', 'response_capabilities_field_present'):
        value = observed.get(name)
        result[name] = value if type(value) is bool else None
    code, message = observed.get('process_exit_code_after_failure'), observed.get('response_message_state')
    result['process_exit_code_after_failure'] = code if type(code) is int and -255 <= code <= 255 else None
    result['response_message_state'] = message if type(message) is str and message in (
        'absent', 'empty_string', 'nonempty_string', 'non_string') else None
    return result


def cleanup_diagnostic(observed):
    """Fixed teardown facts only; never stringify an exception or response."""
    if type(observed) is not dict:
        return None
    result = {}
    for name, allowed in (
        ('close_result', ('true', 'not_true', 'exception')),
        ('delete_outcome', ('not_required', 'acknowledged', 'unexpected_response', 'webdriver_error', 'other_failure')),
        ('process_result', ('wait_returned', 'wait_after_kill_returned', 'poll_failed',
            'terminate_failed', 'wait_failed', 'kill_failed', 'wait_after_kill_failed'))):
        value = observed.get(name)
        result[name] = value if type(value) is str and value in allowed else None
    status, code = observed.get('delete_http_status'), observed.get('delete_error_code')
    result['delete_http_status'] = status if type(status) is int and 100 <= status <= 599 else None
    result['delete_error_code'] = code if type(code) is str and code in W3C_ERRORS else None
    for name in ('terminate_attempted', 'kill_attempted', 'primary_failure_preserved'):
        value = observed.get(name)
        result[name] = value if type(value) is bool else None
    return result


def failure_report(error):
    reason = str(error) if isinstance(error, SafariHold) and str(error) in REASONS else 'SAFARI_OPERATION_FAILED'
    report={'status': 'NATIVE_SAFARI_ACCEPTANCE_HOLD', 'reason': reason}
    try:
        cleanup = cleanup_diagnostic(getattr(error, 'session_cleanup', None))
    except Exception:
        cleanup = None
    if cleanup is not None:
        report['session_cleanup'] = cleanup
    if isinstance(error, CurrentV5ReplayHold):
        phase, upstream = getattr(error, 'phase', None), getattr(error, 'upstream_reason', None)
        counts = error.counts if type(getattr(error, 'counts', None)) is dict else {}
        report.update(
            current_v5_replay_phase=phase if type(phase) is str and phase in CURRENT_V5_REPLAY_PHASES else None,
            current_v5_replay_upstream_reason=upstream if type(upstream) is str
                and upstream in CURRENT_V5_REPLAY_UPSTREAM_REASONS else None,
            current_v5_replay_counts={name: counts[name] if type(counts.get(name)) is int
                and 0 <= counts[name] <= maximum else None for name, maximum in (
                    ('files', 512), ('budget_used_bytes', 256 * 1024 * 1024),
                    ('budget_remaining_bytes', 256 * 1024 * 1024))})
    if isinstance(error, CurrentV5EvidenceHold):
        phase = getattr(error, 'phase', None)
        report.update(current_v5_phase=phase if type(phase) is str and phase in CURRENT_V5_EVIDENCE_PHASES else None,
            current_v5_diagnostic=current_v5_diagnostic(getattr(error, 'diagnostic', None)))
    if isinstance(error, SyntheticEnvironmentHold):
        count = error.unexpected_count
        present = error.known_os_keys if type(error.known_os_keys) is dict else {}
        report.update(environment_phase='synthetic_environment_guard',
            unexpected_environment_key_count=count if type(count) is int and 0 <= count <= 10000 else None,
            known_os_environment_key_present={key: present.get(key) if type(present.get(key)) is bool else None
                                               for key in SYNTHETIC_OS_ENVIRONMENT_KEYS})
    if isinstance(error, DriverHold):
        report.update(
            webdriver_operation=error.operation if type(error.operation) is str and
                error.operation in DRIVER_OPERATIONS else 'unknown_command',
            webdriver_http_status=error.http_status if type(error.http_status) is int and
                100 <= error.http_status <= 599 else None,
            webdriver_error_code=error.w3c_error if type(error.w3c_error) is str and
                error.w3c_error in W3C_ERRORS else None,
            remote_automation_disabled_message_observed=error.remote_automation_disabled is True,
            webdriver_native_browser=failure_native_browser(getattr(error, 'native_browser', None)))
        startup = startup_diagnostic(report['webdriver_operation'], getattr(error, 'startup', None))
        if startup is not None:
            report['webdriver_startup'] = startup
    try:
        observed_context = getattr(error, 'ui_context', None)
    except Exception:
        observed_context = None
    synthetic_context = (type(observed_context) is dict and type(observed_context.get('stage')) is str
                         and observed_context['stage'] == 'synthetic_capture')
    if isinstance(error, (DriverHold, SelectHold)) or synthetic_context:
        context = observed_context if type(observed_context) is dict else {}
        stage, action, width, click_path = (context.get(k) for k in ('stage', 'action', 'width', 'click_path'))
        report.update(ui_stage=stage if type(stage) is str and stage in UI_STAGES else None,
            ui_action=action if type(action) is str and action in UI_ACTIONS else None,
            ui_verified_width=width if type(width) is int and width in VISUAL_WIDTHS else None,
            ui_click_path=click_path if type(click_path) is str and click_path in ('visible_element', 'native_option') else None,
            ui_hit_target_verified=context.get('hit_target_verified') is True)
        if report['ui_stage'] == 'synthetic_capture':
            page = context.get('page')
            report['ui_capture_page'] = page if type(page) is str and page in VISUAL_PAGES else None
        phase = context.get('select_phase')
        if type(phase) is str and phase in ('initial', 'prepared', 'readback'):
            report['ui_select_phase'] = phase
            report['ui_select_preflight'] = select_diagnostic(error.probe if isinstance(error, SelectHold)
                                                             else context.get('select_preflight'))
        ordinal = context.get('seed_comparison_ordinal')
        report['ui_seed_comparison_ordinal'] = ordinal if type(ordinal) is int and ordinal in (1, 2) else None
        preflight = report.get('ui_select_preflight')
        matches = context.get('click_control_matches_preflight')
        report['ui_click_control_matches_preflight'] = (matches
            if type(matches) is bool and report.get('ui_select_phase') == 'initial'
            and report.get('ui_click_path') == 'visible_element' and type(preflight) is dict
            and preflight.get('control_is_select') is True else None)
        first = None
        if (report.get('ui_stage') == 'encrypted_seed_valid' and report.get('ui_action') == 'select_seed_history'
                and report.get('ui_seed_comparison_ordinal') in (1, 2)):
            first = getattr(error, 'first_seed_comparison_initial_selected_target', None)
        report['ui_first_seed_comparison_initial_selected_target'] = (first
            if type(first) is bool and report.get('ui_stage') == 'encrypted_seed_valid'
            and report.get('ui_action') == 'select_seed_history'
            and report.get('ui_seed_comparison_ordinal') in (1, 2) else None)
        report['failure_boundary'] = ('native_select_parent_click'
            if report.get('webdriver_operation') == 'element_click'
            and report.get('webdriver_http_status') == 500 and report.get('webdriver_error_code') == 'unknown error'
            and report.get('ui_select_phase') == 'initial' and report.get('ui_click_path') == 'visible_element'
            and report.get('ui_hit_target_verified') is True and type(preflight) is dict
            and preflight.get('control_is_select') is True else None)
    if isinstance(error, AppHold):
        probe = error.probe if type(error.probe) is dict else {}
        def bounded(name, maximum):
            value = probe.get(name)
            return value if type(value) is int and 0 <= value <= maximum else None
        module = probe.get('error_module')
        report.update(ui_page_errors=bounded('page_errors', 1000000),
                      ui_error_module=module if type(module) is str and module in PUBLIC_UI_MODULES else None,
                      ui_error_line=bounded('error_line', 99999) if type(module) is str and
                      module in PUBLIC_UI_MODULES else None,
                      ui_visible_page=probe.get('visible_page') if probe.get('visible_page') in (
                          'page-home', 'page-races', 'page-detail', 'page-picks',
                          'page-results', 'page-research', 'page-settings') else None,
                      ui_viewport_width=bounded('viewport_width', 16384))
    if isinstance(error, BudgetHold):
        probe = error.probe if type(error.probe) is dict else {}
        observed = probe.get('value')
        amount = (int(observed) if type(observed) is str and
                  re.fullmatch(r'[0-9]{1,8}', observed) else None)
        report.update(budget_target=error.target if type(error.target) is int and
                      error.target in (5000, 10000) else None,
                      budget_observed=amount if amount is not None and amount <= 10000000 else None,
                      budget_field_focused=probe.get('focused') is True,
                      budget_field_valid=probe.get('valid') is True)
    # A public checker line identifies the failing boundary without exporting
    # driver messages, DOM text, source records, owner URLs or credentials.
    callers = []
    for frame in traceback.extract_tb(error.__traceback__):
        if Path(frame.filename).resolve() == Path(__file__).resolve() and frame.name in CHECKER_FUNCTIONS \
                and type(frame.lineno) is int and 1 <= frame.lineno <= 99999:
            report.update(checker_function=frame.name,checker_line=frame.lineno)
            callers.append({'function': frame.name, 'line': frame.lineno})
    if callers:
        report['checker_callers'] = callers[-12:]
    return report


def ui_diagnostic(driver, stage, action, width=None, *, page=None):
    """Fixed labels and an already verified public width; no UI values."""
    driver.ui_context = {'stage': stage, 'action': action, 'width': width}
    if stage == 'synthetic_capture':
        driver.ui_context['page'] = page


def driver_environment(environment):
    return {key: environment[key] for key in ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR')
            if key in environment}


def valid_native_cf_user_text_encoding(value):
    """A bounded Apple producer form with unambiguous current-user binding."""
    # CFStringEncodings.c emits 0x%X:0:0, or 0x%X plus saved 0x%X:0x%X.
    # Its base-0 parser accepts more spellings; this guard accepts only these.
    if type(value) is not str or not 1 <= len(value) <= 32 or not value.isascii():
        return False
    atom = r'0x(?:0|[1-9A-F][0-9A-F]{0,7})'
    if re.fullmatch(atom + r':(?:0:0|' + atom + ':' + atom + ')', value) is None:
        return False
    try:
        system = platform.system()
        if type(system) is not str or system != 'Darwin':
            return False
        uid, euid = os.getuid(), os.geteuid()
    except (AttributeError, OSError):
        return False
    return (type(uid) is int and type(euid) is int
        and 0 <= uid <= 0xffffffff and 0 <= euid <= 0xffffffff
        and int(value.partition(':')[0], 16) == uid == euid)


def require_synthetic_environment():
    # The candidate checker and Safari driver receive only original OS values.
    # Unknown owner/viewer credential variable names fail closed as well.
    unexpected = set(os.environ) - SYNTHETIC_ENVIRONMENT_KEYS
    if '__CF_USER_TEXT_ENCODING' in unexpected and valid_native_cf_user_text_encoding(
            os.environ.get('__CF_USER_TEXT_ENCODING')):
        unexpected.remove('__CF_USER_TEXT_ENCODING')
    if unexpected:
        # Count names in memory; export only fixed OS-key presence, never values
        # or names from the unexpected set. Every unexpected key still refuses.
        raise SyntheticEnvironmentHold(len(unexpected),
            {key: key in os.environ for key in SYNTHETIC_OS_ENVIRONMENT_KEYS})


def candidate_identity():
    return {'commit': CANDIDATE_SHA, 'web_tree': CANDIDATE_WEB_TREE,
            'asset_sha256': dict(CANDIDATE_ASSET_SHA256)}


def candidate_capture_assets(assets):
    # Verify the whole reviewed source tree, but offer only the SPA and its
    # static resources. No other forecast/registry JSON or viewer is an input.
    return {name: raw for name, raw in assets.items()
            if not name.startswith('views/') and
            (Path(name).suffix != '.json' or name == SYNTHETIC_PATH) and
            (Path(name).suffix != '.html' or name == 'index.html')}


def native_identity(capabilities):
    need(isinstance(capabilities, dict), 'SAFARI_CAPABILITIES_INVALID')
    browser, version, system = (capabilities.get(k) for k in ('browserName', 'browserVersion', 'platformName'))
    need(browser == 'Safari' and system == 'macOS' and isinstance(version, str)
         and re.fullmatch(r'[0-9][0-9A-Za-z.() _-]{0,63}', version), 'SAFARI_CAPABILITIES_INVALID')
    return {'browserName': browser, 'browserVersion': version, 'platformName': system}


def viewport_evidence(requested, actual):
    need(type(requested) is int and 320 <= requested <= 1920 and isinstance(actual, dict)
         and all(type(actual.get(k)) is int and 200 <= actual[k] <= 4096 for k in ('width', 'height')),
         'VIEWPORT_INVALID')
    return {'requested_width': requested, 'actual_inner_width': actual['width'],
            'actual_inner_height': actual['height'], 'requested_width_verified': actual['width'] == requested,
            'physical_iphone_verified': False}


def require_viewport(requested, actual):
    evidence = viewport_evidence(requested, actual)
    need(evidence['requested_width_verified'], 'VIEWPORT_INVALID')
    return evidence


def validate_context(context):
    need(isinstance(context, dict) and context.get('schema') == 'RACE_AI_PRIVATE_LIVE_SITE_CHECK_CONTEXT_V1'
         and context.get('stage') == 'P1', 'SAVED_CONTEXT_INVALID')
    for name in ('generation', 'minimum_results', 'day_races', 'native_group_count'):
        need(type(context.get(name)) is int and context[name] > 0, 'SAVED_CONTEXT_INVALID')
    need(context['day_races'] <= 288 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', context.get('day', ''))
         and context['day'] <= context.get('current_day', ''), 'SAVED_CONTEXT_INVALID')
    probe = context.get('model_switch_probe')
    need(isinstance(probe, dict) and re.fullmatch(r'\d{8}-\d{2}-\d{2}', probe.get('race_id', ''))
         and probe['race_id'][:8] == context['day'].replace('-', '')
         and isinstance(probe.get('choices'), list) and len(probe['choices']) == 2, 'SAVED_CONTEXT_INVALID')
    for choice in probe['choices']:
        need(isinstance(choice, dict) and isinstance(choice.get('model_id'), str)
             and 0 < len(choice['model_id']) <= 256 and type(choice.get('index')) is int
             and 0 <= choice['index'] < 32768 and re.fullmatch('[a-f0-9]{64}', choice.get('tickets_sha256', '')),
             'SAVED_CONTEXT_INVALID')
    need(probe['choices'][0]['model_id'] != probe['choices'][1]['model_id'], 'SAVED_CONTEXT_INVALID')
    return {key: context[key] for key in ('schema', 'day', 'current_day', 'stage', 'generation',
            'minimum_results', 'day_races', 'native_group_count', 'native_groups', 'native_probe', 'model_switch_probe')}


def verify_model_choice(choice, detail):
    need(isinstance(detail, dict) and detail.get('model_id') == choice['model_id']
         and detail.get('index') == str(choice['index']) and isinstance(detail.get('tickets'), list)
         and sha(wire(detail['tickets']).encode()) == choice['tickets_sha256'], 'MODEL_ORIGINAL_MISMATCH')


def verify_private_boundary(snapshot, audit, secrets, *, fragment=None, encrypted=False, require_read=True):
    need(isinstance(snapshot, dict) and isinstance(snapshot.get('privacy'), dict)
         and snapshot['privacy'].get('page_errors') == 0, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
    url = urllib.parse.urlsplit(snapshot.get('url', ''))
    checked = snapshot
    if fragment is not None:
        need(encrypted and isinstance(fragment, str) and (fragment == '' or
             re.fullmatch(r'#saved=[a-f0-9]{64}\.[A-Za-z0-9_-]{43}', fragment))
             and ('#' + url.fragment if url.fragment else '') == fragment,
             'PRIVATE_NETWORK_BOUNDARY_FAILED')
        # Only this exact authorized capability location is excepted. Secrets
        # anywhere else in the snapshot, headers, requests or storage still fail.
        checked = dict(snapshot, url=urllib.parse.urlunsplit(url._replace(fragment='')))
    rendered = wire(checked)
    need(not any(value in rendered for value in secrets if isinstance(value, str) and len(value) >= 8),
         'PRIVATE_NETWORK_BOUNDARY_FAILED')
    need(url.scheme == 'http' and url.hostname == '127.0.0.1' and not url.username and not url.password
         and not url.query and url.path == '/'
         and (fragment is not None or not url.fragment or re.fullmatch('[a-z-]+', url.fragment))
         and snapshot.get('session') == {} and snapshot.get('cookie') == '', 'PRIVATE_NETWORK_BOUNDARY_FAILED')
    local = snapshot.get('local')
    need(isinstance(local, dict) and set(local) <= {'race-ai-display-v1'}, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
    if local:
        try:
            preferences = json.loads(local['race-ai-display-v1'])
            need(isinstance(preferences, dict) and set(preferences) <= {'budget', 'raceBudget', 'simulationBudget',
                 'simulationRaceBudget', 'maxPicks', 'sport', 'favoriteVenues'}, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
            for name, value in preferences.items():
                if name == 'sport':
                    need(value in ('boat', 'keirin', 'autorace', 'horse'), 'PRIVATE_NETWORK_BOUNDARY_FAILED')
                elif name == 'favoriteVenues':
                    need(isinstance(value, list) and len(value) <= 64 and all(isinstance(v, str)
                         and len(v) <= 110 and re.match(r'^(boat|keirin|autorace|horse):', v) for v in value),
                         'PRIVATE_NETWORK_BOUNDARY_FAILED')
                else:
                    need(type(value) is int and 0 < value <= 10_000_000, 'PRIVATE_NETWORK_BOUNDARY_FAILED')
        except (ValueError, TypeError):
            raise SafariHold('PRIVATE_NETWORK_BOUNDARY_FAILED') from None
    reads = audit.get('encrypted_seed_reads' if encrypted else 'private_view_reads', 0)
    need((reads > 0 if require_read else reads == 0)
         and (not encrypted or audit.get('private_view_reads') == 0)
         and audit.get('secret_in_request') is False
         and audit.get('non_read_requests') == audit.get('outbound_requests_permitted') == 0,
         'PRIVATE_NETWORK_BOUNDARY_FAILED')


def load_encrypted_seed(root):
    """Read only the exact index-referenced original, bound to its manifest."""
    try:
        root = Path(root).resolve()
        assets = load_public_assets(root)
        index = assets['index.html'].decode('utf-8')
        paths = re.findall(r'<meta name="race-ai-encrypted-saved-view" content="\./(views/[a-f0-9]{64}\.json)">', index)
        anchors = re.findall(r'<meta name="race-ai-saved-view-forecast-sha" content="([a-f0-9]{64})">', index)
        need(len(paths) == len(anchors) == 1, 'ENCRYPTED_SEED_INVALID')
        path = root / paths[0]
        need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
             and 0 < path.stat().st_size <= 90 * 1024 * 1024, 'ASSET_FILE_REJECTED')
        raw = path.read_bytes()
        ident = path.stem
        manifest = json.loads((root / 'site-build.json').read_bytes())
        need(manifest.get('forecast_sha256') == anchors[0], 'ENCRYPTED_SEED_INVALID')
        need(sha(raw) == ident and manifest['files'].get(paths[0]) ==
             {'bytes': len(raw), 'sha256': ident}, 'ASSET_HASH_MISMATCH')
        doc = json.loads(raw)
        need(isinstance(doc, dict) and set(doc) == {'header', 'nonce', 'ciphertext'}
             and isinstance(doc['header'], dict) and doc['header'].get('schema') in
             ('RACE_AI_SAVED_WEB_VIEW_V1', 'RACE_AI_SAVED_WEB_VIEW_V2'), 'ENCRYPTED_SEED_INVALID')
        return {'path': paths[0], 'raw': raw, 'cipher_sha256': ident,
                'forecast_sha256': anchors[0], 'header': doc['header']}
    except (OSError, ValueError, KeyError, UnicodeError) as error:
        if isinstance(error, SafariHold):
            raise
        raise SafariHold('ENCRYPTED_SEED_INVALID') from None


def build_seed_context(seed, bootstrap, view, forecast_anchor, *, retired=()):
    """Expectations from the same independently AES-authenticated seed only."""
    header = seed['header']
    need(seed['forecast_sha256'] == bootstrap.get('forecast_sha256') == forecast_anchor
         and (header.get('view_id') if header.get('schema') == 'RACE_AI_SAVED_WEB_VIEW_V2'
              else seed['cipher_sha256']) == bootstrap.get('view_id')
         and isinstance(view, dict) and view.get('schema') == 'RACE_AI_PRIVATE_CYCLE_VIEW_V1'
         and isinstance(view.get('records'), list), 'ENCRYPTED_SEED_INVALID')
    for row in view['records']:
        if row.get('sport') != 'boat':
            continue
        predictions = [p for p in [row.get('prediction'), *row.get('comparison_predictions', [])]
                       if p is not None and p.get('model_id') not in retired]
        choices, seen = [], set()
        for index, prediction in enumerate(predictions):
            model, tickets = prediction.get('model_id'), prediction.get('ordered_top8')
            if not isinstance(model, str) or not model or model in seen or not isinstance(tickets, list) or not 1 <= len(tickets) <= 8:
                continue
            need(all(isinstance(t, list) and len(t) == 3 and len(set(t)) == 3
                 and all(type(n) is int and 1 <= n <= 6 for n in t) for t in tickets), 'ENCRYPTED_SEED_INVALID')
            seen.add(model)
            choices.append({'model_id': model, 'index': index, 'tickets_sha256': sha(wire(tickets).encode())})
        if len(choices) >= 2:
            need(re.fullmatch(r'\d{8}-\d{2}-\d{2}', row.get('race_id', ''))
                 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row.get('event_date_jst', ''))
                 and isinstance(row.get('cutoff_at'), str), 'ENCRYPTED_SEED_INVALID')
            day = row['event_date_jst']
            return {'seed_sha256': seed['cipher_sha256'], 'day': day,
                    'day_races': sum(r.get('sport') == 'boat' and r.get('event_date_jst') == day for r in view['records']),
                    'probe': {'race_id': row['race_id'], 'cutoff_at': row['cutoff_at'], 'choices': choices[:2]}}
    raise SafariHold('ENCRYPTED_SEED_INVALID')


def synthetic_fixture(assets):
    raw = assets.get(SYNTHETIC_PATH)
    need(isinstance(raw, bytes) and sha(raw) == SYNTHETIC_SHA, 'SYNTHETIC_FIXTURE_INVALID')
    value = json.loads(raw)
    need(value.get('schema') == 'RACE_AI_FORECAST_AUDIT_V1' and value.get('dataset_status') == 'SYNTHETIC_ONLY'
         and tuple(sorted(row.get('race_id', '') for row in value['records'])) == SYNTHETIC_IDS
         and all(row.get('source_provenance') == 'SYNTHETIC_ONLY' for row in value['records']),
         'SYNTHETIC_FIXTURE_INVALID')
    return value


def synthetic_capture_fixture(assets, *, candidate_ui=False):
    """Candidate screenshots alone use the exact existing rich public scenario."""
    need(type(candidate_ui) is bool, 'SYNTHETIC_FIXTURE_INVALID')
    legacy = synthetic_fixture(assets)
    if not candidate_ui:
        return legacy
    try:
        path = REFERENCE_SYNTHETIC_PATH
        need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
             and path.stat().st_size == 7266, 'SYNTHETIC_FIXTURE_INVALID')
        raw = path.read_bytes()
        need(len(raw) == 7266 and sha(raw) == REFERENCE_SYNTHETIC_SHA, 'SYNTHETIC_FIXTURE_INVALID')
        return json.loads(raw)
    except (OSError, ValueError, TypeError):
        raise SafariHold('SYNTHETIC_FIXTURE_INVALID') from None


def load_public_assets(root):
    root = Path(root).resolve()
    try:
        manifest_path = root / 'site-build.json'
        need(manifest_path.is_file() and not manifest_path.is_symlink()
             and manifest_path.stat().st_size <= 1024 * 1024, 'ASSET_MANIFEST_INVALID')
        manifest = json.loads(manifest_path.read_bytes())
        need(manifest.get('schema') == 'RACE_AI_SAVED_PAGES_BUILD_V1'
             and isinstance(manifest.get('files'), dict), 'ASSET_MANIFEST_INVALID')
        assets = {}
        for name, expected in manifest['files'].items():
            need(isinstance(name, str) and re.fullmatch('[A-Za-z0-9_./-]{1,200}', name)
                 and not name.startswith('/') and all(part not in ('', '.', '..') for part in name.split('/')),
                 'ASSET_PATH_REJECTED')
            if name == '.nojekyll' or name.startswith('views/'):
                continue  # No encrypted view or fixture forecast endpoint is needed by this transport.
            need(Path(name).suffix in ('.html', '.js', '.css', '.json', '.webp', '.png', '.svg'), 'ASSET_PATH_REJECTED')
            path = root / name
            need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents))
                 and path.stat().st_size <= MAX_ASSET, 'ASSET_FILE_REJECTED')
            body = path.read_bytes()
            need(expected == {'bytes': len(body), 'sha256': sha(body)}, 'ASSET_HASH_MISMATCH')
            assets[name] = body
        need('index.html' in assets and 'app.js' in assets, 'ASSET_MANIFEST_INVALID')
        return assets
    except (OSError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, SafariHold):
            raise
        raise SafariHold('ASSET_MANIFEST_INVALID') from None


def load_candidate_assets(root):
    """Admit only the fixed reviewed checkout; never import its Python code."""
    root = Path(root).absolute()
    need(root.name == 'web' and root.is_dir() and root == root.resolve()
         and not any(p.is_symlink() for p in (root, *root.parents)), 'ASSET_FILE_REJECTED')
    checkout = root.parent

    def git(*arguments):
        try:
            result = subprocess.run(['git', '-C', str(checkout), *arguments],
                capture_output=True, timeout=15, env=driver_environment(os.environ))
            need(result.returncode == 0 and len(result.stdout) <= 65536, 'SOURCE_REVISION_MISMATCH')
            return result.stdout
        except (OSError, subprocess.SubprocessError):
            raise SafariHold('SOURCE_REVISION_MISMATCH') from None

    need(git('rev-parse', '--show-toplevel').decode().strip() == str(checkout)
         and git('rev-parse', 'HEAD').decode().strip() == CANDIDATE_SHA
         and git('rev-parse', 'HEAD:web').decode().strip() == CANDIDATE_WEB_TREE,
         'SOURCE_REVISION_MISMATCH')
    need(not git('status', '--porcelain', '--untracked-files=all', '--', 'web').strip(),
         'ASSET_HASH_MISMATCH')
    assets = {}
    try:
        entries = git('ls-tree', '-rz', '--full-tree', CANDIDATE_SHA, '--', 'web/').split(b'\0')
        for entry in filter(None, entries):
            metadata, full_name = entry.split(b'\t', 1)
            mode, kind, expected_blob = metadata.decode('ascii').split()
            name = full_name.decode('ascii').removeprefix('web/')
            need(full_name.startswith(b'web/') and re.fullmatch('[A-Za-z0-9_./-]{1,200}', name)
                 and all(part not in ('', '.', '..') for part in name.split('/')),
                 'ASSET_PATH_REJECTED')
            need(mode == '100644' and kind == 'blob'
                 and Path(name).suffix in ('.html', '.js', '.css', '.json', '.webp', '.png', '.svg'),
                 'ASSET_FILE_REJECTED')
            path = root / name
            need(path.is_file() and not any(p.is_symlink() for p in (path, *path.parents)),
                 'ASSET_FILE_REJECTED')
            with path.open('rb') as stream:
                body = stream.read(MAX_ASSET + 1)
            need(len(body) <= MAX_ASSET and hashlib.sha1(
                b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == expected_blob,
                'ASSET_HASH_MISMATCH')
            assets[name] = body
        # Ignored additions must not become an alternate asset or key route.
        need(all(not path.is_symlink() and (path.is_dir() or str(path.relative_to(root)) in assets)
                 for path in root.rglob('*')), 'ASSET_FILE_REJECTED')
        need(all(sha(assets.get(name, b'')) == digest for name, digest in CANDIDATE_ASSET_SHA256.items()),
             'ASSET_HASH_MISMATCH')
        synthetic_fixture(assets)
        return candidate_capture_assets(assets)
    except (OSError, ValueError, UnicodeError, KeyError) as error:
        if isinstance(error, SafariHold):
            raise
        raise SafariHold('ASSET_FILE_REJECTED') from None


def synthetic_candidate_index(index):
    """Only the synthetic candidate gains an in-memory fixture bootstrap."""
    need(isinstance(index, bytes) and sha(index) == CANDIDATE_ASSET_SHA256['index.html'],
         'ASSET_INDEX_INVALID')
    text = index.decode('utf-8')
    need(text.count('<head>') == 1 and not re.search(
        r'<meta\s+name=[\"\']race-ai-(?:encrypted-saved-view|private-saved-view|generation-api)', text),
        'ASSET_INDEX_INVALID')
    text = re.sub(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">', '', text)
    return text.replace('<head>', '<head><script src="/_acceptance/privacy.js"></script>'
        '<meta name="race-ai-private-saved-view" content="/api/forecast/saved">', 1).encode()


def private_index(index, *, encrypted=False):
    try:
        text = index.decode('utf-8')
        pattern = r'<meta name="race-ai-encrypted-saved-view" content="\./views/[a-f0-9]{64}\.json">'
        text, count = re.subn(pattern, lambda match: match[0] if encrypted else
                             '<meta name="race-ai-private-saved-view" content="/api/forecast/saved">', text)
        need(count == 1 and text.count('<head>') == 1, 'ASSET_INDEX_INVALID')
        text = re.sub(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">', '', text)
        return text.replace('<head>', '<head><script src="/_acceptance/privacy.js"></script>', 1).encode()
    except UnicodeError:
        raise SafariHold('ASSET_INDEX_INVALID') from None


PRIVACY_SCRIPT = rb'''"use strict";
globalThis.__raceSafariPrivacy={external_blocked:0,csp_blocked:0,page_errors:0,error_module:null,error_line:null,aes_successes:0};
addEventListener('securitypolicyviolation',()=>{__raceSafariPrivacy.csp_blocked++});
addEventListener('error',e=>{if(e.target!==window)return;__raceSafariPrivacy.page_errors++;
 try {const u=new URL(e.filename,location.href),name=u.pathname.slice(1);
  if(u.origin===location.origin&&['app.js','product-data.js','ui-model.js','saved-performance.js',
   'forecast-audit-model.js','saved-view-crypto.js'].includes(name)){
   __raceSafariPrivacy.error_module=name;__raceSafariPrivacy.error_line=e.lineno;
  }
 }catch{}
});
const originalFetch=globalThis.fetch.bind(globalThis);
const viewer=/^#saved=[a-f0-9]{64}\.([A-Za-z0-9_-]{43})$/.exec(location.hash||'')?.[1];
function admitted(method,url,headers,body){
 let decoded;try{decoded=decodeURIComponent(url.href);}catch{return false;}
 const keyPresent=viewer&&(url.href+decoded+JSON.stringify(headers||{})+String(body||'')).includes(viewer);
 return !keyPresent&&!url.hash&&body==null&&['GET','HEAD'].includes(String(method||'GET').toUpperCase())&&url.origin===location.origin;
}
globalThis.fetch=(input,options)=>{
 const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
 const headers=options?.headers||input?.headers,serialized=typeof Headers!=='undefined'?Array.from(new Headers(headers)):headers;
 if(!admitted(options?.method||input?.method,url,serialized,options?.body)){
  __raceSafariPrivacy.external_blocked++;return Promise.reject(new TypeError('blocked'));}
 return originalFetch(input,options);
};
const originalOpen=XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open=function(method,url,...args){
 if(!admitted(method,new URL(url,location.href))){__raceSafariPrivacy.external_blocked++;throw new TypeError('blocked');}
 return originalOpen.call(this,method,url,...args);
};
const originalHeader=XMLHttpRequest.prototype.setRequestHeader,originalSend=XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.setRequestHeader=function(name,value){
 if(viewer&&(String(name)+String(value)).includes(viewer)){__raceSafariPrivacy.external_blocked++;throw new TypeError('blocked');}
 return originalHeader.call(this,name,value);
};
XMLHttpRequest.prototype.send=function(body){if(body){__raceSafariPrivacy.external_blocked++;throw new TypeError('blocked');}return originalSend.call(this,body);};
navigator.sendBeacon=()=>{__raceSafariPrivacy.external_blocked++;return false};
globalThis.WebSocket=globalThis.EventSource=function(){__raceSafariPrivacy.external_blocked++;throw new TypeError('blocked')};
if(globalThis.crypto?.subtle){const decrypt=crypto.subtle.decrypt.bind(crypto.subtle);
 crypto.subtle.decrypt=async(...args)=>{const value=await decrypt(...args);__raceSafariPrivacy.aes_successes++;return value;};}
'''


def synthetic_guard(fixture):
    """Observe the real parser output; never expose its source data in reports."""
    return ('''\nconst expectedFixture=''' + wire(fixture) + ''';
let product;
Object.defineProperty(globalThis,'RaceProductData',{configurable:false,
 get(){return product;},set(api){
  product=Object.freeze({...api,parse(raw){
   const valid=JSON.stringify(raw)===JSON.stringify(expectedFixture);
   __raceSafariPrivacy.synthetic_fixture_verified=false;
   if(!valid)throw new Error('synthetic fixture required');
   const parsed=api.parse(raw),ids=parsed.records.map(r=>r.race_id).sort();
   if(parsed.dataset_status!=='SYNTHETIC_ONLY'||parsed.records.some(r=>r.scope!=='synthetic')||
      JSON.stringify(ids)!==JSON.stringify(expectedFixture.records.map(r=>r.race_id).sort()))
     throw new Error('synthetic fixture required');
   __raceSafariPrivacy.synthetic_fixture_verified=true;
   __raceSafariPrivacy.synthetic_fixture_sha256=''' + wire(SYNTHETIC_SHA) + ''';
   return parsed;
  }});
 }});
''').encode()


def synthetic_capture_guard(fixture, *, candidate_ui=False):
    if not candidate_ui:
        return synthetic_guard(fixture)
    need(sha(wire(fixture).encode()) == REFERENCE_SYNTHETIC_SHA, 'SYNTHETIC_FIXTURE_INVALID')
    script = synthetic_guard(fixture)
    old = ('__raceSafariPrivacy.synthetic_fixture_sha256=' + wire(SYNTHETIC_SHA) + ';').encode()
    new = ('__raceSafariPrivacy.synthetic_fixture_sha256=' + wire(REFERENCE_SYNTHETIC_SHA) + ';').encode()
    need(script.count(old) == 1, 'SYNTHETIC_FIXTURE_INVALID')
    # The existing app tolerates unavailable preference storage. Disable writes
    # for this fresh public-only capture; never clear or conceal existing values.
    storage = b'''if(typeof Storage==='function')Object.defineProperty(Storage.prototype,'setItem',{
        configurable:false,writable:false,value(){throw new TypeError('synthetic storage disabled');}});\n'''
    return storage + script.replace(old, new, 1)


class LoopbackSite:
    """Known byte assets + one memory-only private route; no filesystem handler."""
    def __init__(self, assets, view, *, secrets=(), encrypted_seed=None, tamper_seed=False,
                 synthetic=False, candidate_ui=False, current_v5=None):
        need(current_v5 is None or (view is None and encrypted_seed is not None
             and not synthetic and not candidate_ui), 'CURRENT_V5_REPLAY_INVALID')
        self.current_v5 = current_v5
        need(not candidate_ui or (synthetic and secrets == () and encrypted_seed is None),
             'SYNTHETIC_SCREENSHOT_REJECTED')
        self.candidate_ui = candidate_ui
        self.assets = candidate_capture_assets(assets) if candidate_ui else dict(assets)
        self.assets['index.html'] = (synthetic_candidate_index(assets['index.html']) if candidate_ui else
                                    private_index(assets['index.html'], encrypted=encrypted_seed is not None))
        need(encrypted_seed is None or view is None, 'ENCRYPTED_SEED_INVALID')
        self.view = wire(view).encode() if view is not None else None
        self.seed_path = encrypted_seed['path'] if encrypted_seed else None
        self.synthetic_fixture_sha256 = None
        self.privacy_script = PRIVACY_SCRIPT
        if current_v5 is not None:
            self.privacy_script += current_v5_replay_script(current_v5)
        if synthetic:
            fixture = synthetic_capture_fixture(assets, candidate_ui=candidate_ui)
            need(encrypted_seed is None and wire(view) == wire(fixture), 'SYNTHETIC_FIXTURE_INVALID')
            self.synthetic_fixture_sha256 = REFERENCE_SYNTHETIC_SHA if candidate_ui else SYNTHETIC_SHA
            self.privacy_script += synthetic_capture_guard(fixture, candidate_ui=candidate_ui)
        if encrypted_seed:
            raw = encrypted_seed['raw']
            if tamper_seed:
                doc = json.loads(raw)
                cipher = doc['ciphertext']
                doc['ciphertext'] = ('A' if cipher[0] != 'A' else 'B') + cipher[1:]
                raw = wire(doc).encode()
            self.assets[self.seed_path] = raw
        self.secrets = tuple(value for value in secrets if isinstance(value, str) and len(value) >= 8)
        need(not any(value.encode() in (self.view or b'') or any(value.encode() in body for body in self.assets.values())
                     for value in self.secrets), 'PRIVATE_NETWORK_BOUNDARY_FAILED')
        self.audit = {'private_view_reads': 0, 'rejected_requests': 0, 'secret_in_request': False,
                      'encrypted_seed_reads': 0, 'non_read_requests': 0, 'outbound_requests_permitted': 0}
        if current_v5 is not None:
            self.audit.update(current_v5_manifest_reads=0, current_v5_cipher_reads=0)

    def __enter__(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_read()

            def do_HEAD(self):
                self.handle_read(head=True)

            def do_POST(self):
                site.audit['non_read_requests'] += 1
                self.handle_read(reject_method=True)

            do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_POST

            def handle_read(self, head=False, reject_method=False):
                details = urllib.parse.unquote(self.path) + str(self.headers)
                if any(value in details for value in site.secrets):
                    site.audit['secret_in_request'] = True
                target = urllib.parse.urlsplit(self.path)
                valid_host = self.headers.get('Host') == site.origin.removeprefix('http://')
                valid_origin = self.headers.get('Origin') in (None, site.origin)
                status, body, mime = 200, b'', 'application/octet-stream'
                name = target.path.removeprefix('/') or 'index.html'
                query_ok = not target.query or (name in site.assets and name.endswith(('.js', '.css'))
                            and target.query == 'v=' + sha(site.assets[name])[:12])
                if reject_method:
                    status = 405
                elif not valid_host or not valid_origin or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    status = 403
                elif not query_ok or target.fragment or self.headers.get('Content-Length') not in (None, '0'):
                    status = 400
                elif name == 'api/forecast/saved' and site.view is not None:
                    body, mime = site.view, 'application/json; charset=utf-8'
                    if not head:
                        site.audit['private_view_reads'] += 1
                elif name == '_acceptance/privacy.js':
                    body, mime = site.privacy_script, 'text/javascript; charset=utf-8'
                elif site.current_v5 is not None and name.startswith('_acceptance/current-v5/'):
                    payload = _current_v5_helpers().current_v5_payload(site.current_v5, '/' + name)
                    if payload is None:
                        status = 404
                    else:
                        body, kind = payload
                        mime = 'application/json; charset=utf-8'
                        if not head:
                            site.audit['current_v5_manifest_reads' if kind == 'manifest'
                                       else 'current_v5_cipher_reads'] += 1
                elif name in site.assets:
                    body = site.assets[name]
                    if name == site.seed_path and not head:
                        site.audit['encrypted_seed_reads'] += 1
                    mime = 'text/javascript' if name.endswith('.js') else mimetypes.guess_type(name)[0] or mime
                elif name == 'favicon.ico':
                    status = 204
                elif name in ('api/forecast/status', 'api/racer-daily', 'api/racer-daily/status'):
                    status = 404  # Existing app treats absent generation/daily endpoints as unavailable.
                else:
                    status = 404
                if status >= 400:
                    body = b''
                    site.audit['rejected_requests'] += 1
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Content-Security-Policy', CSP)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                if not head:
                    self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)
        self.url = self.origin + '/'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        try:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=3)
            need(not self.thread.is_alive(), 'SAFARI_SESSION_CLEANUP_FAILED')
        finally:
            self.view = b''
            self.current_v5 = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SafariHold('LIVE_PAGES_BYTES_DIFFER')


def verify_live_assets(assets):
    """Read only public executable bytes; credentials are never used by this client."""
    opener = urllib.request.build_opener(NoRedirect())
    checked = {}
    for name, body in assets.items():
        if not name.endswith(('.js', '.css', '.html')):
            continue
        url = 'https://haji84.github.io/RACE-AI/' + name + '?verify=' + PAGES_SHA
        request = urllib.request.Request(url, headers={'User-Agent': 'RACE-AI-native-Safari-acceptance/1',
                                                     'Cache-Control': 'no-cache'})
        try:
            with opener.open(request, timeout=24) as response:
                need(response.status == 200 and response.url == url and response.read(len(body) + 1) == body,
                     'LIVE_PAGES_BYTES_DIFFER')
        except (OSError, urllib.error.URLError):
            raise SafariHold('LIVE_PAGES_BYTES_DIFFER') from None
        checked[name] = sha(body)
    return checked


def driver_operation(method, path):
    """Classify internal W3C routes without returning an ID, URL or parameter."""
    if type(method) is not str or type(path) is not str:
        return 'unknown_command'
    if method == 'POST' and path == '/session':
        return 'new_session'
    match = re.fullmatch(r'/session/[A-Za-z0-9-]{1,100}(.*)', path)
    if not match:
        return 'unknown_command'
    suffix = match[1]
    known = {('DELETE', ''): 'delete_session', ('POST', '/url'): 'navigate',
             ('POST', '/execute/sync'): 'execute_script', ('GET', '/window/rect'): 'get_window_rect',
             ('POST', '/window/rect'): 'set_window_rect', ('POST', '/actions'): 'actions',
             ('GET', '/screenshot'): 'screenshot'}
    if method == 'POST' and re.fullmatch(r'/element/[A-Za-z0-9-]{1,160}/click', suffix):
        return 'element_click'
    if method == 'POST' and re.fullmatch(r'/element/[A-Za-z0-9-]{1,160}/value', suffix):
        return 'element_send_keys'
    return known.get((method, suffix), 'unknown_command')


def driver_error(operation, http_status=None, value=None):
    """Extract only public protocol enums and one exact public-message hint."""
    code = value.get('error') if type(value) is dict else None
    code = code if type(code) is str and code in W3C_ERRORS else None
    message = value.get('message') if type(value) is dict else None
    disabled = type(message) is str and (
        "You must enable the 'Allow Remote Automation' option in Safari's Develop menu" in message)
    error = DriverHold(operation=operation, http_status=http_status, w3c_error=code,
                       remote_automation_disabled=disabled)
    if operation == 'new_session' and type(value) is dict:
        error.startup = {
            'response_message_state': ('absent' if 'message' not in value else
                'non_string' if type(message) is not str else
                'nonempty_string' if message else 'empty_string'),
            'response_session_id_field_present': 'sessionId' in value,
            'response_capabilities_field_present': 'capabilities' in value}
    return error


def driver_document(raw, limit):
    if type(raw) is not bytes or len(raw) > limit:
        raise ValueError('driver response bound')
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('driver response duplicate field')
            value[key] = item
        return value
    def invalid_constant(_):
        raise ValueError('driver response nonfinite number')
    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise ValueError('driver response nonfinite number')
        return value
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=invalid_constant, parse_float=finite_float)


def driver_value(raw, limit):
    document = driver_document(raw, limit)
    if type(document) is not dict or set(document) != {'value'}:
        raise ValueError('driver response schema')
    return document['value']


def driver_error_response(operation, status, raw):
    """HTTP errors stay fatal; retain only the known W3C enum/public hint.

    Extra error-envelope metadata never enters reports. The success-response
    schema remains the strict driver_value contract, without this projection.
    """
    try:
        document = driver_document(raw, DRIVER_ERROR_LIMIT)
    except (ValueError, TypeError, RecursionError):
        return driver_error(operation, status)
    value = document.get('value') if type(document) is dict else None
    return driver_error(operation, status, value)


class WebDriver:
    """The Apple W3C endpoint is loopback only; response errors are never exposed."""
    def __init__(self, port):
        need(type(port) is int and 1024 <= port <= 65535, 'SAFARI_WEBDRIVER_FAILED')
        self.base = 'http://127.0.0.1:' + str(port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.session = None
        self.ui_context = {}
        self.native_browser = None
        self.first_seed_comparison_initial_selected_target = None

    def _diagnostic_error(self, error):
        error.ui_context = dict(self.ui_context) if type(self.ui_context) is dict else {}
        error.native_browser = failure_native_browser(self.native_browser)
        first = self.first_seed_comparison_initial_selected_target
        error.first_seed_comparison_initial_selected_target = first if type(first) is bool else None
        return error

    def call(self, method, path, body=None):
        operation = driver_operation(method, path)
        if not isinstance(path, str) or not path.startswith('/') or '?' in path:
            raise self._diagnostic_error(DriverHold(operation=operation))
        status = None
        try:
            request = urllib.request.Request(self.base + path,
                data=None if body is None else wire(body).encode(), method=method,
                headers={'Content-Type': 'application/json'})
            with self.opener.open(request, timeout=60) as response:
                status = response.status
                raw = response.read(DRIVER_RESPONSE_LIMIT + 1)
        except urllib.error.HTTPError as error:
            status, failure = error.code, driver_error(operation, error.code)
            try:
                failure = driver_error_response(operation, status, error.read(DRIVER_ERROR_LIMIT + 1))
            except (OSError, ValueError, TypeError, HTTPException):
                pass
            finally:
                error.close()
            raise self._diagnostic_error(failure) from None
        except (OSError, ValueError, TypeError, HTTPException):
            raise self._diagnostic_error(DriverHold(operation=operation, http_status=status)) from None
        try:
            result = driver_value(raw, DRIVER_RESPONSE_LIMIT)
        except (ValueError, TypeError):
            raise self._diagnostic_error(DriverHold(operation=operation, http_status=status)) from None
        if status != 200 or isinstance(result, dict) and 'error' in result:
            raise self._diagnostic_error(driver_error(operation, status, result)) from None
        return result

    def new_session(self):
        self.first_seed_comparison_initial_selected_target = None
        result = self.call('POST', '/session', {'capabilities': {'alwaysMatch': {
            'browserName': 'Safari', 'platformName': 'macOS'}}})
        if not isinstance(result, dict) or type(result.get('sessionId')) is not str or not re.fullmatch(
                '[A-Za-z0-9-]{1,100}', result['sessionId']):
            raise DriverHold(operation='new_session', http_status=200)
        self.session = result['sessionId']
        try:
            identity = native_identity(result.get('capabilities'))
            self.native_browser = dict(identity)
            return identity
        except SafariHold:
            raise DriverHold('SAFARI_CAPABILITIES_INVALID', operation='new_session', http_status=200) from None

    def command(self, method, suffix, body=None):
        need(self.session is not None, 'SAFARI_WEBDRIVER_FAILED')
        return self.call(method, '/session/' + self.session + suffix, body)

    def script(self, script, *args):
        return self.command('POST', '/execute/sync', {'script': script, 'args': list(args)})

    def wait(self, script, *args, timeout=45):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.script(script, *args)
            if value:
                return value
            time.sleep(0.15)
        try:
            probe = self.script('''return {page_errors:globalThis.__raceSafariPrivacy?.page_errors,
                error_module:globalThis.__raceSafariPrivacy?.error_module,
                error_line:globalThis.__raceSafariPrivacy?.error_line,
                visible_page:document.querySelector('.page:not([hidden])')?.id,
                viewport_width:innerWidth};''')
        except SafariHold:
            probe = {}
        raise AppHold(probe)

    def element(self, selector, visible=True):
        element = self.wait('''return Array.from(document.querySelectorAll(arguments[0])).find(e=>
            !arguments[1] || (e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')) || null;''',
                              selector, visible)
        need(isinstance(element, dict), 'APP_UI_CHECK_FAILED')
        ident = element.get('element-6066-11e4-a52e-4f735466cecf')
        need(isinstance(ident, str) and re.fullmatch('[A-Za-z0-9-]{1,160}', ident), 'APP_UI_CHECK_FAILED')
        return ident

    def click(self, selector, visible=True, *, preflight_control=None):
        context = self.ui_context
        self.ui_context = dict(context, click_path='visible_element' if visible else 'native_option',
                               hit_target_verified=False, click_control_matches_preflight=None)
        try:
            element = self.element(selector, visible)
            if visible:
                if type(preflight_control) is str:
                    self.ui_context['click_control_matches_preflight'] = element == preflight_control
                self._click_visible_element(element)
            else:
                # Preserve the existing native option-click behavior.
                self.command('POST', '/element/' + element + '/click', {})
        finally:
            self.ui_context = context

    def _click_visible_element(self, element):
        context = self.ui_context
        self.ui_context = dict(context, click_path='visible_element', hit_target_verified=False)
        try:
            reference = {'element-6066-11e4-a52e-4f735466cecf': element}
            self.script('arguments[0].scrollIntoView({block:"center",inline:"center",behavior:"instant"});', reference)
            self.wait('''const e=arguments[0],r=e.getBoundingClientRect();
            const left=Math.max(0,r.left),right=Math.min(innerWidth,r.right),
                  top=Math.max(0,r.top),bottom=Math.min(innerHeight,r.bottom);
            if(left>=right||top>=bottom)return false;
            const hit=document.elementFromPoint((left+right)/2,(top+bottom)/2);
            return hit===e||e.contains(hit);''', reference)
            self.ui_context['hit_target_verified'] = True
            self.command('POST', '/element/' + element + '/click', {})
        finally:
            self.ui_context = context

    def _select_probe(self, selector, value):
        probe = self.script('''/* native-select-preflight: read only */
            const controls=Array.from(document.querySelectorAll(arguments[0])),e=controls[0],wanted=String(arguments[1]);
            const isSelect=e instanceof HTMLSelectElement,options=isSelect?Array.from(e.options):[],
                targets=options.filter(o=>o.value===wanted),target=targets[0];
            let visible=!!e?.getClientRects().length;
            for(let node=e;node instanceof Element;node=node.parentElement){
                const s=getComputedStyle(node);
                if(node.hidden||s.display==='none'||s.visibility!=='visible'||Number(s.opacity)===0)visible=false;
            }
            let targetVisible=!!target;
            for(let node=target;node instanceof Element&&node!==e;node=node.parentElement){
                const s=getComputedStyle(node);
                if(node.hidden||s.display==='none'||s.visibility!=='visible'||Number(s.opacity)===0)targetVisible=false;
            }
            const r=e?.getBoundingClientRect(),inView=!!r&&r.width>0&&r.height>0&&r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight,
                hit=inView?document.elementFromPoint(r.left+r.width/2,r.top+r.height/2):null;
            let pickerOpenSupported=null,pickerOpen=null;
            try {
                if(typeof CSS!=='undefined'&&typeof CSS.supports==='function'){
                    const supported=CSS.supports('selector(:open)');
                    if(typeof supported==='boolean'){
                        pickerOpenSupported=supported;
                        if(supported&&isSelect){
                            const opened=e.matches(':open');
                            if(typeof opened==='boolean')pickerOpen=opened;
                        }
                    }
                }
            } catch {}
            return {control:e||null,control_count:controls.length,option_count:options.length,target_count:targets.length,
                control_is_select:isSelect,control_connected:!!e?.isConnected,control_enabled:!!e&&!e.matches(':disabled'),
                control_visible:visible,target_connected:!!target?.isConnected&&target.closest('select')===e,
                target_enabled:!!target&&!target.matches(':disabled')&&!!e&&!e.matches(':disabled'),
                target_visible:targetVisible,
                selected_target:!!target&&e.value===wanted&&target.selected,control_in_view:inView,
                hit_target:!!hit&&(hit===e||e.contains(hit)),focused:!!e&&document.activeElement===e,
                document_focused:document.hasFocus(),document_visibility:document.visibilityState,
                viewport_width:innerWidth,viewport_height:innerHeight,
                page_errors:globalThis.__raceSafariPrivacy?.page_errors,
                error_module:globalThis.__raceSafariPrivacy?.error_module,
                error_line:globalThis.__raceSafariPrivacy?.error_line,
                picker_open_supported:pickerOpenSupported,picker_open:pickerOpen};''', selector, value)
        self.ui_context['select_preflight'] = select_diagnostic(probe)
        valid = type(probe) is dict and all(type(probe.get(key)) is bool for key in SELECT_BOOLEANS if key != 'same_control') \
            and all(type(probe.get(key)) is int and 0 <= probe[key] <= 10000 for key in SELECT_COUNTS)
        reference = probe.get('control') if type(probe) is dict else None
        ident = reference.get('element-6066-11e4-a52e-4f735466cecf') if type(reference) is dict else None
        if not (valid and probe['control_count'] == probe['target_count'] == 1 and probe['option_count'] >= 1
                and all(probe[key] for key in ('control_is_select', 'control_connected', 'control_enabled',
                    'control_visible', 'target_connected', 'target_enabled', 'target_visible'))
                and isinstance(ident, str) and re.fullmatch('[A-Za-z0-9-]{1,160}', ident)):
            raise self._diagnostic_error(SelectHold(probe))
        return ident, probe

    def select(self, selector, value):
        value = str(value)
        self.ui_context['select_phase'] = 'initial'
        ident, initial = self._select_probe(selector, value)
        ordinal, stage, action = (self.ui_context.get(key) for key in ('seed_comparison_ordinal', 'stage', 'action'))
        if (type(ordinal) is int and ordinal == 1 and type(stage) is str and stage == 'encrypted_seed_valid'
                and type(action) is str and action == 'select_seed_history'):
            self.first_seed_comparison_initial_selected_target = initial['selected_target']
        # A closed option has no rectangle. Prepare its parent through the
        # existing scroll/hit/native-click path, even for an already selected target.
        self.click(selector, preflight_control=ident)
        self.ui_context['select_phase'] = 'prepared'
        prepared_ident, prepared = self._select_probe(selector, value)
        prepared['same_control'] = prepared_ident == ident
        self.ui_context['select_preflight'] = select_diagnostic(prepared)
        if not all(prepared[key] for key in ('same_control', 'control_in_view', 'hit_target', 'focused')):
            raise self._diagnostic_error(SelectHold(prepared))
        self.click(selector + ' option[value=' + json.dumps(value) + ']', visible=False)
        self.ui_context['select_phase'] = 'readback'
        self.wait('return document.querySelector(arguments[0])?.value===arguments[1]', selector, value)
        selected_ident, selected = self._select_probe(selector, value)
        selected['same_control'] = selected_ident == ident
        self.ui_context['select_preflight'] = select_diagnostic(selected)
        if not selected['selected_target']:
            raise self._diagnostic_error(SelectHold(selected))

    def budget(self, value):
        element = self.element('#simulation-budget')
        # Use explicit native key events, rather than embedding a modifier
        # chord in Element Send Keys text. Never clear to an invalid empty
        # value or rewrite application state through JavaScript.
        self._click_visible_element(element)
        actions = [{'type': 'keyDown', 'value': '\ue03d'},
                   {'type': 'keyDown', 'value': 'a'}, {'type': 'keyUp', 'value': 'a'},
                   {'type': 'keyUp', 'value': '\ue03d'}]
        for key in str(value) + '\ue004':
            actions.extend([{'type': 'keyDown', 'value': key}, {'type': 'keyUp', 'value': key}])
        self.command('POST', '/actions', {'actions': [
            {'type': 'key', 'id': 'native-budget-keyboard', 'actions': actions}]})
        try:
            self.wait('return document.querySelector("#simulation-budget")?.value===arguments[0]', str(value))
        except SafariHold as error:
            if str(error) != 'APP_UI_CHECK_FAILED':
                raise
            probe = self.script('''const e=document.querySelector('#simulation-budget');
                return {value:e?.value,focused:document.activeElement===e,valid:e?.validity.valid===true};''')
            raise BudgetHold(value, probe) from None

    def close(self):
        self.close_observation = dict(delete_outcome='not_required', delete_http_status=None, delete_error_code=None)
        if self.session is not None:
            self.close_observation['delete_outcome'] = 'other_failure'
            try:
                if self.command('DELETE', '') is not None:
                    self.close_observation['delete_outcome'] = 'unexpected_response'
                    return False
                self.close_observation['delete_outcome'] = 'acknowledged'
            except SafariHold as error:
                self.close_observation['delete_outcome'] = 'other_failure'
                if isinstance(error, DriverHold) and type(error.operation) is str and error.operation == 'delete_session':
                    status, code = error.http_status, error.w3c_error
                    self.close_observation.update(delete_outcome='webdriver_error',
                        delete_http_status=status if type(status) is int and 100 <= status <= 599 else None,
                        delete_error_code=code if type(code) is str and code in W3C_ERRORS else None)
                return False
            finally:
                self.session = None
        return True


@contextmanager
def apple_driver():
    need(platform.system() == 'Darwin', 'NATIVE_MACOS_REQUIRED')
    need(os.path.isfile('/usr/bin/safaridriver') and os.access('/usr/bin/safaridriver', os.X_OK), 'SAFARIDRIVER_REQUIRED')
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    try:
        process = subprocess.Popen(['/usr/bin/safaridriver', '--port', str(port)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=driver_environment(os.environ))
    except OSError:
        raise DriverHold('SAFARIDRIVER_UNAVAILABLE', operation='start_driver') from None
    driver = WebDriver(port)
    startup = {'tcp_connected': None, 'process_running_before_connect': None}
    primary = None
    try:
        try:
            ready = False
            for _ in range(100):
                code = process.poll()
                startup['process_running_before_connect'] = (True if code is None else
                    False if type(code) is int else None)
                if code is not None:
                    raise DriverHold('SAFARIDRIVER_UNAVAILABLE', operation='wait_for_driver')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                        startup['tcp_connected'] = True
                        ready = True
                        break
                except OSError:
                    startup['tcp_connected'] = False
                    time.sleep(0.1)
            if not ready:
                raise DriverHold('SAFARIDRIVER_UNAVAILABLE', operation='wait_for_driver')
            identity = driver.new_session()
        except DriverHold as error:
            observed = getattr(error, 'startup', None)
            observed = dict(observed) if type(observed) is dict else {}
            observed.update(startup)
            try:
                code = process.poll()
                observed['process_running_after_failure'] = (True if code is None else
                    False if type(code) is int else None)
                observed['process_exit_code_after_failure'] = code if type(code) is int else None
            except Exception:
                pass  # Diagnostic sampling must preserve the original startup failure.
            error.startup = observed
            raise
        yield driver, identity
    except BaseException as error:
        primary = error
        try:
            if type(getattr(error, 'ui_context', None)) is not dict:
                context = getattr(driver, 'ui_context', None)
                error.ui_context = dict(context) if type(context) is dict else {}
        except Exception:
            pass
        raise
    finally:
        cleanup = dict(close_result=None, delete_outcome=None, delete_http_status=None,
            delete_error_code=None, process_result=None, terminate_attempted=False,
            kill_attempted=False, primary_failure_preserved=primary is not None)
        try:
            closed = driver.close()
            cleanup['close_result'] = 'true' if closed is True else 'not_true'
        except Exception:
            closed = False
            cleanup['close_result'] = 'exception'
        try:
            observed = getattr(driver, 'close_observation', None)
            if type(observed) is dict:
                cleanup.update((name, observed.get(name)) for name in (
                    'delete_outcome', 'delete_http_status', 'delete_error_code'))
        except Exception:
            pass
        phase = 'poll'
        try:
            if process.poll() is None:
                phase = 'terminate'
                cleanup['terminate_attempted'] = True
                process.terminate()
            phase = 'wait'
            try:
                process.wait(timeout=5)
                cleanup['process_result'] = 'wait_returned'
            except subprocess.TimeoutExpired:
                phase = 'kill'
                cleanup['kill_attempted'] = True
                process.kill()
                phase = 'wait_after_kill'
                process.wait(timeout=5)
                cleanup['process_result'] = 'wait_after_kill_returned'
        except Exception:
            closed = False
            cleanup['process_result'] = phase + '_failed'
        if closed is not True:
            failure = primary if primary is not None else SafariHold('SAFARI_SESSION_CLEANUP_FAILED')
            try:
                failure.session_cleanup = cleanup
                if type(getattr(failure, 'ui_context', None)) is not dict:
                    context = getattr(driver, 'ui_context', None)
                    failure.ui_context = dict(context) if type(context) is dict else {}
            except Exception:
                pass
            if primary is None:
                raise failure


def read_authenticated_view(source_root, seed):
    """Existing read-only feed/AES/context code; no producer or model is invoked."""
    source_root = Path(source_root).resolve()
    result = subprocess.run(['git', '-C', str(source_root), 'rev-parse', 'HEAD'], capture_output=True, timeout=10)
    need(result.returncode == 0 and result.stdout.decode().strip() == SOURCE_SHA, 'SOURCE_REVISION_MISMATCH')
    sys.path.insert(0, str(source_root))
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        from scripts import boat_saved_site_context as context_module
        from scripts import boat_saved_view_feed as feed
        from scripts import boat_private_original_vault as vault
        repo = vault._environment(source_root)
        config = feed._json(feed._read(source_root / 'audit/state/boat-saved-view-input.json', 8192), 8192)
        raw = base64.b64decode(config['bootstrap'], validate=True)
        need(feed.sha(raw) == config['bootstrap_sha256'], 'SAVED_VIEW_UNAVAILABLE')
        bootstrap = feed.F.open_bootstrap(raw)
        git = feed.F.FeedRepository(repo)
        _, _, generation, view = feed.F.current_view(git, bootstrap)
        now = datetime.now(timezone.utc)
        today = now.astimezone(context_module.JST).date().isoformat()
        day = max((row['event_date_jst'] for row in view['records']
                   if row.get('sport') == 'boat' and row['event_date_jst'] <= today), default='')
        context = context_module.build_context(bootstrap, view, generation, now=now, event_day=day)
        # Preserve the independently derived context's counts/hashes while omitting its private URL.
        safe_context = validate_context(context)
        viewer_key = base64.urlsafe_b64encode(bootstrap['key']).decode().rstrip('=')
        _, seed_view = feed.F.decrypt_view(seed['raw'], bootstrap['key'], view_id=bootstrap['view_id'])
        retired = {p.get('model_id') for row in seed_view['records']
            for p in [row.get('prediction'), *row.get('comparison_predictions', [])]
            if p is not None and context_module.is_retired(p.get('model_id'))}
        seed_context = build_seed_context(seed, bootstrap, seed_view, feed.F.forecast_anchor(seed_view), retired=retired)
        fragment = '#saved=' + bootstrap['view_id'] + '.' + viewer_key
    return safe_context, view, {'key': viewer_key, 'fragment': fragment, 'context': seed_context}


def browser_snapshot(driver):
    return driver.script('''return {url:location.href,local:{...localStorage},session:{...sessionStorage},
        cookie:document.cookie,privacy:globalThis.__raceSafariPrivacy};''')


def select_saved_day(driver, day):
    driver.script('''const e=document.querySelector('#selected-date');e.value=arguments[0];
        e.dispatchEvent(new Event('change',{bubbles:true}));''', day)
    driver.wait('return document.querySelector("#display-day")?.textContent.includes(arguments[0])', day)


def click_saved_page(driver, page):
    driver.click('[data-page=' + json.dumps(page) + ']')
    driver.wait('return !document.querySelector(arguments[0])?.hidden', '#page-' + page)


def open_saved_race(driver, item):
    click_saved_page(driver, 'races')
    if driver.script('return !!document.querySelector("#all-venues")?.getClientRects().length'):
        driver.click('#all-venues')
    finished = (item.get('result') or {}).get('status') in ('final', 'void')
    phase = 'upcoming' if not finished and datetime.now(timezone.utc).timestamp() < datetime.fromisoformat(
        item['cutoff_at'].replace('Z', '+00:00')).timestamp() else 'results'
    driver.click('[data-race-view=' + json.dumps(phase) + ']')
    target = '#page-races [data-open-race=' + json.dumps(item['race_id']) + ']'
    for _ in range(5):
        if driver.script('return !!document.querySelector(arguments[0])', target):
            driver.click(target)
            return
        button = driver.script('''return Array.from(document.querySelectorAll('#page-races button'))
            .find(e=>e.textContent.includes('さらに60件表示')) || null;''')
        need(isinstance(button, dict), 'APP_UI_CHECK_FAILED')
        ident = button.get('element-6066-11e4-a52e-4f735466cecf')
        need(isinstance(ident, str) and re.fullmatch('[A-Za-z0-9-]{1,160}', ident), 'APP_UI_CHECK_FAILED')
        driver._click_visible_element(ident)
    raise SafariHold('APP_UI_CHECK_FAILED')


def seed_detail(driver):
    return driver.script('''const panel=document.querySelector('#detail-tab-content .forecast-panel');
        return {model_id:panel?.dataset.modelId,index:document.querySelector('#prediction-select')?.value,
        tickets:Array.from(panel?.querySelectorAll('.saved-ticket .combo')||[],n=>
        Array.from(n.querySelectorAll('.lane'),e=>Number(e.textContent)))};''')


def verify_seed_outcome(kind, probe):
    need(kind in ('missing-key', 'wrong-key', 'wrong-view', 'modified-cipher')
         and isinstance(probe, dict) and probe.get('refused') is True
         and all(type(probe.get(k)) is int and probe[k] == 0 for k in
                 ('forecast_panels', 'race_cards', 'aes_successes')), 'ENCRYPTED_SEED_REFUSAL_FAILED')


def encrypted_seed_checks(assets, seed, private, secrets):
    """No screenshots/DOM exports. Each denial starts with a new origin/session."""
    fragment = private['fragment']
    view_id, key = fragment[7:].split('.')
    wrong_key = ('A' if key[0] != 'A' else 'B') + key[1:]
    wrong_view = ('0' if view_id[0] != '0' else '1') + view_id[1:]
    cases = [('missing-key', '', False), ('wrong-key', '#saved=' + view_id + '.' + wrong_key, False),
             ('wrong-view', '#saved=' + wrong_view + '.' + key, False),
             ('modified-cipher', fragment, True)]
    refusals = []
    for kind, candidate, tamper in cases:
        case_secrets = (*secrets, wrong_key)
        with LoopbackSite(assets, None, encrypted_seed=seed, tamper_seed=tamper, secrets=case_secrets) as site:
            with apple_driver() as (driver, _):
                ui_diagnostic(driver, 'encrypted_seed_refusal', {
                    'missing-key': 'load_missing_key', 'wrong-key': 'load_wrong_key',
                    'wrong-view': 'load_wrong_view', 'modified-cipher': 'load_modified_cipher'}[kind])
                driver.command('POST', '/url', {'url': site.url + candidate})
                driver.wait('''return /いつもの閲覧用リンク|レース情報を読み込めませんでした/.test(
                    document.querySelector('#file-message')?.textContent||'');''', timeout=90)
                probe = driver.script('''return {refused:/いつもの閲覧用リンク|レース情報を読み込めませんでした/.test(
                    document.querySelector('#file-message')?.textContent||''),
                    forecast_panels:document.querySelectorAll('.forecast-panel').length,
                    race_cards:document.querySelectorAll('#all-races [data-open-race]').length,
                    aes_successes:globalThis.__raceSafariPrivacy?.aes_successes};''')
                verify_seed_outcome(kind, probe)
                verify_private_boundary(browser_snapshot(driver), site.audit, case_secrets,
                                        fragment=candidate, encrypted=True, require_read=kind != 'missing-key')
        refusals.append(kind)
    with LoopbackSite(assets, None, encrypted_seed=seed, secrets=secrets) as site:
        with apple_driver() as (driver, _):
            ui_diagnostic(driver, 'encrypted_seed_valid', 'load_valid_seed')
            driver.command('POST', '/url', {'url': site.url + fragment})
            driver.wait('return document.querySelector("#file-message")?.textContent.includes("保存済み予想")', timeout=90)
            context = private['context']
            ui_diagnostic(driver, 'encrypted_seed_valid', 'select_saved_day')
            select_saved_day(driver, context['day'])
            ui_diagnostic(driver, 'encrypted_seed_valid', 'open_seed_probe')
            open_saved_race(driver, context['probe'])
            ui_diagnostic(driver, 'encrypted_seed_valid', 'open_outlook')
            driver.click('[data-detail-tab="outlook"]')
            for ordinal, choice in enumerate(context['probe']['choices'], start=1):
                ui_diagnostic(driver, 'encrypted_seed_valid', 'select_seed_history')
                driver.ui_context['seed_comparison_ordinal'] = ordinal
                driver.select('#prediction-select', choice['index'])
                verify_model_choice(choice, seed_detail(driver))
            snapshot = browser_snapshot(driver)
            need(type(snapshot['privacy'].get('aes_successes')) is int
                 and snapshot['privacy']['aes_successes'] > 0, 'ENCRYPTED_SEED_INVALID')
            verify_private_boundary(snapshot, site.audit, secrets, fragment=fragment, encrypted=True)
    return {'browser_aes_verified': True, 'seed_sha256': seed['cipher_sha256'],
            'same_seed_model_original_comparisons': 2, 'refusals_verified': refusals,
            'viewer_capability_verified': True, 'viewer_key_in_fragment': True,
            'viewer_key_in_requests_or_web_storage': False, 'owner_key_in_browser': False,
            'account_login_verified': False, 'current_v5_live_continuation_verified': False,
            'outbound_browser_requests_permitted': 0, 'real_screenshots_or_traces_exported': 0}


def settle_candidate_synthetic_capture(driver, width, page):
    # A synchronous DOM read does not wait for a presented frame. Require
    # matching geometry on consecutive animation frames after resetting scroll.
    driver.script('''const page=arguments[0],width=arguments[1],state={ready:false};
        globalThis.__raceSafariSyntheticCapture=state;
        window.scrollTo({top:0,left:0,behavior:"instant"});
        const headings={home:"YOUR RACE DASHBOARD",races:"RACES & RESULTS",detail:"RACE DETAIL",
            picks:"TICKET ALLOCATION",results:"AI FORECAST RESULTS",
            research:"RESEARCH & VERIFICATION",settings:"PREFERENCES"};
        const visible=e=>!!e?.getClientRects().length&&getComputedStyle(e).visibility==="visible"
            &&getComputedStyle(e).display!=="none"&&getComputedStyle(e).opacity!=="0";
        const measure=()=>{
            const pages=Array.from(document.querySelectorAll(".page:not([hidden])"));
            const title=document.querySelector("#page-title");
            if(document.visibilityState!=="visible"||location.hash!=="#"+page||innerWidth!==width
                ||pages.length!==1||pages[0].id!=="page-"+page||!visible(pages[0])||!visible(title)
                ||document.querySelector("#page-eyebrow")?.textContent.trim()!==headings[page]
                ||scrollX!==0||scrollY!==0||document.scrollingElement.scrollTop!==0
                ||document.scrollingElement.scrollLeft!==0)return null;
            if(page==="detail"&&(!visible(document.querySelector("#race-detail .detail-tabs"))
                ||document.querySelectorAll("#detail-tab-content .saved-ticket").length!==8))return null;
            const box=title.getBoundingClientRect();
            if(box.top<0||box.bottom>innerHeight)return null;
            return [innerWidth,innerHeight,box.top,box.left,box.width,box.height,
                document.documentElement.scrollHeight].join(",");
        };
        let previous=null;
        const frame=()=>{
            if(globalThis.__raceSafariSyntheticCapture!==state)return;
            const current=measure();
            state.ready=current!==null&&current===previous;previous=current;
            if(!state.ready)requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);''', page, width)
    driver.wait('return globalThis.__raceSafariSyntheticCapture?.ready===true')


def save_synthetic_screenshot(driver, site, folder, width, page):
    expected_sha = REFERENCE_SYNTHETIC_SHA if site.candidate_ui else SYNTHETIC_SHA
    need(site.synthetic_fixture_sha256 == expected_sha and site.seed_path is None
         and width in VISUAL_WIDTHS and page in VISUAL_PAGES, 'SYNTHETIC_SCREENSHOT_REJECTED')
    for settled in range(2 if site.candidate_ui else 1):
        if settled:
            settle_candidate_synthetic_capture(driver, width, page)
        probe = driver.script('''return {origin:location.origin,fragment:location.hash,
            verified:globalThis.__raceSafariPrivacy?.synthetic_fixture_verified===true,
            fixture_sha256:globalThis.__raceSafariPrivacy?.synthetic_fixture_sha256,
            page_errors:globalThis.__raceSafariPrivacy?.page_errors,
            visible_page:document.querySelector('.page:not([hidden])')?.id,
            width:innerWidth,overflow:document.documentElement.scrollWidth>innerWidth,
            encrypted:!!document.querySelector('meta[name="race-ai-encrypted-saved-view"]'),
            synthetic_banner:document.querySelector('#source-state')?.textContent.includes('合成')};''')
        need(isinstance(probe, dict) and probe.get('origin') == site.origin
             and probe.get('fragment') in ('', '#' + page) and probe.get('verified') is True
             and probe.get('fixture_sha256') == expected_sha and probe.get('page_errors') == 0
             and probe.get('visible_page') == 'page-' + page and probe.get('width') == width
             and probe.get('overflow') is False and probe.get('encrypted') is False
             and probe.get('synthetic_banner') is True, 'SYNTHETIC_SCREENSHOT_REJECTED')
        snapshot = browser_snapshot(driver)
        verify_private_boundary(snapshot, site.audit, ())
        if site.candidate_ui:
            need(snapshot.get('local') == {} and snapshot.get('session') == {} and snapshot.get('cookie') == '',
                 'SYNTHETIC_SCREENSHOT_REJECTED')
    encoded = driver.command('GET', '/screenshot')
    need(isinstance(encoded, str) and len(encoded) <= 24 * 1024 * 1024, 'SYNTHETIC_SCREENSHOT_REJECTED')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise SafariHold('SYNTHETIC_SCREENSHOT_REJECTED') from None
    need(raw.startswith(b'\x89PNG\r\n\x1a\n'), 'SYNTHETIC_SCREENSHOT_REJECTED')
    path = Path(folder) / (str(width) + '-' + page + '.png')
    with path.open('xb') as stream:
        stream.write(raw)
    return {'name': path.name, 'bytes': len(raw), 'sha256': sha(raw)}


def _reference_synthetic_counts_valid(value):
    return (type(value) is dict and set(value) == {sport for sport, _, _ in REFERENCE_SYNTHETIC_COUNTS}
            and all(type(value[sport]) is dict and set(value[sport]) == {'races', 'participants'}
                    and type(value[sport]['races']) is int and value[sport]['races'] == races
                    and type(value[sport]['participants']) is int and value[sport]['participants'] == participants
                    for sport, races, participants in REFERENCE_SYNTHETIC_COUNTS))


def reference_synthetic_checks(driver):
    """Measure all invented rosters before using the same seven capture pages."""
    click_saved_page(driver, 'races')
    result = {}
    for sport, races, participants in REFERENCE_SYNTHETIC_COUNTS:
        driver.click('[data-sport=' + json.dumps(sport) + ']')
        driver.click('[data-race-view="upcoming"]')
        ident = 'synthetic:2030-01-01:' + sport + ':1'
        driver.wait('return !!document.querySelector("#all-races [data-race-id="+JSON.stringify(arguments[0])+"]")', ident)
        probe = driver.script('''return {
            races:document.querySelectorAll('#all-races .race-card').length,
            participants:document.querySelector('#all-races [data-race-id='+JSON.stringify(arguments[0])+']')?.querySelectorAll('.racer-card').length,
            upcoming:document.querySelector('[data-race-view="upcoming"]')?.getAttribute('aria-selected')==='true',
            portraits:document.querySelectorAll('#all-races img').length};''', ident)
        need(type(probe) is dict and set(probe) == {'races', 'participants', 'upcoming', 'portraits'}
             and type(probe['races']) is int and probe['races'] == races
             and type(probe['participants']) is int and probe['participants'] == participants
             and probe['upcoming'] is True and type(probe['portraits']) is int and probe['portraits'] == 0,
             'SYNTHETIC_SCREENSHOT_REJECTED')
        result[sport] = {'races': probe['races'], 'participants': probe['participants']}
    driver.click('[data-sport="boat"]')
    return result


def synthetic_visual_checks(assets, folder, *, candidate_ui=False):
    """Fresh process, fresh origin/session, exact public fixture, screenshots only."""
    need(not any(os.environ.get(k) for k in ('RACE_AI_STATE_KEY', 'GH_TOKEN', 'GITHUB_TOKEN')),
         'SYNTHETIC_SCREENSHOT_REJECTED')
    if candidate_ui:
        require_synthetic_environment()
    folder = Path(folder).absolute()
    need(not folder.exists() and not any(p.is_symlink() for p in folder.parents), 'SYNTHETIC_OUTPUT_REJECTED')
    fixture = synthetic_capture_fixture(assets, candidate_ui=candidate_ui)
    screenshots, widths = [], []
    folder.mkdir(mode=0o700)
    with LoopbackSite(assets, fixture, synthetic=True, candidate_ui=candidate_ui) as site:
        with apple_driver() as (driver, identity):
            ui_diagnostic(driver, 'synthetic_capture', 'load_saved_view')
            driver.command('POST', '/url', {'url': site.url})
            driver.wait('return globalThis.__raceSafariPrivacy?.synthetic_fixture_verified===true', timeout=90)
            need(driver.script('return Object.keys(localStorage).length===0&&Object.keys(sessionStorage).length===0&&document.cookie===""'),
                 'SYNTHETIC_SCREENSHOT_REJECTED')
            select_saved_day(driver, fixture['event_date_jst'])
            ui_diagnostic(driver, 'synthetic_capture', 'prepare_synthetic_tickets')
            click_saved_page(driver, 'picks')
            driver.click('#copy-top8')
            driver.wait('return document.querySelectorAll(".ticket-row").length===8')
            driver.click('#equal-allocate')
            for width in VISUAL_WIDTHS:
                ui_diagnostic(driver, 'synthetic_capture', 'set_viewport')
                driver.command('POST', '/window/rect', {'width': width, 'height': 1000})
                widths.append(require_viewport(width, driver.script('return {width:innerWidth,height:innerHeight}')))
                ui_diagnostic(driver, 'synthetic_capture', 'select_saved_day', width)
                select_saved_day(driver, fixture['event_date_jst'])
                if candidate_ui:
                    ui_diagnostic(driver, 'synthetic_capture', 'verify_synthetic_sports', width)
                    widths[-1]['reference_synthetic_sports'] = reference_synthetic_checks(driver)
                for page in VISUAL_PAGES:
                    ui_diagnostic(driver, 'synthetic_capture', 'open_synthetic_page', width, page=page)
                    if page == 'detail':
                        open_saved_race(driver, fixture['records'][0])
                    else:
                        click_saved_page(driver, page)
                    if page == 'races':
                        driver.click('[data-race-view="upcoming"]' if candidate_ui else '[data-race-view="results"]')
                        driver.wait('return document.querySelectorAll("#all-races [data-open-race]").length>0')
                    driver.script('window.scrollTo({top:0,left:0,behavior:"instant"});')
                    ui_diagnostic(driver, 'synthetic_capture', 'capture_synthetic_page', width, page=page)
                    screenshots.append(save_synthetic_screenshot(driver, site, folder, width, page))
    report = {'schema': 'RACE_AI_SYNTHETIC_SAFARI_VISUAL_V1', 'dataset_status': 'SYNTHETIC_ONLY',
              'public_fixture_sha256': REFERENCE_SYNTHETIC_SHA if candidate_ui else SYNTHETIC_SHA, 'native_browser': identity,
              'viewports': widths, 'screenshots': screenshots, 'real_data_context_used_for_capture': False,
              'physical_iphone_verified': False, 'all_eight_reference_screens_visually_verified': False}
    if candidate_ui:
        report.update(schema='RACE_AI_SYNTHETIC_SAFARI_VISUAL_V2', candidate_source=candidate_identity(),
            synthetic_session_cleanup_verified=True, account_login_verified=False,
            current_v5_live_continuation_verified=False, real_data_verified=False)
    with (folder / 'synthetic-only.json').open('x') as stream:
        stream.write(wire(report) + '\n')
    verify_synthetic_artifacts(folder, candidate_ui=candidate_ui)
    return report


def verify_synthetic_artifacts(folder, *, candidate_ui=False):
    folder = Path(folder)
    need(folder.is_dir() and not any(p.is_symlink() for p in (folder, *folder.parents)), 'SYNTHETIC_OUTPUT_REJECTED')
    try:
        manifest = folder / 'synthetic-only.json'
        need(manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size < 32768,
             'SYNTHETIC_OUTPUT_REJECTED')
        report = json.loads(manifest.read_bytes())
        names = {str(w) + '-' + p + '.png' for w in VISUAL_WIDTHS for p in VISUAL_PAGES}
        need(report['schema'] == ('RACE_AI_SYNTHETIC_SAFARI_VISUAL_V2' if candidate_ui else
                                  'RACE_AI_SYNTHETIC_SAFARI_VISUAL_V1')
             and report['dataset_status'] == 'SYNTHETIC_ONLY'
             and report['public_fixture_sha256'] == (REFERENCE_SYNTHETIC_SHA if candidate_ui else SYNTHETIC_SHA)
             and report.get('real_data_context_used_for_capture') is False
             and report.get('physical_iphone_verified') is False
             and report.get('all_eight_reference_screens_visually_verified') is False
             and len(report['screenshots']) == len(names)
             and {row['name'] for row in report['screenshots']} == names
             and {p.name for p in folder.iterdir()} == names | {'synthetic-only.json'}, 'SYNTHETIC_OUTPUT_REJECTED')
        if candidate_ui:
            need(report.get('candidate_source') == candidate_identity()
                 and report.get('synthetic_session_cleanup_verified') is True
                 and all(report.get(key) is False for key in ('account_login_verified',
                     'current_v5_live_continuation_verified', 'real_data_verified')),
                 'SYNTHETIC_OUTPUT_REJECTED')
            native_identity(report.get('native_browser'))
        viewports = report.get('viewports')
        need(isinstance(viewports, list) and len(viewports) == len(VISUAL_WIDTHS), 'SYNTHETIC_OUTPUT_REJECTED')
        for width, viewport in zip(VISUAL_WIDTHS, viewports):
            need(isinstance(viewport, dict) and viewport.get('requested_width') == width
                 and viewport.get('requested_width_verified') is True
                 and viewport.get('physical_iphone_verified') is False, 'SYNTHETIC_OUTPUT_REJECTED')
            require_viewport(width, {'width': viewport.get('actual_inner_width'),
                                     'height': viewport.get('actual_inner_height')})
            if candidate_ui:
                need(_reference_synthetic_counts_valid(viewport.get('reference_synthetic_sports')),
                     'SYNTHETIC_OUTPUT_REJECTED')
        for row in report['screenshots']:
            path = folder / row['name']
            need(path.is_file() and not path.is_symlink() and 8 <= path.stat().st_size <= 16 * 1024 * 1024,
                 'SYNTHETIC_OUTPUT_REJECTED')
            raw = path.read_bytes()
            need(raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw) == row['bytes'] and sha(raw) == row['sha256'],
                 'SYNTHETIC_OUTPUT_REJECTED')
    except (OSError, ValueError, KeyError, TypeError):
        raise SafariHold('SYNTHETIC_OUTPUT_REJECTED') from None
    result = {'status': 'SYNTHETIC_SCREENSHOT_ARTIFACTS_VERIFIED', 'screenshots': len(names),
              'dataset_status': 'SYNTHETIC_ONLY'}
    if candidate_ui:
        result.update(candidate_source=candidate_identity(), physical_iphone_verified=False,
                      all_eight_reference_screens_visually_verified=False)
    return result


def app_checks(driver, site, context, secrets):
    ui_diagnostic(driver, 'latest_p1_private_transport', 'load_saved_view')
    driver.command('POST', '/url', {'url': site.url})
    driver.wait('return document.querySelector("#file-message")?.textContent.includes("保存済み予想")', timeout=90)
    viewport_results, comparisons, native_views, result_views = [], 0, 0, 0
    probe = context['model_switch_probe']

    def click_page(page):
        click_saved_page(driver, page)

    def select_day():
        select_saved_day(driver, context['day'])

    def open_race(item):
        open_saved_race(driver, item)

    for width in (1440, 390):
        ui_diagnostic(driver, 'latest_p1_private_transport', 'set_viewport')
        driver.command('POST', '/window/rect', {'width': width, 'height': 1000})
        actual = driver.script('return {width:innerWidth,height:innerHeight}')
        viewport_results.append(require_viewport(width, actual))
        ui_diagnostic(driver, 'latest_p1_private_transport', 'select_saved_day', width)
        select_day()
        native = context['native_probe']
        ui_diagnostic(driver, 'latest_p1_private_transport', 'open_native_race', width)
        open_race(native)
        ui_diagnostic(driver, 'latest_p1_private_transport', 'select_native_history', width)
        driver.select('#prediction-select', native['index'])
        need(driver.script('''return document.querySelector('#prediction-select').selectedOptions[0].textContent.startsWith('P1 ')
            && document.querySelector('#detail-tab-content .forecast-panel')?.dataset.nativeDispatch==='true';'''),
             'APP_UI_CHECK_FAILED')
        native_views += 1
        ui_diagnostic(driver, 'latest_p1_private_transport', 'open_comparison_race', width)
        open_race(probe)
        ui_diagnostic(driver, 'latest_p1_private_transport', 'open_outlook', width)
        driver.click('[data-detail-tab="outlook"]')
        for choice in probe['choices']:
            ui_diagnostic(driver, 'latest_p1_private_transport', 'select_comparison_history', width)
            driver.select('#prediction-select', choice['index'])
        for choice in probe['choices']:
            ui_diagnostic(driver, 'latest_p1_private_transport', 'select_comparison_model', width)
            driver.select('#detail-model-select', choice['model_id'])
            detail = driver.script('''const panel=document.querySelector('#detail-tab-content .forecast-panel');
                return {model_id:panel?.dataset.modelId,index:document.querySelector('#prediction-select')?.value,
                tickets:Array.from(panel.querySelectorAll('.saved-ticket .combo'),n=>
                Array.from(n.querySelectorAll('.lane'),e=>Number(e.textContent)))};''')
            verify_model_choice(choice, detail)
            comparisons += 1
        ui_diagnostic(driver, 'latest_p1_private_transport', 'open_research', width)
        click_page('research')
        need(driver.script('return document.querySelector("#research-model-select")?.value===arguments[0]',
                           probe['choices'][1]['model_id']), 'APP_UI_CHECK_FAILED')
        ui_diagnostic(driver, 'latest_p1_private_transport', 'return_from_research', width)
        driver.click('#research-race-audit [data-return-to-race]')
        need(driver.script('return document.querySelector("#detail-model-select")?.value===arguments[0]',
                           probe['choices'][1]['model_id']), 'APP_UI_CHECK_FAILED')
        ui_diagnostic(driver, 'latest_p1_private_transport', 'open_results', width)
        click_page('results')
        values = driver.script('return Array.from(document.querySelectorAll("#results-model option"),e=>e.value)')
        groups = set()
        for value in values:
            try:
                fields = json.loads(value)
                if isinstance(fields, list) and len(fields) >= 6 and fields[1:3] == ['boat', 'P1']:
                    groups.add(wire((fields[3:7] + [None])[:4]))
            except (TypeError, ValueError):
                pass
        need(all(wire(group) in groups for group in context['native_groups']), 'APP_UI_CHECK_FAILED')
        metrics = driver.script('return document.querySelector("#saved-result-metrics")?.textContent')
        count = re.search(r'取得結果\s*(\d+)レース', metrics or '')
        need(count and int(count[1]) >= context['minimum_results'] and
             all(label in metrics for label in ('的中', '不的中', '結果待ち')), 'APP_UI_CHECK_FAILED')
        for budget in (10000, 5000):
            ui_diagnostic(driver, 'latest_p1_private_transport', 'set_simulation_budget', width)
            driver.budget(budget)
            ui_diagnostic(driver, 'latest_p1_private_transport', 'select_simulation_mode', width)
            driver.select('#simulation-race-budget', '1000')
            simulation = driver.script('return document.querySelector("#simulation-metrics")?.textContent')
            need(isinstance(simulation, str) and all(label in simulation for label in
                 ('確定分の収支', '確定分の回収率', '未確定購入額', '全体の収支'))
                 and '試算を表示できません' not in simulation, 'APP_UI_CHECK_FAILED')
        need(driver.script('return document.documentElement.scrollWidth<=innerWidth'), 'APP_UI_CHECK_FAILED')
        result_views += 1
    snapshot = driver.script('''return {url:location.href,local:{...localStorage},session:{...sessionStorage},
                                cookie:document.cookie,privacy:globalThis.__raceSafariPrivacy};''')
    verify_private_boundary(snapshot, site.audit, secrets)
    return {'desktop_viewports': viewport_results, 'model_switch_original_comparisons': comparisons,
            'native_p1_detail_views': native_views, 'result_budget_views': result_views,
            'external_requests_blocked_before_network': snapshot['privacy']['external_blocked'],
            'csp_violations_blocked': snapshot['privacy']['csp_blocked'],
            'private_view_reads': site.audit['private_view_reads'], 'key_in_requests_url_or_storage': False,
            'outbound_browser_requests_permitted': 0, 'official_source_requests': 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--public-root', type=Path, required=True)
    parser.add_argument('--synthetic-only', action='store_true')
    parser.add_argument('--candidate-ui', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-synthetic-artifacts', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.candidate_ui:
            require_synthetic_environment()
            need(args.source_root is None and ((args.synthetic_only and args.output is not None
                 and args.verify_synthetic_artifacts is None) or (args.verify_synthetic_artifacts is not None
                 and not args.synthetic_only and args.output is None)), 'SYNTHETIC_OUTPUT_REJECTED')
        if args.verify_synthetic_artifacts is not None:
            print(wire(verify_synthetic_artifacts(args.verify_synthetic_artifacts, candidate_ui=args.candidate_ui)))
            return 0
        need(platform.system() == 'Darwin', 'NATIVE_MACOS_REQUIRED')
        assets = load_candidate_assets(args.public_root) if args.candidate_ui else load_public_assets(args.public_root)
        if args.synthetic_only:
            need(args.output is not None and args.source_root is None, 'SYNTHETIC_OUTPUT_REJECTED')
            report = synthetic_visual_checks(assets, args.output, candidate_ui=args.candidate_ui)
            print(wire({key: value for key, value in report.items() if key != 'screenshots'} | {'screenshots': len(report['screenshots'])}))
            return 0
        need(args.source_root is not None and args.output is None, 'SAVED_CONTEXT_INVALID')
        hashes = verify_live_assets(assets)
        seed = load_encrypted_seed(args.public_root)
        context, view, private_seed = read_authenticated_view(args.source_root, seed)
        secrets = tuple(value for value in (private_seed['key'], *(os.environ.get(k) for k in
            ('RACE_AI_STATE_KEY', 'GH_TOKEN', 'GITHUB_TOKEN'))) if value)
        with LoopbackSite(assets, view, secrets=secrets) as site:
            with apple_driver() as (driver, identity):
                checks = app_checks(driver, site, context, secrets)
        seed_checks = encrypted_seed_checks(assets, seed, private_seed, secrets)
        replay = read_current_v5_replay(args.source_root, seed)
        current = current_v5_checks(assets, seed, private_seed, replay, secrets)
        print(wire({'schema': 'RACE_AI_NATIVE_SAFARI_ACCEPTANCE_V2',
            'status': 'NATIVE_MACOS_SAFARI_SAVED_VIEW_VERIFIED', 'native_browser': identity,
            'verified_at': datetime.now(timezone.utc).isoformat(), 'pages_sha': PAGES_SHA,
            'read_only_source_sha': SOURCE_SHA, 'live_asset_sha256': hashes,
            'saved_day': current['saved_day'], 'authenticated_generation': current['authenticated_generation'],
            'authenticated_results': current['authenticated_results'],
            'authenticated_native_p1_groups': current['authenticated_native_p1_groups'],
            'latest_p1_private_transport': {**checks, 'transport': 'LOOPBACK_EXISTING_PRIVATE_SAVED_ENDPOINT',
                'saved_day': context['day'], 'authenticated_generation': context['generation'],
                'authenticated_results': context['minimum_results'],
                'authenticated_native_p1_groups': context['native_group_count']},
            'encrypted_seed': seed_checks, 'encrypted_current_v5': current,
            'browser_aes_verified': seed_checks.get('browser_aes_verified') is True and current.get('browser_aes_verified') is True,
            'private_sessions_cleanup_verified': True,
            'account_login_verified': False, 'current_v5_live_continuation_verified': current['current_v5_live_continuation_verified'],
            'current_day_verified': current['current_day_verified'],
            'browser_aes_and_owner_login_verified': False, 'physical_iphone_verified': False,
            'all_eight_reference_screens_visually_verified': False, 'plaintext_published': False,
            'forecast_or_result_mutation': False}))
        return 0
    except Exception as error:
        print(wire(failure_report(error)))
        return 2


MAX_CURRENT_V5_FILES = 512
MAX_CURRENT_V5_BYTES = 256 * 1024 * 1024
_CURRENT_V5_HELPERS = None


CURRENT_V5_REPLAY_PHASES = frozenset((
    'source_revision', 'module_binding', 'source_environment', 'input_binding',
    'bootstrap_authentication', 'snapshot_lookup', 'current_day_authentication',
    'context_binding', 'retained_history_authentication', 'seed_authentication',
    'replay_binding', 'snapshot_path_binding', 'snapshot_read_bounds',
    'snapshot_read', 'snapshot_cipher_binding'))
CURRENT_V5_REPLAY_UPSTREAM_REASONS = frozenset((
    'HISTORY_DAY_UNAVAILABLE', 'HISTORY_CHUNK_MISSING', 'HISTORY_CHUNK_HASH',
    'HISTORY_AUTH_FAILED', 'HISTORY_DAY_INVENTORY_MISMATCH',
    'HISTORY_CATALOG_UNAVAILABLE', 'HISTORY_INDEX_MISMATCH',
    'FEED_CIPHER_HASH', 'FEED_MANIFEST_MISMATCH', 'FEED_ORIGINAL_CHANGED',
    'STATE_GIT_BLOB_BOUND_EXCEEDED', 'FEED_GITHUB_TOKEN_REQUIRED'))


class CurrentV5ReplayHold(SafariHold):
    """Fixed replay failure facts; arbitrary exception text is never projected."""
    def __init__(self, phase, upstream_reason, counts):
        super().__init__('CURRENT_V5_REPLAY_INVALID')
        self.phase = phase if type(phase) is str and phase in CURRENT_V5_REPLAY_PHASES else None
        self.upstream_reason = upstream_reason if type(upstream_reason) is str \
            and upstream_reason in CURRENT_V5_REPLAY_UPSTREAM_REASONS else None
        self.counts = counts


CURRENT_V5_EVIDENCE_PHASES = frozenset((
    'native_p1_detail', 'comparison_originals', 'result_groups', 'result_metrics',
    'verify_probe', 'private_boundary', 'current_day_recheck'))


class CurrentV5EvidenceHold(SafariHold):
    def __init__(self, phase, diagnostic):
        super().__init__('CURRENT_V5_EVIDENCE_INVALID')
        self.phase = phase if type(phase) is str and phase in CURRENT_V5_EVIDENCE_PHASES else None
        self.diagnostic = current_v5_diagnostic(diagnostic)


class _CurrentV5API:
    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(name) from None


_CURRENT_V5_API = _CurrentV5API()


def _current_v5_helpers():
    global _CURRENT_V5_HELPERS
    if _CURRENT_V5_HELPERS is None:
        import importlib.util
        source = Path(__file__).resolve().with_name('boat_native_safari_current_v5.py')
        need(source.is_file() and not source.is_symlink(), 'CURRENT_V5_REPLAY_INVALID')
        spec = importlib.util.spec_from_file_location('native_safari_current_v5', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CURRENT_V5_HELPERS = module
        globals()['CurrentV5Replay'] = module.CurrentV5Replay
    return _CURRENT_V5_HELPERS


def build_current_v5_replay(*, snapshot_sha, latest_raw, ciphertexts, context,
        view_id, forecast_sha256, secrets=(), now=None):
    return _current_v5_helpers().build_current_v5_replay(
        snapshot_sha=snapshot_sha, latest_raw=latest_raw, ciphertexts=ciphertexts,
        context=context, view_id=view_id, forecast_sha256=forecast_sha256,
        secrets=secrets, now=now, _api=_CURRENT_V5_API)


def current_v5_replay_route(replay, logical_url):
    return _current_v5_helpers().current_v5_replay_route(replay, logical_url, _api=_CURRENT_V5_API)


def current_v5_replay_script(replay):
    return _current_v5_helpers().current_v5_replay_script(replay, _api=_CURRENT_V5_API)


def current_v5_probe_script():
    return _current_v5_helpers().current_v5_probe_script()


def count_current_v5_native_groups(reference_groups, UI_option_values):
    return _current_v5_helpers().count_current_v5_native_groups(
        reference_groups, UI_option_values, _api=_CURRENT_V5_API)


def current_v5_diagnostic(value):
    return _current_v5_helpers().current_v5_diagnostic(value)


def verify_current_v5_evidence(replay, probe, audit):
    return _current_v5_helpers().verify_current_v5_evidence(replay, probe, audit, _api=_CURRENT_V5_API)


def read_current_v5_replay(source_root, seed):
    return _current_v5_helpers().read_current_v5_replay(source_root, seed, _api=_CURRENT_V5_API)


def current_v5_checks(assets, seed, private, replay, secrets):
    return _current_v5_helpers().current_v5_checks(assets, seed, private, replay, secrets, _api=_CURRENT_V5_API)


class _CurrentV5SnapshotReader:
    """Narrow public seam; no writer methods or general delegation."""
    def __init__(self, git, snapshot_sha):
        self._reader = _current_v5_helpers()._CurrentV5SnapshotReader(
            git, snapshot_sha, _api=_CURRENT_V5_API)

    def head(self):
        return self._reader.head()

    def read(self, commit, path, limit):
        return self._reader.read(commit, path, limit)

    def fetch(self, commit):
        return self._reader.fetch(commit)

    def exists(self, commit, path):
        return self._reader.exists(commit, path)

    def validate_tree(self, commit):
        return self._reader.validate_tree(commit)


if __name__ == '__main__':
    raise SystemExit(main())
