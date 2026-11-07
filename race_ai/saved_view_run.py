"""Identify the workflow's explicitly non-collecting push mode."""
PREFIX='saved-view:'

def display_only_run(run):
    # Both fields are GitHub-authenticated run metadata. The workflow uses the
    # same head-message predicate to exclude its official collector job.
    return (run.get('event')=='push' and isinstance(run.get('display_title'),str)
            and run['display_title'].casefold().startswith(PREFIX)
            and isinstance(run.get('head_commit'),dict)
            and isinstance(run['head_commit'].get('message'),str)
            and run['head_commit']['message'].casefold().startswith(PREFIX))
