"""Owner-authorized HTTPS JSON export intake for private KEIRIN research.

Multiple explicit, authorized endpoints can be queried in one cycle. There is
no arbitrary API call-count quota in RACE-AI. Each request still validates
host, rights, credentials, response size, schema, source SHA and odds.
Published provider rate limits, 429/403, and access-control remain binding.
No endpoint discovery, internal/private API probing or page scraping.
"""
from __future__ import annotations

from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
from urllib import request
from urllib.parse import urlsplit

from .keirin_permissioned_owner import (
    LicenseDeliveryError, _need, _write_private_once, _valid_prefix
)
from .keirin_result_delivery import canonical
from .keirin_non_rakuten_sources import is_rakuten_url

EXPORT_SCHEMA = "RACE_AI_KEIRIN_LICENSED_PROVIDER_EXPORT_V1"
EXPORT_SCHEMA_V2 = "RACE_AI_KEIRIN_LICENSED_PROVIDER_EXPORT_V2"
EXPORT_SCHEMA_V3 = "RACE_AI_KEIRIN_LICENSED_PROVIDER_EXPORT_V3"
MAX_BODY = 32_000_000
MAX_DELIVERIES = 5000


def _no_redirect_opener():
    class RejectRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    return request.build_opener(RejectRedirect)


def _network_once(endpoint, token):
    headers = {
        "Accept": "application/json",
        "User-Agent": "RACE-AI-Owner-Authorized-Data-Client/1.0"
    }
    if token is not None:
        _need(type(token) is str and 0 < len(token) <= 4096 and
              "\r" not in token and "\n" not in token,
              "INVALID_API_TOKEN")
        headers["Authorization"] = "Bearer " + token
    req = request.Request(endpoint, headers=headers, method="GET")
    with _no_redirect_opener().open(req, timeout=12) as resp:
        _need(resp.status == 200 and "json" in
              resp.headers.get("Content-Type", "").lower(),
              "SOURCE_NOT_APPROVED_JSON")
        data = resp.read(MAX_BODY + 1)
        _need(0 < len(data) <= MAX_BODY, "SOURCE_BATCH_TOO_LARGE")
        return data


