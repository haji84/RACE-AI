"""Ticket-bound public evidence for the scoped, result-unread racecard model."""

from datetime import datetime

from . import keirin_nationwide_auto_generator as model
from . import keirin_nationwide_forecast_view as nationwide
from . import keirin_public_forecast_updates as updates
from . import keirin_public_forecasts as public
from . import keirin_research_stability as stability


SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_FORECAST_DETAILS_V1'
GRADE = '未校正'
LIMIT_SCENARIOS = 2
ARM_FIELDS = {'tickets', 'grade', 'reasons', 'scenarios'}
CASE_FIELDS = {'cars', 'condition'}
STYLES = {'NIGE': '逃', 'MAKURI': '捲', 'SASHI': '差', 'MARK': '追', 'ALLROUND': '両'}


def _display_text(text):
    return (type(text) is str and 1 <= len(text) <= 240 and text == text.strip() and
            not any(char in text for char in ('\n', '\r', '<', '>')))


def _checked_arm(arm, *, conditional=False):
    required = ARM_FIELDS | CASE_FIELDS if conditional else ARM_FIELDS
    public.need(type(arm) is dict and required <= set(arm) <= required | {'coherence_grade'} and
                arm['grade'] == GRADE and
                ('coherence_grade' not in arm or arm['coherence_grade'] in stability.GRADES[1:]), 'DETAIL_ARM')
    tickets = arm['tickets']
    public.need(public._tickets(tickets) or (conditional and tickets == []), 'DETAIL_TICKETS')
    public.need(type(arm['reasons']) is list and 1 <= len(arm['reasons']) <= 4 and
                all(_display_text(text) for text in arm['reasons']), 'DETAIL_REASONS')
    scenarios = arm['scenarios']
    public.need(type(scenarios) is list and len(scenarios) == min(LIMIT_SCENARIOS, len(tickets)), 'DETAIL_SCENARIOS')
    roster = None
    for scenario, ticket in zip(scenarios, tickets):
        public.need(type(scenario) is dict and set(scenario) == {'ticket', 'orders'} and
                    scenario['ticket'] == ticket, 'DETAIL_SCENARIO_TICKET')
        orders = scenario['orders']
        public.need(type(orders) is list and len(orders) == len(model.PHASES), 'DETAIL_PHASES')
        for order in orders:
            if order is None:
                continue
            public.need(type(order) is list and 5 <= len(order) <= 9 and
                        all(type(car) is int and 1 <= car <= 9 for car in order) and
                        len(set(order)) == len(order) and set(ticket) <= set(order), 'DETAIL_PHASE_ORDER')
            roster = set(order) if roster is None else roster
            public.need(set(order) == roster, 'DETAIL_PHASE_ROSTER')
        public.need(orders[-1] is None or orders[-1][:3] == ticket, 'DETAIL_GOAL')


def checked(body):
    public.need(type(body) is dict and set(body) == {'schema', 'day', 'published_at', 'races'} and
                body['schema'] == SCHEMA, 'DETAIL_SCHEMA')
    day = nationwide._day(body['day'])
    published_at = model.when(body['published_at'])
    rows = body['races']
    public.need(type(rows) is list and len(rows) <= nationwide.MAX_RACES, 'DETAIL_ROWS')
    for row in rows:
        required = {'race_id', 'a', 'b'}
        public.need(type(row) is dict and required <= set(row) <= required | {'b_conditions', 'saved_at'} and
                    (row['a'] is not None or row['b'] is not None or 'b_conditions' in row), 'DETAIL_ROW')
        if 'saved_at' in row:
            public.need(row['a'] is not None and row['b'] is not None and 'b_conditions' not in row and
                        model.when(row['saved_at']) <= published_at, 'DETAIL_SAVED_ORIGINAL')
        for arm in ('a', 'b'):
            if row[arm] is not None:
                _checked_arm(row[arm])
        if 'b_conditions' in row:
            cases = row['b_conditions']
            public.need(row['b'] is None and type(cases) is list and len(cases) in (2, 4), 'DETAIL_CONTESTS')
            for case in cases:
                _checked_arm(case, conditional=True)
                public.need(_display_text(case['condition']), 'DETAIL_CONDITION')
            updates._check_contests([{'cars': case['cars'], 'tickets': case['tickets']} for case in cases], set(range(1, 10)))
    nationwide._ids([row['race_id'] for row in rows], day)
    return body


def _assessment(analysis, snapshot, generated_at, assessed_at, selections):
    # Match the existing research assessment's essential-feature contract.
    missing_points = [field for field in analysis['feature_audit']['missing']
                      if field.endswith('.competition_points')]
    assessment_input = dict(analysis, race_id=snapshot['race_id'], generated_at=generated_at,
                            line_warnings=snapshot['line_warnings'], missing_model_features=missing_points,
                            line_status='UNAVAILABLE' if snapshot['line_groups'] is None else 'PUBLISHED_PREDICTION')
    for arm, tickets in selections.items():
        assessment_input[arm] = dict(analysis[arm], ranked_tickets=tickets)
    return stability.assess_research_analysis(assessment_input, assessed_at=assessed_at.isoformat())['evaluations']


