"""Prepared official-source extension; no forecasts, storage, or activation.

The main runner must verify its real canary PASS receipt before invoking this
extension. These functions build a day inventory and independent baseline
inputs. A complete day inventory does not establish prediction coverage.
Unobserved class/round formats and contested lines remain explicit holds.
"""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import re
from subprocess import TimeoutExpired

from . import keirin_official_canary_card as card_api
from . import keirin_official_form_history as form
from . import keirin_official_schedule as calendar
from . import keirin_official_sp_receipt as receipt
from . import keirin_nationwide_auto_generator as core
from .keirin_public_two_source_normalizer import _style


class OfficialExtensionError(ValueError):
    pass


def _need(ok, code):
    if not ok:
        raise OfficialExtensionError('OFFICIAL_EXTENSION_'+code)


def _source(raw, expected):
    _need(type(raw) is bytes and 0 < len(raw) <= calendar.MAX_HTML_BYTES and
          sha256(raw).hexdigest() == expected, 'SOURCE_SHA_MISMATCH')
    return raw


# Exact labels, after the existing NFKC normalization, observed in the
# retained official /sp/racelist response:
# SHA256 c5828c08f1a84a3dbc1174e473abe87103290dd83a85b652ca6d6c94a4f91588,
# SJ0301.kaisaiDayList[].raceProgramList[].strSyumokuName (2026-11-20).
# Later-day labels were published with no usable navigation reference then.
# Naming a round never admits a card: current published reference, roster,
# grade, cutoff and line checks below remain mandatory; advance rules unknown.
# The official continuation runs 44987254723, 45017430382 and 45023069187
# also verified future cards for the six A-class labels below, with A3 or
# A1/A2 grades.
# Run 45684840895 also bound the exact challenge preliminary, A preliminary
# and A general labels to published seven-rider cards with those grades.
# Run 45693553031 verified seven-rider special preliminary, semifinal and
# first-day special selection cards in the same A1/A2 scoring group.
# Run 45700002485 observed seven-rider future cards for the S preliminary
# (S2) and first-day special selection (S1).
# A label never supplies a qualification rule or any missing card input.
OBSERVED_CLASSES = {
    'A級チャレンジ予選': 'CHALLENGE',
    'A級チャレンジ一般': 'CHALLENGE',
    'A級チャレンジ選抜': 'CHALLENGE',
    'A級チャレンジ決勝': 'CHALLENGE',
    'A級予選': 'A1_A2',
    'A級特予選': 'A1_A2',
    'A級準決勝': 'A1_A2',
    'A級初日特選': 'A1_A2',
    'A級一般': 'A1_A2',
    'A級特一般': 'A1_A2',
    'A級特選': 'A1_A2',
    'A級決勝': 'A1_A2',
    'S級予選': 'S',
    'S級初日特選': 'S',
    'S級一次予選1': 'S',
    'S級一次予選2': 'S',
    'S級選抜': 'S',
    'S級二次予選B': 'S',
    'S級二次予選A': 'S',
    'S級ダイヤモンドレース': 'S',
    'S級一般': 'S',
    'S級特選': 'S',
    'S級準決勝': 'S',
    'S級特別優秀': 'S',
    'S級決勝': 'S',
    'L級ガールズ予選': 'GIRLS',
    'L級ガールズ準決勝': 'GIRLS',
    'L級ガールズ選抜': 'GIRLS',
    'L級ガールズ特選': 'GIRLS',
    'L級ガールズ決勝': 'GIRLS',
}

RIDER_GRADE_PATTERNS = {
    'CHALLENGE': r'A3',
    'A1_A2': r'A[12]',
    'S': r'S[12S]|S級[12S]班',
    'GIRLS': r'L1|L級1班',
}
LINE_VIEW_PATH = '/sp/static/js/SJ0314_v.js'
_LINE_VIEW_FRAGMENTS = (
    'ichi=index*14+ilop+1;',
    'jsondata["narabiyoso"]["shaban"][jlop]["ichi"]==ichi.toString()',
    'obj["shaban"]=jsondata["narabiyoso"]["shaban"][jlop]["shaban"];',
    'obj["shaban"]="";',
    'jsondata["narabiyoso"]["kyoHyoji"]=="true"',
)


