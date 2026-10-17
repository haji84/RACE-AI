"""Readiness of the real current-day private feed; protected by Vercel auth."""
from datetime import datetime
from http.server import BaseHTTPRequestHandler
import json

from api.today import load_feed, utc_now


def readiness():
    status, feed = load_feed()
    if status != 200:
        return 503, {'ready':False, 'status':'unavailable',
                     'error':feed.get('error','FEED_UNAVAILABLE')}
    venues = feed['venues']
    errors = [venue['venue'] for venue in venues
              if venue.get('status') in {'UNOBTAINED','ERROR','PARTIAL'}
              or (venue.get('no_event') is False and
                  (venue.get('status') != 'READY' or len(venue['races']) != 12))]
    ready = (feed.get('schedule_verified') is True and not errors and len(venues) in (0,24)
             and feed['races'] == feed['complete_six_boat_races'])
    observed = feed.get('last_observed_at') or feed['first_observed_at']
    observed_time = datetime.fromisoformat(observed.replace('Z','+00:00'))
    return (200 if ready else 503), {
        'ready':ready, 'status':'ready' if ready else 'degraded',
        'date_jst':feed['date_jst'], 'venue_states':len(venues),
        'active_venues':sum(venue.get('no_event') is False for venue in venues),
        'races':feed['races'], 'complete_six_boat_races':feed['complete_six_boat_races'],
        'error_venues':errors, 'last_observed_at':observed,
        'observation_age_seconds':max(0,int((utc_now()-observed_time).total_seconds())),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, data = readiness()
        body = json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Robots-Tag','noindex')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
