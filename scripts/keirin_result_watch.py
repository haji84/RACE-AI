"""Observe results inside GitHub Actions and publish encrypted updates promptly.

No ChatGPT scheduled task, new source route, stop release or prediction write is
performed here. Existing key pins, source opt-ins, archive replay, official-byte
parsing and original-result scoring remain the admission boundaries.
"""
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse
import json
import os
import re
import subprocess
import time

from race_ai.keirin_result_observer import run_observer
from scripts import keirin_official_day_pipeline as pipeline


SCHEMA = 'RACE_AI_KEIRIN_RESULT_WATCH_V1'
REPOSITORY = 'haji84/RACE-AI'
JST = timezone(timedelta(hours=9))
RESULT_RACE_BUDGET = 8
BACKLOG_EVERY_TICKS = 10
PREFLIGHT_STAGES = frozenset({'RUNTIME_CONTEXT', 'ARCHIVE_AUTHORIZATION', 'OWNER_KEY',
    'PRIVATE_OUTPUT', 'CLOCK', 'SOURCE_COMMIT'})
PREFLIGHT_REASONS = frozenset('RESULT_WATCH_' + reason for reason in (
    'MODE_INVALID', 'TRUSTED_MAIN_EVENT_REQUIRED', 'SAVED_GIT_STORE_REQUIRED',
    'EXISTING_PUBLIC_KEY_REQUIRED', 'OWNER_KEY_PAIR_MISMATCH',
    'PRIVATE_ROOT_OUTSIDE_REPOSITORY_REQUIRED', 'AWARE_CLOCK_REQUIRED',
    'SOURCE_COMMIT_INVALID', 'CHECKOUT_COMMIT_MISMATCH', 'PREFLIGHT_CHECK_FAILED'))


class ResultWatchError(ValueError):
    def __init__(self, code, *, failure_stage=None):
        super().__init__(code)
        self.failure_stage = failure_stage


def need(ok, code):
    if not ok:
        raise ResultWatchError('RESULT_WATCH_' + code)


def utc_now():
    return datetime.now(timezone.utc)


def aware_time(clock):
    at = clock()
    need(isinstance(at, datetime) and at.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    return at


def current_commit(repo):
    value = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                    stderr=subprocess.DEVNULL, timeout=20).decode().strip()
    need(re.fullmatch('[a-f0-9]{40}', value), 'SOURCE_COMMIT_INVALID')
    expected = os.getenv('GITHUB_SHA')
    need(expected is None or value == expected, 'CHECKOUT_COMMIT_MISMATCH')
    return value


class TickOfficialFetcher:
    """Refresh each tick's cache without resetting its refusal/transport latch.

    The existing official_fetcher closure caches responses indefinitely. One
    such closure per entire observer lease would keep a pending result stale.
    This outer object persists for the lease, while only the response cache is
    renewed between successful ticks. Any failure prohibits renewal and calls.
    """
    def __init__(self, repo, clock):
        self.repo = repo
        self.clock = clock
        self._fetch = None
        self._failure = None
        self._past_diagnostics = []

    @property
    def stopped(self):
        return self._failure is not None

    @property
    def provider_denied(self):
        from race_ai.keirin_official_public_source import OfficialProviderStop
        return isinstance(self._failure, OfficialProviderStop)

    def safe_diagnostics(self):
        from race_ai.keirin_result_diagnostics import checked_diagnostics
        getter = getattr(self._fetch, 'safe_diagnostics', None)
        current = getter() if callable(getter) else []
        return checked_diagnostics((self._past_diagnostics + current)[-32:])

    def record_validation_failure(self):
        record = getattr(self._fetch, 'record_validation_failure', None)
        if callable(record):
            record()

    def begin_tick(self):
        if self._failure is not None:
            raise self._failure
        try:
            self._past_diagnostics = self.safe_diagnostics()
            self._fetch = pipeline.official_fetcher(self.repo, self.clock)
        except Exception as exc:
            self._failure = exc
            raise

    def __call__(self, url):
        if self._failure is not None:
            raise self._failure
        need(self._fetch is not None, 'SOURCE_TICK_NOT_STARTED')
        try:
            return self._fetch(url)
        except Exception as exc:
            self._failure = exc
            raise