def parse_published_lines(detail_raw, *, detail_sha256, starters, competition,
                          line_view_source=None):
    """Read the published fourteen-column layout, never infer a contested line."""
    raw = _source(detail_raw, detail_sha256)
    doc = card_api.browser_source._document(raw)
    data = receipt._embedded(doc).get('SJ0314', {})
    line = data.get('narabiyoso')
    _need(data.get('resultCd') == 0 and type(line) is dict and
          line.get('errFlg') == 'false' and line.get('ryoikiFlg') == 'true',
          'LINE_NOT_PUBLISHED')
    rows = line.get('shaban')
    _need(type(rows) is list and len(rows) == len(starters) and
          all(type(r) is dict and re.fullmatch('[1-9]', str(r.get('shaban', '')))
              for r in rows), 'LINE_PARENTHESIS_OR_ROSTER_UNSUPPORTED')
    cars = [int(r['shaban']) for r in rows]
    _need(len(set(cars)) == len(cars) and set(cars) == set(starters), 'LINE_ROSTER_MISMATCH')
    if competition == 'GIRLS':
        _need(line.get('lineKeitai') == 'ライン無し' and
              line.get('lineKeitaiClass') == 'noline', 'GIRLS_LINE_NOT_EXPLICIT')
        groups, kind, view_sha = [[c] for c in sorted(cars)], 'NO_FIXED_LINE', None
    else:
        _need(line.get('kyoHyoji') == 'false' and type(line.get('maxAxixY')) is int and
              line['maxAxixY'] == 1, 'CONTESTED_OR_MULTILEVEL_LINE_UNSUPPORTED')
        _need(type(line_view_source) is dict and
              any(n.tag == 'script' and n.attrs.get('src') == LINE_VIEW_PATH for n in doc.nodes),
              'LINE_VIEW_NOT_BOUND')
        view_sha = line_view_source['expected_sha256']
        script = _source(line_view_source['raw_bytes'], view_sha).decode('utf-8', 'strict')
        compact = re.sub(r'\s+', '', script)
        _need(all(s in compact for s in _LINE_VIEW_FRAGMENTS), 'LINE_VIEW_CHANGED')
        positions = []
        for row in rows:
            _need(type(row.get('ichi')) is str and re.fullmatch(r'[1-9]|1[0-4]', row['ichi']),
                  'LINE_POSITION_UNSUPPORTED')
            positions.append((int(row['ichi']), int(row['shaban'])))
        _need(len({p for p, _ in positions}) == len(positions), 'LINE_POSITION_DUPLICATED')
        groups, previous = [], None
        for position, car in sorted(positions):
            if previous is None or position != previous+1:
                groups.append([])
            groups[-1].append(car); previous = position
        numeral = {2:'二', 3:'三', 4:'四', 5:'五', 6:'六', 7:'七', 8:'八', 9:'九'}
        _need(len(groups) in numeral and line.get('lineKeitai') == numeral[len(groups)]+'分戦',
              'LINE_GROUP_COUNT_OR_LABEL_UNKNOWN')
        kind = 'PUBLISHED_UNCONTESTED_LINES'
    return dict(kind=kind, groups=groups, provider_raw=line.get('teikyo', ''),
                source_sha256=detail_sha256, view_source_sha256=view_sha,
                source_field='SJ0314.narabiyoso')


