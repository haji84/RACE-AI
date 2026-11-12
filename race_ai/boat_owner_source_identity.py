"""Strictly distinguish old BOAT source issuance from approved production owner runs.

This is only provenance admission. The legacy original/PDCA engines, published
models, source request ceilings and AES codec are unchanged. Never treat a PR
test or a viewer push as an original live P0/P1 issuance.
"""
WORKFLOW_ID = 405276784
LEGACY_BRANCH = "feat/four-sport-forecast-audit-view-20261022"
OWNER_BRANCH = "production/boat-p0-p1-20261111"
REPO_ID = 1416489937
REPO = "haji84/RACE-AI"


def owner_run_origin(branch, event=None, *, allow_missing_legacy_event=False):
    """Return true only for the original workflow and a permitted source event.

    With event omitted, this validates only an already HMAC-bound catalog's
    historical branch, not an unsigned live run response.
    """
    if branch == LEGACY_BRANCH:
        return event in ("push", "workflow_dispatch") or (
            event is None and allow_missing_legacy_event)
    return branch == OWNER_BRANCH and event == "workflow_dispatch"


def archived_owner_branch(branch):
    """Catalog branch identity only; original run event is separately checked."""
    return branch in (LEGACY_BRANCH, OWNER_BRANCH)


def authenticated_live_owner_run(run):
    if type(run) is not dict or run.get("workflow_id") != WORKFLOW_ID:
        return False
    if not owner_run_origin(run.get("head_branch"), run.get("event")):
        return False
    return all(type(run.get(name)) is dict and
               type(run[name].get("id")) is int and
               run[name]["id"] == REPO_ID and
               run[name].get("full_name") == REPO
               for name in ("repository", "head_repository"))
