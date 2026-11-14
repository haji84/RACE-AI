"""One research profile, two explicit periods; no prediction feature writes."""
from .boat_history_store import instant
from .teiai_history import need


def assemble_profile(history_store,racer_database,racer_id,*,as_of,allow_source):
    recent=history_store.racer_profile(racer_id,as_of)
    term=racer_database.lookup(racer_id,as_of=as_of,allow_source=allow_source)
    need(term is None or term['racer_id']==recent['racer_id']==racer_id,'PROFILE_RACER_IDENTITY_MISMATCH')
    proof=None
    if term is not None:
        sid=racer_database._latest_sources('TERM',as_of)[term['term']]
        url,sha,captured=racer_database.db.execute('SELECT url,sha,captured_at FROM sources WHERE id=?',(sid,)).fetchone()
        proof=dict(source_url=url,source_sha256=sha,captured_at=captured,record_sha256=term['record_sha256'])
    return dict(schema='RACE_AI_BOAT_RACER_RESEARCH_PROFILE_V1',racer_id=racer_id,
        as_of=instant(as_of).isoformat(),official_term=term,official_term_source=proof,recent_history=recent,
        period_policy='TERM_RECORDED_IDENTITY_AND_STATS_SEPARATE_FROM_DATED_PROGRAM_AND_RECENT_STARTS',
        all_career_history_complete=False,current_active_registry_complete=False,
        features_applied_to_predictions=False,causal_tactical_labels_verified=False,motor_epoch_verified=False)
