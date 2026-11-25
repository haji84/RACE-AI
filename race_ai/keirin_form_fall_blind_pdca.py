"""Blind forward cohort comparison: original A/B vs documented-form shadow.

Pure post-result scorer. No network, no private source bytes, no writing,
no new betting. Inputs must be authenticated by trusted producer/official
verifiers; boolean callbacks alone are NOT issuer signatures. A historical
result must NEVER be used to create or adjust the frozen forecast.

Both arms use exactly the same eligible race IDs per model. Missing shadow
does not become a miss. C history remains a separate comparison family.
"""
from __future__ import annotations

from datetime import datetime
from collections import Counter, defaultdict
from itertools import product

from . import keirin_nationwide_auto_generator as original
from . import keirin_form_fall_shadow as condition


class ForwardComparisonError(ValueError):
    pass


def need(ok, code):
    if not ok:
        raise ForwardComparisonError(code)


def _ticket(raw, cars):
    need(type(raw) is list and len(raw) == 3 and
         all(type(x) is int and x in cars for x in raw) and
         len(set(raw)) == 3, "FORM_PDCA_TICKET_INVALID")
    return tuple(raw)


def _tickets(arm, cars):
    need(type(arm) is dict and type(arm.get("ranked_tickets")) is list
         and 1 <= len(arm["ranked_tickets"]) <= 12,
         "FORM_PDCA_TICKETS_MISSING")
    values = [_ticket(x,cars) for x in arm["ranked_tickets"]]
    need(len(values) == len(set(values)), "FORM_PDCA_TICKET_DUPLICATE")
    return values


def _result(record, cars, rid):
    need(type(record) is dict and record.get("race_id") == rid,
         "FORM_PDCA_RESULT_IDENTITY_INVALID")
    need(record.get("status") == "FINAL_NORMAL" and
         record.get("refund_status") == "NONE", "FORM_PDCA_RESULT_NOT_FINAL_NORMAL")
    triples = record.get("winning_triples")
    payouts = record.get("payouts_100yen")
    need(type(triples) is list and bool(triples) and
         type(payouts) is list and len(payouts) == len(triples),
         "FORM_PDCA_FINAL_PAYOUTS_REQUIRED")
    wins = [_ticket(x,cars) for x in triples]
    need(len(wins) == len(set(wins)), "FORM_PDCA_RESULT_DUPLICATE_WINNER")
    paid = {}
    for p in payouts:
        need(type(p) is dict and type(p.get("yen")) is int and
             100 <= p["yen"] <= 10**9,
             "FORM_PDCA_PAYOUT_INVALID")
        t = _ticket(p.get("triple"),cars)
        need(t not in paid, "FORM_PDCA_PAYOUT_DUPLICATE")
        paid[t] = p["yen"]
    need(set(wins) == set(paid), "FORM_PDCA_WINNER_PAYOUT_DISAGREE")
    return paid


def _score(tickets, paid):
    stake = 100*len(tickets)
    value = sum(paid.get(t,0) for t in tickets)
    return {"first_hit": tickets[0] in paid,
            "all_hit":any(t in paid for t in tickets),
            "points":len(tickets), "stake_yen":stake,
            "payout_yen":value,"virtual_profit_yen":value-stake}


