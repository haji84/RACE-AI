"""Protected current-day single-race observations; never fetches official sites."""
from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlsplit, parse_qs

from api.today import load_feed, create_blob_client, utc_now, JST
from api.race_store import find_program, read_current_race


def load_race(race_id):
    client=None
    try:
        before=utc_now()
        status,feed=load_feed()
        if status!=200:return 503,{'error':'DAY_PROGRAM_UNAVAILABLE'}
        race=find_program(feed,race_id,before)
        client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
        data=read_current_race(race,client=client,now=utc_now())
        if utc_now().astimezone(JST).date()!=before.astimezone(JST).date():
            raise ValueError('JST_MIDNIGHT_CROSSED')
        if data is None:return 404,{'error':'RACE_UPDATES_NOT_OBTAINED'}
        return 200,data
    except ValueError:
        return 422,{'error':'RACE_DATA_REJECTED'}
    except Exception:
        return 503,{'error':'RACE_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try:client.close()
            except Exception:pass


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,strict_parsing=True,max_num_fields=1)
            if set(query)!={'race_id'} or len(query['race_id'])!=1:raise ValueError
            status,data=load_race(query['race_id'][0])
        except ValueError:
            status,data=400,{'error':'RACE_QUERY_INVALID'}
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Robots-Tag','noindex')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)
