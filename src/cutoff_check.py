from datetime import datetime

def verify_cutoff(created_at, cutoff_at):
    created = datetime.fromisoformat(created_at)
    cutoff = datetime.fromisoformat(cutoff_at)
    return created.tzinfo is not None and cutoff.tzinfo is not None and created < cutoff