def _qualified(row, rid, callbacks):
    """Require exact race and cutoff lineage plus trusted external witnesses."""
    need(type(row) is dict and set(row) >= {
        "baseline", "conditioned", "result", "starters",
        "baseline_sealed_at", "conditioned_sealed_at", "verified_receipts"},
        "FORM_PDCA_INPUTS_MISSING")
    base, adjusted = row["baseline"], row["conditioned"]
    need(type(base) is dict and type(adjusted) is dict and
         base.get("race_id") == adjusted.get("race_id") == rid and
         base.get("schema") == original.PREDICTION and
         adjusted.get("schema") == condition.SCHEMA and
         adjusted.get("baseline_prediction_sha256") == base.get("prediction_sha256") and
         adjusted.get("baseline_source_sha256") == base.get("source_facts_sha256") and
         adjusted.get("generated_at") == base.get("generated_at"),
         "FORM_PDCA_FROZEN_PRE_CUTOFF_LINEAGE_INVALID")
    need(base.get("prediction_sha256") == original.digest({
         k:v for k,v in base.items() if k != "prediction_sha256"}) and
         adjusted.get("sha256") == original.digest({
         k:v for k,v in adjusted.items() if k != "sha256"}),
         "FORM_PDCA_PREDICTION_SHA_INVALID")
    close = original.when(base["published_cutoff_at"])
    need(adjusted.get("published_cutoff_at") == base["published_cutoff_at"] and
         original.when(base["generated_at"]) <= original.when(row["baseline_sealed_at"]) and
         original.when(adjusted["generated_at"]) <= original.when(row["conditioned_sealed_at"]) and
         (close-original.when(row["baseline_sealed_at"])).total_seconds() >= 65 and
         (close-original.when(row["conditioned_sealed_at"])).total_seconds() >= 65,
         "FORM_PDCA_PRE_CUTOFF_MARGIN_NOT_PROVEN")
    need(type(row["starters"]) is list and
         5 <= len(row["starters"]) <= 9 and
         all(type(x) is int and 1 <= x <= 9 for x in row["starters"]) and
         len(set(row["starters"])) == len(row["starters"]),
         "FORM_PDCA_STARTERS_INVALID")
    need(type(row["verified_receipts"]) is dict and
         all(k in row["verified_receipts"] for k in (
             "baseline_origin", "condition_origin", "official_final")),
         "FORM_PDCA_WITNESS_RECEIPTS_MISSING")
    need(all(callable(callbacks.get(name)) for name in (
        "baseline_origin", "condition_origin", "official_final")),
        "FORM_PDCA_TRUSTED_VERIFIERS_REQUIRED")
    for name in ("baseline_origin", "condition_origin", "official_final"):
        # The witness must be authenticated externally by the caller, not
        # constructed from boolean flags inside the original payload.
        need(callbacks[name](rid,row,row["verified_receipts"][name]) is True,
             "FORM_PDCA_EXTERNAL_WITNESS_FAILED")
    return base,adjusted,_result(row["result"],set(row["starters"]),rid)


def compare_cohort(*, registered_race_ids, joined_private_rows,
                   independently_verify):
    """Comparable results only, no prior-day backfill or model promotion."""
    need(type(registered_race_ids) is list and
         len(set(registered_race_ids)) == len(registered_race_ids) and
         all(type(rid) is str and original.VENUE.fullmatch(rid)
             for rid in registered_race_ids),
         "FORM_PDCA_COHORT_INVALID")
    need(type(joined_private_rows) is dict and
         set(joined_private_rows).issubset(set(registered_race_ids)),
         "FORM_PDCA_UNKNOWN_RACE")
    per_race = []
    combined = {"A":{"original":{"first":0,"hit":0,"stake":0,"payout":0},
                     "conditioned":{"first":0,"hit":0,"stake":0,"payout":0}},
                "B":{"original":{"first":0,"hit":0,"stake":0,"payout":0},
                     "conditioned":{"first":0,"hit":0,"stake":0,"payout":0}}}
    statuses = Counter()
    for rid in registered_race_ids:
        if rid not in joined_private_rows:
            status = "HOLD_NO_AUTHENTICATED_PAIRED_ORIGINAL"
            per_race.append({"race_id":rid,"state":status})
            statuses[status] += 1
            continue
        row = joined_private_rows[rid]
        try:
            base,adj,paid = _qualified(row,rid,independently_verify)
            scores = {}
            for role in ("A","B"):
                name = role+"_research"
                prior = _tickets(base[role],set(row["starters"]))
                new = _tickets(adj[name],set(row["starters"]))
                old_score,new_score = _score(prior,paid),_score(new,paid)
                scores[role] = {"old":old_score, "conditioned":new_score,
                                "changed":prior != new}
            # Admit the complete four-arm comparison atomically. A failed
            # B validation must not leave A's hits or stakes in the cohort.
            for role, score in scores.items():
                for dest,result in (("original",score["old"]),
                                    ("conditioned",score["conditioned"])):
                    combined[role][dest]["first"] += int(result["first_hit"])
                    combined[role][dest]["hit"] += int(result["all_hit"])
                    combined[role][dest]["stake"] += result["stake_yen"]
                    combined[role][dest]["payout"] += result["payout_yen"]
            status = "PAIRED_CONDITIONED_RESEARCH_COMPARABLE"
            per_race.append({"race_id":rid,"state":status,
                             "scored":scores})
        except (ForwardComparisonError,ValueError,KeyError,TypeError):
            status = "HOLD_UNVERIFIED_PRE_CUTOFF_OR_FINAL"
            per_race.append({"race_id":rid,"state":status})
        statuses[status] += 1
    n = statuses["PAIRED_CONDITIONED_RESEARCH_COMPARABLE"]
    metrics = {}
    for role, families in combined.items():
        metrics[role] = {}
        for family, v in families.items():
            metrics[role][family] = {
                "eligible_same_races":n,
                "first_hit":v["first"],
                "all_hit":v["hit"],
                "stake_yen":v["stake"],
                "payout_yen":v["payout"],
                "virtual_profit_yen":v["payout"]-v["stake"],
                "virtual_roi":(v["payout"]/v["stake"] if v["stake"] else None),
                "hit_rate":(v["hit"]/n if n else None)}
    return {
        "schema":"RACE_AI_KEIRIN_CONDITION_SHADOW_BLIND_PDCA_V1",
        "registered_races":len(registered_race_ids),
        "paired_comparable_races":n,
        "missing_never_scored_as_miss":True,
        "conditional_model_not_promoted":True,
        "historical_result_fed_into_forecast":False,
        "official_results_externally_authenticated_by_caller":True if n else False,
        "statuses":dict(sorted(statuses.items())),
        "metrics":metrics, "records":per_race,
    }


