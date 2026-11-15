"""Bind verified private captures to explicit, still-unvalidated intake jobs.

Capture-only is the default. Licensed development footage cannot be relabelled
as an owner-authorized race. This bridge neither authenticates a race nor
changes prediction originals, model eligibility, or running workers.
"""
from copy import deepcopy

from .boat_video_evaluation import _job

_ERROR = "CAPTURE_BINDING_REJECTED"


def build_job(export_record, template=None):
    """Build JOB_V1 after receipt verification by the caller.

    This pure transformation is not an authenticity check. ``enqueue_export``
    is the entry point that verifies the actual saved media and receipt.
    """
    try:
        if template is None:
            return None
        role = export_record["source_role"]
        expected = {"OWNER_AUTHORIZED": ("OWNER_LOCAL", "OWNER_DECLARED"),
                    "SYNTHETIC_TEST": ("SYNTHETIC_TEST", "SYNTHETIC")}.get(role)
        if expected is None or type(template) is not dict:
            raise ValueError(_ERROR)
        job = deepcopy(template)
        source = job["source"]
        if type(source) is not dict or (source.get("kind"), source.get("identity_status")) != expected:
            raise ValueError(_ERROR)
        for key, value in {
            "media_sha256": export_record["media_sha256"],
            "captured_at": export_record["captured_at"],
            "source_metadata_sha256": export_record["receipt_sha256"],
        }.items():
            if key in source and source[key] != value:
                raise ValueError(_ERROR)
            source[key] = value
        return _job(job)
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None


def enqueue_export(private_root, export_record, template=None):
    """Verify saved capture, then enqueue only an explicit compatible binding."""
    from .boat_video_capture import verify_export
    from .boat_video_intake import enqueue
    try:
        verified = verify_export(export_record)
        job = build_job(verified, template)
        if job is None:
            return {"status": "CAPTURE_ONLY", "window_id": verified["window_id"],
                    "media_sha256": verified["media_sha256"], "job_sha256": None}
        ident = enqueue(private_root, verified["media_path"], job)
        return {"status": "ENQUEUED_UNVALIDATED", "window_id": verified["window_id"],
                "media_sha256": verified["media_sha256"], "job_sha256": ident}
    except (ValueError, KeyError, TypeError, OSError, OverflowError, RecursionError):
        raise ValueError(_ERROR) from None
