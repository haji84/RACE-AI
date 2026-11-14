"""Pure JRA HTTP sidecar from complete capture-time originals.

Legacy/imported captures remain readable but cannot supply observations they
never retained. No fetching, key access, clock assignment or header synthesis.
"""
from hashlib import sha256
import re

from . import manual_official_capture as capture

SCHEMA='RACE_AI_JRA_HTTP_SIDECAR_BUILD_V1'


def _need(ok,reason):
    if not ok:raise ValueError('JRA_HTTP_SIDECAR_'+reason)


def _build(cache,bodies):
    capture._validate_cache(cache)
    sources=cache['captures'];day=capture._day(cache['execution_day'])
    _need(type(bodies) is dict and 1<=len(sources)<=capture.MAX_REQUESTS and set(bodies)==set(sources),'EXACT_RETAINED_SOURCES')
    metadata={};used=set()
    for url,source in sorted(sources.items()):
        _need(capture._url(url)[0]=='horse' and source['capture_origin']=='HTTP_GET' and
              source['url']==source['final_url']==url and source['redirect_chain']==[url],'DIRECT_ORIGINAL_JRA_GET_REQUIRED')
        raw=bodies[url]
        _need(type(raw) is bytes and len(raw)==source['size'] and sha256(raw).hexdigest()==source['source_sha256'],'ORIGINAL_BYTES')
        http=source.get('http_metadata')
        _need(type(http) is dict,'CAPTURE_TIME_HTTP_OBSERVATIONS_REQUIRED')
        matches=[(number,attempt) for number,attempt in enumerate(cache['attempts'],1)
                 if attempt['target_url']==url and attempt['state']=='SUCCESS']
        _need(len(matches)==1,'UNIQUE_SUCCESS_ATTEMPT_REQUIRED')
        number,attempt=matches[0]
        _need(number==http['attempt_no'] and number not in used and attempt['url']==url==http['source_url']==http['final_url'] and
              attempt['started_at']==http['fetched_at'] and attempt['http_status']==http['status']==200 and
              url not in cache['failures'],'ACTUAL_ATTEMPT_BINDING')
        used.add(number)
        clocks=[capture._time(value) for value in (attempt['started_at'],http['headers_received_at'],
                                                  http['response_received_at'],attempt['finished_at'])]
        _need(clocks==sorted(clocks) and all(clock.astimezone(capture.JST).date()==day for clock in clocks),'ACTUAL_ATTEMPT_CLOCK')
        pairs=http['headers'];names=[name.lower() for name,_ in pairs]
        _need(len(names)==len(set(names)) and 'content-type' in names,'UNAMBIGUOUS_ORIGINAL_HEADERS_REQUIRED')
        headers=dict(pairs);content_type=pairs[names.index('content-type')][1]
        _need(content_type==source['content_type'] and content_type.split(';',1)[0].strip().lower() in
              ('text/html','application/xhtml+xml'),'ACTUAL_HTML_MIME_REQUIRED')
        charsets=re.findall(r'\bcharset\s*=\s*[\'\"]?([\w-]+)',content_type,re.I)
        _need(len(charsets)==1,'EXPLICIT_ORIGINAL_CHARSET_REQUIRED')
        encoding=charsets[0].lower();encoding={'shift_jis':'cp932','shift-jis':'cp932','utf8':'utf-8'}.get(encoding,encoding)
        _need(encoding in ('cp932','utf-8'),'SUPPORTED_ORIGINAL_CHARSET_REQUIRED')
        raw.decode(encoding,'strict')
        length=[value for name,value in pairs if name.lower()=='content-length']
        _need(not length or length[0].isdigit() and int(length[0])==len(raw),'ORIGINAL_CONTENT_LENGTH')
        content_encoding=[value for name,value in pairs if name.lower()=='content-encoding']
        _need(not content_encoding or content_encoding[0].lower() in ('','identity'),'ORIGINAL_CONTENT_ENCODING')
        metadata[url]={key:http[key] for key in ('source_url','final_url','status','byte_count','source_sha256',
                                               'fetched_at','headers_received_at','response_received_at')}
        metadata[url]['headers']=headers
    return dict(schema=SCHEMA,state='READY_ORIGINAL_METADATA',document=dict(
        schema='RACE_AI_MANUAL_OFFICIAL_ORIGINAL_METADATA_V1',execution_day=cache['execution_day'],metadata_by_url=metadata),
        source_count=len(metadata),source_requests=0,independent_receipt_verified=False,card_identity_verified=False,
        clocks_rewritten=False,headers_rewritten=False)


def build_jra_http_metadata(cache,bodies):
    """Join one actual SUCCESS per retained direct JRA source, or return HOLD.

    bodies maps exact original source URLs to their retained bytes. A READY
    document is ready for the existing official-freeze metadata binding; the
    Actions caller still owns encryption, actual baseline and saved receipts.
    """
    try:return _build(cache,bodies)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as exc:
        reason=str(exc)
        if re.fullmatch(r'JRA_HTTP_SIDECAR_[A-Z_]{1,100}',reason) is None:reason='JRA_HTTP_SIDECAR_INPUT_REJECTED'
        return dict(schema=SCHEMA,state='HOLD',reasons=[reason],document=None,source_count=0,source_requests=0,
            independent_receipt_verified=False,card_identity_verified=False,clocks_rewritten=False,headers_rewritten=False)