_CHECKPOINTS = original.PHASES[:-1]
_FLOW_ASPECTS = (*_CHECKPOINTS, 'INITIATIVE', 'ATTACK_ORDER')
_INDEPENDENT_FLOW_SOURCES = {'video', 'official', 'article'}


def _flow_value(aspect, value, starters):
    if aspect == 'INITIATIVE':
        need(type(value) is int and value in starters, 'FLOW_INITIATIVE_INVALID')
        return value
    need(type(value) is list and all(type(car) is int and car in starters for car in value),
         'FLOW_ORDER_INVALID')
    if aspect in _CHECKPOINTS:
        need(bool(value) and len(value) == len(set(value)), 'FLOW_CHECKPOINT_ORDER_INVALID')
    return value


def _is_subsequence(part, total):
    rest = iter(total)
    return all(car in rest for car in part)


def _flow_agrees(aspect, predicted, observed, complete):
    if aspect == 'ATTACK_ORDER':
        return predicted == observed if complete else _is_subsequence(observed, predicted)
    if aspect == 'INITIATIVE':
        return predicted == observed
    length = min(len(predicted), len(observed))
    return predicted[:length] == observed[:length]


def _compare_flow(predicted, evidence, starters):
    compared = {}
    for aspect in _FLOW_ASPECTS:
        rows = evidence.get(aspect, [])
        item = {'sources': sorted({row['source'] for row in rows})}
        if aspect not in predicted:
            state = 'forecast_missing'
        elif not rows:
            state = 'unobserved'
        else:
            main = max(rows, key=lambda row: (row['complete'],
                       1 if aspect == 'INITIATIVE' else len(row['observed'])))
            observed = main['observed']
            if any(not _flow_agrees(aspect, observed, row['observed'], row['complete']) for row in rows):
                state = 'conflict'
            else:
                expected = predicted[aspect]
                item['observed'] = observed
                item['predicted'] = expected
                if not _flow_agrees(aspect, expected, observed, main['complete']):
                    state = 'different'
                elif not main['complete'] or aspect in _CHECKPOINTS and len(expected) < len(starters):
                    state = 'partial_match'
                else:
                    state = 'match'
        compared[aspect] = dict(item, state=state)
    states = Counter(x['state'] for x in compared.values())
    state = ('different' if states['different'] else
             'match' if states['match'] == len(_FLOW_ASPECTS) else 'insufficient')
    return {'state': state, 'aspects': compared, 'counts': dict(states)}


def _development_grade(hit, flow):
    if hit is None:
        return None
    if flow == 'match':
        return 'A' if hit else 'C'
    if flow == 'different':
        return 'B' if hit else 'D'
    return 'E'