def register_day(*, calendar_receipt, list_sources, event_day, now, prior_race_ids=()):
    """Keep every calendar venue and previously registered race in the denominator."""
    now = form._aware(now)
    cal = dict(calendar_receipt, observed_at=form._aware(calendar_receipt['observed_at']))
    parsed = calendar.parse_calendar(cal['raw_bytes'], source_url=calendar.OFFICIAL_DOCUMENT,
        body_sha256=cal['expected_sha256'], received_at=form._aware(cal['observed_at']),
        now=now, http_status=200)
    projection = calendar.project_day(parsed, event_day=event_day)
    expected = set(projection['calendar_venue_candidates'])
    _need(type(list_sources) is list and len(list_sources) <= len(expected), 'LIST_SOURCE_SET_INVALID')
    races, seen, source_shas = [], set(), []
    for source in list_sources:
        venue = source['venue_code']; at = form._aware(source['observed_at'])
        _need(type(venue) is int and venue in expected and venue not in seen and
              source.get('http_status') == 200 and at <= now, 'LIST_SOURCE_OR_CLOCK_INVALID')
        listed = receipt.parse_race_list(source['raw_bytes'], expected_day=event_day,
            expected_venue_code=venue, observed_at=at,
            expected_sha256=source['expected_sha256'], calendar_receipt=cal)
        refs = {r['race_no']: r for r in listed['race_references']}
        for row in listed['day_roster_manifest']['races']:
            races.append(dict(row, official_cutoff_at=None,
                source_state='RESULT_PUBLISHED' if refs[row['race_no']]['link_kind']=='2'
                             else 'RACECARD_PUBLISHED',
                list_source_sha256=source['expected_sha256']))
        seen.add(venue); source_shas.append(source['expected_sha256'])
    prefix = event_day.replace('-', '')
    prior = set(prior_race_ids)
    _need(all(type(r) is str and core.VENUE.fullmatch(r) and r.startswith(prefix) for r in prior),
          'PRIOR_DAY_REGISTRY_INVALID')
    observed = {r['race_id'] for r in races}
    disappeared, missing = sorted(prior-observed), sorted(expected-seen)
    complete = bool(expected) and not missing and not disappeared
    return dict(schema='RACE_AI_OFFICIAL_EXTENSION_DAY_REGISTRY_V1', event_day=event_day,
        state='DAY_REGISTRY_COMPLETE' if complete else 'HOLD_DAY_REGISTRY_INCOMPLETE',
        calendar_source_sha256=cal['expected_sha256'], list_source_sha256=source_shas,
        expected_venues=sorted(expected), observed_venues=sorted(seen), missing_venues=missing,
        disappeared_race_ids=disappeared, registered_race_ids=sorted(observed|prior),
        races=sorted(races,key=lambda x:x['race_id']), day_inventory_complete=complete,
        all_prediction_coverage_complete=False, execution_requires_verified_canary_pass=True)


