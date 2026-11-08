"""Read-only independent AES/Git PDCA acceptance check. No source GET or bets."""
from copy import deepcopy
from datetime import datetime,timezone
import argparse,json,os,re,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def _need(ok,code):
    if not ok:raise ValueError('ALL_HISTORY_PDCA_'+code)


def _count_only_day_pdca(view, score):
    """Count-only verified diagnostics; never log private race IDs or tickets.

    First-place rank is appearance order of distinct first-place candidates
    in the saved Top8, not a probability rank among all six racers.
    High payout means official trifecta >= 10,000 yen per 100 yen.
    """
    from collections import Counter
    from hashlib import sha256
    from race_ai import retained_model_pdca_audit as P, saved_view_feed as F
    from race_ai.actions_contract import digest
    anchor=F.forecast_anchor(view)
    inventory=F.inventory_sha(view)
    indexed={}
    for g in score['model_groups']:
        key=(g['model_id'],g['stage'],g.get('version') or '',g.get('variant') or '')
        _need(key not in indexed,'DUPLICATE_MODEL_GROUP')
        indexed[key]=dict(first_rank=Counter(),winner_rank=Counter(),eligible=0,
                          high_cases=0,high_hit=0,high_miss=0,high_first_absent=0,multi_winners=0)
    seen=set()
    for row in view['records']:
        if row.get('sport')!='boat':continue
        state,winners,refunds=P._result_context(row)
        if state!='FINAL':continue
        predictions=([row['prediction']] if row.get('prediction') is not None else [])+list(row.get('comparison_predictions') or [])
        for p in predictions:
            identity=digest([row['race_id'],anchor,inventory,p])
            if identity in seen:continue
            seen.add(identity)
            try: cutoff=P._saved_clock(p,row)
            except ValueError:continue
            if P._clock(row['result']['observed_at'])<cutoff:continue
            key=(p['model_id'],p['stage'],p.get('model_version') or '',p.get('variant') or '')
            _need(key in indexed,'MISSING_MODEL_GROUP')
            a=indexed[key]
            a['eligible']+=1
            tickets=[tuple(t) for t in p['ordered_top8']]
            firsts=list(dict.fromkeys(t[0] for t in tickets))
            positions=[firsts.index(w[0])+1 for w in winners if w[0] in firsts]
            a['first_rank'][str(min(positions)) if positions else 'NOT_IN_TOP8']+=1
            matching=[i+1 for i,t in enumerate(tickets) if t in winners]
            a['winner_rank'][str(min(matching)) if matching else 'NOT_IN_TOP8']+=1
            if len(winners)>1:a['multi_winners']+=1
            if any(amount>=10000 for amount in winners.values()):
                a['high_cases']+=1
                if any(w in tickets and amount>=10000 for w,amount in winners.items()):
                    a['high_hit']+=1
                else:
                    a['high_miss']+=1
                    if not positions:a['high_first_absent']+=1
    groups=[]
    for g in score['model_groups']:
        key=(g['model_id'],g['stage'],g.get('version') or '',g.get('variant') or '')
        a=indexed[key]
        _need(a['eligible']==g['eligible'] and
              sum(a['first_rank'].values())==g['eligible'] and
              sum(a['winner_rank'].values())==g['eligible'],'MODEL_ELIGIBILITY_NOT_REPRODUCED')
        _need(a['high_cases']==a['high_hit']+a['high_miss'],'HIGH_PAYOUT_ACCOUNTING')
        version=g.get('version')
        groups.append(dict(model_id=g['model_id'],stage=g['stage'],
            variant=g.get('variant'),version_ref=sha256(str(version).encode()).hexdigest()[:12] if version is not None else None,
            forecasts=g['forecasts'],eligible=g['eligible'],hits=g['hits'],misses=g['misses'],
            void=g['void'],pending=g['pending'],held=g['held'],
            hit_rate=g['hit_rate'],miss_reasons=g['miss_reasons'],unresolved_reasons=g['unresolved_reasons'],
            stake_yen_reference=g['stake_yen'],returned_yen_reference=g['returned_yen'],
            refund_yen_reference=g['refund_yen'],net_yen_reference=g['net_yen'],roi_reference=g['roi'],
            first_candidate_rank_by_top8_order=dict(sorted(a['first_rank'].items())),
            actual_winning_combo_rank_in_top8=dict(sorted(a['winner_rank'].items())),
            high_payout_official_cases=a['high_cases'],high_payout_captured=a['high_hit'],
            high_payout_missed=a['high_miss'],high_payout_first_not_selected=a['high_first_absent'],
            multi_winner_cases=a['multi_winners']))
    return dict(races=sum(r.get('sport')=='boat' for r in view['records']),
        forecasts=score['total_forecasts'],eligible=score['total_scored'],unresolved=score['unresolved'],
        source_provider_requests=0,actual_purchases=False,
        stake_policy='REFERENCE_100_YEN_PER_FROZEN_TICKET_WITH_OFFICIAL_REFUNDS',
        first_rank_basis='FIRST_DISTINCT_FIRST_PLACE_APPEARANCE_NOT_ALL_RACER_RANK',
        model_groups=groups)