def _preflight(*, repo, mode, private_root, owner_public_path,
               owner_private_pem, clock, source_commit):
    from race_ai import keirin_nationwide_auto_storage as storage
    from scripts.keirin_capture_public_two_sources import private_dir
    stage = 'RUNTIME_CONTEXT'
    try:
        need(mode in {'saved-only', 'observe'}, 'MODE_INVALID')
        need(os.getenv('GITHUB_REPOSITORY') == REPOSITORY and
             os.getenv('GITHUB_REF') == 'refs/heads/main' and
             os.getenv('GITHUB_EVENT_NAME') in {'schedule', 'workflow_dispatch'},
             'TRUSTED_MAIN_EVENT_REQUIRED')
        stage = 'ARCHIVE_AUTHORIZATION'
        if mode == 'saved-only':
            need(os.getenv('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED') == 'true',
                 'SAVED_GIT_STORE_REQUIRED')
        stage = 'OWNER_KEY'
        # No provider or GitHub request precedes the existing private/public pin.
        private_public = pipeline.check_owner_private_key(owner_private_pem)
        path = Path(owner_public_path)
        need(path.is_file() and not path.is_symlink(), 'EXISTING_PUBLIC_KEY_REQUIRED')
        public = storage.checked_public_key(path.read_bytes())
        private_public = storage.checked_public_key(private_public)
        need(public.public_numbers() == private_public.public_numbers(), 'OWNER_KEY_PAIR_MISMATCH')
        stage = 'PRIVATE_OUTPUT'
        root = private_dir(private_root)
        repo = Path(repo).resolve()
        need(root.resolve() != repo and repo not in root.resolve().parents,
             'PRIVATE_ROOT_OUTSIDE_REPOSITORY_REQUIRED')
        stage = 'CLOCK'
        at = aware_time(clock)
        stage = 'SOURCE_COMMIT'
        commit = source_commit if source_commit is not None else current_commit(repo)
        need(type(commit) is str and re.fullmatch('[a-f0-9]{40}', commit), 'SOURCE_COMMIT_INVALID')
    except Exception as exc:
        reason = str(exc) if type(exc) is ResultWatchError and str(exc) in PREFLIGHT_REASONS else \
            'RESULT_WATCH_PREFLIGHT_CHECK_FAILED'
        raise ResultWatchError(reason, failure_stage=stage) from None
    return repo, root, at, commit


def _content_identity(doc):
    # The producer reparses source bytes and derives each revision from all
    # result/arm/diagnostic fields. Re-observing the same revision is not new.
    content = [(r['race_id'], r['revision']) for r in doc['races']]
    return sha256(json.dumps(content, sort_keys=True,
                            separators=(',', ':')).encode()).hexdigest()


def _official_sp_context():
    return (os.getenv('GITHUB_ACTIONS')=='true' and
        os.getenv('GITHUB_REPOSITORY_ID')=='1416489937' and
        os.getenv('GITHUB_WORKFLOW_REF')==
            'haji84/RACE-AI/.github/workflows/keirin-result-live.yml@refs/heads/main' and
        os.getenv('GITHUB_JOB')=='observe-results')