def collect_day_inventory(*, request, clock, event_day, prior_race_ids=()):
    """Use the runner's ordinary public cookie session to read each listed venue.

    No transport substitution is performed. Any error stops further requests;
    a partial inventory retains all calendar candidates as unresolved. The
    caller must keep returned raw bytes private and owns the canary PASS gate.
    The runner must persist ``provider_denied`` and block later scheduled
    requests after a denial or challenge; persistence is not this parser's job.
    """
    sources, lists, captures, bound = {}, [], [], None
    failure = None
    provider_denied, last_failed_request = False, None

    def reject(attempt, code, *, denied=False):
        nonlocal provider_denied, last_failed_request
        provider_denied = provider_denied or denied
        attempt.update(failure_code='OFFICIAL_EXTENSION_'+code, provider_denied=denied)
        last_failed_request = attempt
        raise OfficialExtensionError(attempt['failure_code'])

    def read(path, fields=None, referer=None):
        _need(path in ('/sp/raceschedule','/sp/racelist','/sp/static/js/SJ0201.js',
                       '/sp/static/js/commonSubmit.js'), 'UNOBSERVED_ROUTE')
        url='https://keirin.jp'+path
        attempt=dict(source_url=url,method='POST' if fields else 'GET',form_fields=fields,
                     http_status=None,captured_at=None)
        captures.append(attempt)
        try:
            response=request(url,fields,referer)
        except (TimeoutError,TimeoutExpired):
            attempt['captured_at']=form._aware(clock()).isoformat()
            reject(attempt,'PROVIDER_TIMEOUT')
        except (OSError,ValueError):
            attempt['captured_at']=form._aware(clock()).isoformat()
            reject(attempt,'PROVIDER_TRANSPORT_UNAVAILABLE')
        if type(response) is not dict:
            reject(attempt,'PROVIDER_RESPONSE_INVALID')
        status=response.get('status')
        if type(status) is int and 100 <= status <= 599:
            attempt['http_status']=status
        try:
            at=form._aware(response.get('observed_at'))
            attempt['captured_at']=at.isoformat()
        except ValueError:
            at=None
        raw=response.get('raw')
        digest=None
        if type(raw) is bytes and 0 < len(raw) <= calendar.MAX_HTML_BYTES:
            digest=sha256(raw).hexdigest()
            sources[digest]=raw
            attempt['bytes_sha256']=digest
        if attempt['http_status'] in (401,403,407,429):
            reject(attempt,'PROVIDER_HTTP_DENIED_'+str(status),denied=True)
        if digest is not None and card_api.browser_source._CHALLENGE.search(raw.decode('utf-8','replace')):
            reject(attempt,'PROVIDER_CHALLENGE_REFUSED',denied=True)
        if attempt['http_status'] is None:
            reject(attempt,'PROVIDER_HTTP_STATUS_UNKNOWN')
        if status!=200:
            reject(attempt,'PROVIDER_HTTP_UNAVAILABLE_'+str(status))
        if response.get('url')!=url:
            reject(attempt,'PROVIDER_REDIRECT_REFUSED')
        if digest is None:
            reject(attempt,'PROVIDER_BODY_INVALID')
        if at is None or at>form._aware(clock()):
            reject(attempt,'SOURCE_CLOCK_AFTER_CAPTURE')
        return dict(raw_bytes=raw,expected_sha256=digest,observed_at=at)

    try:
        bound=read('/sp/raceschedule')
        initial=register_day(calendar_receipt=bound,list_sources=[],event_day=event_day,
                             now=clock(),prior_race_ids=prior_race_ids)
        doc=card_api.browser_source._document(bound['raw_bytes'])
        linked={n.attrs.get('src') for n in doc.nodes if n.tag=='script'}
        for path,parts in (
            ('/sp/static/js/SJ0201.js',('params["encp"]=encp;',
                'params["disp"]="SJ0301";','commonSubmit.formPost(next,params,null);')),
            ('/sp/static/js/commonSubmit.js',('.attr("method","post")',))):
            _need(path in linked,'NAVIGATION_SCRIPT_NOT_LINKED')
            script=read(path)
            text=re.sub(r'\s+','',script['raw_bytes'].decode('utf-8','strict'))
            _need(all(part in text for part in parts),'NAVIGATION_SCRIPT_CHANGED')
        parsed=calendar.parse_calendar(bound['raw_bytes'],source_url=calendar.OFFICIAL_DOCUMENT,
            body_sha256=bound['expected_sha256'],received_at=bound['observed_at'],now=form._aware(clock()),http_status=200)
        projection=calendar.project_day(parsed,event_day=event_day)
        for venue in initial['expected_venues']:
            candidate=[r for r in projection['calendar_meeting_candidates'] if r['venue_code']==venue]
            _need(len(candidate)==1,'CURRENT_MEETING_NOT_UNIQUE')
            nodes=[n for n in doc.nodes if n.tag=='table' and
                sha256(calendar._attribute(n,'onclick').encode()).hexdigest()==candidate[0]['navigation_reference_sha256']]
            _need(len(nodes)==1,'PUBLISHED_MEETING_CONTROL_NOT_UNIQUE')
            match=calendar._REFERENCE.fullmatch(calendar._attribute(nodes[0],'onclick'))
            _need(match is not None,'PUBLISHED_MEETING_CONTROL_CHANGED')
            source=read('/sp/racelist',[('encp',match[1]),('disp','SJ0301')],calendar.OFFICIAL_DOCUMENT)
            receipt.parse_race_list(source['raw_bytes'],expected_day=event_day,expected_venue_code=venue,
                observed_at=source['observed_at'],expected_sha256=source['expected_sha256'],calendar_receipt=bound)
            lists.append(dict(source,venue_code=venue,http_status=200))
    except (ValueError,KeyError,TypeError,OSError) as error:
        code=str(error)
        failure=code if re.fullmatch(r'[A-Z][A-Z0-9_]{0,120}',code) else 'HOLD_DAY_SOURCE_CAPTURE_FAILED'
    registry = None
    if bound is not None:
        try:
            registry=register_day(calendar_receipt=bound,list_sources=lists,event_day=event_day,
                                  now=clock(),prior_race_ids=prior_race_ids)
        except (ValueError,KeyError,TypeError):
            failure=failure or 'HOLD_CALENDAR_DAY_INVALID'
    return dict(state='DAY_SOURCES_CAPTURED' if failure is None else failure,
        registry=registry,calendar_receipt=bound,list_sources=lists,
        source_bytes_by_sha=sources,source_receipts=captures,
        provider_denied=provider_denied, failure_code=failure,
        last_failed_http_status=last_failed_request['http_status'] if last_failed_request else None,
        last_failed_request=last_failed_request,
        execution_requires_verified_canary_pass=True,model_generation=0)


