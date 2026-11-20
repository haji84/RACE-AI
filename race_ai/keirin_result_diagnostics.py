"""Bounded public acquisition receipts without request or response secrets.

Routes come from this fixed registry, never from a URL, exception, response,
query string or form token supplied by a remote source.
"""
from datetime import datetime
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit, parse_qsl

SCHEMA = 'RACE_AI_KEIRIN_RESULT_DIAGNOSTIC_V1'
ROUTES = {
    'OFFICIAL_CALENDAR': ('keirin.jp', '/sp/raceschedule', 'GET'),
    'CALENDAR_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0201.js', 'GET'),
    'FORM_SCRIPT': ('keirin.jp', '/sp/static/js/commonSubmit.js', 'GET'),
    'OFFICIAL_RACE_LIST': ('keirin.jp', '/sp/racelist', 'POST'),
    'RACE_LIST_VIEW_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0301_v.js', 'GET'),
    'RACE_LIST_CONTROLLER_SCRIPT': ('keirin.jp', '/sp/static/js/SJ0301_c.js', 'GET'),
    'OFFICIAL_FINAL_RESULT': ('keirin.jp', '/sp/race', 'POST'),
    'OFFICIAL_PAYOUT_UNIT': ('www.hofukeirin.jp', '/ticket/', 'GET'),
    'OFFICIAL_JSON_CALENDAR': ('keirin.jp', '/pc/json', 'GET'),
    'OFFICIAL_JSON_DAY_LIST': ('keirin.jp', '/pc/json', 'GET'),
    'OFFICIAL_JSON_RESULT_SUMMARY': ('keirin.jp', '/pc/json', 'GET'),
    'OFFICIAL_JSON_HEADER': ('keirin.jp', '/pc/json', 'GET'),
    'OFFICIAL_JSON_DETAIL': ('keirin.jp', '/pc/json', 'GET'),
}
STAGES = frozenset(('REQUEST', 'HTTP_RESPONSE', 'CONTENT_CHECK', 'PARSE_RESULT',
                    'VERIFY_UNIT', 'PERSIST_STOP'))
REASONS = frozenset(('SOURCE_ACCEPTED', 'TRANSPORT_FAILED', 'HTTP_DENIED',
    'HTTP_ERROR', 'REDIRECT_REFUSED', 'SOURCE_BYTES_INVALID', 'CHALLENGE_MARKUP',
    'CAPTURE_CLOCK_INVALID', 'SOURCE_VALIDATION_FAILED', 'UNIT_TEXT_MISSING',
    'UNIT_VERIFIED', 'RESULT_VALIDATED', 'RESULT_NOT_PUBLISHED',
    'PROVIDER_STOP_PERSISTENCE_FAILED'))
FIELDS = frozenset(('schema', 'purpose', 'source_host', 'source_path', 'method',
                    'stage', 'reason', 'http_status', 'observed_at'))
_CHALLENGE = re.compile(r'captcha|turnstile|challenge-platform|just a moment|'
                        r'browser[ ._-]?check|verify (?:you are|your browser)', re.I)
_SCRIPT = re.compile(r'<script\b[^>]*>.*?</script\s*>', re.I | re.S)


def _need(condition):
    if not condition:
        raise ValueError('RESULT_DIAGNOSTIC_NOT_SAFE')


def make_diagnostic(*, purpose, stage, reason, observed_at, http_status=None):
    _need(type(purpose) is str and purpose in ROUTES and
          type(stage) is str and stage in STAGES and
          type(reason) is str and reason in REASONS)
    _need(http_status is None or type(http_status) is int and 100 <= http_status <= 599)
    _need(type(observed_at) is str)
    try:
        at = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('RESULT_DIAGNOSTIC_NOT_SAFE') from None
    _need(at.utcoffset() is not None and len(observed_at) <= 40)
    host, path, method = ROUTES[purpose]
    return dict(schema=SCHEMA, purpose=purpose, source_host=host, source_path=path,
                method=method, stage=stage, reason=reason, http_status=http_status,
                observed_at=at.isoformat())


def checked_diagnostics(rows):
    _need(type(rows) is list and len(rows) <= 32)
    checked = []
    for row in rows:
        _need(type(row) is dict and set(row) == FIELDS)
        canonical = make_diagnostic(**{key: row[key] for key in
            ('purpose', 'stage', 'reason', 'observed_at', 'http_status')})
        _need(canonical == row)
        checked.append(canonical)
    return checked


class _ScriptAttributes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.attributes = None

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and self.attributes is None and len(dict(attrs)) == len(attrs):
            self.attributes = dict(attrs)


def _passive_script(block):
    """Recognize only saved ordinary Contact Form 7 asset shapes.

    Widget elements, challenge iframes, interactive checks, and unknown scripts
    remain visible to the fail-closed check. No script is executed.
    """
    parser = _ScriptAttributes()
    try:
        parser.feed(block)
        attrs = parser.attributes
        if type(attrs) is not dict or set(attrs) - {'id', 'src', 'type', 'defer', 'async'}:
            return False
        body = block[block.index('>') + 1:block.lower().rindex('</script')].strip()
        kind, source = attrs.get('id'), attrs.get('src')
        if kind == 'wpcf7-recaptcha-js-extra' and source is None:
            match = re.fullmatch(r'var\s+wpcf7_recaptcha\s*=\s*(\{.*\})\s*;\s*'
                r'(?://#\s*sourceURL=wpcf7-recaptcha-js-extra\s*)?', body, re.S)
            if match is None:
                return False
            data = json.loads(match[1])
            return (type(data) is dict and set(data) <= {'sitekey', 'actions'} and
                type(data.get('sitekey')) is str and
                re.fullmatch(r'[A-Za-z0-9_-]{1,200}', data['sitekey']) is not None and
                type(data.get('actions', {})) is dict and
                all(type(k) is str and type(v) is str and
                    re.fullmatch(r'[A-Za-z0-9_-]{1,80}', k) and
                    re.fullmatch(r'[A-Za-z0-9_-]{1,80}', v)
                    for k, v in data.get('actions', {}).items()))
        if body or type(source) is not str:
            return False
        url = urlsplit(source)
        if url.scheme != 'https' or url.username or url.password or url.port or url.fragment:
            return False
        query = parse_qsl(url.query, keep_blank_values=True)
        if kind == 'google-recaptcha-js':
            return (url.hostname == 'www.google.com' and url.path == '/recaptcha/api.js' and
                    any(k == 'render' and v != 'explicit' and
                        re.fullmatch(r'[A-Za-z0-9_-]{6,200}', v) for k, v in query) and
                    all(k in ('render', 'ver') for k, _ in query))
        return (kind == 'wpcf7-recaptcha-js' and url.hostname == 'www.hofukeirin.jp' and
                url.path == '/wp-content/plugins/contact-form-7/modules/recaptcha/index.js' and
                all(k == 'ver' for k, _ in query))
    except (ValueError, TypeError, IndexError):
        return False


def challenge_reason(raw, *, passive_guide_scripts=False):
    _need(type(raw) is bytes and type(passive_guide_scripts) is bool)
    text = raw.decode('utf-8', 'replace')
    if passive_guide_scripts:
        text = _SCRIPT.sub(lambda m: '' if _passive_script(m[0]) else m[0], text)
    return 'CHALLENGE_MARKUP' if _CHALLENGE.search(text) else None
