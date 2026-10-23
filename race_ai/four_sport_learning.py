"""Chronological outcome-supervised research ranking, four sports, no odds.

This intentionally separate TRAINABLE family complements the fixed,
untrained factor and scenario models. It never fetches source data, issues a
permission grant, creates an external freeze receipt or purchases tickets.

Training labels are separate from pre-race inputs, and model fitting uses
TRAIN ONLY. VALIDATION and TEST are disjoint chronological future cohorts.
"""
from __future__ import annotations

from datetime import date
import itertools
import math

from .comprehensive_four_sport_models import (
    ModelInputError, MODEL_IDS, COMMON_REQUIRED, SPORT_REQUIRED, SPORT_OPTIONAL,
    ENV_COMMON, ENV_SPORT, SYNTHETIC, RESEARCH,
    digest, moment, validate, _number
)

LEARNED_ID="multisport-chronological-ranker-v1"
VECTOR_VERSION="sparse-observed-feature-and-observation-mask-v1"


def vector_schema(sport):
    return (tuple(COMMON_REQUIRED)+tuple(SPORT_REQUIRED[sport])+
            tuple(SPORT_OPTIONAL[sport])+
            tuple("observed_"+name for name in SPORT_OPTIONAL[sport])+
            ("draw_prior","is_front","is_closer","is_stalker",
             "wetness_x_course","wind_x_tactics","distance_x_stamina"))


def _vector(p,race,env,sport):
    f=p["features"]
    vals=[f[x]["value"] for x in COMMON_REQUIRED+SPORT_REQUIRED[sport]]
    vals.extend(f[x]["value"] if x in f else 0.0 for x in SPORT_OPTIONAL[sport])
    vals.extend(1.0 if x in f else 0.0 for x in SPORT_OPTIONAL[sport])
    n=len(race["participants"])
    vals.extend([
        1-(p["draw"]-1)/max(1,n-1),
        1.0 if p["style"]=="front" else 0.0,
        1.0 if p["style"]=="closer" else 0.0,
        1.0 if p["style"]=="stalker" else 0.0,
        env["surface_wetness"]["value"]*f["course_compatibility"]["value"],
        min(1,env["wind_mps"]["value"]/40)*f["tactical_adaptability"]["value"],
        min(1,race["race"]["distance_m"]/10000)*f["stamina"]["value"],
    ])
    schema=vector_schema(sport)
    if len(vals)!=len(schema) or any(not math.isfinite(x) for x in vals):
        raise ModelInputError("feature vector not finite")
    return vals


def _vectors(snapshot,sport):
    rows={p["number"]:_vector(p,snapshot,snapshot["environment"],sport)
          for p in snapshot["participants"]}
    return rows


def _dot(w,x):
    return math.fsum(a*b for a,b in zip(w,x))


def _softmax(scores):
    upper=max(scores)
    weights=[math.exp(x-upper) for x in scores]
    total=math.fsum(weights)
    return [v/total for v in weights]


def _all_triples(x_by_number,weights):
    numbers=sorted(x_by_number)
    utilities={n:_dot(weights,x_by_number[n]) for n in numbers}
    universe=[]
    for a,b,c in itertools.permutations(numbers,3):
        remain=numbers[:]
        probability=1.0
        for chosen in (a,b,c):
            probs=_softmax([utilities[n] for n in remain])
            probability*=probs[remain.index(chosen)]
            remain.remove(chosen)
        universe.append({"combination":[a,b,c],"score":probability})
    universe.sort(key=lambda item:(-item["score"],item["combination"]))
    total=math.fsum(v["score"] for v in universe)
    if len(universe)!=len(numbers)*(len(numbers)-1)*(len(numbers)-2):
        raise ModelInputError("complete candidate universe missing")
    for v in universe:v["score"]/=total
    return universe


