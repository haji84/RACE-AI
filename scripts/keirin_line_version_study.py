"""Compare two source-verified racecard observations before their shared cutoff."""

from scripts import keirin_generate_result_unread_analysis as ingest


def lineup(groups, cars):
    if groups is None:
        return None
    if not groups or any(not group for group in groups):
        raise ValueError('An available lineup must contain nonempty lines.')
    starters = [car for group in groups for car in group]
    if len(set(starters)) != len(starters) or set(starters) != cars:
        raise ValueError('The lineup must contain each starter once.')
    return tuple(sorted(tuple(group) for group in groups))


def roster(card):
    rows = card['riders']
    field = {row['number']: ingest.person_key(row['name']) for row in rows}
    if len(field) != len(rows) or not 5 <= len(field) <= 9 or not all(field.values()):
        raise ValueError('The same full field is required in each version.')
    return field


def compare(earlier, later):
    day = earlier['date']
    if day != later['date'] or earlier['race_id'] != later['race_id']:
        raise ValueError('Versions must describe the same race.')
    close = ingest.published_cutoff(day, earlier['deadline_time'])
    captures = [ingest.instant(row['fetched_at']) for row in (earlier, later)]
    if close is None or close != ingest.published_cutoff(day, later['deadline_time']) or not captures[0] < captures[1] < close:
        raise ValueError('Both observations must be ordered before the same cutoff.')
    field = roster(earlier)
    if field != roster(later):
        raise ValueError('The same full field is required in each version.')
    old, new = (lineup(row['lines'], set(field)) for row in (earlier, later))
    if old == new:
        return 'unpublished' if old is None else 'unchanged'
    if old is None:
        return 'newly_listed'
    if new is None:
        return 'no_longer_listed'
    prior = {frozenset(group) for group in old}
    replacement = {frozenset(group) for group in new}
    if prior == replacement:
        return 'within_line_order'
    if all(any(line <= previous for previous in prior) for line in replacement):
        return 'split'
    if all(any(line <= current for current in replacement) for line in prior):
        return 'merge'
    return 'regrouped'
