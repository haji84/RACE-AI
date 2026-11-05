"""As-of-safe, reconciled history supplement for existing observed models.

No new prediction model or coefficient. Reuses the existing strict history
means/counts and native validator. Available now is not available historically:
API capture, private save AND official verification must precede forecast time.
No inferred current entry course, motor cycle, subjective young-racer bonus,
missing value imputation, learned weights or production promotion.
"""
from copy import deepcopy
from datetime import date, timedelta, timezone
import hashlib
import re
from statistics import mean, pstdev

from .actions_contract import digest, stamp
from .teiai_history import BASE, RIGHTS, need, parse_history_csv, parse_race_json, race_parts
from .teiai_official_reconciliation import official_day, reconcile_rows
from .observed_result_history import _features
from .boat_observed_pairwise_models import _validate, HISTORY_FIELDS
from .official_lzh_extract import extract_daily_lzh
from .official_archive_probe import official_url

JST=timezone(timedelta(hours=9))


def descriptive_summary(rows):
    """Descriptive numeric-finish-only denominator, not provider's starts formula.

    Abnormal/missing rows remain counted separately. Population ST deviation
    uses OK starts only. This summary does not certify source truth or timing.
    Entry/kimarite tactical profiles remain in existing boat_racer_tendencies.
    """
    rows=sorted(rows,key=lambda r:r['race_id'],reverse=True)
    def st_stats(sample):
        values=[r['st'] for r in sample if r['st_status']=='OK' and r['st'] is not None]
        return dict(n=len(values),mean=mean(values) if values else None,std_population=pstdev(values) if values else None)
    def finish_stats(sample):
        values=[r['finish'] for r in sample if r['finish'] is not None]
        n=len(values)
        return dict(starts=len(sample),numeric_finish_n=n,abnormal_or_missing_n=len(sample)-n,
                    wins=values.count(1),top2=sum(v<=2 for v in values),top3=sum(v<=3 for v in values),
                    win_rate=values.count(1)/n if n else None,top2_rate=sum(v<=2 for v in values)/n if n else None,
                    top3_rate=sum(v<=3 for v in values)/n if n else None,st=st_stats(sample))
    return dict(period_start=min((r['race_id'][:8] for r in rows),default=None),
                period_end=max((r['race_id'][:8] for r in rows),default=None),
                definition='numeric_finish_only_rates_v1; OK_ST_only_population_std_v1; recent_by_race_id_day_rno',
                source='艇愛ボートレースDB https://boatrace-db.jp/ (BOAT RACE official-derived)',
                grade_basis='PROVIDER_INFERRED',total=finish_stats(rows),st=st_stats(rows),
                courses={str(i):finish_stats([r for r in rows if r['course']==i]) for i in range(1,7)},
                recent_10=finish_stats(rows[:10]),recent_30=finish_stats(rows[:30]),
                by_venue={v:finish_stats([r for r in rows if r['race_id'][9:11]==v]) for v in sorted({r['race_id'][9:11] for r in rows})},
                by_inferred_grade={g:finish_stats([r for r in rows if r['grade']==g]) for g in sorted({r['grade'] for r in rows if r['grade'] is not None})})


