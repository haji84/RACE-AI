"""Pre-cutoff race-class, round and advancement-context sidecar for KEIRIN.

Research only. This does not scrape, identify a rider, rewrite PR71, learn a
strategy weight, or claim official/event-program assignment. A race labelled
"チャレンジ準決勝" contains TWO dimensions: CHALLENGE class and SEMI_FINAL
round. The exact advancement program must come from the matching event,
not be inferred from the label or a generic PDF.

The stage-aware output is a conditional input to the existing 6-phase
tactical research. It is NOT a calibrated chance of winning or new Top12
prediction. Stage-only ranking is never considered a formal forecast.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from unicodedata import normalize
import json
import math
import os
import re

SCHEMA = "RACE_AI_KEIRIN_PRE_CUTOFF_ROUND_CONTEXT_V1"
PLAN = "RACE_AI_KEIRIN_ROUND_TACTICAL_CONDITIONS_V1"
STUDY = "RACE_AI_KEIRIN_ROUND_STRATEGY_SHADOW_V1"
CLASS = frozenset(("CHALLENGE", "A1_A2", "S", "GIRLS", "OTHER"))
ROUND = frozenset(("PRELIMINARY", "PRELIMINARY_1", "PRELIMINARY_2",
                   "SEMI_FINAL", "FINAL", "INITIAL_SPECIAL",
                   "SELECTION", "GENERAL", "OTHER"))
RULES = frozenset(("DIRECT_RANK", "RANK_AND_CROSS_RACE",
                   "CUMULATIVE_POINTS", "NO_ADVANCEMENT", "UNKNOWN"))
HEX = re.compile(r"^[a-f0-9]{64}$")
ID = re.compile(r"^(?:20\d{10}|keirin:20\d{2}-\d{2}-\d{2}:[a-z0-9_-]{2,40}:[1-9]\d?)$")


class RoundError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise RoundError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha256(canonical(value)).hexdigest()


def _timestamp(value):
    _need(type(value) is str, "TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RoundError("TIMESTAMP_INVALID") from None
    _need(dt.utcoffset() is not None, "OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)


def _sha(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _source(url):
    _need(type(url) is str and 1 <= len(url) <= 2048,
          "PROGRAM_URL_INVALID")
    try:
        parsed = urlsplit(url)
        good = (parsed.scheme == "https" and
                parsed.hostname in {"www.keirin.jp", "keirin.jp"} and
                parsed.username is None and parsed.password is None and
                parsed.port is None and parsed.path.endswith(".pdf") and
                not parsed.fragment)
    except ValueError:
        good = False
    _need(good, "PROGRAM_PDF_SOURCE_NOT_KEIRIN_JP")
    return url


def _class_and_label(competition, stage, label):
    _need(competition in CLASS and stage in ROUND and
          type(label) is str and 1 <= len(label) <= 80,
          "RACE_CLASS_OR_STAGE_REQUIRED")
    title = normalize("NFKC", label)
    # Avoid changing grade into a phase. In particular, a Challenge final
    # is a final; "チャレンジ" by itself is never a racing round.
    if competition == "CHALLENGE":
        _need("チャレンジ" in title, "CHALLENGE_LABEL_DISAGREES")
    if competition == "GIRLS":
        _need("ガールズ" in title or title.startswith("ガ"),
              "GIRLS_LABEL_DISAGREES")
    token = {
        "PRELIMINARY":"予選", "PRELIMINARY_1":"予", "PRELIMINARY_2":"予",
        "SEMI_FINAL":"準決勝", "FINAL":"決勝", "INITIAL_SPECIAL":"初特選",
        "GENERAL":"一般", "SELECTION":"選抜",
    }.get(stage)
    if token is not None:
        _need(token in title or (stage == "SELECTION" and "特選" in title),
              "ROUND_LABEL_DISAGREES")
    _need(not (stage == "PRELIMINARY" and "準決勝" in title),
          "PRELIM_AND_SEMI_CONFLICT")
    return title


def _advancement(stage, race_size, rule):
    keys = {"kind", "direct_through", "conditional_ranks", "points_rule"}
    _need(type(rule) is dict and set(rule) == keys and
          rule.get("kind") in RULES, "PROGRAM_RULE_SCHEMA")
    kind = rule["kind"]
    direct, maybe, point = rule["direct_through"],rule["conditional_ranks"],rule["points_rule"]
    _need(type(maybe) is list and
          all(type(i) is int and 1 <= i <= race_size for i in maybe) and
          maybe == sorted(set(maybe)), "CONDITIONAL_RANKS_INVALID")
    if kind in ("DIRECT_RANK","RANK_AND_CROSS_RACE"):
        _need(type(direct) is int and 1 <= direct <= race_size and
              point is None and
              all(i > direct for i in maybe) and
              (kind != "DIRECT_RANK" or not maybe) and
              (kind != "RANK_AND_CROSS_RACE" or bool(maybe)),
              "RANK_ADVANCEMENT_RULE_INVALID")
        _need(stage not in ("FINAL","GENERAL"),
              "FINAL_OR_GENERAL_CANNOT_BE_DIRECT_PROMOTION")
    elif kind == "CUMULATIVE_POINTS":
        _need(direct is None and not maybe and
              type(point) is str and 1 <= len(point) <= 120,
              "POINTS_RULE_NEEDS_PROGRAM_IDENTIFICATION")
    else:
        _need(direct is None and not maybe and point is None,
              "UNKNOWN_OR_NONE_RULE_MUST_NOT_INFER_RANK")
    if stage == "FINAL":
        _need(kind == "NO_ADVANCEMENT", "FINAL_MUST_NOT_PROMOTE")
    return rule


def build_context(*, race_id, competition, stage, label, race_size,
                  as_of, official_cutoff_at, parent_input_sha256,
                  event_program_code, program_pdf, rule):
    """Require a source-bound event/program receipt supplied before cutoff.

    A SHA and same-string program code do not independently certify a
    promoter/organizer assignment: the consumer must verify that separately.
    """
    _need(type(race_id) is str and ID.fullmatch(race_id) is not None,
          "RACE_ID_INVALID")
    _need(type(race_size) is int and 5 <= race_size <= 9,
          "RACE_SIZE_INVALID")
    _need(_sha(parent_input_sha256), "PARENT_INPUT_SHA_REQUIRED")
    title = _class_and_label(competition,stage,label)
    _need(type(event_program_code) is str and
          1 <= len(event_program_code) <= 40, "EVENT_PROGRAM_CODE_REQUIRED")
    need = {"url","sha256","observed_at","program_code","event_program_receipt_sha256"}
    _need(type(program_pdf) is dict and set(program_pdf) == need,
          "PROGRAM_SOURCE_FIELDS_REQUIRED")
    _source(program_pdf["url"])
    _need(_sha(program_pdf["sha256"]) and
          _sha(program_pdf["event_program_receipt_sha256"]) and
          event_program_code == program_pdf["program_code"],
          "EVENT_AND_PROGRAM_NOT_BOUND")
    seen = _timestamp(program_pdf["observed_at"])
    created = _timestamp(as_of)
    cutoff = _timestamp(official_cutoff_at)
    _need(seen <= created and (cutoff-created).total_seconds() >= 65,
          "PROGRAM_NOT_OBSERVED_PRE_CUTOFF")
    _advancement(stage,race_size,rule)
    return {
        "schema":SCHEMA, "race_id":race_id,
        "competition":competition, "round_stage":stage,
        "official_race_label":title, "race_size":race_size,
        "as_of":as_of, "official_cutoff_at":official_cutoff_at,
        "parent_input_sha256":parent_input_sha256,
        "event_program_code":event_program_code,
        "program_pdf":program_pdf, "advancement_rule":rule,
        # This is an evidence pointer, not independent legal or official proof.
        "official_program_match_independently_authenticated":False,
        "predictive_probabilities_calibrated":False,
        "formal_prediction_created":False,
    }


def conditions(doc):
    """Stage-specific tactical OBJECTIVES, not rider-specific predictions."""
    _need(type(doc) is dict and doc.get("schema") == SCHEMA,
          "ROUND_CONTEXT_REQUIRED")
    kind = doc["advancement_rule"]["kind"]
    direct = doc["advancement_rule"]["direct_through"]
    conditional = doc["advancement_rule"]["conditional_ranks"]
    stage = doc["round_stage"]
    if kind in ("DIRECT_RANK","RANK_AND_CROSS_RACE"):
        if direct == doc["race_size"]:
            modes = ["ALL_FINISHES_DIRECTLY_ADVANCE",
                     "RACE_POINTS_OR_RIDER_GOAL_STILL_UNKNOWN"]
        else:
            modes = ["DIRECT_QUALIFICATION_ZONE",
                     "ATTACK_IF_OUTSIDE_DIRECT_ZONE",
                     "DEFEND_POSITION_WITHOUT_ASSUME_PASSIVITY"]
            if conditional:
                modes += ["CROSS_RACE_WILDCARD_NOT_AUTOMATIC",
                          "BOUNDARY_POSITION_TACTIC_DEPENDS_ON_OTHER_HEATS"]
    elif stage == "FINAL":
        modes = ["WIN_IS_ONLY_TITLE_RANK",
                 "ATTACK_VS_BANTE_REACTION_HYPOTHESES",
                 "NO_AUTOMATIC_AGGRESSIVENESS_CLAIM"]
    elif kind == "CUMULATIVE_POINTS":
        modes = ["TWO_RACE_POINTS_CONTEXT",
                 "CANNOT_CHOOSE_RIDER_STRATEGY_WITHOUT_PRIOR_POINTS",
                 "OFFICIAL_POINTS_TIEBREAKER_NEEDED"]
    elif kind == "NO_ADVANCEMENT":
        modes = ["NO_NEXT_ROUND_FROM_THIS_RACE",
                 "WIN_AND_COMPETITION_POINTS_STILL_RELEVANT"]
    else:
        modes = ["HOLD_PROGRAM_ADVANCEMENT_UNKNOWN"]
    # Changes the tactical research objective, NOT original PR71 weights.
    return {
        "schema":PLAN, "race_id":doc["race_id"],
        "class":doc["competition"], "round_stage":stage,
        "program_code":doc["event_program_code"],
        "advancement_kind":kind,
        "guaranteed_rank_through":direct,
        "conditional_finish_ranks":conditional,
        "strategic_conditions":modes,
        "context_sha256":digest(doc),
        "win_or_advancement_probability":None,
        "hit_at_1_uplift":None,
        "candidate_top12_reranked":False,
        "model_promotion_allowed":False,
    }


def shadow_strategy_intervals(doc, proposals):
    """Evaluate hypothetical pre-race finish-rank masses, never official picks.

    This is an *untrained simulation proxy*. It can compare guaranteed and
    wildcard possibilities but MUST NOT claim calibrated rider chances.
    If official points/qualification rules are unknown, refuse ordering.
    """
    con = conditions(doc)
    kind = con["advancement_kind"]
    if kind not in ("DIRECT_RANK","RANK_AND_CROSS_RACE") and doc["round_stage"] != "FINAL":
        return {"schema":STUDY,"race_id":doc["race_id"],
                "state":"HOLD_POINTS_OR_PROGRAM_UNKNOWN",
                "ranked":[], "context_sha256":con["context_sha256"],
                "calibrated":False,"formal_top12_changed":False}
    _need(type(proposals) is list and 1 <= len(proposals) <= 64,
          "PROPOSAL_LIST_REQUIRED")
    seen = set()
    rows = []
    for p in proposals:
        _need(type(p) is dict and set(p) == {
            "scenario_id","rider_no","rank_mass","as_of","input_sha256"
        }, "SCENARIO_FIELDS_INVALID")
        _need(type(p["scenario_id"]) is str and
              re.fullmatch(r"[A-Za-z0-9_.-]{1,64}",p["scenario_id"]) and
              p["scenario_id"] not in seen,
              "SCENARIO_ID_INVALID_OR_DUPLICATE")
        seen.add(p["scenario_id"])
        _need(type(p["rider_no"]) is int and 1<=p["rider_no"]<=9 and
              type(p["rank_mass"]) is list and
              len(p["rank_mass"]) == doc["race_size"] and
              all(type(x) in (int,float) and math.isfinite(x)
                  and 0 <= x <= 1 for x in p["rank_mass"]) and
              abs(math.fsum(p["rank_mass"])-1) <= 1e-8,
              "SCENARIO_UNCALIBRATED_MASS_INVALID")
        _need(_timestamp(p["as_of"]) <= _timestamp(doc["as_of"]) and
              p["input_sha256"]==doc["parent_input_sha256"],
              "SCENARIO_POST_CUTOFF_OR_INPUT_MISMATCH")
        ranks = p["rank_mass"]
        if doc["round_stage"] == "FINAL":
            lo = hi = ranks[0]
        else:
            n=con["guaranteed_rank_through"]
            lo = math.fsum(ranks[:n])
            hi = lo+math.fsum(ranks[i-1] for i in con["conditional_finish_ranks"])
        rows.append({
            "scenario_id":p["scenario_id"],
            "rider_no":p["rider_no"],
            "guaranteed_or_win_proxy_lower":lo,
            "conditional_proxy_upper":hi,
            "known_wildcard_dependency":hi>lo,
        })
    # A conservative *qualitative* preference is possible only if the
    # top lower bound strictly exceeds every opponent's upper bound.
    # Neither result is a rider's calibrated likelihood or new bet ranking.
    ranking = sorted(rows,key=lambda r:(-r["guaranteed_or_win_proxy_lower"],
                                        r["scenario_id"]))
    top=ranking[0]
    clear = len(ranking)==1 or all(
        top["guaranteed_or_win_proxy_lower"] >
        r["conditional_proxy_upper"]+1e-12 for r in ranking[1:])
    return {
        "schema":STUDY,"race_id":doc["race_id"],
        "state":"RESEARCH_PROXY_STRICTLY_SEPARATED" if clear else
                "HOLD_OVERLAPPING_CONDITIONAL_OUTCOMES",
        "ranked":ranking if clear else [],
        "candidate_details":rows,
        "context_sha256":con["context_sha256"],
        "calibrated":False,"formal_top12_changed":False,
        "unverified_stage_assignment":True,
    }


def freeze_context_once(path, context):
    """Private immutable SHA readback; not Git/AES independent-runner proof."""
    conditions(context)
    p = Path(path)
    _need(p.parent.is_dir() and not p.parent.is_symlink() and
          not p.exists() and not p.is_symlink() and
          p.parent.stat().st_mode & 0o077 == 0,
          "STAGE_SIDECAR_REQUIRES_PRIVATE_CREATE_ONCE")
    payload=canonical(context)+b"\n"
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as sink:
        sink.write(payload)
        sink.flush()
        os.fsync(sink.fileno())
    _need(p.read_bytes()==payload, "STAGE_SIDECAR_DISK_READBACK_MISMATCH")
    return sha256(payload).hexdigest()
