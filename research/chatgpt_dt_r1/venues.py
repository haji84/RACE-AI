"""Dated, source-bound nominal venue geometry for the independent DT-R1 study.

Currently published geometry is not evidence of historical geometry. Unknown
indoor status, curvature and wind bearings remain null. Nominal circumference
does not measure an individual rider's travelled distance or absolute speed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

try:
    from .observations import day, finite, utc
except ImportError:
    from observations import day, finite, utc


GEOMETRY_FIELDS = ("circumference_m", "straight_m", "cant_deg", "straight_cant_deg",
    "home_width_m", "back_width_m", "center_width_m", "curve_radius_m", "indoor",
    "home_bearing_deg", "back_bearing_deg")


@dataclass(frozen=True)
class VenueGeometry:
    venue_code: str
    name: str
    source_url: str
    source_sha256: str
    retrieved_at: str
    circumference_m: float | None = None
    straight_m: float | None = None
    cant_deg: float | None = None
    straight_cant_deg: float | None = None
    home_width_m: float | None = None
    back_width_m: float | None = None
    center_width_m: float | None = None
    curve_radius_m: float | None = None
    indoor: bool | None = None
    home_bearing_deg: float | None = None
    back_bearing_deg: float | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    geometry_scope: str = "current_unversioned"
    source_fields: dict | None = None
    note: str | None = None

    def __post_init__(self):
        if not self.venue_code or not self.name or urlparse(self.source_url).scheme not in {"http","https"}:
            raise ValueError("Venue identity and an attributable source URL are required")
        if not re.fullmatch(r"[0-9a-f]{64}",self.source_sha256):
            raise ValueError("Geometry source must carry the actual source-byte SHA256")
        utc(self.retrieved_at)
        if self.geometry_scope not in {"dated","current_unversioned","legacy_noncurrent"}:
            raise ValueError("Unknown geometry effective-date scope")
        if self.geometry_scope == "dated" and self.effective_from is None:
            raise ValueError("Dated geometry requires an evidenced effective-from date")
        if self.effective_from:
            day(self.effective_from)
        if self.effective_to:
            if self.effective_from is None or day(self.effective_to) <= day(self.effective_from):
                raise ValueError("Geometry effective-to must follow effective-from (exclusive end)")
        for key in GEOMETRY_FIELDS:
            value = getattr(self,key)
            if value is None:
                continue
            if key == "indoor":
                if type(value) is not bool:
                    raise ValueError("Unknown indoor status must be null")
            elif key.endswith("_deg"):
                finite(value,key,low=0,high=360 if "bearing" in key else 90)
                if value == (360 if "bearing" in key else 90):
                    raise ValueError("Geometry angle must be below its upper limit")
            elif finite(value,key,low=0) == 0:
                raise ValueError("Physical lengths must be positive")
        if self.straight_m is not None and self.circumference_m is not None and self.straight_m >= self.circumference_m:
            raise ValueError("Straight distance cannot equal or exceed a whole lap")


class VenueStore:
    def __init__(self, records):
        self.records = tuple(records)
        keys = [(r.venue_code,r.effective_from,r.effective_to,r.retrieved_at) for r in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate geometry revisions need explicit resolution")

    @classmethod
    def from_records(cls, records):
        if isinstance(records,dict):
            records = records["records"]
        return cls(r if isinstance(r,VenueGeometry) else VenueGeometry(**r) for r in records)

    @classmethod
    def load(cls, path=None):
        source = Path(path) if path else Path(__file__).with_name("fixtures")/"venue_geometry.json"
        return cls.from_records(json.loads(source.read_text(encoding="utf-8")))

    def features(self, venue_id, race_at, as_of, *, allow_current_geometry_assumption=False):
        """Use dated facts known by as_of, or an explicitly disclosed current-value assumption."""
        cutoff, target = utc(as_of),day(race_at)
        available = [r for r in self.records if r.venue_code==str(venue_id) and utc(r.retrieved_at)<=cutoff]
        candidates = []
        for row in available:
            if row.geometry_scope == "legacy_noncurrent":
                continue
            if row.effective_from is not None and day(row.effective_from)>target:
                continue
            if row.effective_to is not None and target>=day(row.effective_to):
                continue
            assumed = row.geometry_scope=="current_unversioned" and target<day(row.retrieved_at)
            if assumed and not allow_current_geometry_assumption:
                continue
            candidates.append((row,assumed))
        result = {"venue_"+key:None for key in GEOMETRY_FIELDS}
        result.update(venue_geometry_present=0,retrospective_current_geometry_assumption=0)
        if not candidates:
            return result
        row,assumed = max(candidates,key=lambda item:(item[0].geometry_scope=="dated",utc(item[0].retrieved_at)))
        result.update({"venue_"+key:(int(getattr(row,key)) if key=="indoor" and getattr(row,key) is not None else getattr(row,key)) for key in GEOMETRY_FIELDS})
        result["venue_geometry_present"] = 1
        result["retrospective_current_geometry_assumption"] = int(assumed)
        return result

    def summary(self):
        return {"venue_count":len({r.venue_code for r in self.records}),"revision_count":len(self.records),
            "dated_count":sum(r.geometry_scope=="dated" for r in self.records),
            "current_unversioned_count":sum(r.geometry_scope=="current_unversioned" for r in self.records),
            "complete_basic_geometry_count":sum(all(getattr(r,key) is not None for key in ("circumference_m","straight_m","cant_deg")) for r in self.records),
            "missing_counts":{key:sum(getattr(r,key) is None for r in self.records) for key in GEOMETRY_FIELDS}}


def _embedded_json(text,name):
    match = re.search(r"\b"+re.escape(name)+r"\s*=\s*(\{)",text)
    if not match:
        raise ValueError("Official page has no supported embedded geometry data: "+name)
    return json.JSONDecoder().raw_decode(text[match.start(1):])[0]["data"]


def _metres(text):
    if text is None or str(text).strip() in {"","-","―"}:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*m\s*",str(text))
    if not match:
        raise ValueError("Unsupported official length representation: "+str(text))
    return float(match.group(1))


def _degrees(text):
    if text is None or str(text).strip() in {"","-","―"}:
        return None
    match = re.fullmatch(r"\s*(\d+)°\s*(\d+)′\s*(\d+(?:\.\d+)?)″\s*",html.unescape(text))
    if not match:
        raise ValueError("Unsupported official cant representation: "+str(text))
    degrees,minutes,seconds = map(float,match.groups())
    if minutes>=60 or seconds>=60:
        raise ValueError("Invalid sexagesimal angle")
    return degrees+minutes/60+seconds/3600


def parse_keirin_jp_geometry(raw_html: bytes, source_url: str, retrieved_at: str):
    """Parse only published physical facts from KEIRIN.JP's normal guide HTML.

    Does not fetch, probe APIs, or retain rider names, records, source HTML,
    results or historic tactic percentages. The source SHA identifies the
    complete privately captured HTML bytes, not a reconstructed JSON string.
    """
    parsed = urlparse(source_url)
    if parsed.scheme!="https" or parsed.hostname not in {"keirin.jp","www.keirin.jp"} or parsed.path!="/pc/jyoguide":
        raise ValueError("Expected the normal public KEIRIN.JP venue guide URL")
    text = raw_html.decode("utf-8")
    identity = _embedded_json(text,"PJ0701json")
    source = _embedded_json(text,"PJ0703json")
    code = str(identity["jyoCode"])
    if source["jyoCode"]!=code or parse_qs(parsed.query).get("jocd")!=[code]:
        raise ValueError("Geometry source venue identities disagree")
    image = source.get("syutyoImg","")
    circumference = re.fullmatch(r"/pc/static/img/sisetsu/bank(\d+(?:\.\d+)?)\.gif",image)
    fields = {key:source.get(key) for key in ("syutyoImg","tyokusen","kant","tkant","homeHukuin","backHukuin","centerHukuin")}
    record = dict(venue_code=code,name=identity["jyoName"],
        circumference_m=float(circumference.group(1)) if circumference else None,
        straight_m=_metres(source.get("tyokusen")),cant_deg=_degrees(source.get("kant")),
        straight_cant_deg=_degrees(source.get("tkant")),home_width_m=_metres(source.get("homeHukuin")),
        back_width_m=_metres(source.get("backHukuin")),center_width_m=_metres(source.get("centerHukuin")),
        indoor=None,home_bearing_deg=None,back_bearing_deg=None,curve_radius_m=None,
        source_url=source_url,source_sha256=hashlib.sha256(raw_html).hexdigest(),retrieved_at=retrieved_at,
        effective_from=None,effective_to=None,geometry_scope="current_unversioned",source_fields=fields,
        note="Published nominal values; historical effective dates and current construction/operation status are unverified.")
    VenueGeometry(**record)
    return record


def context_features(record, as_of, *, store=None, allow_current_geometry_assumption=False):
    snapshot = record.get("snapshot",record)
    venue = snapshot.get("venue_id",snapshot.get("venue_code"))
    target = snapshot.get("race_at",snapshot.get("event_at",snapshot.get("day")))
    if venue is None or target is None:
        return {}
    return (store or VenueStore.load()).features(venue,target,as_of,
        allow_current_geometry_assumption=allow_current_geometry_assumption)