def _entire_saved_period_coverage(state, bridge, *, now, independently_verified, snapshot_holds):
    """Verify all indexed saved days, not only the latest two plus one older day.

    This only reads existing authenticated AES/Git data, never uses a provider,
    and never exports saved race IDs or guesses missing official results.
    """
    from race_ai import model_pdca_history as H, retained_model_pdca_audit as P
    from race_ai import result_due_ledger as D, saved_view_feed as F
    available=sorted(set(bridge.available_days))
    archived=set(H._unwrap(state.control)['days'])
    indexed=set(available)
    verified=set(independently_verified)&indexed
    failed=0
    current_view=None
    if not bridge.history and any(day not in verified and day in archived for day in available):
        current_view=F.current_view(bridge.git,bridge.bootstrap)[3]
    for day in available:
        if day in verified or day not in archived:
            continue
        try:
            if bridge.history:
                view=F.current_view(bridge.git,bridge.bootstrap,day=day)[3]
            else:
                view=dict(current_view,records=[r for r in current_view['records']
                    if r.get('sport')=='boat' and r.get('event_date_jst')==day])
            score=P.score_view(view,authenticated=True)
            H.verify_day(state.control,day=day,view=view,summary=score)
        except (ValueError,TypeError,KeyError):
            # A failed old-day readback never counts as a zero or an exclusion.
            failed+=1
        else:
            verified.add(day)
    due=D.ledger(deepcopy(state.control),now=now.isoformat())
    all_scores=H.latest(state.control)
    backlog=D.pending_count(due)
    unavailable=D.unavailable_days(due,available)
    unscored=all_scores['unscored']
    index_complete=bool(available) and indexed==archived
    readback_complete=index_complete and len(verified)==len(available) and failed==0
    fully_resolved=readback_complete and backlog==0 and unscored==0 and snapshot_holds==0 and unavailable==0
    return dict(
        full_period_saved_days=len(available),
        full_period_pdca_archived_days=len(archived),
        full_period_independently_read_days=len(verified),
        full_period_missing_pdca_days=len(indexed-archived),
        full_period_orphan_pdca_days=len(archived-indexed),
        full_period_readback_holds=failed,
        full_period_unavailable_backlog_days=unavailable,
        full_period_ledger_open_races=backlog,
        full_period_unscored_model_forecasts=unscored,
        full_period_readback_coverage_proven=bool(readback_complete),
        all_history_completion_proven=bool(fully_resolved))

