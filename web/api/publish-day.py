"""Preview-only signed-workflow publication of owner-approved official facts.

The private store token stays in Vercel. No client-selected storage keys,
original media, arbitrary source origins or historical day relabeling.
The workflow must serialize writers; SDK 0.11.6 does not offer compare-and-swap.
"""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
import hashlib
import json
import os
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from api.github_oidc import verify_github_oidc
from api.today import validate_feed, https_url, unique_object, reject_constant

MAX_BYTES = 6_000_000
REVIEW = 'user-confirmation-2026-10-15-official-facts'
JST = ZoneInfo('Asia/Tokyo')


def checked_source(url, day):
    parsed = https_url(url)
    if parsed.hostname == 'www1.mbrace.or.jp':
        if parsed.path != f'/od2/B/{day:%Y%m}/b{day:%y%m%d}.lzh' or parsed.query:
            raise ValueError('SOURCE_SCOPE_INVALID')
    elif parsed.hostname == 'www.boatrace.jp':
        query = parse_qs(parsed.query)
        if parsed.path not in ('/owpc/pc/race/index', '/owpc/pc/race/racelist') or query.get('hd') != [f'{day:%Y%m%d}']:
            raise ValueError('SOURCE_SCOPE_INVALID')
    elif parsed.hostname == 'www.boatrace-tokuyama.jp':
        if parsed.path != '/modules/raceinfo/' or parse_qs(parsed.query).get('targetday') != [f'{day:%Y%m%d}']:
            raise ValueError('SOURCE_SCOPE_INVALID')
    else:
        raise ValueError('SOURCE_SCOPE_INVALID')


def read_bytes(client, key):
    from vercel.blob import BlobNotFoundError
    try:
        response = client.get(key, access='private', use_cache=False, timeout=10)
    except BlobNotFoundError:
        return None
    if response is None:
        return None
    if response.status_code != 200 or not isinstance(response.content, bytes) or len(response.content) > MAX_BYTES:
        raise ValueError('READBACK_INVALID')
    return response.content


def publish_snapshot(data, *, now, client):
    day = now.astimezone(JST).date()
    if not isinstance(data, dict) or data.get('publication_review') != REVIEW:
        raise ValueError('PUBLICATION_REVIEW_REQUIRED')
    validate_feed(data, day=day, now=now)
    checked_source(data['source_url'], day)
    for source in data.get('sources', []):
        checked_source(source['source_url'], day)
    for venue in data['venues']:
        if venue.get('schedule_source_url'):
            checked_source(venue['schedule_source_url'], day)
        for race in venue['races']:
            for boat in race['boats']:
                detail = boat.get('detail_source_url')
                if detail:
                    checked_source(detail, day)
                    parsed = https_url(detail)
                    query = parse_qs(parsed.query)
                    if (parsed.hostname != 'www.boatrace.jp' or parsed.path != '/owpc/pc/race/racelist'
                            or query.get('jcd') != [venue['venue']]
                            or query.get('rno') not in ([str(int(race['race_id'][-2:]))], [race['race_id'][-2:]])):
                        raise ValueError('DETAIL_SOURCE_RACE_MISMATCH')
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_BYTES:
        raise ValueError('SNAPSHOT_TOO_LARGE')
    digest = hashlib.sha256(raw).hexdigest()
    key = f'race-ai/day/{day.isoformat()}.json'
    version = f'race-ai/versions/{day.isoformat()}/{digest}.json'
    report = {'status':'verified', 'date_jst':day.isoformat(), 'pathname':key,
              'version_pathname':version, 'sha256':digest, 'bytes':len(raw),
              'races':data['races'], 'complete_six_boat_races':data['complete_six_boat_races']}
    current = read_bytes(client, key)
    identical = current is not None and hashlib.sha256(current).hexdigest() == digest
    if current is not None and not identical:
        old = json.loads(current, object_pairs_hook=unique_object, parse_constant=reject_constant)
        validate_feed(old, day=day, now=now)
        old_time = datetime.fromisoformat(old.get('last_observed_at', old['first_observed_at']).replace('Z', '+00:00'))
        new_time = datetime.fromisoformat(data.get('last_observed_at', data['first_observed_at']).replace('Z', '+00:00'))
        if old_time >= new_time:
            raise ValueError('NEWER_SNAPSHOT_EXISTS')
    stored_version = read_bytes(client, version)
    if stored_version is None:
        result = client.put(version, raw, access='private', content_type='application/json', add_random_suffix=False, overwrite=False)
        if result.pathname != version:
            raise ValueError('VERSION_PATH_MISMATCH')
    elif hashlib.sha256(stored_version).hexdigest() != digest:
        raise ValueError('VERSION_READBACK_MISMATCH')
    if read_bytes(client, version) != raw:
        raise ValueError('VERSION_READBACK_MISMATCH')
    if identical:
        return report
    result = client.put(key, raw, access='private', content_type='application/json', add_random_suffix=False, overwrite=True)
    if result.pathname != key or read_bytes(client, key) != raw:
        raise ValueError('DAY_READBACK_MISMATCH')
    return report


class handler(BaseHTTPRequestHandler):
    def respond(self, status, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond(405, {'error':'POST_REQUIRED'})

    def do_POST(self):
        if os.environ.get('VERCEL_ENV') != 'preview':
            self.respond(404, {'error':'NOT_FOUND'})
            return
        bearer = self.headers.get('Authorization', '')
        try:
            if not bearer.startswith('Bearer '):
                raise ValueError('missing bearer')
            verify_github_oidc(bearer[7:])
        except Exception:
            self.respond(404, {'error':'NOT_FOUND'})
            return
        commit = os.environ.get('VERCEL_GIT_COMMIT_SHA', '')
        if len(commit) != 40 or self.headers.get('X-Race-AI-Commit') != commit:
            self.respond(409, {'error':'DEPLOYMENT_NOT_CURRENT'})
            return
        client = None
        try:
            size = int(self.headers.get('Content-Length', '-1'))
            if not 0 < size <= MAX_BYTES or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.respond(400, {'error':'BODY_INVALID'})
                return
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError('incomplete body')
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=reject_constant)
            if not os.environ.get('BLOB_READ_WRITE_TOKEN'):
                self.respond(503, {'error':'STORE_NOT_CONFIGURED'})
                return
            from vercel.blob import BlobClient
            client = BlobClient(token=os.environ['BLOB_READ_WRITE_TOKEN'])
            result = publish_snapshot(data, now=datetime.now(timezone.utc), client=client)
            self.respond(200, {**result, 'commit_sha':commit})
        except ValueError:
            self.respond(422, {'error':'SNAPSHOT_REJECTED'})
        except Exception as error:
            print('DAY_PUBLISH_FAILED ' + type(error).__name__, flush=True)
            self.respond(503, {'error':'PUBLICATION_FAILED'})
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
