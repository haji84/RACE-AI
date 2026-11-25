"""Bounded public GitHub reads for the pre-key joint forecast verification step."""

import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


RETRYABLE_HTTP = {502, 503, 504}
GITHUB_HOSTS = {'api.github.com', 'raw.githubusercontent.com'}
STAGES = {
    'local_receipts', 'original_cipher', 'original_index', 'witness_jobs', 'prior_publication',
    'recovery_cipher', 'write_snapshot', 'result_ref', 'result_roster', 'result_data',
}


class ReadbackError(RuntimeError):
    def __init__(self, reason, attempts, status=None):
        super().__init__(reason)
        self.reason = reason
        self.attempts = attempts
        self.status = status


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def diagnostic(stage, error):
    """Return only the verification phase and transport status for public logs."""
    report = {'stage': stage if stage in STAGES else 'unknown', 'reason': 'VALIDATION_FAILED'}
    if isinstance(error, ReadbackError):
        report.update(reason=error.reason, attempts=error.attempts)
        if error.status is not None:
            report['http_status'] = error.status
    elif isinstance(error, OSError):
        report['reason'] = 'LOCAL_IO_FAILED'
    return report


def get(url, limit, *, open_request=None, pause=time.sleep):
    address = urlsplit(url)
    if address.scheme != 'https' or address.netloc not in GITHUB_HOSTS or address.fragment:
        raise ReadbackError('INVALID_GITHUB_URL', 0)
    open_request = open_request or build_opener(_NoRedirect()).open
    request = Request(url, headers={'User-Agent': 'RACE-AI-joint-origin-readback/1'})
    for attempt in (1, 2):
        try:
            with open_request(request, timeout=45) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ReadbackError('UNEXPECTED_RESPONSE', attempt, response.status)
                raw = response.read(limit + 1)
            if not 0 < len(raw) <= limit:
                raise ReadbackError('INVALID_RESPONSE_SIZE', attempt)
            return raw
        except HTTPError as error:
            status = error.code
            retry = status in RETRYABLE_HTTP and not (error.headers and error.headers.get('Retry-After'))
            error.close()
            failure = ReadbackError('HTTP_STATUS', attempt, status)
        except URLError as error:
            retry = isinstance(error.reason, (TimeoutError, ConnectionResetError))
            failure = ReadbackError('CONNECTION_FAILED', attempt)
        except (TimeoutError, ConnectionResetError):
            retry = True
            failure = ReadbackError('CONNECTION_FAILED', attempt)
        except OSError:
            retry = False
            failure = ReadbackError('CONNECTION_FAILED', attempt)
        if attempt == 2 or not retry:
            raise failure from None
        pause(1)