def enrich_observed_snapshot(snapshot,histories,official_archives,*,verified_at,
                             allow_source=None,authenticate_official=None):
    """Return a NEW native snapshot plus private lineage and quarantine counts.

    ``histories`` maps registration strings to HistoryCache documents.
    ``official_archives`` maps ISO dates to raw LZH bytes, URL, capture and SHA.
    Caller must authenticate upstream bytes independently through the callback;
    hashes alone never establish official identity. No input mutation occurs.
    For each supplied racer all history fields are replaced from this cohort.
    Unsupplied racers retain their already-validated input features.
    """
    _validate(snapshot)
    need(snapshot['scope']=='OPERATOR_SUPPLIED_RESEARCH','TEIAI_RESEARCH_ONLY')
    need(callable(allow_source) and callable(authenticate_official),'TEIAI_INDEPENDENT_REVIEW_REQUIRED')
    now=stamp(snapshot['as_of']);verified=stamp(verified_at)
    need(verified<=now<stamp(snapshot['sales_cutoff_at']),'TEIAI_VERIFIED_OR_CUTOFF_CLOCK')
    event_day=date.fromisoformat(snapshot['event_date_jst'])
    roster={p['registration_no'] for p in snapshot['participants']}
    need(type(histories) is dict and set(histories)<=roster,'TEIAI_HISTORY_ROSTER_MISMATCH')
    need(type(official_archives) is dict,'TEIAI_OFFICIAL_ARCHIVE_MAP_REQUIRED')
    out=deepcopy(snapshot)
    official_rows=[];official_sources=[]
    for day,doc in sorted(official_archives.items()):
        d=date.fromisoformat(day)
        need(d<event_day,'TEIAI_CURRENT_OR_FUTURE_OFFICIAL_HISTORY')
        raw=doc['raw'];sha=hashlib.sha256(raw).hexdigest();url=official_url(d,'K')
        need(doc['source_url']==url and doc['source_sha256']==sha and stamp(doc['captured_at'])<=verified,
             'TEIAI_OFFICIAL_HASH_IDENTITY_OR_CLOCK')
        need(authenticate_official(doc) is True,'TEIAI_OFFICIAL_NOT_AUTHENTICATED')
        need(allow_source(url,'OFFICIAL_DOWNLOAD_PERSONAL_CROSSCHECK','analysis') is True,'TEIAI_OFFICIAL_RIGHTS_REQUIRED')
        parsed=official_day(extract_daily_lzh(raw,f'K{d:%y%m%d}.TXT'),day=day)
        official_rows.extend(parsed['rows'])
        official_sources.append(dict(source_id='official-k-'+day,source_url=url,source_sha256=sha,
            source_rights_ref='OFFICIAL_DOWNLOAD_PERSONAL_CROSSCHECK',published_at=None,
            captured_at=doc['captured_at'],evidence_basis='CAPTURED_BY_CLAIM'))
    reports={};source_additions=[]
    for participant in out['participants']:
        pid=participant['registration_no'];doc=histories.get(pid)
        if doc is None:continue
        url=doc['source_url'];raw=doc['raw'];sha=hashlib.sha256(raw).hexdigest()
        need(doc['source_sha256']==sha,'TEIAI_HISTORY_HASH_OR_IDENTITY')
        captured=stamp(doc['captured_at']);stored=stamp(doc['stored_at'])
        need(captured<=stored<=verified<=now,'TEIAI_HISTORY_AVAILABILITY_CLOCK')
        published=doc.get('published_at')
        need(published is None or stamp(published)<=captured,'TEIAI_PUBLICATION_CLOCK')
        need(all(allow_source(url,RIGHTS,p) is True for p in ('analysis','private_storage')),'TEIAI_HISTORY_RIGHTS_REQUIRED')
        if url==f'{BASE}/api/racer/{pid}/results/':
            parsed=parse_history_csv(raw,racer_id=pid,source_url=url)
            source_id='teiai-history-'+pid
        else:
            m=re.fullmatch(re.escape(BASE)+r'/api/race/([0-9]{8})/([0-9]{2})/([0-9]{1,2})/',url)
            need(m is not None,'TEIAI_HISTORY_HASH_OR_IDENTITY')
            rid=f'{m[1]}-{m[2]}-{int(m[3]):02d}'
            race=parse_race_json(raw,race_id=rid)
            selected=[r for r in race['rows'] if r['racer_id']==pid]
            need(selected,'TEIAI_HISTORY_REGISTRATION_NOT_IN_RACE')
            parsed=dict(rows=selected,duplicate_count=0,quarantine=[])
            source_id='teiai-race-'+rid
        need(all(race_parts(r['race_id'])[0]<=captured.astimezone(JST).date() for r in parsed['rows']),
             'TEIAI_RACE_AFTER_CAPTURE')
        eligible=[r for r in parsed['rows'] if race_parts(r['race_id'])[0]<event_day]
        report=reconcile_rows(eligible,official_rows)
        # Sorting by date + race number is chronological only within each
        # racer's history. A racer cannot start at two venues on the same day.
        per_day={}
        for r in eligible:per_day.setdefault(r['race_id'][:8],set()).add(r['race_id'][9:11])
        need(all(len(v)==1 for v in per_day.values()),'TEIAI_MULTIPLE_VENUES_SAME_RACER_DAY')
        accepted=sorted(report['accepted'],key=lambda r:r['race_id'],reverse=True)
        source_additions.append(dict(source_id=source_id,source_url=url,source_sha256=sha,source_rights_ref=RIGHTS,
                                     captured_at=doc['captured_at'],published_at=published,
                                     evidence_basis='CAPTURED_BY_CLAIM' if published is None else 'SOURCE_PUBLISHED_AT_CLAIM'))
        # Reuse existing count/disposition semantics. Course is the historical
        # actual course, grouped by today's FRAME as a declared conditional
        # statistic; it is not an estimate of today's actual entry.
        admitted={r['race_id']:r for r in accepted}
        opportunities=sorted(eligible,key=lambda r:r['race_id'],reverse=True)
        def features(sample):
            observations=[]
            for original in sample:
                r=admitted.get(original['race_id'])
                if r is None:
                    value=dict(finish=None,finish_status='MISSING',actual_st=None,actual_st_status='MISSING')
                else:
                    code=r['result_code']
                    status='SPECIAL' if r['special_result'] else ('FINISHED' if r['finish'] is not None else
                            ('F' if code=='F' else 'L' if code.startswith('L') else 'MISSING'))
                    value=dict(finish=r['finish'],finish_status=status,actual_st=r['st'],actual_st_status=r['st_status'])
                observations.append((value,digest(dict(row=original,provider_sha256=sha,officially_admitted=r is not None))))
            return _features(observations,source_id,pid)
        recent,missing=features(opportunities[:10])
        # Unknown courses cannot be assumed to be outside this course cohort.
        course_sample=[r for r in opportunities if r['course'] in (None,participant['lane'])][:30]
        course,course_missing=features(course_sample)
        for name in HISTORY_FIELDS:
            participant['features'].pop(name,None);participant['missing'].pop(name,None)
        for name in ('recent_mean_finish','recent_mean_st'):
            if name in recent:participant['features'][name]=recent[name]
            else:participant['missing'][name]=missing[name]
        for name in ('finish','st'):
            old='recent_mean_'+name;new='course_mean_'+name
            if old in course:participant['features'][new]=course[old]
            else:participant['missing'][new]=course_missing[old]
        reports[pid]={k:v for k,v in report.items() if k!='accepted'}
        reports[pid].update(summary=descriptive_summary(accepted),
                            provider_sha256=sha,stored_at=doc['stored_at'],verified_at=verified_at,
                            duplicate_count=parsed['duplicate_count'],duplicate_quarantine=parsed['quarantine'],
                            window_basis='PROVIDER_OPPORTUNITIES_LAST10_COURSE_LAST30_UNVERIFIED_REMAIN_MISSING',
                            excluded_on_or_after_target_day=len(parsed['rows'])-len(eligible))
    if source_additions:
        by_id={s['source_id']:s for s in out['sources']}
        for source in official_sources+source_additions:
            old=by_id.get(source['source_id'])
            need(old is None or old==source,'TEIAI_CONFLICTING_SOURCE_DOCUMENTS')
            if old is None:out['sources'].append(source);by_id[source['source_id']]=source
    _validate(out)
    coverage={k:sum(r[k] for r in reports.values()) for k in
              ('provider_rows','compared_rows','matched_rows','mismatched_rows','missing_rows','special_result_rows')}
    return dict(snapshot=out,reports=reports,coverage=coverage,
                comparison_cohort_sha256=digest(dict(histories={k:v['source_sha256'] for k,v in histories.items()},
                                                     official=[s['source_sha256'] for s in official_sources],as_of=snapshot['as_of'])),
                formal_backtest_eligible=False,production_promoted=False,
                not_provided=['motor_exchange_cycle','boat_exchange_cycle','intentional_maezuke',
                              'video_verified_makurare_or_sasare','historical_publication_revision_log'])
