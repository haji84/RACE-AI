"""Derive a deadline view from caller-authenticated, retained P1 originals.

The caller still owns artifact authentication. An observation alone never
changes a deadline. This view never rewrites a forecast or its original hash.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import timezone,timedelta
from .actions_contract import digest


def cutoff_views(rows, *, as_of=None):
    from .frozen_day_cycle import check_clock, ts
    grouped=defaultdict(list)
    for row in rows:
        try:
            ts(row['cutoff_at'])
            if as_of is not None and ts(row['server_saved_at'])>as_of:continue
            grouped[row['race_id']].append(row)
        except (ValueError,TypeError,KeyError,AttributeError):continue
    revisions={}; blocked={}
    for rid, items in grouped.items():
        if len({ts(r['cutoff_at']) for r in items})<2:continue
        if any(r.get('roster')!=items[0].get('roster') for r in items):
            blocked[rid]='CUTOFF_REVISION_ROSTER_CONFLICT';continue
        candidates=[]
        for row in items:
            if row['stage']!='P1':continue
            try:
                check_clock(row['as_of'],row['cutoff_at'],row['server_saved_at'])
                stamp=ts(row['cutoff_at'])
                if stamp.astimezone(timezone(timedelta(hours=9))).strftime('%Y%m%d')!=rid[:8]:continue
                candidates.append(row)
            except (ValueError,TypeError,KeyError,AttributeError):continue
        if not candidates:continue
        latest=max(ts(r['server_saved_at']) for r in candidates)
        current=[r for r in candidates if ts(r['server_saved_at'])==latest]
        if len({ts(r['cutoff_at']) for r in current})!=1:
            blocked[rid]='CUTOFF_REVISION_CAPTURE_CONFLICT';continue
        witness=min(current,key=lambda r:(r['artifact_id'],r['model_id']))
        revisions[rid]=dict(effective_cutoff_at=witness['cutoff_at'],
            roster_sha256=digest(witness['roster']),
            artifact_id=witness['artifact_id'],model_sha256=witness['model_sha256'],
            original_json_sha256=witness['original_json_sha256'],
            server_saved_at=witness['server_saved_at'],basis='VERIFIED_PRE_CUTOFF_P1_ORIGINAL')
    return apply_cutoff_evidence(rows,revisions),revisions,blocked


def apply_cutoff_evidence(rows,revisions):
    from .frozen_day_cycle import ts
    output=deepcopy(rows)
    for row in output:
        evidence=revisions.get(row['race_id'])
        if evidence is not None and digest(row.get('roster'))==evidence['roster_sha256'] and ts(row['cutoff_at'])!=ts(evidence['effective_cutoff_at']):
            row['frozen_cutoff_at']=row['cutoff_at']
            row['cutoff_at']=evidence['effective_cutoff_at']
            row['cutoff_revision_evidence']=deepcopy(evidence)
    return output


def retain_frozen_cutoff(verdict, row):
    if 'frozen_cutoff_at' in row:
        verdict['cutoff_at']=row['frozen_cutoff_at']
        verdict['settlement_cutoff_at']=row['cutoff_at']
        verdict.pop('frozen_cutoff_at',None)
    return verdict
