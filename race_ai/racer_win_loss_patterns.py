"""Explainable win/loss pattern counts from time-valid race outcomes.

Winning method belongs to the race winner. For a losing racer it describes
the opponent's winning method, not the loser's individual maneuver.
"""
from __future__ import annotations
from collections import Counter
from .core import SourceError, utc

METHODS={"逃げ","差し","まくり","まくり差し","抜き","恵まれ"}


def analyze_patterns(rows: list[dict], *, racer_id: str, asof: str) -> dict:
    cutoff=utc(asof)
    seen=set()
    wins=Counter()
    losses=Counter()
    by_course=Counter()
    observed=0
    excluded_future=0
    for row in rows:
        if row.get("racer_id")!=racer_id:
            continue
        if utc(row["published_at"])>cutoff or utc(row["observed_at"])>cutoff:
            excluded_future+=1
            continue
        rid=row.get("race_id")
        if not rid or rid in seen:
            raise SourceError("duplicate or missing race ID")
        seen.add(rid)
        finish=row.get("finish")
        if type(finish) is not int or not 1<=finish<=6:
            continue
        method=row.get("winner_method")
        if method is not None and method not in METHODS:
            raise SourceError("unknown official winning method")
        course=row.get("actual_course")
        if course is not None and (type(course) is not int or not 1<=course<=6):
            raise SourceError("invalid actual course")
        observed+=1
        if course is not None:
            by_course[(course,"win" if finish==1 else "loss")]+=1
        if finish==1:
            wins[method or "未取得"]+=1
        else:
            losses[method or "未取得"]+=1
    return {
        "racer_id":racer_id,"asof":cutoff,
        "valid_finishes":observed,"excluded_future":excluded_future,
        "wins_by_own_winning_method":dict(sorted(wins.items())),
        "losses_by_opponent_winning_method":dict(sorted(losses.items())),
        "course_outcomes":[{"actual_course":course,"outcome":outcome,"count":count}
                           for (course,outcome),count in sorted(by_course.items())],
        "causal_loss_explanation":"UNKNOWN_REQUIRES_VIDEO_OR_VERIFIED_TURN_EVIDENCE",
        "status":"DESCRIPTIVE_ONLY" if observed else "NO_VERIFIED_HISTORY"
    }
