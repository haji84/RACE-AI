"""Adjudicate a bounded BOAT result refresh without inventing a new final.

Only called AFTER the authenticated encrypted state, immutable P0 inventory,
source GET cap and original dates have been verified. A source fetch that saved
observations but changed no race is a truthful HOLD, not a failed save and
not permission to rerun the provider collector.
"""


def _int(value):
    return type(value) is int and value >= 0


def decision(*, before_final, after_final, changed_races, provider_gets, get_cap):
    if (not all(_int(n) for n in (before_final, after_final, changed_races,
                                 provider_gets, get_cap))
            or not 0 < provider_gets <= get_cap):
        raise ValueError("BOAT_FRESH_POSTFLIGHT_UNVERIFIED_COUNTS")
    if after_final < before_final:
        raise ValueError("BOAT_FRESH_POSTFLIGHT_FINAL_REGRESSION")
    if after_final == before_final:
        return "BOAT_NO_NEW_FORMAL_FINAL_HOLD"
    if changed_races == 0:
        # Another actor might have advanced the view. Our source refresh
        # cannot claim its result or trigger further model/site work.
        raise ValueError("BOAT_FRESH_POSTFLIGHT_UNATTRIBUTED_FINAL_ADVANCE")
    return "FRESH_OFFICIAL_FINAL_INCREASE_VERIFIED"