def _run_official_sp_watch(*,summary,repo,root,private,commit,clock,monotonic,sleep,
                          interval_seconds,duration_seconds,max_ticks):
    from scripts import keirin_official_nationwide_continuation as continuation
    context=continuation.SettlementContext();last_state=None
    def stop_check():
        if context.lease is not None:
            try:context.lease.assert_active(repo=repo,now=clock())
            except Exception:
                summary['stop_check_failed']=True
                raise ResultWatchError('RESULT_WATCH_OFFICIAL_SP_STOP_CHECK_FAILED') from None
        return False
    def tick():
        nonlocal last_state
        out=continuation.settle_tick(repo=repo,owner_private_pem=private,private_root=root,
            clock=clock,max_races=RESULT_RACE_BUDGET,context=context,publish=True,source_commit=commit)
        last_state=out['state']
        summary['provider_requests']+=out['source_requests']
        summary['published_races']+=out['published_races']
        summary['publication_acks']+=out['publication_acks']
        summary['published_originals']+=out.get('published_originals',0)
        summary['original_publication_acks']+=out.get('original_publication_acks',0)
        summary['published_day_status']+=out.get('published_day_status',0)
        summary['published_snapshots']+=int(out['published_races']>0)
        summary['provider_denied']=out['provider_denied']
        summary['source_unavailable']=out['source_unavailable']
        summary['safe_diagnostics']=out['safe_diagnostics'][-32:]
        summary['safe_holds']=out.get('safe_holds',[])[-32:]
        # settle_tick publishes each captured, archived race immediately. The
        # controller only bounds the next poll; no private result enters this
        # summary or waits for the whole observation window to end.
        return dict(snapshot=None,provider_denied=out['provider_denied'],done=out['source_unavailable'])
    try:
        observed=run_observer(tick=tick,publish=lambda _:None,stop_check=stop_check,
            monotonic=monotonic,sleep=sleep,interval_seconds=interval_seconds,
            duration_seconds=duration_seconds,max_ticks=max_ticks)
    finally:context.close(clock)
    for key in ('state','ticks','done'):summary[key]=observed[key]
    summary['no_provider_tick']=summary['provider_requests']==0
    summary['source_route']='OFFICIAL_SP_VERIFIED_CONTINUATION'
    summary['source_lease_finish_failed']=context.finish_failed
    if last_state and last_state.startswith('HOLD_'):summary['state']=last_state
    if summary['stop_check_failed']:summary['state']='HOLD_RESULT_WATCH_OFFICIAL_SP_STOP_CHECK_FAILED'
    if context.finish_failed:summary['state']='HOLD_RESULT_WATCH_OFFICIAL_SP_FINISH_RECEIPT_FAILED'
    return summary


