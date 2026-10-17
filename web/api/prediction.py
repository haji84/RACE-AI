"""Protected current-day durable research prediction, without source requests."""
from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlsplit, parse_qs

from api.today import load_feed, create_blob_client, utc_now, JST
from api.race_store import find_program
from api.prediction_store import read_prediction


def load_prediction(race_id,request_id=None):
    client=None
    try:
        before=utc_now();status,feed=load_feed()
        if status!=200:return 503,{'error':'DAY_PROGRAM_UNAVAILABLE'}
        race=find_program(feed,race_id,before)
        client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
        data=read_prediction(race,client=client,now=utc_now(),request_id=request_id)
        if utc_now().astimezone(JST).date()!=before.astimezone(JST).date():raise ValueError('JST_MIDNIGHT_CROSSED')
        if data is None:return 404,{'error':'PREDICTION_NOT_SAVED'}
        return 200,data
    except ValueError:return 422,{'error':'PREDICTION_DATA_REJECTED'}
    except Exception:return 503,{'error':'PREDICTION_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try:client.close()
            except Exception:pass


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,strict_parsing=True,max_num_fields=2)
            if not {'race_id'}<=set(query)<={'race_id','request_id'} or any(len(v)!=1 for v in query.values()):raise ValueError
            status,data=load_prediction(query['race_id'][0],query.get('request_id',[None])[0])
        except ValueError:status,data=400,{'error':'PREDICTION_QUERY_INVALID'}
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        for name,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex'),('Content-Length',str(len(body)))]:
            self.send_header(name,value)
        self.end_headers();self.wfile.write(body)
