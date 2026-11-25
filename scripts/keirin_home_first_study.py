"""Research-only ordering of the first four published trifectas.

Offsets were estimated from 5,392 historical fields with verified registered
home riders through 2026-05-23, with a penalty of .005 on squared offsets.
Use the physical velodrome's prefecture (e.g. its Kdreams information page)
and registered prefectures from the same pre-deadline programme. An unknown
or relocated venue should be supplied as None. Home is not residence.
"""
from collections.abc import Mapping
from math import exp, isfinite
from numbers import Integral, Real

from scripts.keirin_rider_profile_identity import is_registration, prefecture_key

# Columns: visitor, home without local teammate, home leader with another
# local, home follower with another local, visitor sharing a local's line.
FINISH_OFFSETS = (
    (0., 0.4360668891332676, -0.10186301136541641, 0.6208645041847749, 0.05737971598259234),
    (0., 0.2735618754376244, 0.06176621919734048, 0.4426010834032415, 0.1523383914181469),
    (0., 0.12562132939722825, 0.0533863981071006, 0.20161184125154982, 0.042310142554272824),
)
PREFECTURES = frozenset('北海道 青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 東京 神奈川 新潟 富山 石川 福井 山梨 長野 岐阜 静岡 愛知 三重 滋賀 京都 大阪 兵庫 奈良 和歌山 鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄'.split())


def prefecture_name(value):
    if not isinstance(value, str):
        return None
    name = prefecture_key(value)
    return name if name in PREFECTURES or name == '外国' else None


def home_roles(starters, programme, venue_prefecture, lines, *, individual=False):
    """Bind programme {car: (registration, prefecture)} to the original starters."""
    venue = prefecture_name(venue_prefecture)
    if (venue not in PREFECTURES or not isinstance(starters, Mapping) or not starters
            or not isinstance(programme, Mapping) or set(starters) != set(programme)):
        return {}
    local = set()
    registrations = set()
    for car, registration in starters.items():
        entry = programme[car]
        if (type(car) is not int or not 1 <= car <= 9 or not isinstance(registration, str)
                or not is_registration(registration) or registration == '000000'
                or registration in registrations or not isinstance(entry, (tuple, list))
                or len(entry) != 2 or entry[0] != registration):
            return {}
        registrations.add(registration)
        pref = prefecture_name(entry[1])
        if pref is None:
            return {}
        if pref == venue:
            local.add(car)
    if not local:
        return {}
    if not lines and individual:
        lines = [[car] for car in starters]
    if (not isinstance(lines, (tuple, list)) or not lines
            or any(not isinstance(group, (tuple, list)) or not group for group in lines)):
        return {}
    field = [car for group in lines for car in group]
    if (any(type(car) is not int for car in field) or len(field) != len(starters)
            or set(field) != set(starters)):
        return {}
    roles = {}
    for group in lines:
        local_count = len(local.intersection(group))
        for pos, car in enumerate(group):
            if car in local:
                roles[car] = 1 if local_count == 1 else (2 if pos == 0 else 3)
            else:
                roles[car] = 4 if local_count else 0
    return roles


def prioritize_first(tickets, probabilities, roles, *, published_points):
    """Return the original ordered tickets with at most one swap inside the first four.

    probabilities maps ordered triples to their pre-race joint model probabilities.
    Only the first four triples are inspected. No outcome labels are accepted.
    """
    ordered = list(tickets)
    if type(published_points) is not int or not 1 <= published_points <= min(8, len(ordered)):
        raise ValueError('Invalid published ticket count.')
    if any(not isinstance(ticket, (tuple, list)) or len(ticket) != 3 or
           any(isinstance(car, bool) or not isinstance(car, Integral) or not 1 <= car <= 9 for car in ticket)
           or len(set(ticket)) != 3 for ticket in ordered):
        raise ValueError('Invalid ordered trifecta or car number.')
    if published_points < 4 or not roles:
        return ordered
    if (not isinstance(roles, Mapping) or not isinstance(probabilities, Mapping)
            or any(isinstance(role, bool) or not isinstance(role, Integral)
                   or not 0 <= role <= 4 for role in roles.values())):
        raise ValueError('Invalid registered home roles or probability map.')
    first_four = [tuple(ticket) for ticket in ordered[:4]]
    if len(set(first_four)) != 4:
        raise ValueError('Expected four distinct ordered trifectas.')
    values = []
    for ticket in first_four:
        if any(car not in roles for car in ticket):
            return ordered
        p = probabilities.get(ticket)
        if isinstance(p, bool) or not isinstance(p, Real) or not isfinite(p) or not 0 <= p <= 1:
            raise ValueError('Missing or invalid baseline probability.')
        offset = sum(FINISH_OFFSETS[pos][roles[car]] for pos, car in enumerate(ticket))
        values.append(p * exp(offset))
    first = max(range(4), key=values.__getitem__)
    ordered[0], ordered[first] = ordered[first], ordered[0]
    return ordered
