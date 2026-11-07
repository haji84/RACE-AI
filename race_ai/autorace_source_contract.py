"""Offline entry for provider-delivered AUTORACE feeds, NOT a scraper/API client.

Only accepts external, independently rights-reviewed and race-bound snapshots.
Never constructs data, fetches provider URLs, claims provider publication
times, or converts a public webpage into permission for automated training.
"""
from __future__ import annotations
from datetime import datetime
from urllib.parse import urlsplit
import re
from .autorace_ab_pdca import PHASES, _moment
from .comprehensive_four_sport_models import digest

SCHEMA = "RACE_AI_AUTORACE_AUTHORIZED_LOCAL_FEED_V1"
USES = ("automated_ingestion", "private_retention", "prediction_analysis")
SHA = re.compile(r"[0-9a-f]{64}\Z")


def admit(bundle, *, race, phase, clock, rights_reviewer, observation_reviewer):
    """Return tick.acquire-compatible gated data. Both verifiers default-deny.

    rights_reviewer(source, requested_uses) must confirm an actual grant from
    an independent permission register, NOT a claimant-provided boolean.
    observation_reviewer(bundle) must independently validate recorded
    publication stage, same-race participant IDs and full sample provenance.
    No network, public deployment, payment or provider capture occurs here.
    """
    if not callable(clock) or not callable(rights_reviewer) or not callable(observation_reviewer):
        return {"status": "RIGHTS_BLOCKED"}
    if not isinstance(bundle, dict) or set(bundle) != {
            "schema","phase","race_id","snapshot","source","trial_publication",
            "participant_ids","revision"} or bundle["schema"] != SCHEMA:
        return {"status": "UNAVAILABLE"}
    if phase not in PHASES or bundle["phase"] != phase or race.get("sport") != "autorace":
        return {"status": "UNAVAILABLE"}
    if bundle["race_id"] != race.get("race_id") or (
            type(bundle["revision"]) is not int or bundle["revision"] < 1):
        return {"status": "UNAVAILABLE"}
    expected = "NOT_YET_PUBLISHED" if phase == PHASES[0] else "PUBLISHED_COMPLETE"
    if bundle["trial_publication"] != expected:
        return {"status": "PENDING"}
    source = bundle["source"]
    if not isinstance(source, dict) or set(source) != {
            "url","sha256","snapshot_sha256","captured_at","published_at",
            "license_ref","expires_at"}:
        return {"status": "UNAVAILABLE"}
    try:
        url = urlsplit(source["url"])
        if (url.scheme != "https" or not url.hostname or url.username or url.password or
                url.port is not None or url.fragment or url.query):
            return {"status": "UNAVAILABLE"}
        if any(not isinstance(source[k],str) or not source[k] or len(source[k])>2048
               for k in source):
            return {"status": "UNAVAILABLE"}
        if not SHA.fullmatch(source["sha256"]) or source["snapshot_sha256"] != digest(bundle["snapshot"]):
            return {"status": "UNAVAILABLE"}
        published, captured, expires = (_moment(source[k]) for k in
                                        ("published_at","captured_at","expires_at"))
        asof = _moment(bundle["snapshot"]["race"]["as_of"])
        cutoff = _moment(race["cutoff_at"])
        now = _moment(clock())
        if not (published <= captured <= asof <= now < cutoff < expires):
            return {"status": "UNAVAILABLE"}
        if (bundle["snapshot"]["race"]["race_id"] != race["race_id"] or
                bundle["snapshot"]["race"]["venue"] != race["venue"] or
                _moment(bundle["snapshot"]["race"]["sales_cutoff_at"]) != cutoff):
            return {"status": "UNAVAILABLE"}
        entrants = {x["number"] for x in bundle["snapshot"]["participants"]}
        if (len(entrants) != len(bundle["snapshot"]["participants"]) or
                sorted(bundle["participant_ids"]) != sorted(entrants)):
            return {"status": "UNAVAILABLE"}
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return {"status": "UNAVAILABLE"}
    try:
        if rights_reviewer(source, USES) is not True:
            return {"status": "RIGHTS_BLOCKED"}
        if observation_reviewer(bundle) is not True:
            return {"status": "UNAVAILABLE"}
    except (ValueError, TypeError, OSError):
        return {"status": "UNAVAILABLE"}
    return {"status": "AVAILABLE", "snapshot": bundle["snapshot"],
            "source_rights_verified": True, "participant_ids_matched": True,
            "trial_not_published_verified": phase == PHASES[0],
            "trial_race_bound_verified": phase == PHASES[1]}


def local_feed_acquire(envelopes, *, clock, rights_reviewer, observation_reviewer):
    """Inject reviewed local records keyed by (race_id, phase); never HTTP GET."""
    if not isinstance(envelopes, dict):
        raise ValueError("LOCAL_FEED_MAP_REQUIRED")
    def acquire(race,phase):
        bundle = envelopes.get((race["race_id"],phase))
        if bundle is None:
            return {"status":"PENDING"}
        return admit(bundle,race=race,phase=phase,clock=clock,
                     rights_reviewer=rights_reviewer,
                     observation_reviewer=observation_reviewer)
    return acquire
