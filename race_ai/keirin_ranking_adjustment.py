"""Research-only finish-order adjustment for the existing keirin A/B paths."""
from collections import defaultdict
from math import exp, fsum, isfinite

from . import keirin_nationwide_auto_generator as core

NUMERIC_FIELDS = ('relative_points', 'win_rate', 'top2_rate', 'top3_rate',
                  'second_only_rate', 'third_only_rate')
MARK_FIELDS = ('mark_first', 'mark_second', 'mark_third', 'mark_other', 'mark_known')
STYLE_FIELDS = ('front_style', 'flexible_style', 'follower_style')
FEATURES = NUMERIC_FIELDS + tuple(
    name.removesuffix('_rate')+'_known' if name.endswith('_rate') else name+'_known'
    for name in NUMERIC_FIELDS
) + MARK_FIELDS + STYLE_FIELDS


def _difference(high, low):
    return high-low if high is not None and low is not None and high >= low else None


def feature_vectors(profiles):
    """Encode relative observed values and preserve which statistics were present."""
    points = [profile['observed']['competition_points'] for profile in profiles.values()
              if profile['observed']['competition_points'] is not None]
    highest = max(points)
    scale = max(10, highest-min(points))
    rows = {}
    for car, profile in profiles.items():
        row = profile['observed']
        p = row['competition_points']
        win, top2, top3 = (row[key] for key in ('win_rate','top2_rate','top3_rate'))
        second, third = _difference(top2,win), _difference(top3,top2)
        relative = (p-highest)/scale if p is not None else None
        values = {'relative_points': relative}
        for key,value in zip(NUMERIC_FIELDS[1:],(win,top2,top3,second,third)):
            values[key] = value/100 if value is not None else None
        for key in NUMERIC_FIELDS:
            values[key.removesuffix('_rate')+'_known'] = float(values[key] is not None)
        mark = profile['mark_index']
        size = len(profiles)
        rank = round(size+1-size*mark) if mark is not None and mark>0 else None
        values.update(mark_first=float(rank==1), mark_second=float(rank==2),
                      mark_third=float(rank==3), mark_other=float(rank is not None and rank>=4),
                      mark_known=float(mark is not None),
                      front_style=float(profile['style']=='NIGE'),
                      flexible_style=float(profile['style'] in ('ALLROUND','MAKURI')),
                      follower_style=float(profile['style'] in ('MARK','SASHI')))
        rows[car] = values
    for field in NUMERIC_FIELDS:
        observed = [row[field] for row in rows.values() if row[field] is not None]
        center = fsum(observed)/len(observed) if observed else 0.0
        for row in rows.values():
            row[field] = row[field]-center if row[field] is not None else 0.0
    return rows


def finish_weights(vectors, coefficients):
    core.need(type(coefficients) is list and len(coefficients)==3 and all(
        type(row) is dict and set(row)<=set(FEATURES) and all(
            type(value) in (float,int) and isfinite(value) and abs(value)<=12
            for value in row.values()) for row in coefficients), 'RESEARCH_FINISH_WEIGHTS_INVALID')
    output = []
    for ordered in coefficients:
        logits = {car: fsum(features[name]*value for name,value in sorted(ordered.items()))
                  for car,features in vectors.items()}
        peak = max(logits.values())
        output.append({car: exp(score-peak) for car,score in logits.items()})
    return output


def ability_pair(profiles, head, second):
    return (max(.001,profiles[head]['head_strength'])**2
            * max(.001,profiles[second]['second_strength'])**1.3)


def adjusted_pair(profiles, weights, blend, head, second):
    first, following, _ = weights
    second_total = fsum(value for car,value in following.items() if car!=head)
    learned = first[head]/fsum(first.values()) * following[second]/second_total
    return ability_pair(profiles,head,second)**(1-blend) * learned**blend


def third_weight(profile, learned, blend):
    return max(.001,profile['third_strength'])**(.8*(1-blend)) * learned**blend


def adjust(snapshot, prediction, arm, coefficients, blend, *, profiles=None):
    """Reorder one arm's evidenced candidates without modifying its phase paths."""
    core.need(type(blend) in (float,int) and 0<=blend<=1 and arm in ('A','B'),
              'RESEARCH_FINISH_BLEND_INVALID')
    if not blend or not prediction['six_phase_scenarios']:
        return prediction
    if profiles is None:
        profiles = core._evidence_profiles(snapshot)[0]
    weights = finish_weights(feature_vectors(profiles),coefficients)
    paths = prediction['six_phase_scenarios']
    branches = defaultdict(set)
    for path in paths:
        head, second, third = path['projected_3ren_tan']
        branches[(path['tactical_branch_id'],head,second)].add(third)
    thirds = {car: third_weight(profile,weights[2][car],blend) for car,profile in profiles.items()}
    denominators = {branch: fsum(thirds[car] for car in sorted(reachable))
                    for branch,reachable in branches.items()}
    ratios = {(head,second): adjusted_pair(profiles,weights,blend,head,second)/ability_pair(profiles,head,second)
              for _,head,second in branches}
    pair_key, support_key = 'pair_support_'+arm, 'support_'+arm
    adjusted, relative = [], []
    for path in paths:
        head, second, third = path['projected_3ren_tan']
        pair = path[pair_key]*ratios[head,second]
        fraction = thirds[third]/denominators[path['tactical_branch_id'],head,second]
        support = pair*fraction
        adjusted.append({**path,pair_key:pair,support_key:support,'conditional_third_support':fraction})
        relative.append(path.get('relative_research_weight',path[support_key])*support/path[support_key])
    indistinguishable = prediction['selection_context']['indistinguishable_solo_field']
    market = core.select_scenario_markets(adjusted,arm=arm,indistinguishable_field=indistinguishable)
    total = fsum(relative)
    paths = [dict(path,relative_research_weight=mass/total) for path,mass in zip(adjusted,relative)]
    return {**prediction,**market,'six_phase_scenarios':paths,
            'research_finish_rank_adjustment':{'blend':blend,'paths_preserved':True}}
