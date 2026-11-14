"""Pure first-receipt merge and append-only result projection."""
from .frozen_day_cycle import need,ts

def first_receipt_rows(rows):
    """Keep the earliest verified original per race/phase/model, retain exclusions.

    Call only after read_p0/read_p1 authenticated every archive and cutoff.
    Repeated later snapshots never replace the first forecast or raise the
    apparent number of forecasted races. An inconsistent identity is an error.
    """
    import copy
    ordered=sorted(rows,key=lambda r:(ts(r['server_saved_at']),r['artifact_id'],r['race_id'],r['stage'],r['model_id']))
    first={};excluded=[]
    for source in ordered:
        row=copy.deepcopy(source)
        key=(row['race_id'],row['stage'],row['model_id'])
        old=first.get(key)
        if old is None:
            first[key]=row;continue
        need(ts(old['cutoff_at'])==ts(row['cutoff_at']) and old['roster']==row['roster'],
             'conflicting identity/cutoff for one forecast key')
        if row['artifact_id']==old['artifact_id']:
            need(row==old,'one authenticated receipt has conflicting content')
            continue
        excluded.append(dict(race_id=row['race_id'],stage=row['stage'],model_id=row['model_id'],
            artifact_id=row['artifact_id'],first_artifact_id=old['artifact_id'],
            state='REPEAT_RETAINED_NOT_SCORED',model_sha256=row['model_sha256']))
    return list(first.values()),excluded


def latest_result_observations(observations):
    """Preserve all distinct captures, project newest per race without reranking."""
    import copy
    seen={};latest={}
    for source in sorted(observations,key=lambda r:(ts(r['captured_at']),r['race_id'])):
        row=copy.deepcopy(source);key=(row['race_id'],row['captured_at'])
        if key in seen:
            need(seen[key]==row,'same result capture has conflicting body');continue
        seen[key]=row;latest[row['race_id']]=row
    return list(latest.values()),list(seen.values())