def run_watch(*, repo, mode, private_root, owner_public_path, owner_private_pem,
              clock=None, monotonic=None, sleep=None, interval_seconds=60,
              duration_seconds=540, max_ticks=10, source_commit=None):
    """Reuse the official settlement path with its existing eight-race budget.

    saved-only visits each selected existing day once without waiting and never
    constructs a provider fetcher. observe uses one persistent GitHub client and
    one refusal-latched provider wrapper. Due current-day archived originals
    take priority; otherwise older days get at most one tick in ten. Each tick
    publishes its bounded batch, without waiting for the whole day to finish.
    All plaintext files live in a per-tick temporary private folder.
    """
    from race_ai import keirin_github_evidence_client as github
    from race_ai import keirin_github_provider_stop as stop
    from race_ai import keirin_result_updates as updates
    from scripts import keirin_official_backlog_days as backlog
    clock = clock or utc_now
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    repo, root, at, commit = _preflight(repo=repo, mode=mode,
        private_root=private_root, owner_public_path=owner_public_path,
        owner_private_pem=owner_private_pem, clock=clock, source_commit=source_commit)
    summary = dict(schema=SCHEMA, mode=mode, day_jst=at.astimezone(JST).date().isoformat(),
        state='RESULT_WATCH_SAVED_COMPLETE', ticks=0, publication_acks=0,
        published_snapshots=0, published_races=0, published_originals=0,published_day_status=0,
        original_publication_acks=0, provider_denied=False,
        no_provider_tick=True, provider_requests=0, days_visited=[], days_held=0,
        stop_check_failed=False, source_unavailable=False, safe_diagnostics=[], done=False,
        target_interval_seconds=interval_seconds, result_race_budget=RESULT_RACE_BUDGET,
        current_day_priority=True, backlog_check_every_ticks=BACKLOG_EVERY_TICKS,
        due_current_originals=None)
    if mode=='observe' and _official_sp_context():
        return _run_official_sp_watch(summary=summary,repo=repo,root=root,private=owner_private_pem,
            commit=commit,clock=clock,monotonic=monotonic,sleep=sleep,interval_seconds=interval_seconds,
            duration_seconds=duration_seconds,max_ticks=max_ticks)
    if mode == 'observe' and not (
            os.getenv('RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED') == 'true' and
            os.getenv('RACE_AI_KEIRIN_OFFICIAL_SOURCE_ENABLED') == 'true'):
        summary['state'] = 'HOLD_RESULT_WATCH_SOURCE_DISABLED'
        return summary

    known_days = None
    client = None
    fetch = None
    day_cursor = 0
    backlog_cursor = 0
    last_stop_code = None

    def stopped():
        nonlocal last_stop_code
        day = aware_time(clock).astimezone(JST).date().isoformat()
        marker = stop.read_for_observed_day(repo=repo, day=day)
        last_stop_code = marker['code'] if marker is not None else None
        return marker is not None

    def retain_diagnostics(value=None):
        from race_ai.keirin_result_diagnostics import checked_diagnostics
        rows = list(summary['safe_diagnostics'])
        if fetch is not None:
            rows += fetch.safe_diagnostics()
        if value is not None:
            rows += value
        # The same validated receipt can appear in the fetcher and day report.
        unique = {json.dumps(row, sort_keys=True): row for row in rows}
        summary['safe_diagnostics'] = checked_diagnostics(list(unique.values())[-32:])

    def days():
        nonlocal known_days
        if known_days is None:
            known_days = backlog.discover_days(repo)
        selected = backlog.select_days(aware_time(clock), known_days)
        return [d for d in selected if d in known_days] if mode == 'saved-only' else selected

    def select_day():
        nonlocal day_cursor, backlog_cursor
        selected = days()
        current = selected[0]
        saved = pipeline.load_day_evidence(repo, current, owner_private_pem)
        schedule = saved['schedule']
        due = 0
        if schedule is not None:
            originals = pipeline.read_originals(repo, current)
            now = aware_time(clock)
            due = sum(row['race_id'] in originals and
                row.get('official_cutoff_at') is not None and
                pipeline.model.when(row['official_cutoff_at']) < now and
                saved['official_records'].get(row['race_id'], {}).get('state') != 'OFFICIAL_FINAL'
                for row in schedule['races'])
        summary['due_current_originals'] = due
        day_cursor += 1
        older = [day for day in selected[1:] if day in known_days]
        if not due and older and day_cursor % BACKLOG_EVERY_TICKS == 0:
            chosen = older[backlog_cursor % len(older)]
            backlog_cursor += 1
            return chosen
        return current

    def one_day(day):
        nonlocal client, fetch
        if day not in summary['days_visited']:
            summary['days_visited'].append(day)
        if mode == 'saved-only':
            # The fixed four-arm trial uses its own authenticated archive and
            # may have no general-day schedule. Publish it independently so a
            # display retry never needs a new provider request or a replayed
            # runtime date. A later general-day failure keeps this receipt.
            from scripts import keirin_official_form_canary as canary
            canary_doc = updates.saved_canary_updates(repo, owner_private_pem) if day == canary.DAY else None
            if canary_doc is not None:
                from race_ai.keirin_frozen_forecast_view import saved_frozen_forecast
                original_receipt = saved_frozen_forecast(repo, owner_private_pem, commit)
                need(type(original_receipt) is dict and original_receipt.get('state') in {
                    'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED', 'EXISTING_FROZEN_DISPLAY_REUSED'} and
                    type(original_receipt.get('published_originals')) is int and
                    original_receipt['published_originals'] in (0, 1) and
                    type(original_receipt.get('provider_requests')) is int and
                    original_receipt['provider_requests'] == 0 and
                    (original_receipt['state'] == 'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED' or
                     original_receipt['published_originals'] == 0), 'FROZEN_PUBLICATION_ACK_INVALID')
                summary['published_originals'] += original_receipt['published_originals']
                summary['original_publication_acks'] += 1
                publish(canary_doc)
            saved = pipeline.load_day_evidence(repo, day, owner_private_pem)
            if saved['schedule'] is None:
                if canary_doc is None:
                    summary['days_held'] += 1
                return None
        if client is None:
            client = github.GitHubEvidenceClient()
        if mode == 'observe':
            if fetch is None:
                fetch = TickOfficialFetcher(repo, clock)
            fetch.begin_tick()
        with TemporaryDirectory(prefix='result-tick-', dir=root) as folder:
            tick_root = Path(folder); tick_root.chmod(0o700)
            try:
                report = pipeline.run_settlement(day=day, repo=repo,
                    private_root=tick_root, owner_public_path=owner_public_path,
                    owner_private_pem=owner_private_pem, max_races=RESULT_RACE_BUDGET, clock=clock,
                    collect_official=mode == 'observe', github_client=client,
                    shared_official_fetch=fetch)
            except pipeline.OfficialPipelineError as exc:
                retain_diagnostics(getattr(exc, 'safe_diagnostics', []))
                if str(exc) != 'OFFICIAL_SCHEDULE_NOT_AVAILABLE':
                    raise
                summary['days_held'] += 1
                summary['source_unavailable'] = mode == 'observe'
                return None
            retain_diagnostics(report.get('safe_diagnostics', []))
            if mode == 'observe' and report.get('provider_state') == 'HOLD_OFFICIAL_PROVIDER_STOPPED_THIS_POLL':
                summary['source_unavailable'] = True
            saved = pipeline.load_day_evidence(repo, day, owner_private_pem)
            doc = updates.from_official_records(saved['official_records'], report)
            return doc if doc['races'] else None

    def publish(doc):
        receipt = updates.publish_updates(repo, doc, commit, clock=clock,
                                          owner_private_pem=owner_private_pem)
        need(type(receipt) is dict and receipt.get('state') in {
            'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED',
            'EXISTING_RESULT_DISPLAY_REUSED', 'NO_ADMITTED_RESULT_UPDATES'} and
            type(receipt.get('published_races')) is int and
            0 <= receipt['published_races'] <= len(doc['races']), 'PUBLICATION_ACK_INVALID')
        need(receipt['state'] == 'KEIRIN_NOTE_ENCRYPTED_GIT_READBACK_VERIFIED' or
             receipt['published_races'] == 0, 'PUBLICATION_ACK_INVALID')
        summary['publication_acks'] += 1
        summary['published_races'] += receipt['published_races']
        if receipt['published_races']:
            summary['published_snapshots'] += 1

    if mode == 'saved-only':
        if _official_sp_context():
            # This scope has a separate bounded evidence index. Restoring it
            # never enables the legacy provider or consumes a source lease.
            from race_ai import keirin_official_nationwide_records as sp_records
            from scripts import keirin_official_nationwide_continuation as continuation
            try:
                for day in sp_records.discover_days(repo)[:10]:
                    replay=continuation.replay_results(repo=repo,owner_private_pem=owner_private_pem,
                        day=day,source_commit=commit,publish=True)
                    summary['published_races']+=replay['published_races']
                    summary['publication_acks']+=replay['publication_acks']
                    summary['published_originals']+=replay.get('published_originals',0)
                    summary['original_publication_acks']+=replay.get('original_publication_acks',0)
                    summary['published_day_status']+=replay.get('published_day_status',0)
                    if 'public_forecasts' in replay:
                        summary['public_forecasts']=replay['public_forecasts']
                    summary['published_snapshots']+=int(replay['published_races']>0)
                    summary['days_held']+=replay['results_held']
                    if day not in summary['days_visited']:summary['days_visited'].append(day)
            except Exception:
                summary['days_held']+=1
                summary['state']='HOLD_RESULT_WATCH_OFFICIAL_SP_SAVED_REPLAY_FAILED'
        try:
            selected_days = days()
        except Exception:
            summary.update(state='HOLD_RESULT_WATCH_SAVED_DAY_DISCOVERY_FAILED',
                failure_stage='SAVED_DAY_DISCOVERY',
                failure_reason='RESULT_WATCH_SAVED_HISTORY_UNAVAILABLE')
            return summary
        for day in selected_days:
            summary['ticks'] += 1
            try:
                doc = one_day(day)
                if doc is not None:
                    publish(doc)
            except Exception:
                # A later corrupt/unreadable day must not erase the receipt
                # counts for earlier verified publications in this run.
                summary['days_held'] += 1
                summary['state'] = 'HOLD_RESULT_WATCH_SAVED_DAY_FAILED'
                summary['failure_stage'] = 'SAVED_DAY_REPLAY_OR_PUBLICATION'
                summary['failure_reason'] = 'RESULT_WATCH_SAVED_DAY_FAILED'
                return summary
        summary['done'] = True
        return summary

    def tick():
        day = select_day()
        doc = one_day(day)
        try:
            marker_stop = stopped()
            denied = last_stop_code == stop.DENIED or bool(fetch and fetch.provider_denied)
            if (marker_stop or bool(fetch and fetch.stopped)) and not denied:
                summary['source_unavailable'] = True
        except Exception:
            # Preserve a result captured before stop-state readback failed,
            # then finish this lease without another provider-capable tick.
            summary['stop_check_failed'] = True
            denied = bool(fetch and fetch.provider_denied)
        packet = dict(snapshot=doc, provider_denied=denied,
                      done=summary['stop_check_failed'] or summary['source_unavailable'])
        if doc is not None:
            packet['fingerprint'] = _content_identity(doc)
        return packet

    observed = run_observer(tick=tick, publish=publish, stop_check=stopped,
        monotonic=monotonic, sleep=sleep, interval_seconds=interval_seconds,
        duration_seconds=duration_seconds, max_ticks=max_ticks)
    retain_diagnostics()
    for field in ('state', 'ticks', 'provider_denied', 'done', 'no_provider_tick'):
        summary[field] = observed[field]
    # A provider-capable tick may have used only a cached page or no page. Do
    # not invent an HTTP count; only the zero-request paths are proven here.
    summary['provider_requests'] = 0 if observed['no_provider_tick'] else None
    # The controller's generic pre-tick stop includes daily transport holds;
    # only the explicit denial code or typed refusal supports this flag.
    summary['provider_denied'] = last_stop_code == stop.DENIED or bool(fetch and fetch.provider_denied)
    if summary['stop_check_failed']:
        summary['state'] = 'HOLD_RESULT_WATCH_STOP_CHECK_FAILED'
    elif not summary['provider_denied'] and (summary['source_unavailable'] or last_stop_code is not None):
        summary['state'] = 'HOLD_RESULT_WATCH_SOURCE_UNAVAILABLE'
        summary['source_unavailable'] = True
    return summary


