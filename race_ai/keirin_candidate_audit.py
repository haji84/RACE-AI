"""Read-only research audit of one third-party KEIRIN result candidate.

This is NOT official-result authentication, a provider rights grant, an
externally verified forecast freeze or a model-updating procedure.
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from urllib.parse import urlsplit, parse_qs
import re


class CandidateAuditError(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise CandidateAuditError(reason)


def _utc(instant):
    _require(type(instant) is str and len(instant) <= 64, "TIME_REQUIRED")
    try:
        moment=datetime.fromisoformat(instant.replace("Z","+00:00"))
        _require(moment.utcoffset() is not None, "TIMEZONE_REQUIRED")
        return moment
    except ValueError:
        raise CandidateAuditError("INVALID_TIME") from None


def _source_race(url):
    _require(type(url) is str and len(url) <= 1024, "INVALID_SOURCE_URL")
    parts=urlsplit(url)
    _require(parts.scheme=="https" and parts.hostname=="www.keirin-mobile.jp"
             and not parts.username and not parts.password and
             parts.path=="/top/result.php" and not parts.fragment,
             "SOURCE_URL_NOT_ALLOWED")
    q=parse_qs(parts.query,strict_parsing=True)
    _require(set(q)=={"date","jcode","race"} and all(len(v)==1 for v in q.values()),
             "SOURCE_RACE_FIELDS_INVALID")
    ymd,jcode,no=q["date"][0],q["jcode"][0],q["race"][0]
    _require(re.fullmatch(r"[0-9]{8}",ymd) and
             re.fullmatch(r"[0-9]{2}",jcode) and
             re.fullmatch(r"[0-9]{2}",no),
             "SOURCE_RACE_ID_INVALID")
    return ymd+jcode+no


def research_audit_one(source_probe, reference, *, race_id, cutoff_at):
    _require(type(source_probe) is dict and
             source_probe.get("schema")=="RACE_AI_KEIRIN_MOBILE_SINGLE_PAGE_RESEARCH_PROBE_V1" and
             source_probe.get("source_kind")=="THIRD_PARTY_NOT_KEIRIN_JP" and
             source_probe.get("result_officially_authenticated") is False and
             source_probe.get("forecast_generated") is False and
             source_probe.get("perpetual_polling_enabled") is False,
             "UNTRUSTED_PROBE_CONTRACT")
    _require(type(race_id) is str and re.fullmatch(r"\d{12}",race_id) and
             _source_race(source_probe.get("source_url"))==race_id,
             "RACE_ID_MISMATCH")
    _require(type(source_probe.get("source_sha256")) is str and
             re.fullmatch(r"[0-9a-f]{64}",source_probe["source_sha256"]),
             "SOURCE_HASH_REQUIRED")
    _require(source_probe.get("page_date_marker") is True and
             source_probe.get("page_race_marker") is True,
             "SOURCE_RACE_NOT_OBSERVED")
    candidate=source_probe.get("candidate_result")
    _require(type(candidate) is dict and
             candidate.get("state")=="ONE_UNVERIFIED_PROVIDER_CANDIDATE",
             "NO_UNAMBIGUOUS_RESULT_CANDIDATE")
    ticket=candidate.get("triple")
    payout=candidate.get("payout_100yen")
    _require(type(ticket) is list and len(ticket)==3 and
             all(type(n) is int and 1<=n<=9 for n in ticket) and
             len(set(ticket))==3 and
             type(payout) is int and 100<=payout<=1_000_000_000,
             "INVALID_TRIFECTA_CANDIDATE")
    _require(type(reference) is dict and
             reference.get("officially_frozen") is False and
             reference.get("calibrated") is False and
             type(reference.get("races")) is list and
             type(reference.get("version")) is str,
             "REFERENCE_RESEARCH_ONLY_EXPECTED")
    races=[r for r in reference["races"] if r.get("id")==race_id]
    _require(len(races)==1, "RACE_MISSING_OR_DUPLICATE_IN_REFERENCE")
    ranked=races[0].get("ranked")
    _require(type(ranked) is list and len(ranked)==8,
             "REFERENCE_EIGHT_TICKETS_REQUIRED")
    tickets=[]
    for item in ranked:
        _require(type(item) is dict and
                 type(item.get("pick")) is str and
                 re.fullmatch(r"[1-9]-[1-9]-[1-9]",item["pick"]),
                 "BAD_REFERENCE_TICKET")
        values=tuple(int(v) for v in item["pick"].split("-"))
        _require(len(set(values))==3,"BAD_REFERENCE_TICKET")
        tickets.append(values)
    _require(len(set(tickets))==8,"DUPLICATE_REFERENCE_TICKETS")
    original=_utc(reference.get("stamp_jst"))
    cutoff=_utc(cutoff_at)
    observed=_utc(source_probe.get("captured_at_unattested"))
    _require(original<cutoff<observed, "NON_PROSPECTIVE_OR_STALE_PROBE")
    winning=tuple(ticket)
    return {
      "schema":"RACE_AI_KEIRIN_REFERENCE_RESULT_COMPARE_V1",
      "evaluation_kind":"RESEARCH_ONLY_PROVIDER_CANDIDATE",
      "race_id":race_id,
      "forecast_version":reference["version"],
      "reference_stamped_at":reference["stamp_jst"],
      "third_party_forecast_freeze_verified":False,
      "source_url":source_probe["source_url"],
      "source_sha256":source_probe["source_sha256"],
      "source_observed_at_unattested":source_probe["captured_at_unattested"],
      "winning_triple_candidate":"-".join(str(i) for i in winning),
      "payout_100yen_candidate":payout,
      "top8_unmodified":["-".join(map(str,p)) for p in tickets],
      "research_hit8":winning in tickets,
      "formal_hit_at_8_all":None,
      "result_authoritative":False,
      "model_changed":False,
      "next_forecast_saved":False,
      "missing_evidence":[
         "organizer_final_result_or_authorized_provider_attestation",
         "independent_external_pre_cutoff_reference_receipt",
         "authorized_private_next_forecast_worker_and_durable_receipt",
      ],
    }
