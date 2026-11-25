"""Bind historic entry identities to public KEIRIN registration records."""

from collections import defaultdict
from unicodedata import normalize

from scripts.keirin_rider_profile_history import is_registration


def name_key(value):
    return ''.join(normalize('NFKC', value or '').split())


def prefecture_key(value):
    value = name_key(value)
    if value == '東京都' or (len(value) >= 3 and value.endswith(('県', '府'))):
        return value[:-1]
    return value


def same_archived_rider(csv_identity, sql_identity):
    csv_name, csv_term, csv_pref = csv_identity
    sql_name, sql_term, sql_pref = sql_identity
    if not csv_name or csv_term is None or csv_term != sql_term:
        return False
    csv_pref, sql_pref = prefecture_key(csv_pref), prefecture_key(sql_pref)
    return ((csv_name, csv_pref) == (sql_name, sql_pref)
            or (len(sql_pref) == 2 and csv_name == sql_name + sql_pref[0] and csv_pref == sql_pref[1:]))


class IdentityIndex:
    def __init__(self, current, earlier):
        self.names = defaultdict(set)
        self.prefectures = defaultdict(set)
        self.cohorts = {}
        for rider in current:
            registration = rider['registration']
            if not is_registration(registration) or registration in self.cohorts:
                raise ValueError('The reference register has an invalid or duplicate registration.')
            self.names[registration].add(name_key(rider['name']))
            self.prefectures[registration].add(prefecture_key(rider['prefecture_or_country']))
            self.cohorts[registration] = rider['cohort']
        for rider in earlier:
            registration = rider['registrationNo']
            aliases = {name_key(item['name']) for item in rider['nameAliases']
                       if 'KEIRIN.JP:JSJ006' in item['sources']}
            if aliases and is_registration(registration):
                self.names[registration].update(aliases)
                self.prefectures[registration].add(prefecture_key(rider['currentPrefecture']))
        self.by_name = defaultdict(set)
        for registration, aliases in self.names.items():
            for alias in filter(None, aliases):
                self.by_name[alias].add(registration)
        self.direct = defaultdict(set)
        self.earlier_cohorts = defaultdict(set)

    def observe_exact_race(self, identity, registration):
        """Admit a cohort and prefecture after an exact race, car and name match."""
        rider, cohort, prefecture = identity
        if rider not in self.names.get(registration, ()) or cohort is None:
            return
        if (registration in self.cohorts and self.cohorts[registration] is not None
                and self.cohorts[registration] != cohort):
            return
        self.direct[rider, cohort].add(registration)
        self.earlier_cohorts[registration].add(cohort)
        if prefecture:
            self.prefectures[registration].add(prefecture_key(prefecture))

    def candidates(self, rider, cohort):
        matches = set(self.direct.get((rider, cohort), ()))
        for registration in self.by_name.get(rider, ()):
            if registration in self.cohorts:
                known = self.cohorts[registration]
                if cohort == known or (known is None and cohort == 999):
                    matches.add(registration)
            elif self.earlier_cohorts[registration] == {cohort}:
                matches.add(registration)
        return matches

    def bind(self, identity, *, from_csv=False):
        rider, cohort, prefecture = identity
        if not rider or cohort is None or not prefecture:
            return None
        canonical = prefecture_key(prefecture)
        possible = {registration for registration in self.candidates(rider, cohort)
                    if canonical in self.prefectures[registration]}
        if from_csv and len(rider) > 1 and len(prefecture) == 1:
            # The archive's spaced prefecture was split with its first character in the name.
            restored = prefecture_key(rider[-1] + prefecture)
            possible.update(registration for registration in self.candidates(rider[:-1], cohort)
                            if restored in self.prefectures[registration])
        return next(iter(possible)) if len(possible) == 1 else None
