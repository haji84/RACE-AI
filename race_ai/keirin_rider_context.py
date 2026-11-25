"""Evaluate additional rider-position paths with the existing evidence A/B."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from itertools import permutations

from . import keirin_nationwide_auto_generator as core


METHOD = 'forward-phase-rider-position-context-20261123-v2'
PHASE_LABELS = {'FINAL_HOME': '最終ホーム', 'FINAL_BACK': '最終バック'}


def _self_propelled(profile):
    counts = profile['observed']
    return (profile['style'] in {'NIGE', 'MAKURI', 'ALLROUND'} or profile['comment_attack_intent']
            or any((counts[key] or 0) > 0 for key in ('nige', 'makuri')))


def _attack_hypotheses(profile):
    counts = profile['observed']
    observed = [(phase, key) for phase, key in (('FINAL_HOME','H'), ('FINAL_BACK','B'))
                if (counts[key] or 0) > 0]
    # H and B count leading at a checkpoint. Each resulting move is a hypothesis.
    return observed or [('FINAL_BACK', None)]


def _position_evidence(profiles, groups):
    positions = {car: (group, index) for group in groups or () for index, car in enumerate(group)}
    evidence = {}
    for car, profile in profiles.items():
        group, index = positions.get(car, (None, None))
        role = ('UNAVAILABLE' if group is None else 'SOLO' if len(group) == 1 else
                'LEADER' if index == 0 else 'FOLLOWER' if index == 1 else 'TAIL')
        evidence[car] = dict(line_role=role, line_position=index+1 if index is not None else None,
                             lead_counts={key:profile['observed'][key] for key in ('S','H','B')},
                             self_propelled=_self_propelled(profile))
    return evidence


def _phase_path(groups, profiles, line, opponent, phase, basis):
    leader, rider = line[:2]
    prefix = core._scenario_prefix(groups, profiles, leader, None, 'HOLD')[:2]
    order = prefix[-1]['projected_order']
    if opponent:
        opposite_leader, opposite_follower = opponent[:2]
        order = core._arrange([leader, opposite_leader, rider, opposite_follower], order)
        prefix[-1] = core._evidence_phase('BELL', order,
            f'{leader}番と{opposite_leader}番が踏み合い、両ラインの番手が近い位置で追走する条件。',
            ['LINES_CONTEST_EARLY_PACE'])

    timing = (f'掲載{basis}回数は{profiles[rider]["observed"][basis]:g}。{PHASE_LABELS[phase]}で前に出る仮説。'
              if basis else f'自力の根拠から{PHASE_LABELS[phase]}で動く条件を置く。仕掛け時点の実測は未確認。')
    for checkpoint in PHASE_LABELS:
        events = []
        if checkpoint == phase:
            for _ in range(order.index(rider)):
                order, event = core._adjacent_pass(order, rider, [timing, core._profile_facts(profiles[rider])])
                events.append(event)
            explanation = f'番手の{rider}番が自力で前に出る分岐。{timing}'
            actions = ['FOLLOWER_SELF_PROPELLED_MOVE', f'CAR_{rider}']
        else:
            explanation = f'{order[0]}番を先頭に直前の前後関係を保つ条件。'
            actions = ['MAINTAINS_PRIOR_POSITION']
        step = core._evidence_phase(checkpoint, order, explanation, actions)
        step['local_transitions'] = events
        prefix.append(step)

    events = []
    if opponent:
        fading = {leader, opponent[0]}
        near = [opponent[1]]
        if len(opponent) > 2 and profiles[opponent[2]]['explicit_sashi']:
            near.append(opponent[2])
        for car in near:
            while order.index(car) > 1 and order[order.index(car)-1] in fading:
                order, event = core._adjacent_pass(order, car,
                    [f'踏み合った先頭選手が減速し、近い位置から{car}番が直前を交わす条件。'])
                events.append(event)
    corner = core._evidence_phase('FOURTH_CORNER', order,
        '両先頭の減速に合わせ、後続が前へ入る条件。' if opponent else '番手が前に出た順序で4角へ進む条件。',
        ['CONTESTED_LEADERS_FADE'] if opponent else ['FORWARD_CORNER_POSITION'])
    corner['local_transitions'] = events
    return prefix + [corner]


def _supported_paths(profiles, groups, line, opponent, phase, basis):
    leader, rider = line[:2]
    rival = opponent[0] if opponent else None
    kind = 'CONTESTED_FOLLOWER_ATTACK' if rival else 'FOLLOWER_SELF_ATTACK'
    timing_group = f'{kind}_{leader}_{rider}_{rival or 0}'
    branch = f'{timing_group}_{phase}'
    prefix = _phase_path(groups, profiles, line, opponent, phase, basis)
    support = core._counter_branch_support(profiles[rider])
    if rival:
        support *= min(core._lead_branch_support(profiles[leader]),
                       core._lead_branch_support(profiles[rival]))
    paths = core._local_finish_paths(prefix, profiles, groups, rider, rival, kind)
    pairs = {}
    for order, events, fit in paths:
        if rival and any(event['overtaker'] in (leader,rival) for event in events):
            continue
        pairs.setdefault(tuple(order[:2]), {})[order[2]] = (order, events, fit)
    for (first, second), thirds in pairs.items():
        base = max(.001, profiles[first]['head_strength']) ** 2 * max(.001, profiles[second]['second_strength']) ** 1.3
        pair_a = base * support ** .5
        pair_b = base * support * max(path[2] for path in thirds.values())
        third_weights = {car:max(.001, profiles[car]['third_strength']) ** .8 for car in thirds}
        total = sum(third_weights.values())
        for car, (order, events, _) in thirds.items():
            fraction = third_weights[car] / total
            ticket = order[:3]
            goal = core._evidence_phase('GOAL', order,
                '4角の位置と隣接した選手の攻防から導く条件付き着順。', ['LOCAL_FINISH_TRANSITIONS'])
            yield dict(
                scenario_id=branch+'_'+'-'.join(map(str,ticket)), tactical_branch_id=branch,
                branch_kind=kind, attacking_car=rider, challenger_car=rival, faded_car=leader if rival else None,
                attack_phase=phase, attack_phase_basis=basis, timing_group=timing_group,
                projected_3ren_tan=ticket, six_phases=prefix+[goal], finish_transitions=events,
                rationale=[prefix[core.PHASES.index(phase)]['explanation'], prefix[-1]['explanation']],
                branch_support=support, pair_support_A=pair_a, pair_support_B=pair_b,
                conditional_third_support=fraction, support_A=pair_a*fraction, support_B=pair_b*fraction,
                known_line_hypothesis=True)


def _multi_stage_path(groups, profiles, lead, responses, late_finish):
    initiative = lead[0]
    phases = core._scenario_prefix(groups, profiles, initiative, None, 'HOLD')[:4]
    order = phases[-1]['projected_order']
    corner_order = order
    moves = []
    for index, group in enumerate(responses):
        actor = group[0]
        countered = order[0]
        window = ('FOURTH_CORNER_TO_GOAL' if late_finish and index == len(responses) - 1
                  else 'FINAL_BACK_TO_FOURTH_CORNER')
        order = core._arrange(group, order)
        moves.append(dict(actor_car=actor, countered_car=countered, window=window,
                          conditional_followers=group[1:],
                          condition=f'{actor}番が{countered}番を外から交わし、掲載ラインが追走する条件。',
                          evidence=core._profile_facts(profiles[actor])))
        if window == 'FINAL_BACK_TO_FOURTH_CORNER':
            corner_order = order
    phases.append(core._evidence_phase('FOURTH_CORNER', corner_order,
        '最終バック後から4角までに、想定した仕掛けが順に前へ出る分岐。',
        ['CONDITIONAL_MULTI_STAGE_RESPONSE']))
    phases.append(core._evidence_phase('GOAL', order,
        '想定した捲りの後、さらに位置の入れ替わりなくゴールする分岐。',
        ['CONDITIONAL_FINISH_ORDER']))
    route = '-'.join(str(car) for car in [initiative, *(move['actor_car'] for move in moves)])
    timing = 'LATE' if late_finish else 'BY_CORNER'
    return dict(scenario_id=f'MAKURI_RESPONSE_{route}_{timing}', initiative_car=initiative,
                moves=moves, six_phases=phases, probability=None,
                probability_status='NO_INDEPENDENT_CALIBRATION')


def multi_stage_makuri_hypotheses(snapshot):
    """Generate up to three successive counters on distinct pre-race lines.

    The order and followers describe one conditional path. The evidence does
    not identify when moves will occur or how likely the paths are. The
    caller binds the input to verified sources acquired before the cutoff.
    """
    profiles, _ = core._evidence_profiles(snapshot)
    groups = core._evidence_line_groups(snapshot, profiles)
    core.need(all(type(car) is int for group in groups or () for car in group),
              'LINE_GROUPS_NOT_AN_EXACT_STARTER_PARTITION')
    eligible = sorted((group for group in groups or () if _self_propelled(profiles[group[0]])),
                      key=lambda group: (-profiles[group[0]]['head_strength'], group[0]))[:4]
    paths = []
    for lead in eligible:
        other_lines = [group for group in eligible if group != lead]
        for count in range(1, len(eligible)):
            for responses in permutations(other_lines, count):
                paths.append(_multi_stage_path(groups, profiles, lead, responses, False))
                if count > 1:
                    paths.append(_multi_stage_path(groups, profiles, lead, responses, True))
    return paths


def compare(snapshot):
    """Run a separate comparison on the same snapshot using the existing A/B selector."""
    baseline = core.generate_evidence_analysis(snapshot)
    profiles = {row['car']:row for row in baseline['feature_audit']['riders']}
    groups = core._evidence_line_groups(snapshot, profiles)
    additions = []
    for line in groups or ():
        if len(line) < 2 or not _self_propelled(profiles[line[1]]):
            continue
        opponents = [group for group in groups if group != line and len(group) >= 2 and
                     _self_propelled(profiles[group[0]]) and _self_propelled(profiles[line[0]])]
        opponent = max(opponents, key=lambda group: profiles[group[0]]['head_strength'], default=None)
        for phase, basis in _attack_hypotheses(profiles[line[1]]):
            additions.extend(_supported_paths(profiles, groups, line, None, phase, basis))
            if opponent:
                additions.extend(_supported_paths(profiles, groups, line, opponent, phase, basis))

    candidate = dict(method_id=METHOD, position_evidence=_position_evidence(profiles,groups),
                     new_scenario_count=len(additions))
    def timing_key(scenario):
        return scenario.get('timing_group',scenario['tactical_branch_id']), tuple(scenario['projected_3ren_tan'])

    timing_counts = Counter(timing_key(scenario) for scenario in additions)
    for arm in ('A','B'):
        prediction = deepcopy(baseline[arm])
        if additions:
            scenarios = prediction['six_phase_scenarios'] + additions
            prediction.update(core.select_scenario_markets(scenarios, arm=arm))
            # H and B alternatives share the support of the same terminal path.
            weights = [scenario[f'support_{arm}'] / timing_counts.get(timing_key(scenario),1)
                       for scenario in scenarios]
            strength = sum(weights)
            prediction['six_phase_scenarios'] = [dict(scenario, relative_research_weight=weight/strength)
                                                 for scenario,weight in zip(scenarios,weights)]
            prediction['method_mode'] = METHOD
        candidate[arm] = prediction
    return {'baseline':baseline, 'candidate':candidate}