def compare_race_development(*, race_id, starters, forecast, order, observations,
                             verify_forecast, verify_order, verify_observation):
    """Score a saved order and the observed flow separately, with external evidence.

    ``forecast`` carries its projected checkpoint sequences, the first main
    move (INITIATIVE), and the expected late attacking actors (ATTACK_ORDER).
    A checkpoint may be a measured leading prefix. An incomplete attack
    sequence records only the relative order of the actions actually seen.
    Verifiers must independently bind the inputs to their source receipts.
    A conversation example can receive a reference grade only.
    """
    need(type(race_id) is str and original.VENUE.fullmatch(race_id) and
         type(starters) is list and 3 <= len(starters) <= 9 and
         all(type(car) is int and 1 <= car <= 9 for car in starters) and
         len(set(starters)) == len(starters), 'FLOW_RACE_SCOPE_INVALID')
    need(type(forecast) is dict and forecast.get('race_id') == race_id and
         forecast.get('scope') in {'registered', 'conversation_reference'}, 'FLOW_FORECAST_SCOPE_INVALID')
    need(all(callable(check) for check in (verify_forecast, verify_order, verify_observation)),
         'FLOW_VERIFIERS_REQUIRED')
    cars = set(starters)
    reference = forecast['scope'] == 'conversation_reference'
    registered = (not reference and original.when(forecast.get('sealed_at')) <
                  original.when(forecast.get('cutoff_at')) and verify_forecast(forecast) is True)
    tickets = _tickets({'ranked_tickets': forecast.get('tickets')}, cars)
    need(len(tickets) <= 8, 'FLOW_TICKET_CAP_EXCEEDED')
    predicted = forecast.get('flow', {})
    need(type(predicted) is dict and set(predicted) <= set(_FLOW_ASPECTS), 'FLOW_PROJECTION_INVALID')
    for aspect, value in predicted.items():
        _flow_value(aspect, value, cars)

    accepted, reported = defaultdict(list), defaultdict(list)
    unverified = 0
    need(type(observations) is list, 'FLOW_OBSERVATIONS_INVALID')
    for row in observations:
        need(type(row) is dict and row.get('race_id') == race_id and row.get('aspect') in _FLOW_ASPECTS and
             row.get('source') in _INDEPENDENT_FLOW_SOURCES | {'user', 'estimate'} and
             type(row.get('complete')) is bool and 'receipt' in row and 'observed' in row, 'FLOW_OBSERVATION_INVALID')
        aspect, source = row['aspect'], row['source']
        _flow_value(aspect, row['observed'], cars)
        if aspect in _CHECKPOINTS and row['complete']:
            need(len(row['observed']) == len(cars), 'FLOW_COMPLETE_CHECKPOINT_REQUIRES_FULL_ORDER')
        if source in _INDEPENDENT_FLOW_SOURCES and verify_observation(row) is True:
            accepted[aspect].append(row)
        elif source == 'user':
            reported[aspect].append(row)
        else:
            unverified += 1

    need(order is None or type(order) is dict and order.get('race_id') == race_id, 'FLOW_RESULT_IDENTITY_INVALID')
    winners = None
    if order is not None and verify_order(order) is True:
        result_tickets = order.get('winning_triples')
        need(type(result_tickets) is list, 'FLOW_RESULT_ORDER_INVALID')
        winners = {_ticket(value, cars) for value in result_tickets}
        need(len(winners) == len(result_tickets), 'FLOW_RESULT_DUPLICATE_ORDER')
    placing = {'formal': registered and bool(winners), 'hit': None, 'first_hit': None,
               'points': len(tickets), 'matched_points': None, 'hit_rank': None}
    if winners and (registered or reference):
        ranks = [index for index, ticket in enumerate(tickets, 1) if ticket in winners]
        placing.update(hit=bool(ranks), first_hit=1 in ranks, matched_points=len(ranks),
                       hit_rank=ranks[0] if ranks else None)
    flow = _compare_flow(predicted, accepted, cars)
    flow['unverified_observations'] = unverified
    reference_grade = None
    reference_flow = None
    if reference:
        reference_flow = _compare_flow(predicted, reported | accepted, cars)
        reference_grade = _development_grade(placing['hit'], reference_flow['state'])
    grade = _development_grade(placing['hit'], flow['state']) if placing['formal'] else None
    return {'race_id': race_id, 'placing': placing, 'flow': flow, 'grade': grade,
            'reference_grade': reference_grade, 'reference_flow': reference_flow}
