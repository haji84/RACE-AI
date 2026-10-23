"""RACE-AI user purchase-review buffer: a planning/time-order gate only.

All server-side official forecast admission STILL requires a separately
authenticated external freeze receipt and a separately observed public
publication time. Passing these strings cannot prove server timestamps.
No odds or market fields are accepted, and no saved forecast is modified.
"""
from __future__ import annotations
from datetime import timedelta
from .comprehensive_four_sport_models import moment

SCHEMA = "RACE_AI_PURCHASE_REVIEW_WINDOW_V1"


class PurchaseWindowError(ValueError):
    pass


def _instant(v, label):
    try:
        return moment(v)
    except (TypeError, ValueError) as exc:
        raise PurchaseWindowError(label + " requires explicit timestamp with timezone") from exc


def policy(cutoff_at, *, initial_lead_minutes=30, final_buffer_minutes=10):
    """Default proposal: early preview at T-30, ready-to-consider by T-10.

    These values are PRODUCT targets, not organizer deadlines or measured
    delivery performance; they can later be varied per sport/venue.
    """
    if (type(initial_lead_minutes) is not int or
        type(final_buffer_minutes) is not int or
        not 5 <= final_buffer_minutes <= 120 or
        not final_buffer_minutes < initial_lead_minutes <= 240):
        raise PurchaseWindowError("invalid user review buffer settings")
    cutoff = _instant(cutoff_at, "official sales cutoff")
    return {
        "schema": SCHEMA,
        "official_sales_cutoff_at": cutoff_at,
        "first_preview_target_at": (cutoff-timedelta(minutes=initial_lead_minutes)).isoformat(),
        "final_forecast_visible_by": (cutoff-timedelta(minutes=final_buffer_minutes)).isoformat(),
        "initial_lead_minutes": initial_lead_minutes,
        "review_buffer_minutes": final_buffer_minutes,
        "readiness_evidence_independently_verified": False,
    }


def reported_delivery(cutoff_at, frozen_at, visible_at, *,
                      initial_lead_minutes=30, final_buffer_minutes=10):
    """Classify timestamps but never self-certify a genuine public release."""
    plan=policy(cutoff_at, initial_lead_minutes=initial_lead_minutes,
                final_buffer_minutes=final_buffer_minutes)
    if frozen_at is None or visible_at is None:
        status="NOT_PUBLISHED_FOR_REVIEW"
        reported_minutes=None
    else:
        freeze=_instant(frozen_at,"freeze recorded")
        visible=_instant(visible_at,"user-facing publication recorded")
        cutoff=_instant(cutoff_at,"official sales cutoff")
        if not freeze <= visible:
            status="INCONSISTENT_PUBLICATION_EVIDENCE"
        elif visible >= cutoff:
            status="POST_CUTOFF_NOT_ACTIONABLE"
        elif visible > _instant(plan["final_forecast_visible_by"],"buffer target"):
            status="LATE_FOR_PURCHASE_REVIEW"
        else:
            status="BUFFER_TARGET_REPORTED_NOT_ATTESTED"
        reported_minutes=(cutoff-visible).total_seconds()/60
    return {
        **plan,
        "reported_publication_status": status,
        "reported_minutes_before_cutoff": reported_minutes,
        "independent_freeze_receipt_verified": False,
        "independent_user_visibility_time_verified": False,
        "official_forecast_eligible_from_this_check": False,
    }
