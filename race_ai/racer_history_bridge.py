"""Connect imported official K history to descriptive racer statistics.

The existing starts table has actual course, ST and finish, but NOT the
official winner method. This bridge never invents that missing method.
"""
from __future__ import annotations
import sqlite3

from .core import SourceError, utc
from .racer_conditional_form import summarize_racer
from .racer_win_loss_patterns import analyze_patterns


def history_observations(db: sqlite3.Connection, *, racer_id: str, asof: str) -> list[dict]:
    cutoff=utc(asof)
    if not racer_id.isdigit() or len(racer_id)!=4:
        raise SourceError("invalid racer ID")
    rows=db.execute("""
      SELECT * FROM (
        SELECT s.*, ROW_NUMBER() OVER (
          PARTITION BY race_id,lane ORDER BY captured_at DESC,sha DESC
        ) AS rn
        FROM starts s
        WHERE published_at<=? AND captured_at<=?
      ) WHERE rn=1 AND racer_id=? AND st_status!='ABSENT'
      ORDER BY race_at DESC,race_id DESC
    """,(cutoff,cutoff,racer_id)).fetchall()
    return [{
        "race_id":r["race_id"],"racer_id":r["racer_id"],
        "lane":r["lane"],"actual_course":r["course"],
        "finish":r["finish"],"st":r["st"],
        "published_at":r["published_at"],"observed_at":r["captured_at"],
        "winner_method":None
    } for r in rows]


def analyze_imported_history(db: sqlite3.Connection, *, racer_id: str, asof: str) -> dict:
    rows=history_observations(db,racer_id=racer_id,asof=asof)
    return {
        "racer_id":racer_id,"asof":utc(asof),
        "conditional_form":summarize_racer(rows,racer_id=racer_id,asof=asof),
        "win_loss_patterns":analyze_patterns(rows,racer_id=racer_id,asof=asof),
        "winner_method_status":"NOT_STORED_IN_K_STARTS",
        "source":"IMPORTED_OFFICIAL_K_HISTORY_STRUCTURAL_NOT_INDEPENDENTLY_VERIFIED"
    }
