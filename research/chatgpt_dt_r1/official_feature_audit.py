"""Group-only counts and magnitudes for fully replayed official DT-R1 features."""
from collections import Counter
from datetime import date
from math import fsum

import numpy as np

from .abilities import ABILITY_NAMES
from .agari import AGARI_NAMES
from .context import EXTRA_NAMES
from .engine_input_audit import FeatureAudit
from .features import FEATURE_NAMES
from .policy import clock


GROUPS = dict(base_and_history=FEATURE_NAMES, external_context=EXTRA_NAMES,
              agari=AGARI_NAMES, five_abilities=ABILITY_NAMES)
NAMES = tuple(name for group in GROUPS.values() for name in group)
INDEX = {name: i for i, name in enumerate(NAMES)}


def _need(valid):
    if not valid:
        raise ValueError('DT_R1_OFFICIAL_FEATURE_AUDIT_INVALID')


def _conditioned_coverage(row, original):
    """Count older official profile results already authenticated at the forecast clock."""
    if original is None or original.get('condition_state') != 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF':
        return {}
    proof = original['origin_receipts']['condition_origin']
    at = clock(row['context_as_of'])
    if (proof['state'] != 'GITHUB_PRE_CUTOFF_CONDITIONED_ORIGIN_VERIFIED' or
            clock(proof['latest_server_evidence_at']) > at):
        return {}
    evidence = original['supplement']['condition_evidence']
    if clock(evidence['as_of']) > at:
        return {}
    day = date.fromisoformat(row['day'])
    counts = Counter(races=1)
    for rider in evidence['riders']:
        ages = [(day - date.fromisoformat(result['race_date'])).days for result in rider['results']
                if result['status'] == 'FINISHED' and clock(result['published_at']) <= at]
        recent = sum(8 <= age <= 30 for age in ages)
        older = sum(age > 30 for age in ages)
        counts['rider_rows_with_finishes_days_8_to_30'] += int(recent > 0)
        counts['finish_exposures_days_8_to_30'] += recent
        counts['finish_exposures_older_than_30_days'] += older
    return counts


class OfficialFeatureAudit:
    """Call add only after the owner replayer has matched the full frozen row."""

    def __init__(self, trained):
        _need(trained.feature_names == NAMES and len(NAMES) == len(set(NAMES)) == 462)
        self._audit = FeatureAudit(trained)
        self._with_history = 0
        self._riders_with_history = 0
        self._history_exposures = 0
        self._conditioned = Counter(races=0, rider_rows_with_finishes_days_8_to_30=0,
                                    finish_exposures_days_8_to_30=0, finish_exposures_older_than_30_days=0)

    def add(self, row, original=None):
        matrix = np.asarray(row['features'])
        starters = {str(r['car']) for r in row['riders']}
        _need(tuple(row['feature_names']) == NAMES and row['feature_status'] == 'READY' and
              row['cohort'] == 'prospective' and
              matrix.shape == (len(starters), len(NAMES)) and 3 <= len(starters) == len(row['riders']) <= 9)
        evidence = row['history_evidence']
        support, riders = evidence['official_support'], evidence['rider_evidence']
        prior = support['history_races']
        _need(type(prior) is int and prior >= 0 and riders.keys() == starters)
        _need(support['status'] == ('INDEPENDENTLY_VERIFIED' if prior else 'MISSING_HISTORY'))
        _need(all(r['official_identity_verified'] is True and type(r['entries']) is int and
                  0 <= r['entries'] <= prior for r in riders.values()))
        self._audit.add(matrix)
        self._with_history += int(bool(prior))
        self._riders_with_history += sum(r['entries'] > 0 for r in riders.values())
        self._history_exposures += prior
        try:
            self._conditioned.update(_conditioned_coverage(row, original))
        except (KeyError, TypeError, ValueError):
            self._conditioned['profile_coverage_holds'] += 1

    def report(self):
        audit = self._audit
        stats = audit.report()['columns'] if audit.races else {}
        output = {}
        for group, columns in dict(all=NAMES, **GROUPS).items():
            varying = [stats[name] for name in columns if name in stats and stats[name]['races_varying']]
            effects = [row['within_race_top3_logit_rms'] for row in varying
                       if row['within_race_top3_logit_rms'] > 1e-12]
            flagged = [INDEX[name] for name in columns if INDEX[name] in audit.masks]
            output[group] = dict(columns=len(columns), within_race_varying_columns=len(varying),
                within_race_varying_column_exposures=sum(row['races_varying'] for row in varying),
                top3_linear_contributing_columns=len(effects), top3_logit_rms_sum=round(fsum(effects), 9),
                columns_with_explicit_missing_flag=len(flagged),
                explicit_missing_value_count=sum(audit.marked_missing[i] for i in flagged))
        return dict(schema='DT_R1_OFFICIAL_FEATURE_AUDIT_V1', audited_races=audit.races,
                    rider_rows=audit.observations, races_with_official_history=self._with_history,
                    rider_rows_with_official_history=self._riders_with_history,
                    official_history_race_exposures=self._history_exposures,
                    conditioned_profile_history_availability=dict(self._conditioned), groups=output)
