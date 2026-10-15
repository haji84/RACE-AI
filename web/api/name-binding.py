"""Protected immutable independent name proof reads; no official-source I/O."""
from http.server import BaseHTTPRequestHandler
import os
from urllib.parse import urlsplit,parse_qs
from api.today import load_feed,create_blob_client,utc_now,JST
from api.race_store import find_program,canonical
from api.prediction_store import read_prediction,request_identifier
from api.name_binding_store import baseline_request_hint,read_name_binding,MAX_BYTES

def load_name_binding(race_id,request_id=None):
    client=None
    try:
        before=utc_now()
        if request_id is not None:request_identifier(request_id)
        status,feed=load_feed()
        if status!=200:return 503,{'error':'DAY_PROGRAM_UNAVAILABLE'}
        now=utc_now();race=find_program(feed,race_id,now)
        if now.astimezone(JST).date()!=before.astimezone(JST).date():raise ValueError('day changed')
        client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
        nonce=baseline_request_hint(race,client=client,now=now,request_id=request_id)
        if nonce is None:return 404,{'error':'NAME_BINDING_NOT_SAVED'}
        baseline=read_prediction(race,client=client,now=now,request_id=nonce)
        envelope=read_name_binding(race,baseline,client=client,now=utc_now(),request_id=request_id)
        if utc_now().astimezone(JST).date()!=before.astimezone(JST).date():raise ValueError('day changed')
        if envelope is None:return 404,{'error':'NAME_BINDING_NOT_SAVED'}
        return 200,envelope
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError):
        return 422,{'error':'NAME_BINDING_DATA_REJECTED'}
    except Exception:return 503,{'error':'NAME_BINDING_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try:client.close()
            except Exception:pass

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if len(self.path)>256:raise ValueError('query too large')
            query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,strict_parsing=True,max_num_fields=2)
            if not {'race_id'}<=set(query)<={'race_id','request_id'} or any(len(v)!=1 or not v[0] for v in query.values()):
                raise ValueError('query invalid')
            from api.race_store import checked_race_id
            checked_race_id(query['race_id'][0],utc_now())
            if 'request_id' in query:request_identifier(query['request_id'][0])
            status,data=load_name_binding(query['race_id'][0],query.get('request_id',[None])[0])
        except ValueError:status,data=400,{'error':'NAME_BINDING_QUERY_INVALID'}
        body=canonical(data)
        self.send_response(status)
        for key,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex'),('Content-Length',str(len(body)))]:self.send_header(key,value)
        self.end_headers();self.wfile.write(body)
