"""Run actual existing BOAT CV over an encrypted HTML5 screen recording.

This is a private, source-free adapter between Playwright screen capture and
the existing FFmpeg/OpenCV video evaluation. It never downloads a source,
publishes a raw frame, labels boats automatically, scores races, rewrites a P1
original, or calls an experimental model without qualified identity evidence.
Any real-source video still requires separately authenticated rights/receipt.
"""
from datetime import datetime
import os
from pathlib import Path
import tempfile

from .boat_screen_record_research import unseal_screen
from .boat_video_evaluation import _job, analyze_video, _time
from .boat_video_model_context import prepare_video_context

def _hold(code):
    return dict(status=code,source_requests=0,tracking_lane_candidates=0,
                model_prediction_generated=False,production_video_forecast_proven=False,
                original_forecast_modified=False)


def evaluate_encrypted_screen(envelope, job, *, aes_key, clock,
                              verify_real_receipt=None):
    try:
        if type(envelope) is not dict or type(job) is not dict or not callable(clock):
            return _hold('HOLD_SCREEN_JOB_OR_ORIGINAL_INVALID')
        checked=_job(job)
        source=checked['source']
        fixture=envelope.get('synthetic_fixture')
        if (type(fixture) is not bool or
                checked['race_id']!=envelope.get('race_id') or
                source['media_sha256']!=envelope.get('media_sha256') or
                source['captured_at']!=envelope.get('captured_at')):
            return _hold('HOLD_SCREEN_JOB_OR_ORIGINAL_INVALID')
        if ((fixture and (source['kind'],source['identity_status'])!=
                  ('SYNTHETIC_TEST','SYNTHETIC')) or
                not fixture and source['kind'] not in ('OWNER_LOCAL','OFFICIAL_BROWSER_CAPTURE')):
            return _hold('HOLD_SCREEN_DATASET_SCOPE_MISMATCH')
        if not fixture:
            # Public repository metadata or a producer's boolean is not
            # sufficient to license/attest an actual displayed video.
            if (not callable(verify_real_receipt) or
                    verify_real_receipt(envelope,checked) is not True):
                return _hold('HOLD_SCREEN_REAL_SOURCE_RIGHTS_REQUIRED')
        try:
            raw=unseal_screen(envelope,aes_key=aes_key)
        except ValueError:
            return _hold('HOLD_SCREEN_CIPHER_INVALID')
        with tempfile.TemporaryDirectory(prefix='boat-screen-model-private-') as root:
            os.chmod(root,0o700)
            clip=Path(root)/'screen.webm'
            clip.write_bytes(raw)
            os.chmod(clip,0o600)
            report=analyze_video(clip,checked,clock=clock)
        if (not report['pre_cutoff_available'] or report['model_eligible'] is not False or
                report['validation_status']!='UNVALIDATED'):
            return _hold('HOLD_SCREEN_REPORT_NOT_PRE_CUTOFF_OR_UNVALIDATED')
        context=prepare_video_context(report,None,race_id=checked['race_id'],
            cutoff_at=checked['cutoff_at'],roster=checked['roster'],
            as_of=report['analysis_completed_at'])
        if (context.get('prediction_eligible') is not False or
                context.get('production_eligible') is not False or
                context.get('eligible_for_research') is not False):
            return _hold('HOLD_SCREEN_UNEXPECTED_CONTEXT_ELIGIBILITY')
        return dict(status='VIDEO_SCREEN_ANALYZED_UNVALIDATED_IDENTITIES',
                    source_role='SYNTHETIC_FIXTURE' if fixture else 'RESEARCH_OWNER_BROWSER',
                    race_id=checked['race_id'],report_sha256=report['report_sha256'],
                    video_context_sha256=context['context_sha256'],
                    dataset_status=report['dataset_status'],
                    tracking_lane_candidates=len(report['tracking']['tracks']),
                    measured_phase_candidates=sum(
                        phase.get('status')=='MEASURED'
                        for lane in report['measurements']['lanes']
                        for phase in lane['phases'].values()),
                    missing_reasons=context['missing_reasons'],
                    source_requests=0,model_prediction_generated=False,
                    production_video_forecast_proven=False,
                    original_forecast_modified=False)
    except (ValueError,TypeError,KeyError,OSError,OverflowError,RuntimeError,StopIteration):
        return _hold('HOLD_SCREEN_ANALYSIS_UNAVAILABLE')
