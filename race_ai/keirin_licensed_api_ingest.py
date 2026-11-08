"""One explicitly license-authorized HTTPS JSON feed GET per owner cycle.

No website crawling, robots bypass, redirected fetches, endpoint discovery,
arbitrary multi-URL downloads, automatic retries, or real credential logs.
A licensed provider must supply the declared normalized JSON export format.
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
MAX_BODY = 8_000_000
MAX_DELIVERIES = 100


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
    _need(type(endpoint) is str and len(endpoint) <= 256 and
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
        value = json.loads(body.decode("utf-8"),
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               LicenseDeliveryError("NONFINITE_JSON_FORBIDDEN")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LicenseDeliveryError("LICENSED_PROVIDER_GET_FAILED") from exc
    _need(type(value) is dict and set(value) == {
        "schema", "bundle_id", "deliveries"
    } and value["schema"] == EXPORT_SCHEMA and
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
        digest = sha256(canonical(packet)).hexdigest()
        made = _write_private_once(raw / (digest + ".json"), packet)
        if made:
            created += 1
        else:
            existing += 1
    return {
        "schema": "RACE_AI_KEIRIN_AUTHORIZED_FETCH_ONCE_V1",
        "http_requests": 1 if transport is None else 0,
        "provider_packets_created": created,
        "provider_packets_already_present": existing,
        "commercial_or_model_rights_independently_certified": False,
        "provider_license_required": True,
        "auto_wager": False,
    }
