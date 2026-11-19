"""Select the existing GitHub-only A/B route without enabling any source."""
import os


def nationwide_ab_selected(environ=None):
    """Match the nationwide workflow's opt-in; source health is separate.

    A failed or stopped selected provider must not silently restart a legacy
    collector or the old four-model producer. Partial opt-in retains the
    pre-existing route. This does not grant source access or change history.
    """
    values = os.environ if environ is None else environ
    return (
        values.get("RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED") == "true"
        and values.get("RACE_AI_AB_PUBLIC_CAPTURE_ENABLED") == "true"
        and values.get("RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED") == "true"
        and values.get("RACE_AI_AB_SOURCE_S3_PREFIX", "") == ""
    )