def parse_extension_card(*, list_raw, detail_raw, expected_day, venue_code, race_number,
                         calendar_receipt, list_observed_at, detail_observed_at,
                         list_sha256, detail_sha256, now, line_view_source=None):
    now, at = form._aware(now), form._aware(detail_observed_at)
    calendar_receipt = dict(calendar_receipt,
                            observed_at=form._aware(calendar_receipt['observed_at']))
    listing = receipt.parse_race_list(list_raw, expected_day=expected_day,
        expected_venue_code=venue_code, observed_at=form._aware(list_observed_at),
        expected_sha256=list_sha256, calendar_receipt=calendar_receipt)
    ref = next((r for r in listing['race_references'] if r['race_no']==race_number), None)
    _need(ref is not None and ref['link_kind']=='1', 'FUTURE_CARD_REFERENCE_REQUIRED')
    selected = [r for r in card_api._current_rows(list_raw, expected_day)
                if int(receipt._norm(r['strRaceNo'])) == race_number]
    _need(len(selected)==1, 'CURRENT_RACE_CLASS_MISSING')
    label = receipt._norm(selected[0]['strSyumokuName'])
    _need(label in OBSERVED_CLASSES, 'CLASS_OR_ROUND_NOT_YET_OBSERVED')
    competition = OBSERVED_CLASSES[label]
    card = receipt.parse_race_detail(detail_raw, expected_day=expected_day,
        expected_venue_code=venue_code, expected_race_number=race_number, observed_at=at,
        expected_sha256=detail_sha256, calendar_receipt=calendar_receipt)
    _need(form._aware(list_observed_at) <= at <= now and
          now+timedelta(seconds=65) <= form._aware(card['official_cutoff_at']),
          'FUTURE_CLOCK_MARGIN_REQUIRED')
    _need(card['no_published_roster_exclusion_observed'] and 5 <= len(card['riders']) <= 9,
          'WITHDRAWAL_OR_ROSTER_UNRESOLVED')
    embedded = receipt._embedded(card_api.browser_source._document(detail_raw))
    grades = [receipt._norm(r['kyuhan']) for r in embedded['SJ0315']['sensyuTypeInfo']]
    pattern = RIDER_GRADE_PATTERNS[competition]
    _need(all(re.fullmatch(pattern,g) for g in grades), 'CARD_CLASS_DISAGREEMENT')
    if line_view_source is not None:
        _need(form._aware(line_view_source['observed_at']) <= now, 'LINE_VIEW_AFTER_INPUT')
    lines = parse_published_lines(detail_raw, detail_sha256=detail_sha256,
        starters=[r['car'] for r in card['riders']], competition=competition,
        line_view_source=line_view_source)
    card.update(competition=competition, round_stage_raw=label, round_rule=None,
                line_prediction=lines, model_generation=0)
    return card


def _baseline_profile(raw, registration, observed_at):
    """Validate required statistics without requiring any historical finish."""
    form._registration(registration)
    doc=form._document(raw)
    _need(form._text(form._one(doc,'regnum'))==registration, 'PROFILE_REGISTRATION_MISMATCH')
    updated=form._updated(form._text(form._one(doc,'UNQ_orlabel_99')),observed_at)
    values={number:form._text(form._one(doc,'UNQ_orlabel_'+str(number)))
            for number in (1,14,17,18,19)}
    return dict(name=values[1],source_updated_at=updated.isoformat(),
        original_publication_time=None,stats=dict(
            competition_points=form._number(values[19],0,150),
            win_rate_percent=form._number(values[14],0,100),
            h_count=form._number(values[17],0,200,integral=True),
            b_count=form._number(values[18],0,200,integral=True)))


