"""Bounded standard-SP collection and source reconstruction for continuation.

All source I/O shares one ordinary session and the source-specific lease.
Raw data and form tokens stay private. Conditions reuse the original history
selection and assessment rules; this module contains no prediction engine.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from . import keirin_official_nationwide_extension as extension
from . import keirin_official_canary_card as cards
from . import keirin_official_canary_join as join
from . import keirin_official_form_history as form
from . import keirin_github_provider_stop as stop
from . import keirin_result_diagnostics as diagnostics
from . import keirin_nationwide_auto_generator as model
from . import keirin_form_fall_shadow as shadow
from . import keirin_rider_form_evidence as conditions
from scripts import keirin_capture_official_form_history as history


class SourceError(ValueError):
    pass


class CaptureBudgetPending(SourceError):
    """Capture stopped before requesting permission for another provider call."""


REQUEST_SPACING_SECONDS = 1
# Leave time for GitHub lease verification and the 25-second transport process.
CAPTURE_LEASE_RESERVE_SECONDS = 60
CAPTURE_START_MARGIN_SECONDS = 390
CAPTURE_FINALIZATION_SECONDS = 240
CONDITION_REQUEST_LIMIT = 90
CONDITION_DURATION_SECONDS = 120


def need(ok, code):
    if not ok: raise SourceError('OFFICIAL_CONTINUATION_'+code)


STATIC_PURPOSES = {
    '/sp/raceschedule':'OFFICIAL_CALENDAR', '/sp/racelist':'OFFICIAL_RACE_LIST',
    '/sp/static/js/SJ0201.js':'CALENDAR_SCRIPT',
    '/sp/static/js/commonSubmit.js':'FORM_SCRIPT',
    '/sp/static/js/SJ0301_v.js':'RACE_LIST_VIEW_SCRIPT',
    '/sp/static/js/SJ0301_c.js':'RACE_LIST_CONTROLLER_SCRIPT',
    '/sp/static/js/SJ0314_v.js':'LINE_VIEW_SCRIPT',
    '/sp/static/js/FSJ0315.js':'PREDICTION_FRAME_SCRIPT',
    '/sp/static/js/SJ0321_c.js':'PREDICTION_CONTROLLER_SCRIPT',
    '/sp/static/js/commonJSON.js':'PUBLIC_JSON_SCRIPT',
    '/sp/static/js/SJ0321_v.js':'PREDICTION_VIEW_SCRIPT',
}
LIST_SCRIPTS = {
    '/sp/static/js/SJ0301_v.js':('raceProgram.strRaceLnk','raceProgram.strRaceLnkPrm','raceProgram.strRaceLnkKbn'),
    '/sp/static/js/SJ0301_c.js':('varaction=$(children[1]).attr("value");',
        'params["encp"]=$(children[2]).attr("value");','if(dispDI==1){dispDI="SJ0315";}',
        'if(dispDI==2){dispDI="SJ0326";}',
        'commonSubmit.formPost(action,params);'),
}


class OfficialSourceSession:
    def __init__(self, *, repo, private_root, lease, clock, request=None,
                 sleep=time.sleep, monotonic=time.monotonic):
        self.repo, self.root = repo, history._private_directory(private_root)
        self.lease, self.clock = lease, clock
        self.transport = None
        if request is None:
            self.transport = cards._CurlPublicSession(str(self.root), clock)
            request = self.transport.request
        self._request = request
        self.cache, self.sources, self.receipts, self.safe_diagnostics = {}, {}, [], []
        self.halted = self.provider_denied = False
        self.count = 0
        self.sleep,self.monotonic=sleep,monotonic
        self._last_request=None;self._source_bytes=0
        self.capture_deadline=None
        self.capture_budget_enabled=False

    def has_capture_capacity(self, requests, *, seconds=CAPTURE_LEASE_RESERVE_SECONDS):
        if self.halted:
            return False
        try:
            left, remaining = self.lease.remaining_capture_capacity(now=self.clock())
        except Exception:
            self.halted = True
            return False
        return left >= requests and remaining > seconds

    def close(self):
        if self.transport is not None: self.transport.close()

    def _purpose(self, url, fields, purpose):
        path = urlsplit(url).path
        if path in STATIC_PURPOSES: return STATIC_PURPOSES[path]
        if url.startswith('https://keirin.jp/sp/json?'): return 'OFFICIAL_PREDICTION_TAB'
        if url.startswith('https://keirin.jp/sp/racerracentrecord?snum='): return 'OFFICIAL_PROFILE'
        if url == 'https://www.hofukeirin.jp/ticket/': return 'OFFICIAL_PAYOUT_UNIT'
        if url == 'https://keirin.jp/sp/race':
            mode = dict(fields or []).get('disp')
            if mode == 'SJ0315': return 'OFFICIAL_CARD'
            if mode == 'SJ0326' and purpose in ('OFFICIAL_FINAL_RESULT','OFFICIAL_HISTORY_RESULT'):
                return purpose
        need(False, 'UNPUBLISHED_SOURCE_ROUTE')

    def _diagnostic(self, purpose, url, method, stage, reason, status=None):
        parsed = urlsplit(url)
        # Source URL queries, tokens, headers and exception text never enter
        # the public diagnostic. Registry + guard bind this fixed path.
        at=form._aware(self.clock()).isoformat()
        status=status if type(status) is int and 100<=status<=599 else None
        if purpose in diagnostics.ROUTES:
            row=diagnostics.make_diagnostic(purpose=purpose,stage=stage,reason=reason,
                http_status=status,observed_at=at)
        else:
            from .keirin_official_source_continuation import ROUTES
            need(purpose in ROUTES and ROUTES[purpose]==(parsed.hostname,parsed.path,method) and
                 stage in diagnostics.STAGES and reason in diagnostics.REASONS,'DIAGNOSTIC_SCOPE')
            row=dict(schema='RACE_AI_KEIRIN_OFFICIAL_SP_DIAGNOSTIC_V1',purpose=purpose,
                source_host=parsed.hostname,source_path=parsed.path,method=method,
                stage=stage,reason=reason,http_status=status,observed_at=at)
        self.safe_diagnostics.append(row)
        self.safe_diagnostics = self.safe_diagnostics[-32:]

    def fetch(self, url, fields=None, referer=None, *, purpose=None):
        need(not self.halted, 'SOURCE_SESSION_STOPPED')
        need(fields is None or type(fields) in (list,tuple) and
             all(type(item) in (list,tuple) and len(item)==2 and
                 all(type(value) is str for value in item) for item in fields),
             'FORM_PAIRS_REQUIRED')
        purpose = self._purpose(url, fields, purpose)
        method = 'POST' if fields is not None else 'GET'
        key = (url, tuple(tuple(item) for item in (fields or [])))
        if key in self.cache: return self.cache[key]
        # Keep the existing official history collector's one-second spacing.
        # Permission is checked after waiting, never borrowed across expiry.
        if self._last_request is not None:
            elapsed=self.monotonic()-self._last_request
            need(elapsed>=0,'MONOTONIC_CLOCK_CHANGED')
            if elapsed<REQUEST_SPACING_SECONDS:self.sleep(REQUEST_SPACING_SECONDS-elapsed)
        if self.capture_deadline is not None and form._aware(self.clock()) >= self.capture_deadline:
            raise CaptureBudgetPending('OFFICIAL_CONTINUATION_CAPTURE_FINALIZATION_RESERVE')
        if self.capture_budget_enabled and not self.has_capture_capacity(1):
            if self.halted:
                self._diagnostic(purpose,url,method,'REQUEST','SOURCE_VALIDATION_FAILED')
                raise SourceError('OFFICIAL_CONTINUATION_SOURCE_LEASE_CLOSED')
            raise CaptureBudgetPending('OFFICIAL_CONTINUATION_CAPTURE_SOFT_BUDGET_PENDING')
        try:
            self.lease.before_request(purpose=purpose, method=method, url=url,
                                      fields=fields, now=self.clock())
        except Exception:
            self.halted = True
            self._diagnostic(purpose,url,method,'REQUEST','SOURCE_VALIDATION_FAILED')
            raise SourceError('OFFICIAL_CONTINUATION_SOURCE_LEASE_CLOSED') from None
        self.count += 1
        self._last_request=self.monotonic()
        try:
            response = self._request(url, fields, referer)
        except Exception:
            self.halted = True
            self._diagnostic(purpose,url,method,'REQUEST','TRANSPORT_FAILED')
            raise SourceError('OFFICIAL_CONTINUATION_SOURCE_TRANSPORT_FAILED') from None
        status = response.get('status') if type(response) is dict else None
        raw = response.get('raw') if type(response) is dict else None
        denied = type(status) is int and status in (401,403,407,429)
        challenge = (diagnostics.challenge_reason(raw,
            passive_guide_scripts=purpose=='OFFICIAL_PAYOUT_UNIT')
            if type(raw) is bytes and 0<len(raw)<=cards.calendar.MAX_HTML_BYTES else None)
        if denied or challenge:
            self.halted = self.provider_denied = True
            self._diagnostic(purpose,url,method,'HTTP_RESPONSE' if denied else 'CONTENT_CHECK',
                             'HTTP_DENIED' if denied else challenge,status)
            try:
                stop.record_denial(repo=self.repo,code=stop.DENIED,
                                   observed_at=form._aware(self.clock()).isoformat())
            except Exception:
                raise SourceError('OFFICIAL_CONTINUATION_STOP_PERSISTENCE_FAILED_NO_RETRY') from None
            raise SourceError('OFFICIAL_CONTINUATION_PROVIDER_DENIED_NO_RETRY')
        if type(status) is not int or status != 200 or response.get('url') != url:
            self.halted = True
            self._diagnostic(purpose,url,method,'HTTP_RESPONSE',
                'REDIRECT_REFUSED' if type(response) is dict and response.get('url')!=url else 'HTTP_ERROR',status)
            raise SourceError('OFFICIAL_CONTINUATION_SOURCE_HTTP_UNAVAILABLE')
        try:
            at = form._aware(response['observed_at'])
            need(type(raw) is bytes and 0<len(raw)<=cards.calendar.MAX_HTML_BYTES and
                 at<=form._aware(self.clock()), 'SOURCE_BYTES_OR_CLOCK_INVALID')
        except (KeyError,TypeError,ValueError):
            self.halted = True
            self._diagnostic(purpose,url,method,'CONTENT_CHECK','SOURCE_BYTES_INVALID',status)
            raise SourceError('OFFICIAL_CONTINUATION_SOURCE_BYTES_OR_CLOCK_INVALID') from None
        digest = sha256(raw).hexdigest()
        addition=0 if digest in self.sources else len(raw)
        if self._source_bytes+addition>64*1024*1024:
            self.halted=True
            self._diagnostic(purpose,url,method,'CONTENT_CHECK','SOURCE_BYTES_INVALID',status)
            raise SourceError('OFFICIAL_CONTINUATION_SOURCE_TOTAL_BYTE_BOUND')
        self._source_bytes+=addition
        self.sources[digest] = raw
        history._save_once(self.root/(digest+'.bin'),raw)
        receipt = dict(source_url=url,method=method,form_fields=dict(fields) if fields else None,
                       http_status=status,captured_at=at.isoformat(),bytes_sha256=digest,kind='PROGRAM')
        self.receipts.append(receipt)
        history._save_once(self.root/(sha256(history._json_bytes(receipt)).hexdigest()+'.json'),
                          history._json_bytes(receipt))
        result = dict(raw_bytes=raw,expected_sha256=digest,observed_at=at.isoformat(),
            source_url=url,request_url=url,http_status=status,receipt=receipt)
        self.cache[key] = result
        self._diagnostic(purpose,url,method,'CONTENT_CHECK','SOURCE_ACCEPTED',status)
        return result

    def request(self, url, fields=None, referer=None):
        source = self.fetch(url,fields,referer)
        return dict(url=url,status=source['http_status'],raw=source['raw_bytes'],
                    observed_at=form._aware(source['observed_at']))


def require_list_scripts(session, listed):
    doc = cards.browser_source._document(listed['raw_bytes'])
    linked = {n.attrs.get('src') for n in doc.nodes if n.tag=='script'}
    for path, required in LIST_SCRIPTS.items():
        need(path in linked, 'LIST_SCRIPT_NOT_LINKED')
        source = session.fetch('https://keirin.jp'+path)
        compact = re.sub(r'\s+','',source['raw_bytes'].decode('utf-8','strict'))
        need(all(part in compact for part in required),'LIST_SCRIPT_CHANGED')


def _read_capture_card(*, session, inventory, race):
    day, venue, number = inventory['registry']['event_day'], race['venue_code'], race['race_no']
    listed = next(s for s in inventory['list_sources'] if s['venue_code']==venue)
    require_list_scripts(session, listed)
    cal = inventory['calendar_receipt']
    parsed = cards.receipt.parse_race_list(listed['raw_bytes'],expected_day=day,
        expected_venue_code=venue,observed_at=form._aware(listed['observed_at']),
        expected_sha256=listed['expected_sha256'],calendar_receipt=cal)
    ref = next(r for r in parsed['race_references'] if r['race_no']==number)
    need(ref['link_kind']=='1' and ref['path']=='/sp/race','FUTURE_REFERENCE_REQUIRED')
    raw = session.fetch('https://keirin.jp/sp/race',
        [('encp',ref['opaque_reference']),('disp','SJ0315')],'https://keirin.jp/sp/racelist')
    args = dict(list_raw=listed['raw_bytes'],detail_raw=raw['raw_bytes'],expected_day=day,
        venue_code=venue,race_number=number,calendar_receipt=cal,
        list_observed_at=listed['observed_at'],detail_observed_at=raw['observed_at'],
        list_sha256=listed['expected_sha256'],detail_sha256=raw['expected_sha256'])
    current = next(r for r in cards._current_rows(listed['raw_bytes'],day)
                   if int(cards.receipt._norm(r['strRaceNo']))==number)
    label = cards.receipt._norm(current['strSyumokuName'])
    need(label in extension.OBSERVED_CLASSES,'CLASS_OR_ROUND_NOT_OBSERVED')
    return args, label


def collect_capture_cutoff(*, session, inventory, race, clock):
    """Use an exact current card as an ordering hint within the source budget."""
    args, _ = _read_capture_card(session=session, inventory=inventory, race=race)
    observed = form._aware(args['detail_observed_at'])
    need(form._aware(args['list_observed_at']) <= observed <= form._aware(clock()), 'CUTOFF_CARD_CLOCK_INVALID')
    detail = cards.receipt.parse_race_detail(args['detail_raw'], expected_day=args['expected_day'],
        expected_venue_code=args['venue_code'], expected_race_number=args['race_number'],
        observed_at=observed, expected_sha256=args['detail_sha256'],
        calendar_receipt=args['calendar_receipt'])
    return None if detail['race_cancelled'] else form._aware(detail['official_cutoff_at'])


def collect_candidate(*, session, inventory, race, clock):
    args, label = _read_capture_card(session=session, inventory=inventory, race=race)
    detail_raw = args['detail_raw']
    if extension.OBSERVED_CLASSES[label] != 'GIRLS':
        doc = cards.browser_source._document(detail_raw)
        need(any(n.tag=='script' and n.attrs.get('src')==extension.LINE_VIEW_PATH for n in doc.nodes),
             'LINE_VIEW_NOT_LINKED')
        args['line_view_source'] = session.fetch('https://keirin.jp'+extension.LINE_VIEW_PATH)
    card = extension.parse_extension_card(**args,now=clock())
    need((form._aware(card['official_cutoff_at'])-form._aware(clock())).total_seconds()
         >= CAPTURE_START_MARGIN_SECONDS,
         'CAPTURE_START_MARGIN_REQUIRED')
    linked = {n.attrs.get('src') for n in cards.browser_source._document(detail_raw).nodes if n.tag=='script'}
    need(set(cards._TAB_SCRIPT_REQUIREMENTS)<=linked,'MARKS_SCRIPTS_NOT_LINKED')
    scripts = {path:session.fetch('https://keirin.jp'+path)['raw_bytes']
               for path in cards._TAB_SCRIPT_REQUIREMENTS}
    request = cards.derive_prediction_tab_request(detail_raw,scripts)
    prediction = session.fetch(request['url'],referer='https://keirin.jp/sp/race')
    profiles = []
    for rider in card['riders']:
        source = session.fetch('https://keirin.jp/sp/racerracentrecord?snum='+rider['registration_id'])
        profiles.append(dict(source,registration_id=rider['registration_id']))
    arguments = dict(card_arguments=args,prediction_source=prediction,
                     prediction_scripts=scripts,profile_sources=profiles)
    candidate = extension.build_baseline_candidate(**arguments,now=clock())
    return dict(candidate,arguments=arguments,card=card)


class GuardedHistoryCapture(history.OfficialHistoryCapture):
    """Use the existing rider selection with injected shared, leased transport."""
    def __init__(self, *, session, cutoff_at, target_race_id, clock, max_requests=CONDITION_REQUEST_LIMIT,
                 duration_seconds=CONDITION_DURATION_SECONDS, monotonic=time.monotonic):
        self.session, self.clock, self.monotonic = session, clock, monotonic
        self.cutoff = form._aware(cutoff_at)
        self.target_race_id = target_race_id
        self.target_date = datetime.strptime(target_race_id[:8],'%Y%m%d').date()
        self.max_requests, self.count = max_requests, 0
        self.deadline = monotonic()+duration_seconds
        self.receipts, self.cache, self.profile_url = [], {}, None

    def check(self):
        if form._aware(self.clock()) + timedelta(seconds=CAPTURE_FINALIZATION_SECONDS) >= self.cutoff:
            raise CaptureBudgetPending('OFFICIAL_CONTINUATION_CONDITION_MARGIN_EXHAUSTED')
        if self.count >= self.max_requests or self.monotonic() >= self.deadline:
            raise CaptureBudgetPending('OFFICIAL_CONTINUATION_CONDITION_CAPTURE_BUDGET')

    def fetch(self, url, *, token=None):
        key = (url,token)
        if key in self.cache: return self.cache[key]
        self.check()
        if token is None:
            source = self.session.fetch(url)
            self.profile_url = url
        else:
            need(self.profile_url is not None,'HISTORY_PROFILE_REQUIRED')
            source = self.session.fetch(url,[('encp',token),('disp','SJ0326')],
                self.profile_url,purpose='OFFICIAL_HISTORY_RESULT')
        self.count += 1
        row = source['receipt']
        if row not in self.receipts: self.receipts.append(row)
        self.cache[key] = (source['raw_bytes'],row)
        self.check()
        return self.cache[key]


def collect_conditions(*, session, candidate, clock):
    card = candidate['card']
    capture = GuardedHistoryCapture(session=session,cutoff_at=card['official_cutoff_at'],
                                   target_race_id=card['race_id'],clock=clock)
    riders = [capture.capture_rider(car=r['car'],registration_id=r['registration_id'])
              for r in card['riders']]
    return dict(schema='RACE_AI_KEIRIN_OFFICIAL_FORM_CAPTURE_V1',
        state='OFFICIAL_FORM_HISTORY_CAPTURED',target_race_id=card['race_id'],
        captured_at=form._aware(clock()).isoformat(),riders=riders,source_receipts=capture.receipts)


def build_condition_candidate(*, snapshot, card_arguments, prediction_source,
                              prediction_scripts, history_manifest, source_bytes_by_sha, now):
    """Rebuild conditions for the same verified roster, without a girls-only join."""
    now = form._aware(now)
    card = extension.parse_extension_card(**card_arguments,now=now)
    ps = prediction_source
    marks = cards.parse_prediction_tab(raw_bytes=ps['raw_bytes'],expected_sha256=ps['expected_sha256'],
        observed_at=form._aware(ps['observed_at']),now=now,card=card,
        detail_raw=card_arguments['detail_raw'],scripts=prediction_scripts,
        request_url=ps['request_url'],minimum_margin_seconds=65)
    need(snapshot['race_id']==card['race_id'] and
         snapshot['published_cutoff_at']==card['official_cutoff_at'],'BASELINE_CARD_IDENTITY')
    rid = card['race_id']; captured_riders = history_manifest.get('riders'); receipts = history_manifest.get('source_receipts')
    need(history_manifest.get('schema')=='RACE_AI_KEIRIN_OFFICIAL_FORM_CAPTURE_V1' and
         history_manifest.get('state')=='OFFICIAL_FORM_HISTORY_CAPTURED' and
         history_manifest.get('target_race_id')==rid and type(captured_riders) is list and
         len(captured_riders)==len(card['riders']) and type(receipts) is list and 1<=len(receipts)<=150,
         'CONDITION_MANIFEST_INVALID')
    need({(r.get('car'),r.get('registration_id')) for r in captured_riders}==
         {(r['car'],r['registration_id']) for r in card['riders']},'CONDITION_ROSTER_MISMATCH')
    need(all(r.get('http_status')==200 and form._aware(r['captured_at'])<=now for r in receipts),
         'CONDITION_RECEIPT_INVALID')
    by_car = {r['car']:r for r in marks['riders']}
    tab = dict(url=ps['request_url'],bytes_sha256=ps['expected_sha256'],captured_at=ps['observed_at'])
    pages = {ps['expected_sha256']:join._page(tab)}
    evidence, identities, availability, total = [], [], [], 0
    base_by_car = {r['car']:r for r in snapshot['riders']}
    for rider in card['riders']:
        car, registration = rider['car'],rider['registration_id']
        captured = join._one(captured_riders,lambda r:r.get('car')==car,'HISTORY_CAR_DUPLICATE')
        psha = captured.get('profile',{}).get('source_sha256')
        psource = join._one(receipts,lambda r:r.get('bytes_sha256')==psha and
            r.get('source_url')=='https://keirin.jp/sp/racerracentrecord?snum='+registration,
            'PROFILE_REGISTRATION_RECEIPT_MISSING')
        need(psource.get('method')=='GET','PROFILE_METHOD_INVALID')
        profile = form.parse_profile(join._raw(source_bytes_by_sha,psha),
            expected_registration_id=registration,observed_at=psource['captured_at'])
        need(cards.receipt._norm(profile['name'])==cards.receipt._norm(rider['name']) and
             base_by_car[car]['athlete_id']==registration and
             base_by_car[car]['competition_points']==profile['stats']['competition_points'] and
             base_by_car[car]['h_count']==profile['stats']['h_count'] and
             base_by_car[car]['b_count']==profile['stats']['b_count'] and
             base_by_car[car]['recent_form_score']==profile['stats']['win_rate_percent']/100,
             'BASELINE_PROFILE_CHANGED')
        pages[psha] = join._page(psource)
        refs = {r['token_sha256']:r for r in profile['history_references']}
        rows, history_shas, seen, by_ref = [], [], set(), {}
        need(type(captured.get('results')) is list and 1<=len(captured['results'])<=40,'HISTORY_RESULT_SET')
        for hint in captured['results']:
            token_sha,digest = hint.get('reference_token_sha256'),hint.get('source_sha256')
            need(token_sha in refs,'HISTORY_UNPUBLISHED_REFERENCE'); ref=refs[token_sha]
            source = join._one(receipts,lambda r:r.get('bytes_sha256')==digest and
                r.get('form_fields')=={'encp':ref['token'],'disp':'SJ0326'},'HISTORY_REFERENCE_RECEIPT')
            need(source.get('source_url')==ref['source_url'] and source.get('method')=='POST',
                 'HISTORY_SOURCE_INVALID')
            result = form.parse_history_result(join._raw(source_bytes_by_sha,digest),
                expected_registration_id=registration,observed_at=source['captured_at'],expected_reference=ref)
            need(result['race_id'] not in seen and result['race_id'][:8]<rid[:8] and
                 result['status'] in conditions.RESULT_STATES,'HISTORY_FUTURE_OR_DUPLICATE')
            seen.add(result['race_id']); history_shas.append(digest); by_ref[token_sha]=result
            rows.append({k:result[k] for k in ('race_id','race_date','status','place','field_size')})
            rows[-1].update(published_at=result['source_updated_at'],source_sha256=digest)
            pages[digest]=join._page(source)
        need(sum(r['status']=='FINISHED' for r in rows)>=6,'SIX_NORMAL_FINISHES_REQUIRED')
        join._require_capture_selection(profile,by_ref); total += len(rows)
        comment = unescape(by_car[car].get('comment_raw',''))
        usable = bool(comment) and len(comment)<=300 and all(ord(c)>=32 for c in comment)
        comments = [dict(speaker='MEDIA',text=comment,published_at=marks['publisher_updated_at'],
                         source_sha256=ps['expected_sha256'])] if usable else []
        evidence.append(dict(car=car,results=sorted(rows,key=lambda r:(r['race_date'],r['race_id'])),
                             absences=[],comments=comments))
        identities.append(dict(car=car,registration_id=registration,card_sha256=card['source_sha256'],
            marks_sha256=ps['expected_sha256'],profile_sha256=psha,history_sha256=history_shas))
        availability.append(dict(car=car,registration_id=registration,
            absence_observations=profile['absence_observations'],comment_preserved_in_source=bool(comment),
            comment_encoded_in_v1=usable,profile_history_index_count=len(profile['history_references']),
            acquired_result_count=len(rows),exhaustive_fall_history_claimed=False))
    asof=max(form._aware(p['captured_at']) for p in pages.values()).isoformat()
    supplement=dict(schema=shadow.SUPPLEMENT_SCHEMA,race_id=rid,source_pages=list(pages.values()),
        condition_evidence=dict(schema=conditions.SCHEMA,as_of=asof,riders=evidence))
    shadow.source_bundle(snapshot,supplement,generated_at=now.isoformat())
    return dict(supplement=supplement,identity_proof=dict(
        schema='RACE_AI_KEIRIN_OFFICIAL_IDENTITY_JOIN_V1',race_id=rid,verified_riders=len(evidence),
        verified_rider_results=total,source_facts_sha256=model.digest(snapshot),
        supplement_sha256=model.digest(supplement),independent_origin_attested=False,bindings=identities),
        availability=dict(timestamp_basis='DISPLAYED_PAGE_UPDATE_NOT_FIRST_PUBLICATION',
            absence_records_without_verified_period=sum(len(r['absence_observations']) for r in availability),
            medical_recovery_inferred=False,riders=availability))


def collect_final(*,session,inventory,original,clock):
    """Capture a source-published final reference, then optional money basis."""
    from . import keirin_official_reviewed_pdf as unit_source
    rid=original['race_id'];day=original['day_jst'];venue=int(rid[8:10]);number=int(rid[10:])
    listed=next((s for s in inventory['list_sources'] if s['venue_code']==venue),None)
    need(listed is not None,'RESULT_VENUE_NOT_PUBLISHED')
    cal=inventory['calendar_receipt'];require_list_scripts(session,listed)
    parsed=cards.receipt.parse_race_list(listed['raw_bytes'],expected_day=day,expected_venue_code=venue,
        observed_at=form._aware(listed['observed_at']),expected_sha256=listed['expected_sha256'],calendar_receipt=cal)
    ref=next((r for r in parsed['race_references'] if r['race_no']==number),None)
    need(ref is not None and ref['link_kind']=='2' and ref['path']=='/sp/race','RESULT_NOT_PUBLISHED')
    result=session.fetch('https://keirin.jp/sp/race',
        [('encp',ref['opaque_reference']),('disp','SJ0326')],'https://keirin.jp/sp/racelist',
        purpose='OFFICIAL_FINAL_RESULT')
    reference=dict(source_url='https://keirin.jp/sp/race',method='POST',disp='SJ0326',
        token=ref['opaque_reference'],official_cutoff_at=original['baseline']['published_cutoff_at'],
        starters=[dict(car=r['car'],registration_id=r['athlete_id']) for r in original['snapshot']['riders']])
    order=form.parse_final_result(result['raw_bytes'],expected_race_id=rid,
        observed_at=result['observed_at'],expected_reference=reference)
    unit=None;unit_at=None;unit_state='UNAVAILABLE';raws={result['expected_sha256']:result['raw_bytes']}
    try:
        guide=session.fetch('https://www.hofukeirin.jp/ticket/')
        exact=unit_source.UNIT_URLS[guide['source_url']]
        need(exact.encode() in guide['raw_bytes'],'PAYOUT_UNIT_NOT_PUBLISHED')
        unit=dict(url=guide['source_url'],source_sha256=guide['expected_sha256'],
            observed_at=guide['observed_at'],verified_payout_basis_yen=100,exact_excerpt=exact)
        unit_at=form._aware(clock()).isoformat();unit_state='VERIFIED'
        raws[guide['expected_sha256']]=guide['raw_bytes']
    except (ValueError,KeyError,TypeError) as exc:
        if str(exc)=='OFFICIAL_CONTINUATION_STOP_PERSISTENCE_FAILED_NO_RETRY':raise
        unit_state='PROVIDER_STOPPED' if session.provider_denied else 'UNAVAILABLE'
    scripts={path:session.cache[('https://keirin.jp'+path,())]['raw_bytes'] for path in LIST_SCRIPTS}
    safe=[row for row in session.safe_diagnostics if row['purpose'] in diagnostics.ROUTES]
    final=dict(raw_result=result['raw_bytes'],observed_at=result['observed_at'],expected_reference=reference,
        unit_evidence=unit,unit_verified_at=unit_at,payout_unit_state=unit_state,
        source_bytes_by_sha=raws,calendar_receipt=cal,list_source=listed,list_scripts=scripts,
        safe_diagnostics=diagnostics.checked_diagnostics(safe),official_order=order)
    reparse_final(original,final)
    return final


def reparse_final(original,final):
    """Rebind the exact final token to its retained calendar/list and roster."""
    rid=original['race_id'];day=original['day_jst'];listed=final['list_source'];cal=final['calendar_receipt']
    parsed=cards.receipt.parse_race_list(listed['raw_bytes'],expected_day=day,
        expected_venue_code=int(rid[8:10]),observed_at=form._aware(listed['observed_at']),
        expected_sha256=listed['expected_sha256'],calendar_receipt=dict(cal,observed_at=form._aware(cal['observed_at'])))
    ref=next((r for r in parsed['race_references'] if r['race_no']==int(rid[10:])),None)
    reference=final['expected_reference']
    need(ref is not None and ref['link_kind']=='2' and ref['path']=='/sp/race' and
         ref['opaque_reference']==reference['token'] and
         reference['official_cutoff_at']==original['baseline']['published_cutoff_at'] and
         reference['starters']==[dict(car=r['car'],registration_id=r['athlete_id']) for r in original['snapshot']['riders']],
         'RESULT_REFERENCE_OR_ROSTER_CHANGED')
    need(form._aware(cal['observed_at'])<=form._aware(listed['observed_at'])<=form._aware(final['observed_at']),
         'RESULT_NAVIGATION_CLOCK')
    linked={n.attrs.get('src') for n in cards.browser_source._document(listed['raw_bytes']).nodes if n.tag=='script'}
    need(set(final['list_scripts'])==set(LIST_SCRIPTS) and set(LIST_SCRIPTS)<=linked,'RESULT_SCRIPT_BINDING')
    for path,parts in LIST_SCRIPTS.items():
        compact=re.sub(r'\s+','',final['list_scripts'][path].decode('utf-8','strict'))
        need(all(part in compact for part in parts),'RESULT_SCRIPT_CHANGED')
    parsed=form.parse_final_result(final['raw_result'],expected_race_id=rid,observed_at=final['observed_at'],
        expected_reference=reference,verified_unit_evidence=final.get('unit_evidence'),
        source_bytes_by_sha=final['source_bytes_by_sha'],unit_verified_at=final.get('unit_verified_at'))
    return parsed