def verify_snapshot(state,bridge,*,now):
    from race_ai import result_due_ledger as D,retained_model_pdca_audit as P,model_pdca_history as H
    from race_ai import saved_view_feed as F
    from race_ai.racer_daily import wire
    _need(isinstance(now,datetime) and now.utcoffset() is not None,'CLOCK_INVALID')
    original=wire(state.control)
    snapshot=state.control.get('model_pdca_recent_audit')
    _need(type(snapshot) is dict and snapshot.get('schema')=='RACE_AI_PRIVATE_MODEL_PDCA_SNAPSHOT_V1'
          and snapshot.get('verification')=='PRE_SOURCE_REPLAY' and type(snapshot.get('days')) is list,
          'SNAPSHOT_ABSENT_OR_UNTRUSTED')
    _need(0<len(snapshot['days'])<=4,'SNAPSHOT_DAY_BOUND')
    _need('result_due_ledger' in state.control,'PERSISTENT_DUE_LEDGER_MISSING')
    due=D.ledger(deepcopy(state.control),now=now.isoformat())
    authenticated=models=scored=historical=holds=pending=archived_readbacks=0;held_days=0
    verified_daily={}
    seen=set()
    for item in snapshot['days']:
        _need(type(item) is dict and item.get('status') in ('SCORED','HOLD_MODEL_PDCA_INPUT'),'MODEL_PDCA_SNAPSHOT_STATE_INVALID')
        if item['status']=='HOLD_MODEL_PDCA_INPUT':
            held_days+=1
            continue
        day=item.get('day')
        _need(type(day) is str and (day=='CURRENT_VIEW' or
            re.fullmatch(r'\d{4}-\d{2}-\d{2}',day)),'MODEL_PDCA_DAY_INVALID')
        _need(day not in seen,'MODEL_PDCA_DUPLICATE_DAY');seen.add(day)
        _,_,_,view=F.current_view(bridge.git,bridge.bootstrap,
                                  **(dict(day=day) if day!='CURRENT_VIEW' else {}))
        _need(F.inventory_sha(view)==item.get('forecast_inventory_sha256'),'ORIGINAL_FORECAST_SHA_CHANGED')
        recomputed=P.score_view(view,authenticated=True)
        _need(wire(recomputed)==wire(item.get('summary')),'MODEL_PDCA_SNAPSHOT_MISMATCH')
        # Reopen actual AES/Git objects and compare every day's immutable
        # model/stage/version Top8 summary and official result revision.
        slices=[(day,view)] if day!='CURRENT_VIEW' else [
            (d,dict(view,records=[r for r in view['records'] if r.get('event_date_jst')==d]))
            for d in sorted({r.get('event_date_jst') for r in view['records'] if r.get('sport')=='boat'})]
        for archive_day,part in slices:
            part_summary=P.score_view(part,authenticated=True)
            H.verify_day(state.control,day=archive_day,view=part,summary=part_summary)
            details=_count_only_day_pdca(part,part_summary)
            if archive_day in verified_daily:
                _need(verified_daily[archive_day]==details,'DAY_SCORING_CONFLICT')
            else:verified_daily[archive_day]=details
            archived_readbacks+=1
        authenticated+=1;models+=recomputed['model_group_count'];scored+=recomputed['total_scored']
        holds+=sum(g['held'] for g in recomputed['model_groups'])
        pending+=sum(g['pending'] for g in recomputed['model_groups'])
        today=now.astimezone(D.JST).date().isoformat()
        if day!='CURRENT_VIEW' and day<today and recomputed['total_scored']:
            historical+=1
        elif day=='CURRENT_VIEW':
            previous=[r for r in view['records'] if r.get('sport')=='boat'
                      and r.get('event_date_jst','')<today]
            if previous and P.score_view(dict(view,records=previous),authenticated=True)['total_scored']:
                historical+=1
    _need(scored>0 and historical>0,'NO_REAL_HISTORICAL_MODEL_SCORE')
    coverage=_entire_saved_period_coverage(state,bridge,now=now,
        independently_verified=verified_daily,snapshot_holds=held_days)
    # Revalidate every private unresolved case against the authenticated AES
    # due-bitset. A case cannot vanish without an explicit formal resolution.
    from race_ai import result_due_case_audit as RC
    reasons=RC.summary(state.control,due)
    _need(reasons['outstanding']==coverage['full_period_ledger_open_races'],
          'RESULT_DUE_CASE_COVERAGE_MISMATCH')
    _need(wire(state.control)==original,'SOURCE_CONTROL_MUTATED')
    eligible_days=sorted(day for day,detail in verified_daily.items() if detail['eligible']>0)
    focus_day=eligible_days[-1] if eligible_days else None
    day_counts=[dict(day=day,races=d['races'],forecasts=d['forecasts'],eligible=d['eligible'],unresolved=d['unresolved'])
                for day,d in sorted(verified_daily.items())]
    return dict(schema='RACE_AI_INDEPENDENT_PDCA_READBACK_V1',
        status='AES_AUTHENTICATED_HISTORICAL_PDCA_READBACK_VERIFIED',
        saved_days_authenticated=authenticated,model_group_snapshots=models,
        historical_days_with_formal_scores=historical,formally_scored_forecasts=scored,
        pending_forecasts=pending,held_forecasts=holds,
        pdca_day_counts=day_counts,pdca_focus_day=focus_day,
        pdca_focus_groups=verified_daily[focus_day]['model_groups'] if focus_day is not None else [],
        pdca_payout_threshold_yen_per_100=10000,
        pdca_rank_definition='TOP8_FIRST_APPEARANCE_NOT_ALL_RACER_PROBABILITY_RANK',
        pdca_stake_policy='REFERENCE_100_YEN_PER_SAVED_TICKET_NO_ACTUAL_BETS',
        unresolved_case_audit=reasons,
        unresolved_replay_inventory=RC.retained_source_inventory(state,due),
        ledger_outstanding=D.pending_count(due),archived_days=H.latest(state.control)['days'],
        archived_revisions=H.latest(state.control)['revisions'],independent_day_readbacks=archived_readbacks,held_days=held_days,
        source_provider_requests=0,
        forecast_rewrites=0,actual_purchases=False,
        secret_or_private_original_logged=False,**coverage)


