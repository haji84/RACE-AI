"""24-venue source registry and separate rights gates.

A venue being listed does not grant permission. Explicit approval records
must be externally verified; this module only enforces supplied decisions.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

VENUES = (
    "桐生","戸田","江戸川","平和島","多摩川","浜名湖","蒲郡","常滑",
    "津","三国","びわこ","住之江","尼崎","鳴門","丸亀","児島",
    "宮島","徳山","下関","若松","芦屋","福岡","唐津","大村"
)
PURPOSES = frozenset({
    "facts_ingest","facts_publish","photo_publish",
    "video_internal_analysis","video_store","video_publish",
    "derived_features_publish"
})
DECISIONS = frozenset({"allowed","denied","unknown","approval_required"})


@dataclass(frozen=True)
class RightsRecord:
    venue_code: str
    purpose: str
    decision: str
    source_url: str
    reviewed_at: str
    evidence_reference: str
    reviewed_by: str


def validate_record(record: RightsRecord) -> None:
    if record.venue_code not in {f"{i:02d}" for i in range(1,25)}:
        raise ValueError("invalid venue")
    if record.purpose not in PURPOSES or record.decision not in DECISIONS:
        raise ValueError("invalid purpose or decision")
    if record.decision == "allowed":
        if (urlsplit(record.source_url).scheme != "https" or
            not record.evidence_reference.strip() or
            not record.reviewed_by.strip()):
            raise ValueError("approval evidence incomplete")
        timestamp = datetime.fromisoformat(record.reviewed_at.replace("Z","+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("review timestamp needs timezone")


def decision_for(records: list[RightsRecord], venue_code: str, purpose: str) -> str:
    if venue_code not in {f"{i:02d}" for i in range(1,25)} or purpose not in PURPOSES:
        raise ValueError("invalid venue/purpose")
    matching = [r for r in records if r.venue_code == venue_code and r.purpose == purpose]
    if len(matching) != 1:
        return "unknown"
    validate_record(matching[0])
    return matching[0].decision


def can_publish(records: list[RightsRecord], venue_code: str, kind: str) -> bool:
    return decision_for(records, venue_code, kind) == "allowed"
