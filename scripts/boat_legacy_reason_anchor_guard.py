"""Fail closed before legacy display publication can orphan reason anchors.

The caller supplies the pinned current saved-model guard. This adapter leaves
legacy acquisition, projection, readers and transport unchanged, and creates no
history or replacement ACTIVE evidence.
"""

_SIDES = (
    ('result_observations', 'saved_result_observation_reason_variants', False),
    ('result_observation_rejections', 'saved_result_rejection_reason_variants', True),
)
_REJECTED = 'LEGACY_REASON_ANCHOR_GUARD_REJECTED'
_MARKER_ATTRIBUTE = '_boat_legacy_reason_anchor_guard_installation'
_INSTALL_TOKEN = object()


def _need(condition):
    if not condition:
        raise ValueError(_REJECTED)


def _validated_rows(view, guard):
    _need(type(view) is dict and type(view.get('records')) is list)
    rows = {}
    for row in view['records']:
        _need(type(row) is dict)
        race_id = row.get('race_id')
        _need(type(race_id) is str and bool(race_id) and race_id not in rows)
        sides = {}
        for field, history_field, rejection in _SIDES:
            # The guard merges versions of one race; its capture identity is
            # intentionally local to that race, rather than the whole view.
            guard._observations([row], field, rejection=rejection)
            if history_field in row:
                history = {guard._wire(item) for item in row[history_field]}
                active = {guard._wire(item) for item in row.get(field, [])}
                sides[field] = (history, active & history)
        rows[race_id] = sides
    return rows


def _validate_transition(previous, current, guard):
    before = _validated_rows(previous, guard)
    after = _validated_rows(current, guard)
    for race_id, sides in before.items():
        for field, (history, anchors) in sides.items():
            _need(race_id in after and field in after[race_id])
            new_history, new_anchors = after[race_id][field]
            _need(history <= new_history and anchors <= new_anchors)


def _check_candidate(view, guard):
    try:
        _validated_rows(view, guard)
    except Exception:
        pass
    else:
        return
    # Raise outside the handler so a private guard exception is not retained
    # as this exception's context or exposed through normal chaining.
    raise ValueError(_REJECTED) from None


def _check_transition(previous, current, guard):
    try:
        _validate_transition(previous, current, guard)
    except Exception:
        pass
    else:
        return
    raise ValueError(_REJECTED) from None


def _install_guard(feed, guard):
    original_ensure = getattr(feed, 'ensure_append_only', None)
    original_publish = getattr(feed, 'publish_view', None)
    _need(callable(original_ensure) and callable(original_publish))
    _need(callable(getattr(guard, '_observations', None))
        and callable(getattr(guard, '_wire', None)))
    left = getattr(original_ensure, _MARKER_ATTRIBUTE, None)
    right = getattr(original_publish, _MARKER_ATTRIBUTE, None)
    if left is not None or right is not None:
        _need(left is right and type(left) is tuple and len(left) == 5)
        _need(left[0] is _INSTALL_TOKEN and left[1] is feed and left[2] is guard
            and left[3] is original_ensure and left[4] is original_publish)
        return feed

    def ensure_append_only(previous, current):
        _check_transition(previous, current, guard)
        # Preserve the original result object and original forecast failures.
        return original_ensure(previous, current)

    def publish_view(git, bootstrap, view, *, parent, previous, generation, history=False):
        # A new V5 day has no previous descriptor, so validate at entry as well
        # as at the existing before/after comparison for an older day.
        _check_candidate(view, guard)
        return original_publish(git, bootstrap, view, parent=parent,
            previous=previous, generation=generation, history=history)

    state = (_INSTALL_TOKEN, feed, guard, ensure_append_only, publish_view)
    setattr(ensure_append_only, _MARKER_ATTRIBUTE, state)
    setattr(publish_view, _MARKER_ATTRIBUTE, state)
    ensure_append_only.__wrapped__ = original_ensure
    publish_view.__wrapped__ = original_publish
    feed.ensure_append_only = ensure_append_only
    feed.publish_view = publish_view
    return feed


def install_guard(feed, *, guard):
    """Install only the two display-publication checks, once per feed/guard."""
    try:
        return _install_guard(feed, guard)
    except Exception:
        pass
    raise ValueError(_REJECTED) from None
