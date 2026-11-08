"""Private owner-captured observations, with NO external API or licence manifest.

Personal possession and self-asserted use must NEVER be represented as a
provider-authenticated machine licence. This object intentionally allows
ONLY already saved, locally supplied data. It never fetches webpages.
"""
from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlsplit

from .keirin_preflight import audit_pre_race
from .keirin_non_rakuten_sources import is_rakuten_domain, is_rakuten_url
from .keirin_result_delivery import canonical, utc

PERSONAL_MARKER = "RACE_AI_PRIVATE_OWNER_MANUAL_OBSERVATION_V1"
PURPOSES = frozenset({"schedule", "pre_race", "analysis",
                      "model_inference", "private_retention"})


class PersonalOwnerError(ValueError):
    pass


class PersonalOwnerObservations:
    """Owner-selected origin hosts for self-captured, private research only."""

    def __init__(self, *, source_hosts, now):
        if not isinstance(source_hosts, (tuple, list)) or not (1 <= len(source_hosts) <= 20):
            raise PersonalOwnerError("OWNER_SOURCE_HOSTS_REQUIRED")
        hosts = set()
        for h in source_hosts:
            if type(h) is not str or not (1 <= len(h) <= 128) or "/" in h:
                raise PersonalOwnerError("INVALID_OWNER_SOURCE_HOST")
            parsed = urlsplit("https://" + h)
            if parsed.hostname != h.lower() or parsed.username or parsed.password or parsed.port:
                raise PersonalOwnerError("INVALID_OWNER_SOURCE_HOST")
            if is_rakuten_domain(h):
                raise PersonalOwnerError("RAKUTEN_SOURCE_EXCLUDED_BY_OWNER")
            hosts.add(h.lower())
        self.hosts = frozenset(hosts)
        self.now = utc(now)
        self.bundle_id = PERSONAL_MARKER

    def allowed(self, source_url, rights_ref, purpose):
        # This is acceptance of user-owned local input for PRIVATE research.
        # It is not an approval for remote automated retrieval, commercial
        # redistribution, or an assertion that third parties licensed data.
        if purpose not in PURPOSES or rights_ref != PERSONAL_MARKER:
            return False
        try:
            p = urlsplit(source_url)
            return (not is_rakuten_url(source_url) and
                    p.scheme == "https" and p.hostname in self.hosts and
                    p.username is None and p.password is None and p.port is None)
        except (ValueError, TypeError):
            return False

    def certificate(self, snapshot, intent):
        # A SELF-ATTESTED source receipt required by existing research spool.
        # It is not an external time witness or independently authenticated
        # race organiser result.
        if not isinstance(snapshot, dict) or not isinstance(intent, dict):
            return None
        if (snapshot.get("permission_ref") != PERSONAL_MARKER or
            intent.get("permission_ref") != PERSONAL_MARKER or
            snapshot.get("race_id") != intent.get("race_id") or
            snapshot.get("official_cutoff_at") != intent.get("official_cutoff_at")):
            return None
        try:
            if not utc(snapshot["as_of"]) <= self.now < utc(intent["official_cutoff_at"]):
                return None
            facts = snapshot["facts"]
            evidence = facts["pr71_evidenced_snapshot"]
            if evidence.get("scope") != "OPERATOR_SUPPLIED_RESEARCH":
                return None
            sha = sha256(canonical(snapshot)).hexdigest()
            if sha != intent["pre_race_snapshot_sha256"]:
                return None
            audit = facts["keirin_pre_race_audit_v1"]
            check = audit_pre_race(
                audit, race_id=intent["race_id"], starters=snapshot["starters"],
                cutoff_at=intent["official_cutoff_at"],
                snapshot_as_of=snapshot["as_of"],
                issued_at=self.now.isoformat(),
                evidence_sha256=sha256(canonical(evidence)).hexdigest())
            if not check["full_forecast_gate_passed"]:
                return None
            if not all(all(self.allowed(item["source_url"], item["rights_ref"], p)
                           for p in PURPOSES)
                       for item in audit["items"] if item["status"] == "verified"):
                return None
            return {
                "race_id": intent["race_id"],
                "source_sha256": sha,
                "permission_ref": PERSONAL_MARKER,
                "official_cutoff_at": intent["official_cutoff_at"],
                "verified_purposes": ["schedule", "pre_race",
                                      "private_retention", "model_inference"],
                "valid_until": intent["official_cutoff_at"],
            }
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