def forecast(snapshot,model,*,allow_source=None):
    checked=validate(snapshot,allow_source=allow_source)
    race=snapshot["race"]
    if model.get("model_id")!=LEARNED_ID or model.get("sport")!=race["sport"] or (
         model.get("vector_schema") != list(vector_schema(race["sport"]))):
        raise ModelInputError("model version/sport/features conflict")
    if model.get("trained_scope")!=snapshot["scope"]:
        raise ModelInputError("training source scope differs")
    if moment(race["as_of"])<=moment(model["trained_until"]):
        raise ModelInputError("prediction must follow training cutoff")
    weights=model.get("weights")
    if (not isinstance(weights,list) or len(weights)!=len(vector_schema(race["sport"])) or
        any(type(x) not in (int,float) or not math.isfinite(x) for x in weights)):
        raise ModelInputError("untrusted learned weights")
    universe=_all_triples(_vectors(snapshot,race["sport"]),weights)
    answer={
       "model_id":LEARNED_ID,"model_version":model["model_version"],
       "sport":race["sport"],"race_id":race["race_id"],"race_revision":race["race_revision"],
       "training_end_at":model["trained_until"],
       "as_of":race["as_of"],"cutoff_at":race["sales_cutoff_at"],
       "input_sha256":checked["snapshot_sha256"],
       "model_sha256":model["model_sha256"],
       "ordered_top8":[x["combination"] for x in universe[:8]],
       "candidate_count":len(universe),"candidates":universe,
       "scope":snapshot["scope"],"odds_independent":True,
       "trained":True,"calibrated":False,"official_prediction":False,
       "purchase_decision":"NO_BET","external_pre_cutoff_receipt":None,
       "official_result":None,
       "missing_optional_by_participant":checked["missing_optional"],
       "validation_status":"RESEARCH_NO_EXTERNAL_RECEIPT"}
    answer["prediction_sha256"]=digest(answer)
    return answer


def _label(result,snapshot,*,scope,allow_result,window_end):
    if not isinstance(result,dict) or set(result)!={
        "race_id","status","ordered_top3","published_at","captured_at",
        "source_ref","source_rights_ref"}:
        raise ModelInputError("result label separate schema required")
    if result["race_id"]!=snapshot["race"]["race_id"] or result["status"]!="settled":
        raise ModelInputError("only settled same-race labels admitted")
    ids={x["number"] for x in snapshot["participants"]}
    result_order=result["ordered_top3"]
    if not isinstance(result_order,list) or len(result_order)!=3 or any(
        type(x) is not int or x not in ids for x in result_order
    ) or len(set(result_order))!=3:
        raise ModelInputError("official ordered three-place label invalid")
    published=moment(result["published_at"]);captured=moment(result["captured_at"])
    if not moment(snapshot["race"]["sales_cutoff_at"])<published<=captured<=window_end:
        raise ModelInputError("result unavailable at cohort verification boundary")
    if not result["source_ref"] or not result["source_rights_ref"]:
        raise ModelInputError("result source proof missing")
    if scope==RESEARCH and (allow_result is None or
        allow_result(result["source_ref"],result["source_rights_ref"],"result_evaluation") is not True):
        raise ModelInputError("result label source not independently admitted")
    return result_order


def _gradient(x_by_number,finish,w):
    numbers=sorted(x_by_number)
    grad=[0.0]*len(w)
    loss=0.0
    for position in finish:
        logits=[_dot(w,x_by_number[n]) for n in numbers]
        probs=_softmax(logits)
        k=numbers.index(position)
        loss-=math.log(max(probs[k],1e-300))
        for j in range(len(w)):
            mean=math.fsum(prob*x_by_number[n][j] for n,prob in zip(numbers,probs))
            grad[j]+=x_by_number[position][j]-mean
        numbers.pop(k)
    return grad,loss


def _evaluate(records,w,sport):
    hits=0;losses=[]
    for snap,label in records:
        x=_vectors(snap,sport)
        u=_all_triples(x,w)
        hits+=int(label in [v["combination"] for v in u[:8]])
        losses.append(_gradient(x,label,w)[1])
    return {"n":len(records),"hit8":hits/len(records) if records else None,
            "hits":hits,"mean_log_loss":math.fsum(losses)/len(losses) if losses else None}


