"""Official B fixed-position motor allocation, validated against B boat identities.

Official B program rows use per-boat fixed columns. The motor number is the
two-character field at columns 42-43 (Python indices 41:43). Motor 2-ren rate
is indices 44:49. Boat number is indices 50:52, boat 2-ren 53:58.

The offsets were corroborated against an independently published B parser and
MUST be tested on real B files/official race cards before being trusted as
complete future-compatible parsing.
"""
from __future__ import annotations
import re
import unicodedata
from datetime import date
from .core import SourceError, _blocks, _decode, _race_id, _ensure_day, parse_b

def _numeric(text:str)->str:
    return unicodedata.normalize("NFKC",text).strip()

def parse_b_motors(raw:bytes,day:str)->list[dict]:
    text=_decode(raw)
    if "STARTB" not in text[:200]:
        raise SourceError("not an official B text")
    # Independent official B existing parser yields all race/lane/racer IDs.
    canonical=parse_b(raw,day)
    identities={(r['race_id'],r['lane']):r['racer_id'] for r in canonical}
    output={}
    for venue,block in _blocks(text,"B"):
        _ensure_day(block,day)
        race=None
        for line in block.splitlines():
            header=re.match(r"^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m",
                            unicodedata.normalize("NFKC",line),re.I)
            if header:
                race=int(header.group(1)); continue
            if race is None or race not in range(1,13):
                continue
            # Keep original CP932-decoded code-point positions. NFKC of
            # the entire line might shift indices of some names.
            if not re.match(r"^[1-6]\s+\d{4}",line):
                continue
            if len(line)<58:
                raise SourceError("B racer row shorter than documented motor columns")
            lane=int(line[0])
            racer=line[2:6]
            rid=_race_id(day,venue,race)
            key=(rid,lane)
            if identities.get(key)!=racer or key in output:
                raise SourceError("B fixed-width identity mismatch/duplicate row")
            m_text=_numeric(line[41:43])
            mr_text=_numeric(line[44:49])
            b_text=_numeric(line[50:52])
            br_text=_numeric(line[53:58])
            if not (re.fullmatch(r"\d{1,2}",m_text)
                    and re.fullmatch(r"\d{1,2}",b_text)
                    and re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?",mr_text)
                    and re.fullmatch(r"\d{1,2}(?:\.\d{1,2})?",br_text)):
                raise SourceError(f"B motor/boat fixed columns invalid: venue={venue}, race={race}, lane={lane}")
            motor=int(m_text);boat=int(b_text)
            rate=float(mr_text);boat_rate=float(br_text)
            if motor<=0 or boat<=0 or not 0<=rate<=100 or not 0<=boat_rate<=100:
                raise SourceError("motor/boat number/rate out of bounds")
            output[key]=dict(race_id=rid,venue=f"{venue:02d}",lane=lane,
                             racer_id=racer,motor_no=motor,
                             motor_top2_rate=rate,boat_no=boat,
                             boat_top2_rate=boat_rate,source_kind="OFFICIAL_B")
    if len(output)!=len(identities) or set(output)!=set(identities):
        raise SourceError("motor allocations absent from B for some of the registered boats")
    # Within the same race no motor may be mounted on multiple boats.
    seen=set()
    for x in output.values():
        key=(x['race_id'],x['motor_no'])
        if key in seen:
            raise SourceError("same motor number allocated to multiple boats in one race")
        seen.add(key)
    # An individual motor is assigned consistently to the same racer
    # throughout a venue's program on the same date; do not assume that
    # race number or lane alone determines that relationship.
    motor_racer={}
    for x in output.values():
        key=(x['venue'],x['motor_no'])
        incumbent=motor_racer.setdefault(key,x['racer_id'])
        if incumbent!=x['racer_id']:
            raise SourceError("different racer shares a motor in one day's program")
    return [output[k] for k in sorted(output)]
