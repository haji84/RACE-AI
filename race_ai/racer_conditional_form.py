"""As-of-safe descriptive racer profiles from verified race observations.

This module never infers a losing boat's own 'winning method'. Winner method
and observed losing circumstances remain separate evidence fields.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from math import sqrt

from .core import SourceError, utc


def _wilson(success: int, total: int, z: float = 1.96):
    if total == 0:
        return None
    p = success / total
    denom = 1 + z*z/total
    center = (p + z*z/(2*total)) / denom
    spread = z*sqrt((p*(1-p)+z*z/(4*total))/total)/denom
    return [round(max(0,center-spread),4),round(min(1,center+spread),4)]


def summarize_racer(observations: list[dict], *, racer_id: str, asof: str) -> dict:
    cutoff = utc(asof)
    if not racer_id.isdigit() or len(racer_id) != 4:
        raise SourceError("invalid racer ID")
    groups = defaultdict(list)
    seen = set()
    for row in observations:
        if row.get("racer_id") != racer_id:
            continue
        observed = utc(row["observed_at"])
        published = utc(row["published_at"])
        if observed > cutoff or published > cutoff:
            continue
        rid = row.get("race_id")
        if not isinstance(rid,str) or rid in seen:
            raise SourceError("duplicate or missing race identity")
        seen.add(rid)
        lane = row.get("lane")
        course = row.get("actual_course")
        finish = row.get("finish")
        if type(lane) is not int or not 1 <= lane <= 6:
            raise SourceError("invalid lane")
        if course is not None and (type(course) is not int or not 1 <= course <= 6):
            raise SourceError("invalid actual course")
        if finish is not None and (type(finish) is not int or not 1 <= finish <= 6):
            raise SourceError("invalid finish")
        if course is not None:
            groups[("actual_course",course)].append(row)
        groups[("lane",lane)].append(row)
    output = []
    for (dimension,number),rows in sorted(groups.items()):
        ranked = [x for x in rows if x.get("finish") is not None]
        n = len(ranked)
        wins = sum(x["finish"] == 1 for x in ranked)
        top2 = sum(x["finish"] <= 2 for x in ranked)
        top3 = sum(x["finish"] <= 3 for x in ranked)
        output.append({
            "dimension":dimension,"number":number,
            "observations":len(rows),"valid_finishes":n,
            "win_rate":round(wins/n,4) if n else None,
            "top2_rate":round(top2/n,4) if n else None,
            "top3_rate":round(top3/n,4) if n else None,
            "win_rate_95pct_interval":_wilson(wins,n),
            "insufficient_sample":n < 20
        })
    return {"racer_id":racer_id,"asof":cutoff,
            "groups":output,"status":"DESCRIPTIVE_NOT_CAUSAL" if output else "NO_VERIFIED_HISTORY"}
