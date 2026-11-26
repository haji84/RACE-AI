"""Project already admitted A/B originals onto the matching public shortlist."""

from . import keirin_nationwide_forecast_view as nationwide
from . import keirin_public_forecast_details as details
from . import keirin_public_forecasts as public
from .keirin_nationwide_auto_generator import PHASES, when


def _saved_paths(baseline, tickets):
    paths = sorted(baseline['B']['six_phase_scenarios'],
                   key=lambda path: (-path['relative_research_weight'], path['scenario_id']))
    rows = []
    for ticket in tickets[:details.LIMIT_SCENARIOS]:
        path = next((path for path in paths if path['projected_3ren_tan'] == ticket), None)
        public.need(path is not None, 'DETAIL_FROZEN_SCENARIO_REQUIRED')
        rows.append(dict(ticket=ticket, orders=[step['projected_order'].copy() for step in path['six_phases']]))
    return rows


def _arm(original, name, tickets):
    facts, baseline = original['facts'], original['baseline']
    riders = {rider['car']: rider for rider in facts['riders']}
    top_cues = '、'.join(details._rider_cue(riders[car]) for car in tickets[0])
    reasons = [f'保存時の上位候補 {top_cues}。']
    if name == 'B':
        lines = '／'.join('−'.join(map(str, line)) for line in facts['line_groups'])
        reasons.append(f'保存時の掲載並び {lines} を起点とした6局面の見立てです。')
        scenarios = _saved_paths(baseline, tickets)
    else:
        reasons.append('保存時の印順位と競走得点などを用いた着順候補です。')
        scenarios = [dict(ticket=ticket, orders=[None] * len(PHASES))
                     for ticket in tickets[:details.LIMIT_SCENARIOS]]
    out = dict(tickets=tickets, grade=details.GRADE, reasons=reasons, scenarios=scenarios)
    assessment = original.get('confidence_assessment')
    if assessment is not None and tickets == baseline[name]['ranked_tickets']:
        entry = assessment['evaluations'][name]
        if entry['rank'] > 0:
            out['coherence_grade'] = entry['grade']
    return out


def project(doc, shortlist, *, published_at):
    """Copy details only when both ordered arms and original timing still match."""
    expected = public.project(doc, published_at=published_at)
    day = expected['day']
    public.checked(shortlist)
    public.need(shortlist['day'] == day and when(shortlist['published_at']) <= published_at and
                when(doc['observed_at']) <= published_at,
                'DETAIL_OFFICIAL_SHORTLIST_SCOPE')
    by_race = {row['race_id']: row for row in shortlist['races']}
    matches = {row['race_id']: row for row in expected['races'] if row['status'] == 'saved' and
               by_race.get(row['race_id']) == row}
    rows = []
    for row in doc['races']:
        rid = row['race_id']
        if rid in matches:
            matched = matches[rid]
            rows.append(dict(race_id=rid, saved_at=matched['saved_at'],
                a=_arm(row['original'], 'A', matched['a']), b=_arm(row['original'], 'B', matched['b'])))
    return details.checked(dict(schema=details.SCHEMA, day=day, published_at=expected['published_at'],
                                races=sorted(rows, key=lambda row: row['race_id'])))


def _receipt(state, body, commit, matched):
    return dict(public._candidates_receipt('PUBLIC_OFFICIAL_DETAILS_' + state, body, commit),
                matched_official_races=matched)


def publish(repo, doc, *, published_at, store=None):
    """Merge a verified official projection into the existing day's details."""
    store = store or public.PublicForecastGit(repo)
    day = nationwide._day(doc['day_jst'])
    path = f'details/{day}.json'
    parent = store.head()
    for attempt in range(2):
        public.need(parent is not None, 'DETAIL_OFFICIAL_SHORTLIST_REQUIRED')
        previous = public._previous_candidates(store, parent, path, day, details.checked)
        raw = store.read_previous(parent, f'forecasts/{day}.json')
        public.need(raw is not None, 'DETAIL_OFFICIAL_SHORTLIST_REQUIRED')
        body = project(doc, public._json(raw), published_at=published_at)
        matched = {row['race_id']: row for row in body['races']}
        if not matched:
            return _receipt('NO_ELIGIBLE_RACES', previous or body, parent, 0)
        prior = {row['race_id']: row for row in previous['races']} if previous else {}
        merged = {**prior, **matched}
        if merged == prior:
            return _receipt('CURRENT', previous, parent, len(matched))
        public.need(previous is None or when(previous['published_at']) <= published_at,
                    'DETAIL_PUBLICATION_CLOCK_BACKWARDS')
        body = details.checked(dict(body, races=[merged[rid] for rid in sorted(merged)]))
        commit, raw = public._commit_projection(store, parent, path, body)
        try:
            public._push_projection(store, parent, path, commit, raw)
        except ValueError as error:
            if attempt or str(error) not in ('KEIRIN_NOTE_FEED_CONCURRENT_UPDATE', 'KEIRIN_NOTE_FEED_REMOTE_READBACK'):
                raise
            latest = store.head()
            if latest is None or latest == parent:
                raise
            store.fetch(latest)
            ancestor = commit if str(error) == 'KEIRIN_NOTE_FEED_REMOTE_READBACK' else parent
            store.run(['merge-base', '--is-ancestor', ancestor, latest])
            parent = latest
        else:
            return _receipt('UPDATED', body, commit, len(matched))
