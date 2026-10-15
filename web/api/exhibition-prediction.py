"""Protected read-only original post-exhibition receipt and pinned source replay."""
from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlsplit, parse_qs

from api.today import load_feed, create_blob_client, utc_now, JST
from api.race_store import find_program
from api.exhibition_store import read_exhibition_prediction, request_identifier
from api.original_prediction_store import read_original_prediction


def load_exhibition_prediction(race_id, request_id=None,variant=None):
    client=None
    try:
        before=utc_now()
        if variant not in (None,'original-v1'):
            raise ValueError('unsupported prediction variant')
        if request_id is not None:
            request_identifier(request_id)
        status,feed=load_feed()
        if status!=200:
            return 503,{'error':'DAY_PROGRAM_UNAVAILABLE'}
        race=find_program(feed,race_id,before)
        client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
        reader=read_original_prediction if variant=='original-v1' else read_exhibition_prediction
        receipt=reader(race,client=client,now=utc_now(),request_id=request_id)
        if utc_now().astimezone(JST).date()!=before.astimezone(JST).date():
            raise ValueError('JST_MIDNIGHT_CROSSED')
        if receipt is None:
            return 404,{'error':'EXHIBITION_PREDICTION_NOT_SAVED'}
        return 200,receipt
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return 422,{'error':'EXHIBITION_PREDICTION_DATA_REJECTED'}
    except Exception:
        return 503,{'error':'EXHIBITION_PREDICTION_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try: client.close()
            except Exception: pass


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,strict_parsing=True,max_num_fields=3)
            if (not {'race_id'}<=set(query)<={'race_id','request_id','variant'}
                    or any(len(values)!=1 or not values[0] for values in query.values())):
                raise ValueError('strict single query identities required')
            if 'variant' in query:
                if query['variant']!=['original-v1']:raise ValueError('unsupported prediction variant')
                status,data=load_exhibition_prediction(query['race_id'][0],query.get('request_id',[None])[0],variant='original-v1')
            else:
                status,data=load_exhibition_prediction(query['race_id'][0],query.get('request_id',[None])[0])
        except ValueError:
            status,data=400,{'error':'EXHIBITION_PREDICTION_QUERY_INVALID'}
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        for name,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex'),('Content-Length',str(len(body)))]:
            self.send_header(name,value)
        self.end_headers(); self.wfile.write(body)
