"""GET-only scoring of an exact immutable name-bound forecast version."""
from http.server import BaseHTTPRequestHandler
import os
from urllib.parse import urlsplit, parse_qs

from api.today import load_feed, create_blob_client, utc_now, JST
from api.race_store import find_program, checked_race_id, read_current_race, canonical, MAX_BYTES
from api.name_bound_exhibition_store import read_name_bound_exhibition, request_identifier
from name_bound_inputs import _context
from name_bound_evaluation import build_name_bound_evaluation


def load_name_bound_evaluation(race_id, forecast_request_id):
    client = None
    try:
        before = utc_now()
        request_identifier(forecast_request_id)
        status, feed = load_feed()
        if status != 200:
            return 503, {'error':'DAY_PROGRAM_UNAVAILABLE'}
        race = find_program(feed, race_id, before)
        client = create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
        forecast = read_name_bound_exhibition(race, client=client, now=utc_now(), request_id=forecast_request_id)
        context_clock = utc_now()
        if context_clock.astimezone(JST).date() != before.astimezone(JST).date():
            raise ValueError('JST_MIDNIGHT_CROSSED')
        if forecast is None:
            return 404, {'error':'NAME_BOUND_PREDICTION_NOT_SAVED'}
        projected = _context(race, forecast['baseline'], forecast['name_binding'], context_clock)[3]
        results = read_current_race(projected, client=client, now=utc_now())
        now = utc_now()
        if now.astimezone(JST).date() != before.astimezone(JST).date():
            raise ValueError('JST_MIDNIGHT_CROSSED')
        report = build_name_bound_evaluation(forecast, results, race, now)
        if len(canonical(report)) > MAX_BYTES:
            raise ValueError('NAME_BOUND_EVALUATION_RESPONSE_TOO_LARGE')
        return 200, report
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return 422, {'error':'NAME_BOUND_EVALUATION_DATA_REJECTED'}
    except Exception:
        return 503, {'error':'NAME_BOUND_EVALUATION_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try: client.close()
            except Exception: pass


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if len(self.path) > 256:
                raise ValueError('query too large')
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True, strict_parsing=True, max_num_fields=2)
            if (set(query) != {'race_id','forecast_request_id'}
                    or any(len(values) != 1 or not values[0] for values in query.values())):
                raise ValueError('exact single query identities required')
            checked_race_id(query['race_id'][0], utc_now())
            request_identifier(query['forecast_request_id'][0])
            status, data = load_name_bound_evaluation(query['race_id'][0], query['forecast_request_id'][0])
        except ValueError:
            status, data = 400, {'error':'NAME_BOUND_EVALUATION_QUERY_INVALID'}
        body = canonical(data)
        self.send_response(status)
        for name, value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex'),('Content-Length',str(len(body)))]:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)