def _rider_cue(rider):
    points = rider['competition_points']
    score = f'得点{points:g}' if points is not None else '得点未確認'
    rank = rider['mark_rank']
    mark = '無印' if rank == 'UNMARKED' else f'掲載印{rank}位'
    style = STYLES.get(rider['style'])
    return f'{rider["car"]}番（{score}・{mark}・{style or "脚質未確認"}）'


def _display_arm(analysis, snapshot, arm, tickets, evaluation):
    result = dict(tickets=tickets, grade=GRADE, scenarios=[])
    if not tickets:
        result['reasons'] = ['三連単は見送り。候補を絞る根拠が不足しています。']
        return result
    riders = {rider['car']: rider for rider in snapshot['riders']}
    result['reasons'] = ['上位候補の出走表 ' + '、'.join(_rider_cue(riders[car]) for car in tickets[0]) + '。']
    ranked = sorted(analysis[arm]['six_phase_scenarios'], key=lambda s: (-s['support_' + arm], s['scenario_id']))
    for index, ticket in enumerate(tickets[:LIMIT_SCENARIOS]):
        scenario = next((path for path in ranked if path['projected_3ren_tan'] == ticket), None)
        public.need(scenario is not None and
                    [phase['phase'] for phase in scenario['six_phases']] == list(model.PHASES), 'DETAIL_MATCHED_PATH')
        if scenario['known_line_hypothesis']:
            orders = [phase['projected_order'] for phase in scenario['six_phases']]
            reason = scenario['rationale'][0]
        else:
            # Ability-only GOAL has an arbitrary tail after the selected three.
            orders = [None] * len(model.PHASES)
            reason = '出走表の得点と印を比較。並びが未確定のため各局面の隊列は未評価です。'
        result['scenarios'].append(dict(ticket=ticket, orders=orders))
        if index == 0:
            result['reasons'].append(reason)
    if evaluation['grade'] in stability.GRADES[1:]:
        result['coherence_grade'] = evaluation['grade']
    return result


def project_race(snapshot, scheduled, research, *, assessed_at, update=None, contest_cases=None):
    """Attach scoped explanations only to the same ordered research selections."""
    generated_at = model.when(research['generated_at'])
    public.need(isinstance(assessed_at, datetime) and assessed_at.utcoffset() is not None and
                generated_at <= assessed_at, 'DETAIL_CLOCK')
    projected = public.project_research_race(snapshot, scheduled, generated_at=generated_at)
    public.need(projected['race_id'] == research['race_id'] and
                model.when(projected['cutoff_at']) == model.when(research['cutoff_at']) and
                projected['starter_cars'] == research['starter_cars'], 'DETAIL_RACE_BINDING')
    result = dict(race_id=research['race_id'], a=None, b=None)
    update = update or {}
    if update:
        public.need(update['race_id'] == research['race_id'] and update['starter_cars'] == research['starter_cars'] and
                    model.when(update['cutoff_at']) == model.when(research['cutoff_at']), 'DETAIL_UPDATE_BINDING')
    selections = {arm.upper(): research[arm] for arm in ('a', 'b')
                  if research[arm] and research[arm] == projected[arm] and update.get(arm) is None}
    if selections:
        analysis = model.generate_evidence_analysis(snapshot)
        grades = _assessment(analysis, snapshot, research['generated_at'], assessed_at, selections)
        for arm, tickets in selections.items():
            result[arm.lower()] = _display_arm(analysis, snapshot, arm, tickets, grades[arm + '_3t'])

    overlay = update.get('b') or {}
    if overlay.get('kind') == 'contested_lineup' and contest_cases and not research['b']:
        selected = [dict(cars=case['cars'], tickets=case['tickets']['3t'][:public.LIMIT]) for case in contest_cases]
        if selected == overlay['hypotheses']:
            result['b_conditions'] = []
            for case, published in zip(contest_cases, selected):
                assumed = dict(snapshot, line_groups=case['line_groups'], line_warnings=[])
                analysis = model.generate_evidence_analysis(assumed)
                tickets = published['tickets']
                public.need(analysis['B']['ranked_tickets'][:public.LIMIT] == tickets, 'DETAIL_CONTEST_TICKET_BINDING')
                grade = _assessment(analysis, assumed, overlay['registered_at'], assessed_at, {'B': tickets})['B_3t']
                detail = _display_arm(analysis, assumed, 'B', tickets, grade)
                result['b_conditions'].append(dict(detail, cars=case['cars'], condition=case['condition']))
    return result