def _safe_same_race_shadow_comparison(view):
    """Run the existing strict paired reader on a private 0600 view in Actions.

    The Node child receives PATH/LANG/TZ only; no GitHub or owner secret.
    It returns counts, never race IDs, original predictions or bets.
    """
    import tempfile
    from race_ai.boat_history_store import wire
    from scripts.boat_prospective_audit import _run_node
    root=Path(os.environ.get('RUNNER_TEMP',''))
    _need(root.is_absolute() and root.is_dir(),'TEMP_DIRECTORY_UNAVAILABLE')
    raw=wire(view).encode('utf-8')
    _need(0<len(raw)<=64*1024*1024,'PAIRED_VIEW_BOUND')
    with tempfile.TemporaryDirectory(dir=root,prefix='verified-boat-paired-') as folder:
        path=Path(folder)/'owner-verified-view.json'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out:out.write(raw)
        code,report=_run_node('saved_performance_report.cjs',['--input',str(path)])
    _need(code==0 and report.get('schema')=='RACE_AI_SAVED_PERFORMANCE_AGGREGATES_V1',
          'PAIRED_READER_UNAVAILABLE')
    indexed={g['id']:g for g in report['groups']}
    pairs=[]
    for item in report['paired_comparisons']:
        if item['axis']!='LEARNED_WEIGHT_VERSION':continue
        original=indexed.get(item['baseline_group'])
        learned=indexed.get(item['challenger_group'])
        _need(original is not None and learned is not None and
              original['model_id']==learned['model_id'] and
              original['stage']==learned['stage'],'PAIRED_MODEL_IDENTITY')
        sims=[]
        for sim in item['simulations']:
            if sim['daily_budget']!=10000 or sim['race_budget']!=800:continue
            sims.append(dict(daily_budget_yen=sim['daily_budget'],
                             per_race_limit_yen=sim['race_budget'],
                             identical_selected_races=sim['identical_selected_races'],
                             baseline_bought=sim['baseline']['bought'],
                             learned_bought=sim['challenger']['bought'],
                             baseline_spent_yen=sim['baseline']['spent'],
                             learned_spent_yen=sim['challenger']['spent'],
                             baseline_net_yen=sim['baseline']['net'],
                             learned_net_yen=sim['challenger']['net'],
                             baseline_roi=sim['baseline']['roi'],
                             learned_roi=sim['challenger']['roi']))
        pairs.append(dict(model_id=original['model_id'],stage=original['stage'],
            baseline_variant=original['variant'],learned_variant=learned['variant'],
            paired_races=item['paired_races'],both_hit=item['both_hit'],
            baseline_only=item['baseline_only'],learned_only=item['challenger_only'],
            both_miss=item['both_miss'],baseline_hits=item['baseline_hits'],
            learned_hits=item['challenger_hits'],baseline_hit_rate=item['baseline_hit_rate'],
            learned_hit_rate=item['challenger_hit_rate'],
            learned_minus_baseline_rate=item['hit_rate_difference'],
            exact_discordance_p_value=item['exact_discordance_p_value'],
            exclusions=item['excluded'],identical_budget_scenarios=sims,
            future_accuracy_improvement_proven=False))
    return dict(status='STRICT_DESCRIPTIVE_PAIRED_REVIEW',
        matched_pairs=sum(g['paired_races'] for g in pairs),
        models_compared=len(pairs),per_model=pairs,
        independent_prediction_receipts_verified_by_node=False,
        input_view_AES_GIT_independent_readback=True,
        future_accuracy_improvement_proven=False,actual_purchases=False,
        provider_requests=0)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repository-root',default=str(ROOT))
    a=p.parse_args(argv)
    try:
        _need(os.environ.get('GITHUB_ACTIONS')=='true' and
              os.environ.get('GITHUB_REPOSITORY')=='haji84/RACE-AI','EXISTING_ACTIONS_ONLY')
        _need(bool(os.environ.get('RACE_AI_STATE_KEY')),'EXISTING_SECRET_REQUIRED')
        from scripts.racer_intraday_refresh import _stage_git_header_scope
        _stage_git_header_scope()
        from scripts.boat_private_original_vault import _environment
        from scripts.boat_saved_view_feed import git_auth
        from race_ai.racer_intraday_handoff import load_intraday
        from race_ai.racer_result_bridge import SavedResultBridge
        root=_environment(Path(a.repository_root));git_auth()
        instant=datetime.now(timezone.utc)
        state=load_intraday(root,now=instant)['state']
        bridge=SavedResultBridge(root,now=instant)
        result=verify_snapshot(state,bridge,now=instant)
        day=result.get('pdca_focus_day')
        if day is not None:
            from race_ai import saved_view_feed as F,retained_model_pdca_audit as P
            _,_,_,focus_view=F.current_view(bridge.git,bridge.bootstrap,day=day)
            before=_count_only_day_pdca(focus_view,P.score_view(focus_view,authenticated=True))
            _need(before['model_groups']==result['pdca_focus_groups'],'FOCUS_DAY_CHANGED')
            try:result['pdca_focus_strict_pairs']=_safe_same_race_shadow_comparison(focus_view)
            except Exception as error:
                result['pdca_focus_strict_pairs']=dict(status='HOLD_PAIRED_READER_UNAVAILABLE',
                    error_type=type(error).__name__,paired_improvement_proven=False,
                    provider_requests=0,actual_purchases=False)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        reason=(str(exc) if type(exc) is ValueError and
               re.fullmatch(r'ALL_HISTORY_PDCA_[A-Z0-9_]+',str(exc))
               else 'ALL_HISTORY_PDCA_READBACK_UNAVAILABLE')
        # Never log private race IDs, original payloads or auth exceptions. A
        # bounded source-code-only trace identifies the failing acceptance gate.
        trace=[Path(frame.filename).name+':'+str(frame.lineno)+':'+frame.name
               for frame in traceback.extract_tb(exc.__traceback__)[-5:]]
        print(json.dumps(dict(schema='RACE_AI_INDEPENDENT_PDCA_READBACK_V1',
          status='HOLD',reason=reason,exception_type=type(exc).__name__,code_trace=trace,
          source_provider_requests=0,actual_purchases=False,
          all_history_completion_proven=False),sort_keys=True))
        return 2

if __name__=='__main__':raise SystemExit(main())
