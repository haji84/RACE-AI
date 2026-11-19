"""Prepare a private rejection-anchor candidate; never publish or mint a receipt.

The caller supplies the exact pinned proof module and unchanged guard. This
module does not import a proof namespace, read ciphertext, or accept a cached
proof decision. The existing authenticated reader owns receipt provenance.
"""
from copy import deepcopy
import hashlib
import json
from types import ModuleType


SCHEMA = 'RACE_AI_REJECTION_ANCHOR_RESTORATION_V1'
_ACTIVE = 'result_observation_rejections'
_HISTORY = 'saved_result_rejection_reason_variants'
_OBSERVATIONS = 'result_observations'
_PROOF_HOLDS = frozenset((
    'INPUT_OR_CHAIN_INVALID', 'BOUND_EXCEEDED', 'CURRENT_HISTORY_INVALID',
    'ACTIVE_PROOF_CONFLICT', 'ACTIVE_PROOF_MISSING',
))
_EFFECTS = dict(originals_changed=False, observations_reconciled=0,
    source_requests=0, publication_performed=False, forecast_generated=False,
    broader_goals_proven=False)


class RejectionAnchorRestorationCandidate:
    """Opaque, unpublished private data; never an authenticated snapshot."""
    __slots__ = ('_view',)

    def __init__(self):
        raise TypeError('INTERNAL_CANDIDATE_FACTORY_REQUIRED')

    def _copy_view(self):
        return deepcopy(self._view)

    def __repr__(self):
        return 'RejectionAnchorRestorationCandidate()'


def _require(condition):
    if not condition:
        raise ValueError('INPUT_OR_CHAIN_INVALID')


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _summary(status, *, counts=None, current_hash=None, candidate_hash=None, reason=None):
    result = dict(schema=SCHEMA, status=status, counts=counts,
        current_view_sha256=current_hash, candidate_view_sha256=candidate_hash,
        **_EFFECTS)
    if reason is not None:
        result['reason'] = reason
    return result


def _hold(reason):
    safe = reason if type(reason) is str and (
        reason in _PROOF_HOLDS or reason == 'CANDIDATE_GUARD_REJECTED'
    ) else 'INPUT_OR_CHAIN_INVALID'
    return None, _summary('HOLD', reason=safe)


def _validate_rows(view, guard):
    """Run both unchanged guards on every row without accepting their mutation."""
    try:
        before = _wire(view)
        for row in view['records']:
            guard._observations([row], _OBSERVATIONS)
            guard._observations([row], _ACTIVE, rejection=True)
        return _wire(view) == before
    except Exception:
        return False


def build_rejection_anchor_restoration(current, older_chain, *, guard, proof):
    """Return an opaque all-groups candidate and counts, or no candidate.

    Only a freshly recomputed ALL_ORPHAN_ANCHORS_PROVEN decision may supply
    bodies. Cached decisions and authentication flags are never inputs. READY
    describes an unpublished candidate, not writer or CAS authorization.
    """
    try:
        _require(type(proof) is ModuleType)
        decision = proof.match_rejection_anchor_proofs(current, older_chain, guard=guard)
        _require(type(decision) is proof.AnchorProofDecision)
        report = decision.public_summary()
        _require(type(report) is dict)
        status = report.get('status')
        if status == 'HOLD':
            return _hold(report.get('reason'))
        _require(status in ('ALL_ORPHAN_ANCHORS_PROVEN', 'NO_ORPHAN_ANCHORS'))

        # The existing matcher has checked every receipt, cipher/hash binding,
        # contiguous header and ACTIVE authority. Copy only its bound base view.
        original = deepcopy(current._view)
        current_hash = _digest(original)
        _require(current_hash == current._view_sha256)
        # Detach all JSON aliases so unknown fields keep their original body.
        candidate_view = json.loads(_wire(original))
        rows = {row['race_id']: row for row in candidate_view['records']}
        plan = decision._plan
        counts = report.get('counts')
        _require(type(plan) is tuple and type(counts) is dict)
        _require(all(type(counts.get(name)) is int and counts[name] >= 0 for name in (
            'snapshots_checked', 'current_active_rejections', 'retained_history_originals',
            'orphan_groups', 'proved_groups', 'planned_active_originals')))
        _require(counts['snapshots_checked'] == len(older_chain) + 1)

        current_active = sum(len(row.get(_ACTIVE, [])) for row in original['records'])
        history_originals = sum(len(row.get(_HISTORY, [])) for row in original['records'])
        _require(counts['current_active_rejections'] == current_active and
                 counts['retained_history_originals'] == history_originals)
        changed_rows = set()
        if status == 'NO_ORPHAN_ANCHORS':
            _require(plan == () and counts['orphan_groups'] == 0 and
                     counts['proved_groups'] == 0 and counts['planned_active_originals'] == 0)
        else:
            _require(0 < len(plan) == counts['orphan_groups'] ==
                     counts['proved_groups'] == counts['planned_active_originals'])
            for item in plan:
                _require(type(item) is tuple and len(item) == 2)
                race_id, body = item
                _require(type(race_id) is str and race_id in rows and type(body) is dict)
                # No history representative, reason rewrite, clock edit or
                # result verdict is used to manufacture an ACTIVE original.
                target = rows[race_id].get(_ACTIVE, [])
                _require(type(target) is list)
                # Detach the list itself too: a synthetic alias in an unknown
                # field must not change when the ACTIVE field gains an anchor.
                rows[race_id][_ACTIVE] = [*target, deepcopy(body)]
                changed_rows.add(race_id)

        if not _validate_rows(candidate_view, guard):
            return _hold('CANDIDATE_GUARD_REJECTED')

        candidate_active = sum(len(row.get(_ACTIVE, [])) for row in candidate_view['records'])
        _require(candidate_active == current_active + len(plan))
        public_counts = dict(snapshots_checked=counts['snapshots_checked'],
            orphan_groups=len(plan), current_active_rejections=current_active,
            candidate_active_rejections=candidate_active,
            retained_history_originals=history_originals,
            restored_active_originals=len(plan), rows_changed=len(changed_rows))
        if status == 'NO_ORPHAN_ANCHORS':
            return None, _summary('NO_CHANGE', counts=public_counts, current_hash=current_hash)

        candidate = object.__new__(RejectionAnchorRestorationCandidate)
        candidate._view = candidate_view
        return candidate, _summary('READY', counts=public_counts,
            current_hash=current_hash, candidate_hash=_digest(candidate_view))
    except Exception:
        return _hold('INPUT_OR_CHAIN_INVALID')
