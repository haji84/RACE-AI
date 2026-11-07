"""Bounded parameters of the existing four-sport equations, research only.

These adapters do not fit, relabel a PL surrogate, grant source permission or
claim supervised training. Native default inference remains byte-identical.
"""
from datetime import datetime
import math

from .comprehensive_four_sport_models import (
    MODEL_IDS as FACTOR_IDS, SPORT_REQUIRED, ModelInputError, moment,
)
from .four_sport_matchup_models import MODEL_IDS as MATCHUP_IDS

MODEL_IDS = FACTOR_IDS + MATCHUP_IDS
_COMMON = dict(ability=1.35, recent_form=1.05, start_reliability=.40,
               finishing_power=.75, course_compatibility=.85, stamina=.30,
               tactical_adaptability=.65, consistency=.40)
_SPORT = {
    "boat": dict(motor_form=.95, start_timing=.62, lane_course_fit=.75),
    "keirin": dict(line_coordination=.85, sprint_acceleration=.74,
                   attack_success=.85, bank_fit=.55),
    "autorace": dict(handicap_adjustment=.80, machine_reliability=.85,
                     wet_track_fit=.70),
    "horse": dict(speed_figure=1.10, closing_sectional=.92, jockey_fit=.53,
                  distance_surface_fit=.82),
}


def specs(model_id, sport):
    """Existing coefficient defaults and finite native bounds; no new factors."""
    if type(model_id) is not str or type(sport) is not str or model_id not in MODEL_IDS or sport not in SPORT_REQUIRED:
        raise ModelInputError("existing common model/sport required")
    defaults = {"utility."+k: v for k, v in {**_COMMON, **_SPORT[sport]}.items()}
    if model_id in FACTOR_IDS:
        if sport == "keirin":
            defaults.update({"pair.line_first_second": .12, "pair.line_second_third": .09})
        if model_id == FACTOR_IDS[1]:
            defaults.update({"scenario.front_start": .8, "scenario.closing_power": .9,
                             "scenario.disruption_tactics": .9,
                             "scenario.disruption_start": -.25,
                             "pair.front_follower": .07, "pair.closing_third": .11})
    else:
        defaults.update({"slot.first_start": .42, "slot.first_draw": .18,
                         "slot.later_finish": .27, "slot.later_stamina": .18,
                         "slot.third_stamina": .23, "coupling.third_closer_stamina": .12})
        if sport == "keirin":
            defaults.update({"coupling.line_leader": .48, "coupling.line_second": .17})
        elif sport == "horse":
            defaults["coupling.horse_front_competition"] = -.20
        elif sport == "autorace":
            defaults["coupling.autorace_closer"] = .16
        if model_id == MATCHUP_IDS[1]:
            defaults.update({"trajectory.front_start": .42, "trajectory.chase_finish": .36,
                             "trajectory.disrupted_tactics": .55})
    return {name: (value, -2. if value < 0 else 0., 0. if value < 0 else 4.)
            for name, value in defaults.items()}


def _resolve(model_id, sport, parameters):
    schema = specs(model_id, sport)
    if not isinstance(parameters, dict) or any(type(k) is not str or k not in schema for k in parameters):
        raise ModelInputError("unknown native research parameters")
    resolved = {name: values[0] for name, values in schema.items()}
    for name, value in parameters.items():
        _default, low, high = schema[name]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ModelInputError("invalid bounded native research parameter: "+name)
        resolved[name] = value
    return resolved


def _resolve_model_sets(parameter_sets, sport, model_ids):
    """Shared validation for direct native optional-parameter callers."""
    if parameter_sets is None:
        return {}
    if not isinstance(parameter_sets, dict) or any(type(k) is not str or k not in model_ids for k in parameter_sets):
        raise ModelInputError("native research model parameter roster mismatch")
    return {mid: _resolve(mid, sport, values) for mid, values in parameter_sets.items()}


def _stamp(record, parameters):
    if parameters is not None:
        record.update(parameter_source="OPERATOR_SUPPLIED_RESEARCH_PARAMETERS",
                      research_parameters=dict(parameters))


def predict(model_id, payload, parameters=None, *, at, allow_source=None):
    """Run one existing family on its genuine native snapshot and coefficients."""
    if not isinstance(payload, dict) or not isinstance(payload.get("snapshot"), dict):
        raise ModelInputError("native snapshot payload required")
    snapshot = payload["snapshot"]
    race = snapshot.get("race")
    if not isinstance(race, dict):
        raise ModelInputError("native race required")
    sport = race.get("sport")
    specs(model_id, sport)
    if "sport" in payload and payload["sport"] != sport:
        raise ModelInputError("native payload sport mismatch")
    clock = at if isinstance(at, datetime) else moment(at)
    if clock.utcoffset() is None or not moment(race.get("as_of")) <= clock < moment(race.get("sales_cutoff_at")):
        raise ModelInputError("native inference clock must follow input and precede cutoff")
    sets = None if parameters is None else {model_id: _resolve(model_id, sport, parameters)}
    if model_id in FACTOR_IDS:
        from .comprehensive_four_sport_models import predict as native
    else:
        from .four_sport_matchup_models import predict as native
    return native(snapshot, allow_source=allow_source, research_parameters=sets)[model_id]


def fit_ranker(records, *, sport, now, train_end_at, allow_source=None, allow_result=None):
    """Reuse the existing ranker's train-only API without a new model identity."""
    from .four_sport_learning import fit_training_only
    clock = now if callable(now) else lambda: now
    return fit_training_only(records, sport=sport, train_end_at=train_end_at,
                             now=clock, allow_source=allow_source, allow_result=allow_result)