def _report_path(path, private_root):
    path = Path(path)
    root = Path(private_root).resolve()
    need(path.is_absolute() and path.parent.is_dir() and not path.exists() and
         not path.is_symlink() and all(not p.is_symlink() for p in path.parents) and
         path.resolve() != root and root not in path.resolve().parents,
         'NEW_SAFE_REPORT_OUTSIDE_PRIVATE_ROOT_REQUIRED')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('saved-only', 'observe'), required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--owner-public-pem', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--interval-seconds', type=int, default=60)
    parser.add_argument('--duration-seconds', type=int, default=540)
    parser.add_argument('--max-ticks', type=int, default=10)
    args = parser.parse_args(argv)
    out = None
    stage = 'REPORT_PATH'
    try:
        out = _report_path(args.report, args.private_root)
        stage = 'RUNNER'
        report = run_watch(repo=Path(args.repo), mode=args.mode,
            private_root=Path(args.private_root), owner_public_path=Path(args.owner_public_pem),
            owner_private_pem=os.getenv('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode(),
            interval_seconds=args.interval_seconds, duration_seconds=args.duration_seconds,
            max_ticks=args.max_ticks)
        failed = report['state'].startswith('HOLD_') and report['state'] not in {
            'HOLD_RESULT_OBSERVER_PROVIDER_STOP', 'HOLD_RESULT_WATCH_SOURCE_DISABLED'}
    except Exception as exc:
        report = dict(schema=SCHEMA, mode=args.mode,
                      state='HOLD_RESULT_WATCH_PREFLIGHT_OR_SAVED_PUBLICATION_FAILED',
                      failure_stage=stage, failure_reason='RESULT_WATCH_OPERATION_UNVERIFIED')
        if type(exc) is ResultWatchError and exc.failure_stage in PREFLIGHT_STAGES:
            reason = str(exc) if str(exc) in PREFLIGHT_REASONS else 'RESULT_WATCH_PREFLIGHT_CHECK_FAILED'
            report.update(state='HOLD_RESULT_WATCH_PREFLIGHT_FAILED',
                failure_stage=exc.failure_stage, failure_reason=reason,
                no_provider_tick=True, provider_requests=0)
        failed = True
    raw = (json.dumps(report, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')) + '\n').encode()
    if out is not None:
        try:
            from scripts.keirin_capture_public_two_sources import _write_once
            _write_once(out, raw)
        except Exception:
            report = dict(schema=SCHEMA, mode=args.mode,
                          state='HOLD_RESULT_WATCH_SAFE_REPORT_SAVE_FAILED')
            failed = True
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 2 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
