"""Read-only verified market results; no purchases or ledger data are handled."""
from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlsplit, parse_qs

from api.today import load_feed, create_blob_client, utc_now, JST
from api.race_store import find_program, read_current_race, MAX_BYTES, canonical
from settlement_contract import build_settlement_report


def load_settlement(race_id):
    client = None
    try:
        before = utc_now()
        status, feed = load_feed()
        if status != 200:
            return 503, {'error': 'DAY_PROGRAM_UNAVAILABLE'}
        race = find_program(feed, race_id, before)
        client = create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
        results = read_current_race(race, client=client, now=utc_now())
        now = utc_now()
        if now.astimezone(JST).date() != before.astimezone(JST).date():
            raise ValueError('JST_MIDNIGHT_CROSSED')
        report = build_settlement_report(results, race, now)
        if len(canonical(report)) > MAX_BYTES:
            raise ValueError('SETTLEMENT_RESPONSE_TOO_LARGE')
        return 200, report
    except ValueError:
        return 422, {'error': 'SETTLEMENT_DATA_REJECTED'}
    except Exception:
        return 503, {'error': 'SETTLEMENT_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query = parse_qs(urlsplit(self.path).query, keep_blank_values=True,
                             strict_parsing=True, max_num_fields=1)
            if set(query) != {'race_id'} or len(query['race_id']) != 1 or not query['race_id'][0]:
                raise ValueError('single race identity required')
            status, data = load_settlement(query['race_id'][0])
        except ValueError:
            status, data = 400, {'error': 'SETTLEMENT_QUERY_INVALID'}
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        for key, value in [('Content-Type', 'application/json; charset=utf-8'), ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'), ('X-Robots-Tag', 'noindex'), ('Content-Length', str(len(body)))]:
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
