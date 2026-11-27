"""Run from repository root: python -m research.chatgpt_dt_r1.cli --help."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _context_options(parser):
    parser.add_argument('--venues', type=Path)
    parser.add_argument('--timings', type=Path)
    parser.add_argument('--allow-current-geometry-assumption', action='store_true')


def _context(rows, args, at, *, force=False):
    if not (args.venues or args.timings or force):
        return rows
    if not at:
        raise ValueError('ACTUAL_CONTEXT_ANALYSIS_CLOCK_REQUIRED')
    from .context import augment_features
    from .venues import VenueStore
    timings = _read(args.timings) if args.timings else []
    if isinstance(timings, dict):
        timings = timings['records']
    return augment_features(rows, venue_store=VenueStore.load(args.venues) if args.venues else None,
        timing_records=timings, as_of=at,
        allow_current_geometry_assumption=args.allow_current_geometry_assumption)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Independent DT-R1 research, no wagers or automatic production promotion.')
    sub = parser.add_subparsers(dest='command', required=True)
    study = sub.add_parser('study', help='Admit pinned archives, train, calibrate, and evaluate on chronological splits.')
    study.add_argument('--archive', action='append', required=True, type=Path)
    study.add_argument('--output-dir', type=Path, required=True, help='New private directory outside tracked repository files.')
    study.add_argument('--max-iter', type=int, default=160)
    study.add_argument('--splits', type=Path)
    study.add_argument('--venues', type=Path, help='Source-bound geometry JSON, not assumed historical by default.')
    study.add_argument('--timings', type=Path, help='Reviewed/official timing observations with provenance.')
    study.add_argument('--weather', type=Path, help='Race-ID mapping of timestamped weather evidence; no same-day archive leakage.')
    study.add_argument('--allow-current-geometry-assumption', action='store_true',
                       help='Disclose current nominal geometry as an assumption for historical research.')
    compare = sub.add_parser('compare', help='Compare real frozen exports of all three participants.')
    compare.add_argument('--forecasts', type=Path, action='append', required=True)
    compare.add_argument('--outcomes', type=Path, required=True)
    compare.add_argument('--registry', type=Path, required=True)
    compare.add_argument('--model-id', action='append', required=True)
    compare.add_argument('--output', type=Path, required=True)
    forecast = sub.add_parser('forecast', help='Predict a normalized record using a pinned model and earlier history.')
    forecast.add_argument('--model', type=Path, required=True)
    forecast.add_argument('--record', type=Path, required=True)
    forecast.add_argument('--history', type=Path, required=True)
    forecast.add_argument('--at', help='Authenticated current prediction time; never use on retrospective inputs.')
    forecast.add_argument('--output', type=Path, required=True)
    forecast.add_argument('--venues', type=Path)
    forecast.add_argument('--timings', type=Path)
    forecast.add_argument('--analysis-at', help='Actual research clock when forecasting retrospectively with context.')
    forecast.add_argument('--allow-current-geometry-assumption', action='store_true')
    forecast.add_argument('--phase-bundle', type=Path, help='Optional independently fitted six-phase bundle.')
    forecast.add_argument('--phase-samples', type=int, default=64)
    selection = sub.add_parser('select', help='Apply the odds/count policy; this command is not independent source attestation.')
    selection.add_argument('--forecast', type=Path, required=True)
    selection.add_argument('--odds', type=Path, help='Missing odds produces HOLD, never inferred prices.')
    selection.add_argument('--policy-config', type=Path)
    selection.add_argument('--calibrator', type=Path)
    selection.add_argument('--at', required=True)
    selection.add_argument('--output', type=Path, required=True)
    report = sub.add_parser('report', help='Render aggregate evidence, or explicitly requested private owner details.')
    report.add_argument('--report', type=Path, required=True)
    report.add_argument('--output', type=Path, required=True)
    report.add_argument('--owner-forecasts', type=Path, help='Private output must be outside every Git worktree.')
    phase = sub.add_parser('fit-phases', help='Fit observed phase transitions; insufficient real labels produces HOLD.')
    phase.add_argument('--history', type=Path, required=True)
    phase.add_argument('--observations', type=Path, required=True)
    phase.add_argument('--before', required=True)
    phase.add_argument('--available-by', required=True)
    phase.add_argument('--output', type=Path, required=True)
    _context_options(phase)
    init = sub.add_parser('ledger-init', help='Explicitly initialize a NEW private three-participant research ledger.')
    init.add_argument('--path', type=Path, required=True)
    init.add_argument('--participant-id', action='append', required=True)
    init.add_argument('--pins', type=Path)
    status = sub.add_parser('ledger-status', help='Read existing state; missing state stops and never initializes.')
    status.add_argument('--path', type=Path, required=True)
    checkpoint = sub.add_parser('ledger-checkpoint', help='Encrypt existing history using the established owner public key.')
    checkpoint.add_argument('--path', type=Path, required=True)
    checkpoint.add_argument('--output-dir', type=Path, required=True)
    checkpoint.add_argument('--owner-public-key', type=Path, required=True)
    restore = sub.add_parser('ledger-restore', help='Authenticate every encrypted shard before creating a NEW private state DB.')
    restore.add_argument('--checkpoint-dir', type=Path, required=True)
    restore.add_argument('--manifest-sha256', required=True)
    restore.add_argument('--path', type=Path, required=True)
    restore.add_argument('--private-key-env', default='RACE_AI_KEIRIN_PRIVATE_RSA_PEM',
                         help='Name of an already configured secret; no key is generated or printed.')
    schedule = sub.add_parser('schedule-candidate', help='Record a retraining due time; does not install a second external schedule.')
    schedule.add_argument('--path', type=Path, required=True)
    schedule.add_argument('--id', required=True)
    schedule.add_argument('--due-at', required=True)
    candidates = sub.add_parser('run-candidates', help='Run due studies from the existing scheduler; active model remains pinned.')
    candidates.add_argument('--path', type=Path, required=True)
    candidates.add_argument('--archive', type=Path, action='append', required=True)
    candidates.add_argument('--output-dir', type=Path, required=True)
    candidates.add_argument('--splits', type=Path, help='New chronological contract; a future promotion still needs independent evidence.')
    candidates.add_argument('--max-iter', type=int, default=160)
    _context_options(candidates)
    candidates.add_argument('--weather', type=Path)
    args = parser.parse_args(argv)
    from .pipeline import run_study, write_private_json, forecast_row
    if args.command == 'study':
        splits = json.loads(args.splits.read_text()) if args.splits else None
        report = run_study(args.archive, args.output_dir, splits=splits, max_iter=args.max_iter,
                           venue_path=args.venues, timing_path=args.timings, weather_path=args.weather,
                           allow_current_geometry_assumption=args.allow_current_geometry_assumption,
                           progress=lambda message: print(message, flush=True))
        print(json.dumps({'status': 'RETROSPECTIVE_STUDY_COMPLETE',
                          'model_sha256': report['model_sha256'], 'final_period': report['final_period']}, ensure_ascii=False))
    elif args.command == 'compare':
        from .comparison import compare_models
        forecasts = []
        for path in args.forecasts:
            forecasts.extend(json.loads(path.read_text()))
        report = compare_models(forecasts, json.loads(args.outcomes.read_text()),
                                json.loads(args.registry.read_text()), expected_model_ids=args.model_id)
        write_private_json(args.output, report)
        print(json.dumps({'status': 'COMPARISON_SAVED', 'expected_models': args.model_id}))
    elif args.command == 'forecast':
        from .features import build_features, require_history_available
        from .model import RankModel
        model = RankModel.from_dict(json.loads(args.model.read_text()))
        row = json.loads(args.record.read_text())
        history = json.loads(args.history.read_text())
        if any(r['day'] >= row['day'] for r in history):
            raise ValueError('HISTORY_MUST_PRECEDE_TARGET_DAY')
        if row.get('cohort') == 'prospective':
            require_history_available(history, args.at)
        features = build_features(history + [row])
        target = next(r for r in features if r['race_id'] == row['race_id'])
        from .agari import augment_agari, uses_agari
        declared = model.fit_meta.get('context', {})
        if (declared.get('venue_file_sha256') and not args.venues) or (declared.get('timing_file_sha256') and not args.timings):
            raise ValueError('FEATURE_SCHEMA_CONTEXT_SIDECARS_REQUIRED')
        target = _context([target], args, args.at or args.analysis_at,
            force=bool(declared.get('weather_file_sha256')) and any(n.startswith(('context_', 'history_observed_')) for n in model.feature_names))[0]
        if uses_agari(model.feature_names):
            target = augment_agari([target])[0]
        prediction = forecast_row(model, target, prediction_at=args.at, full=True)
        prediction['explanation'] = model.explain(target) if prediction['status'] == 'READY' else []
        if args.phase_bundle and prediction['status'] == 'READY':
            from .phases import forecast_phase_paths
            prediction['phase_paths'] = forecast_phase_paths(_read(args.phase_bundle), target,
                prediction_at=args.at, samples=args.phase_samples)
        write_private_json(args.output, prediction)
        print(json.dumps({'status': prediction['status'], 'private_original_saved': True}))
    elif args.command == 'select':
        from .policy import select_tickets
        from .calibration import assess_selection
        selected = select_tickets(_read(args.forecast), _read(args.odds) if args.odds else None,
            config=_read(args.policy_config) if args.policy_config else None, decision_at=args.at)
        # Keep the sealed selection untouched; assessment is a separate artifact.
        confidence = assess_selection(selected, _read(args.calibrator) if args.calibrator else None)
        write_private_json(args.output, {'schema': 'dt-r1-policy-assessment-v1', 'selection': selected,
            'confidence_assessment': confidence, 'independent_source_attestation': False})
        print(json.dumps({'status': selected['status'], 'confidence': confidence['label'],
            'ticket_count': selected['ticket_count'], 'independent_source_attestation': False}))
    elif args.command == 'report':
        from .view import write_report, write_owner_report
        if args.owner_forecasts:
            write_owner_report(_read(args.report), _read(args.owner_forecasts), args.output)
        else:
            write_report(_read(args.report), args.output)
        print(json.dumps({'status': 'REPORT_SAVED', 'mode': 'owner_private' if args.owner_forecasts else 'aggregate'}))
    elif args.command == 'fit-phases':
        from .features import build_features
        from .phases import fit_phase_bundle
        rows = _context(build_features(_read(args.history)), args, args.available_by)
        raw = _read(args.observations)
        observations = raw['records'] if isinstance(raw, dict) else raw
        bundle = fit_phase_bundle(rows, observations, train_before=args.before, available_by=args.available_by)
        write_private_json(args.output, bundle)
        print(json.dumps({'status': 'FITTED_UNVALIDATED' if len(bundle['models']) == 6 else 'HOLD',
            'artifact_sha256': bundle['artifact_sha256'], 'coverage': bundle['coverage']}))
    elif args.command.startswith('ledger-') or args.command in ('schedule-candidate', 'run-candidates'):
        from .runtime import ResearchLedger, restore_checkpoint
        if args.command == 'ledger-init':
            ledger = ResearchLedger.initialize(args.path, participant_ids=args.participant_id,
                pins=_read(args.pins) if args.pins else None)
        elif args.command == 'ledger-restore':
            key = os.environ.get(args.private_key_env)
            if not key:
                raise ValueError('EXISTING_OWNER_PRIVATE_KEY_REQUIRED')
            ledger = restore_checkpoint(args.checkpoint_dir, args.path,
                expected_manifest_sha256=args.manifest_sha256, owner_private_pem=key)
        else:
            ledger = ResearchLedger.open(args.path)
        try:
            if args.command == 'ledger-checkpoint':
                output = ledger.checkpoint(args.output_dir, args.owner_public_key.read_text())
            elif args.command == 'schedule-candidate':
                event = ledger.schedule_candidate(args.id, args.due_at)
                output = {'status': 'SCHEDULE_RECORDED', 'event_sha256': event['event_sha256']}
            elif args.command == 'run-candidates':
                from .model import digest
                def fit_candidate(*, study_directory):
                    result = run_study(args.archive, study_directory / 'run',
                        splits=_read(args.splits) if args.splits else None, max_iter=args.max_iter,
                        venue_path=args.venues, timing_path=args.timings, weather_path=args.weather,
                        allow_current_geometry_assumption=args.allow_current_geometry_assumption)
                    return {'model_sha256': result['model_sha256'], 'study_manifest_sha256': digest(result),
                        'scope': result['scope'], 'production_promoted': False}
                output = {'status': 'CANDIDATE_CYCLE_COMPLETE', 'candidates':
                    ledger.run_due_candidates(fit_candidate, args.output_dir), 'changes_active_model': False}
            else:
                output = {'status': 'RESEARCH_STATE_VERIFIED', **ledger.coverage()}
            print(json.dumps(output, ensure_ascii=False))
        finally:
            ledger.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as error:
        print(json.dumps({'status': 'STOPPED', 'reason_type': type(error).__name__, 'reason': str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