def fetch_licensed_export_once(inbox, grants, *, endpoint, rights_ref,
                               token=None, transport=None):
    """Return the number of private source packets written.

    A *real legal grant for automated_fetch* is required. The caller must
    independently verify that grant from the provider; a local manifest
    and a matching SHA do not certify its legality.
    """
    _need(type(endpoint) is str and len(endpoint) <= 2048 and
          type(rights_ref) is str, "ENDPOINT_CONFIG_INVALID")
    try:
        target = urlsplit(endpoint)
        host = target.hostname
        _need(target.scheme == "https" and host is not None and
              target.username is None and target.password is None and
              target.port is None and not target.fragment,
              "UNSAFE_LICENSED_ENDPOINT")
        # IP literals, loopback, metadata endpoints and raw private endpoints
        # are never legitimate targets for this generic public HTTPS collector.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise LicenseDeliveryError("IP_LITERAL_ENDPOINT_FORBIDDEN")
    except (TypeError, AttributeError) as exc:
        raise LicenseDeliveryError("UNSAFE_LICENSED_ENDPOINT") from exc
    _need(not is_rakuten_url(endpoint), "RAKUTEN_SOURCE_EXCLUDED_BY_OWNER")
    _need(grants.allowed(endpoint, rights_ref, "automated_fetch"),
          "AUTOMATED_SOURCE_ACCESS_NOT_AUTHORIZED")
    root = Path(inbox).expanduser()
    _need(root.is_absolute() and root.is_dir() and not root.is_symlink(),
          "PRIVATE_INBOX_REQUIRED")
    raw = root / "raw"
    if not raw.exists():
        raw.mkdir(mode=0o700)
    _need(raw.is_dir() and not raw.is_symlink(), "PRIVATE_RAW_DIR_REQUIRED")
    # Dependency injection is for offline CI only; in production this is one
    # GET with no retry and no redirect. Never log token or response body.
    try:
        body = transport(endpoint, token) if transport else _network_once(endpoint, token)
        _need(type(body) is bytes and 0 < len(body) <= MAX_BODY,
              "PROVIDER_RESPONSE_INVALID")
        def unique(pairs):
            result = {}
            for key, item in pairs:
                _need(key not in result, "DUPLICATE_PROVIDER_JSON_KEY")
                result[key] = item
            return result
        value = json.loads(
            body.decode("utf-8"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(
                LicenseDeliveryError("NONFINITE_JSON_FORBIDDEN")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LicenseDeliveryError("LICENSED_PROVIDER_GET_FAILED") from exc
    _need(type(value) is dict and
          ((value.get("schema") == EXPORT_SCHEMA and
            set(value) == {"schema", "bundle_id", "deliveries"}) or
           (value.get("schema") == EXPORT_SCHEMA_V2 and
            set(value) == {"schema", "bundle_id", "deliveries",
                           "odds_snapshots"}) or
           (value.get("schema") == EXPORT_SCHEMA_V3 and
            set(value) == {"schema", "bundle_id", "deliveries",
                           "odds_snapshots", "result_observations"})) and
          value["bundle_id"] == grants.bundle_id and
          type(value["deliveries"]) is list and
          len(value["deliveries"]) <= MAX_DELIVERIES,
          "LICENSED_EXPORT_SCHEMA_OR_BUNDLE_MISMATCH")
    created = 0
    existing = 0
    for packet in value["deliveries"]:
        _need(type(packet) is dict and packet.get("schema") ==
              "RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1" and
              type(packet.get("race")) is dict and
              packet["race"].get("permission_ref") == grants.bundle_id,
              "UNTRUSTED_RACE_PACKET")
    # V3 adds result revisions to the SAME already-authorized GET.
    # Validate ALL result purposes, clocks and settlement shapes before
    # staging ANY raw/odds/source file. The result still is not independently
    # authenticated as official; its true provider rights remain external.
    result_stage=None
    if value["schema"] == EXPORT_SCHEMA_V3:
        from .keirin_licensed_result_stage import (
            validate_result,stage_licensed_result_export
        )
        results=value["result_observations"]
        _need(type(results) is list and len(results)<=2000,
              "LICENSED_RESULT_BATCH_BOUNDS_INVALID")
        for result in results:
            validate_result(result,grants,checked_at=grants.now.isoformat())
    # V2/V3 odds share this same response. Validate them before any
    # forecast source packet or result is written.
    if value["schema"] in (EXPORT_SCHEMA_V2,EXPORT_SCHEMA_V3):
        from .keirin_licensed_odds_export import stage_licensed_odds_export
        odds_report = stage_licensed_odds_export(
            root, value["odds_snapshots"], value["deliveries"],
            checked_at=grants.now.isoformat(), grant_check=grants.allowed)
    else:
        odds_report = None
    if value["schema"] == EXPORT_SCHEMA_V3:
        result_stage=stage_licensed_result_export(
            root,value["result_observations"],
            checked_at=grants.now.isoformat(),grants=grants)
    for packet in value["deliveries"]:
        digest = sha256(canonical(packet)).hexdigest()
        made = _write_private_once(raw / (digest + ".json"), packet)
        if made:
            created += 1
        else:
            existing += 1
    return {
        "schema": "RACE_AI_KEIRIN_AUTHORIZED_FETCH_ONCE_V1",
        "licensed_full_odds_staged": odds_report,
        "licensed_result_rows_staged": result_stage,
        "http_requests": 1 if transport is None else 0,
        "provider_packets_created": created,
        "provider_packets_already_present": existing,
        "commercial_or_model_rights_independently_certified": False,
        "provider_license_required": True,
        "auto_wager": False,
    }


def fetch_authorized_exports(inbox, grants, *, sources, token=None,
                             transport=None):
    """Fetch each explicitly approved endpoint, not an artificial single-GET cap.

    All endpoints are validated for owner-granted automated_fetch BEFORE any
    network activity. This is not a provider-rate-limit bypass. The caller
    selects a supported API path; no internal endpoints are discovered.
    """
    _need(type(sources) in (list,tuple) and bool(sources),
          "AUTHORIZED_SOURCES_REQUIRED")
    checked=[]
    for pair in sources:
        _need(type(pair) in (tuple,list) and len(pair)==2,
              "SOURCE_ENDPOINT_RIGHTS_PAIR_REQUIRED")
        endpoint, rights_ref=pair
        _need(type(endpoint) is str and 1<=len(endpoint)<=2048 and
              type(rights_ref) is str and bool(rights_ref),
              "EXPLICIT_ENDPOINT_AND_RIGHTS_REQUIRED")
        parts=urlsplit(endpoint)
        try:
            host=parts.hostname
            unsafe=(parts.scheme!="https" or not host or
                    parts.username is not None or
                    parts.password is not None or
                    parts.port is not None or parts.fragment)
            _need(not unsafe,"UNSAFE_AUTHORIZED_ENDPOINT")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise LicenseDeliveryError("IP_LITERAL_ENDPOINT_FORBIDDEN")
        except ValueError:
            raise LicenseDeliveryError("UNSAFE_AUTHORIZED_ENDPOINT") from None
        _need(not is_rakuten_url(endpoint),
              "RAKUTEN_SOURCE_EXCLUDED_BY_OWNER")
        _need(grants.allowed(endpoint,rights_ref,"automated_fetch") is True,
              "AUTOMATED_SOURCE_ACCESS_NOT_AUTHORIZED")
        checked.append((endpoint,rights_ref))
    # Do not create endless duplicate requests by mistake.
    _need(len(set(checked))==len(checked),
          "DUPLICATE_SAME_CYCLE_REQUEST")
    reports=[]
    for endpoint,rights_ref in checked:
        reports.append(fetch_licensed_export_once(
            inbox,grants,endpoint=endpoint,rights_ref=rights_ref,
            token=token,transport=transport))
    return {
        "schema":"RACE_AI_KEIRIN_AUTHORIZED_MULTI_SOURCE_CYCLE_V1",
        "authorized_endpoint_count":len(checked),
        "http_requests":sum(x["http_requests"] for x in reports),
        "provider_packets_created":sum(
            x["provider_packets_created"] for x in reports),
        "provider_packets_already_present":sum(
            x["provider_packets_already_present"] for x in reports),
        "licensed_full_odds_staged":[
            x["licensed_full_odds_staged"] for x in reports
            if x["licensed_full_odds_staged"] is not None
        ],
        "licensed_result_rows_staged":[
            x["licensed_result_rows_staged"] for x in reports
            if x["licensed_result_rows_staged"] is not None
        ],
        "internal_api_discovery":False,
        "provider_rate_limits_bypassed":False,
        "automatic_wagering":False,
    }
