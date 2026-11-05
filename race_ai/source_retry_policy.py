"""Pure respectful upstream wait policy shared by existing local runners.

No fetching, alternate endpoint, sleep, clock fabrication, credential handling,
or model work. A source denial is never reclassified as permission to collect.
"""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import re

_CODE=re.compile(r'[A-Z][A-Z0-9_]{0,127}\Z')

def _instant(value):
    try:
        stamp=value if isinstance(value,datetime) else datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.utcoffset() is None:raise ValueError()
        return stamp
    except (ValueError,TypeError,AttributeError,OverflowError):
        raise ValueError('SOURCE_RETRY_CLOCK_INVALID') from None

class SourceWait(ValueError):
    def __init__(self,reason,retry_at=None,*,state='SOURCE_WAIT'):
        if not isinstance(reason,str) or not _CODE.fullmatch(reason):reason='SOURCE_REVIEW_REQUIRED'
        if not isinstance(state,str) or not _CODE.fullmatch(state):state='SOURCE_REVIEW_WAIT'
        if retry_at is not None:_instant(retry_at)
        self.reason,self.retry_at,self.state=reason,retry_at,state
        super().__init__(reason)

def plan_http_wait(status,headers,now,attempt=1,not_yet_published=False):
    now=_instant(now)
    if type(attempt) is not int or attempt<1:raise ValueError('SOURCE_RETRY_ATTEMPT_INVALID')
    if status is not None and (type(status) is not int or not 100<=status<=599):
        raise ValueError('SOURCE_RETRY_STATUS_INVALID')
    state,reason='SOURCE_REVIEW_WAIT','SOURCE_REVIEW_REQUIRED'
    retry=None
    if status in (401,403):state,reason='AUTHORIZATION_WAIT','SOURCE_AUTHORIZATION_REQUIRED'
    elif status==429:state,reason='RATE_LIMIT_WAIT','HTTP_RATE_LIMIT'
    elif status is None or status>=500:state,reason='TRANSIENT_SOURCE_WAIT','SOURCE_TEMPORARILY_UNAVAILABLE'
    elif status in (200,404) and not_yet_published:state,reason='WAITING_PUBLICATION','SOURCE_NOT_YET_PUBLISHED'
    if state not in ('AUTHORIZATION_WAIT','SOURCE_REVIEW_WAIT'):
        delay=min(180*(2**min(attempt-1,5)),3600)
        value=(headers.get('Retry-After') or headers.get('retry-after')) if hasattr(headers,'get') else None
        if isinstance(value,str) and len(value.strip())<=256:
            value=value.strip()
            try:
                if re.fullmatch(r'[0-9]+',value):
                    retry=now+timedelta(seconds=max(delay,int(value)))
                else:
                    requested=parsedate_to_datetime(value)
                    if requested.utcoffset() is not None:retry=max(now+timedelta(seconds=delay),requested)
            except OverflowError:
                state,reason='SOURCE_REVIEW_WAIT','SERVER_RETRY_TIME_UNREPRESENTABLE'
            except (ValueError,TypeError,AttributeError):pass
        if retry is None and state!='SOURCE_REVIEW_WAIT':
            try:retry=now+timedelta(seconds=delay)
            except OverflowError:state,reason='SOURCE_REVIEW_WAIT','SERVER_RETRY_TIME_UNREPRESENTABLE'
    return dict(state=state,reason=reason,retry_at=retry.isoformat() if retry else None,
                http_status=status,attempts=attempt)

def wait_active(wait,now):
    now=_instant(now)
    if wait is None:return False
    if not isinstance(wait,dict) or not isinstance(wait.get('reason'),str) or not _CODE.fullmatch(wait['reason']):
        raise ValueError('SOURCE_WAIT_STATE_INVALID')
    if wait.get('state') in ('AUTHORIZATION_WAIT','SOURCE_REVIEW_WAIT'):return True
    retry=wait.get('retry_at')
    return retry is None or now<_instant(retry)
