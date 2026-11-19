# Verbatim isolated functions from public haji84/RACE-AI.
# Source: race_ai/saved_view_feed.py at 0da3f00b0f5c5115f956658d306ddcb9833ec7af
# Source Git blob: 3295add3abdacb88ee23e38875c6af47e8f33979
# Synthetic dependency bindings are supplied by the contract test; no I/O.

def originals_sha(view):
    need(type(view) is dict and view.get('schema')=='RACE_AI_PRIVATE_CYCLE_VIEW_V1'
         and type(view.get('records')) is list and 0<len(view['records'])<=5000,'FEED_VIEW_REQUIRED')
    records=[{k:v for k,v in r.items() if k not in MUTABLE} for r in view['records']]
    need(len({r['race_id'] for r in records})==len(records),'FEED_DUPLICATE_RACE')
    return digest(records)

def update_view(view,observations,*,synced_at,captures=()):
    """Append observations; latest pending/rejected evidence never falls back."""
    instant(synced_at);pin=originals_sha(view);out=deepcopy(view)
    from datetime import date
    from .official_race_updates import endpoint
    rows={endpoint(date.fromisoformat(r['event_date_jst']),r['race_id'][9:11],int(r['race_id'][-2:]),'raceresult'):r for r in out['records']}
    from .racer_intraday_source import result_url
    rows.update({result_url(r['event_date_jst'],r['race_id'][9:11],int(r['race_id'][-2:])):r for r in out['records'] if r.get('sport')=='boat'})
    parsed=[]
    for raw,receipt in captures:
        need(receipt.get('http_status')==200 and sha(raw)==receipt.get('source_sha256'),'FEED_CAPTURE_HASH')
        row=rows.get(receipt.get('source_url'))
        if row is None:continue
        instant(receipt['captured_at'])
        try:parsed.append(parse_capture(raw,receipt))
        except Exception:
            # Source layouts are isolated per race, just like the native audit.
            # Keep the newer rejection visible rather than reuse an old final.
            parsed.append(dict(race_id=row['race_id'],closed_at=row['cutoff_at'],captured_at=receipt['captured_at'],
                source_sha256=receipt['source_sha256'],source_url=receipt['source_url'],body_identity_verified=False,
                status='UNSUPPORTED',data=None,source_parse_rejected=True))
    raw_ids={digest(o) for o in parsed}
    by_capture={(o['race_id'],instant(o['captured_at'])):o for o in _merge(parsed)}
    observations=_merge(observations);native={(o['race_id'],instant(o['captured_at'])):o for o in observations}
    for identity,o in by_capture.items():
        if identity in native:
            need(native[identity].get('source_sha256')==o.get('source_sha256'),'RESULT_CAPTURE_CONFLICT')
        else:observations.append(o)
    by_race={}
    for o in _merge(observations):by_race.setdefault(o['race_id'],[]).append(o)
    for row in out['records']:
        incoming=by_race.get(row['race_id'],[])
        if not incoming:continue
        old=row['result_observations'];merged=_merge([*old,*incoming]);row['result_observations']=merged
        latest=max(merged,key=lambda o:instant(o['captured_at']))
        previous_result=row.get('result') or {}
        receipt_unchanged=(previous_result.get('source_sha256')==latest.get('source_sha256') and
                           previous_result.get('observed_at')==latest.get('captured_at'))
        if old and digest(latest)==digest(max(old,key=lambda o:instant(o['captured_at']))) and \
           previous_result.get('status') in ('final','void','pending') and \
           receipt_unchanged and (previous_result.get('status')=='pending' or
                                  latest.get('body_identity_verified') is True) and \
           (row.get('cutoff_at') is not None or previous_result.get('cutoff_reconciliation')):
            continue
        need(instant(latest['captured_at'])<=instant(synced_at),'FEED_FUTURE_OBSERVATION')
        row['result_observation_rejections']=[]
        row['missing_reasons']=[r for r in row['missing_reasons'] if r!='LATEST_RESULT_OBSERVATION_REJECTED']
        # Native observations keep their ST and other source fields. The raw
        # parser supplies this display projection only; next runners can replay
        # the exact native journal without needing the previous raw cache.
        selected=by_capture.get((latest['race_id'],instant(latest['captured_at'])),latest)
        try:row['result']=project_observation(selected,row,freeze_at=row['prediction']['persisted_at'],raw_bound=digest(selected) in raw_ids)
        except (KeyError,ValueError,TypeError) as error:
            code=getattr(error,'reason_code',None) or str(error)
            reason=code if re.fullmatch('[A-Z][A-Z0-9_]{1,199}',code) else 'RESULT_OBSERVATION_INVALID'
            row['result']=dict(status='unsupported',winning_combinations=[],confirmed_at=None,observed_at=latest['captured_at'],official=False,source_sha256=latest.get('source_sha256'))
            row['result_observation_rejections']=[dict(captured_at=latest['captured_at'],source_sha256=latest.get('source_sha256'),reason=reason)]
            row['missing_reasons'].append('LATEST_RESULT_OBSERVATION_REJECTED')
    out['results_synced_at']=synced_at;need(originals_sha(out)==pin,'FEED_ORIGINAL_CHANGED');return out

