"""Rights-gated, bounded BOAT RACE HTML capture for an approved exact URL.

No scheduler, crawler, betting or live requests in CI. Rights/terms review is
a separate human-owned decision. Captures only an AUDIT_ONLY schedule.
"""
from __future__ import annotations

from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler
import hashlib
from .boat_official_web_adapter import (_identity,transform_official_screen,
                                         MAX_HTML_BYTES)
from .operator_export_intake import IntakeError

class CaptureError(ValueError):pass

class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise CaptureError("provider redirect refused")

def capture_boat_racelist(url,*,rights_checker,source_rights_ref,captured_at,opener=None):
    """Make exactly one GET after externally evaluated source-method permission.

    rights_checker(url, "single_bounded_html_get") MUST be an independently
    audited reviewer function. A website being public is not its approval.
    """
    _identity(url) # exact official domain, path, query validation
    if not callable(rights_checker) or rights_checker(url,"single_bounded_html_get") is not True:
        raise CaptureError("source access purpose NOT_ADMITTED")
    if not isinstance(source_rights_ref,str) or not source_rights_ref or len(source_rights_ref)>512:
        raise CaptureError("rights basis/reference missing")
    client=opener or build_opener(_NoRedirect(),HTTPSHandler())
    request=Request(url,method="GET",headers={
        "Accept":"text/html",
        "User-Agent":"RACE-AI-evidence-capture/1"})
    try:
        with client.open(request,timeout=8) as response:
            if response.geturl()!=url or response.status!=200:
                raise CaptureError("wrong final source URL/status")
            mime=response.headers.get("Content-Type","").split(";",1)[0].strip().lower()
            if mime not in ("text/html","application/xhtml+xml"):
                raise CaptureError("source did not return HTML")
            data=response.read(MAX_HTML_BYTES+1)
    except CaptureError:raise
    except Exception as exc:
        raise CaptureError("approved source access failed") from exc
    if len(data)>MAX_HTML_BYTES:
        raise CaptureError("HTML too large")
    result=transform_official_screen(data,source_url=url,captured_at=captured_at,
                                     rights_ref=source_rights_ref)
    result["controlled_capture"]={
        "transport":"ONE_APPROVED_HTTPS_GET",
        "source_html_sha256":hashlib.sha256(data).hexdigest(),
        "source_html_published_to_git":False,
        "source_access_approved_by_independent_callback":True,
        "source_legal_basis_authenticity_not_verified_by_code":True,
        "server_side_capture_timestamp_unverified":True,
        "actual_cutoff_verified":False,
        "model_ready":False,
        "official_result_verified":False}
    return result