def build_baseline_candidate(*, card_arguments, prediction_source, prediction_scripts,
                             profile_sources, now):
    """Construct the original A/B input without depending on condition history."""
    now = form._aware(now)
    args = dict(card_arguments, now=now)
    card = parse_extension_card(**args)
    ps = prediction_source
    marks = card_api.parse_prediction_tab(raw_bytes=ps['raw_bytes'],
        expected_sha256=ps['expected_sha256'], observed_at=form._aware(ps['observed_at']),
        now=now, card=card, detail_raw=args['detail_raw'], scripts=prediction_scripts,
        request_url=ps['request_url'], minimum_margin_seconds=65)
    by_car = {r['car']:r for r in marks['riders']}
    _need(type(profile_sources) is list and len(profile_sources)==len(card['riders']),
          'PROFILE_ROSTER_INCOMPLETE')
    by_reg = {s['registration_id']:s for s in profile_sources}
    _need(len(by_reg)==len(profile_sources) and
          set(by_reg)=={r['registration_id'] for r in card['riders']}, 'PROFILE_REGISTRATION_MISMATCH')
    pages = [dict(kind=kind,url='https://keirin.jp/sp/race',bytes_sha256=args['detail_sha256'],
                  captured_at=form._aware(args['detail_observed_at']).isoformat())
             for kind in ('RACECARD','LINE')]
    pages.append(dict(kind='MARKS',url=ps['request_url'],bytes_sha256=ps['expected_sha256'],
                      captured_at=form._aware(ps['observed_at']).isoformat()))
    riders=[]
    for rider in card['riders']:
        registration=rider['registration_id']; source=by_reg[registration]
        at=form._aware(source['observed_at'])
        url='https://keirin.jp/sp/racerracentrecord?snum='+registration
        _need(source.get('source_url')==url and source.get('http_status')==200 and at<=now,
              'PROFILE_SOURCE_OR_CLOCK_INVALID')
        profile=_baseline_profile(_source(source['raw_bytes'],source['expected_sha256']),registration,at)
        stats=profile['stats']
        _need(receipt._norm(profile['name'])==receipt._norm(rider['name']) and
              float(rider['score_raw'])==stats['competition_points'] and
              int(rider['statistics_raw']['backCnt'])==stats['b_count'], 'PROFILE_CARD_DISAGREEMENT')
        riders.append(dict(car=rider['car'],athlete_id=registration,
            mark_rank=by_car[rider['car']]['mark_rank'], competition_points=stats['competition_points'],
            recent_form_score=stats['win_rate_percent']/100,h_count=stats['h_count'],
            b_count=stats['b_count'],style=_style(rider['style_raw'])))
        pages.append(dict(kind='PROGRAM',url=url,bytes_sha256=source['expected_sha256'],captured_at=at.isoformat()))
    snapshot=dict(schema=core.SCHEMA,race_id=card['race_id'],
        as_of=max(form._aware(p['captured_at']) for p in pages).isoformat(),
        published_cutoff_at=card['official_cutoff_at'],
        cutoff_source={k:pages[0][k] for k in ('url','bytes_sha256','captured_at')},
        source_pages=pages,competition=card['competition'],round_stage=card['round_stage_raw'],
        round_rule=None,line_groups=deepcopy(card['line_prediction']['groups']),riders=riders)
    core.validate_snapshot(snapshot,computed_at=now.isoformat())
    return dict(snapshot=snapshot,baseline_state='BASELINE_INPUT_READY',
        condition_state='HOLD_CONDITION_HISTORY_NOT_JOINED',C_state='INDEPENDENT',
        execution_requires_verified_canary_pass=True,model_generation=0,
        all_prediction_coverage_complete=False)


def deadline_candidates(registry, prepared_cards, *, now):
    """Order only actual verified cutoffs; keep unparsed cards in an explicit hold."""
    now=form._aware(now); registered=set(registry['registered_race_ids']); known={}
    for card in prepared_cards:
        rid=card['race_id']
        _need(rid in registered and rid not in known, 'UNREGISTERED_OR_DUPLICATE_CARD')
        cutoff=form._aware(card['official_cutoff_at'])
        known[rid]=dict(race_id=rid,official_cutoff_at=cutoff.isoformat(),
                       state='READY_FOR_SOURCE_CAPTURE' if now+timedelta(seconds=65)<=cutoff
                             else 'CUTOFF_ALREADY_PASSED_OR_TOO_CLOSE')
    result_ids={r['race_id'] for r in registry['races'] if r['source_state']=='RESULT_PUBLISHED'}
    return dict(candidates=sorted(known.values(),key=lambda r:(r['official_cutoff_at'],r['race_id'])),
        unresolved_race_ids=sorted(registered-set(known)-result_ids),
        published_result_race_ids=sorted(result_ids),
        all_prediction_coverage_complete=False,execution_requires_verified_canary_pass=True)