def fit_chronological(rows,*,sport,train_end_at,validation_end_at,test_end_at,
                      allow_source=None,allow_result=None,epochs=48,
                      learning_rate=.025,l2=.005):
    if sport not in SPORT_REQUIRED:
        raise ModelInputError("unknown sport")
    train_end=moment(train_end_at);valid_end=moment(validation_end_at);test_end=moment(test_end_at)
    if not train_end<valid_end<test_end:
        raise ModelInputError("chronological evaluation windows overlap")
    if type(epochs) is not int or not 1<=epochs<=500:
        raise ModelInputError("invalid epoch count")
    lr=_number(learning_rate,1e-5,.1,"learning_rate")
    regularization=_number(l2,0,.1,"l2")
    if not isinstance(rows,list) or len(rows)>10000:
        raise ModelInputError("labeled dataset size invalid")
    seen=set();train=[];valid=[];test=[];scope=None
    for item in rows:
        if not isinstance(item,dict) or set(item)!={"snapshot","result"}:
            raise ModelInputError("feature snapshot/label isolation required")
        snap=item["snapshot"]
        checked=validate(snap,allow_source=allow_source)
        race=snap["race"]
        if race["sport"]!=sport:
            raise ModelInputError("mixed sport models not admitted")
        if scope is None:scope=snap["scope"]
        if scope!=snap["scope"]:
            raise ModelInputError("cannot mix real and synthetic source scopes")
        key=race["race_id"]
        if key in seen:raise ModelInputError("duplicate racing identity in training dataset")
        seen.add(key)
        cutoff=moment(race["sales_cutoff_at"])
        cohort=train if cutoff<=train_end else valid if cutoff<=valid_end else test if cutoff<=test_end else None
        if cohort is None:continue
        cap=train_end if cohort is train else valid_end if cohort is valid else test_end
        label=_label(item["result"],snap,scope=scope,allow_result=allow_result,window_end=cap)
        cohort.append((snap,label))
    if len(train)<6 or len(valid)<2 or len(test)<2:
        raise ModelInputError("at least six train, two validation, two test races required")
    schema=vector_schema(sport)
    weights=[0.0]*len(schema)
    # TRAIN ONLY: validation and test labels do not enter the gradient.
    # Deterministic order of race identity makes fitting reproducible.
    train.sort(key=lambda row:row[0]["race"]["race_id"])
    for _ in range(epochs):
        for snap,finish in train:
            grad,_loss=_gradient(_vectors(snap,sport),finish,weights)
            weights=[max(-8,min(8,w+lr*(g/3-regularization*w)))
                     for w,g in zip(weights,grad)]
    # Measured numbers below are research diagnostics; not official Hit@8.
    validation=_evaluate(valid,weights,sport)
    heldout=_evaluate(test,weights,sport)
    model={
        "model_id":LEARNED_ID,"model_version":"0.1-research-trained",
        "sport":sport,"vector_version":VECTOR_VERSION,
        "vector_schema":list(schema),
        "trained_until":train_end_at,"validation_end":validation_end_at,
        "test_end":test_end_at,"trained_scope":scope,
        "trained_examples":len(train),
        "train_example_ids":[s["race"]["race_id"] for s,_ in train],
        "weights":weights,"epochs":epochs,"learning_rate":lr,"l2":regularization,
        "trained_on_licensed_real_data":False if scope==SYNTHETIC else "REQUIRES_EXTERNAL_AUDIT",
        "calibrated":False,"official_model_approved":False,
        "validation_diagnostics":validation,"holdout_diagnostics":heldout,
        "prediction_eligible_without_external_receipt":False,
        "data_sources_independently_attested":False
    }
    model["model_sha256"]=digest(model)
    return model
