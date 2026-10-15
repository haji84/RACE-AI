"""Protected read-only complete finalized name-bound v2 envelope."""
from http.server import BaseHTTPRequestHandler
import json
import os
from urllib.parse import urlsplit, parse_qs

from api.today import load_feed, create_blob_client, utc_now, JST
from api.race_store import find_program,checked_race_id,canonical
from api.name_bound_exhibition_store import read_name_bound_exhibition, request_identifier


def load_name_bound_exhibition(race_id, request_id=None):
    client=None
    try:
        before=utc_now()
        if request_id is not None:
            request_identifier(request_id)
        status,feed=load_feed()
        if status!=200:
            return 503,{'error':'DAY_PROGRAM_UNAVAILABLE'}
        race=find_program(feed,race_id,before)
        client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
        receipt=read_name_bound_exhibition(race,client=client,now=utc_now(),request_id=request_id)
        if utc_now().astimezone(JST).date()!=before.astimezone(JST).date():
            raise ValueError('JST_MIDNIGHT_CROSSED')
        if receipt is None:
            return 404,{'error':'NAME_BOUND_EXHIBITION_NOT_SAVED'}
        return 200,receipt
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        return 422,{'error':'NAME_BOUND_EXHIBITION_DATA_REJECTED'}
    except Exception:
        return 503,{'error':'NAME_BOUND_EXHIBITION_STORE_UNAVAILABLE'}
    finally:
        if client is not None:
            try: client.close()
            except Exception: pass


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if len(self.path)>256:raise ValueError('query too large')
            query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,strict_parsing=True,max_num_fields=2)
            if (not {'race_id'}<=set(query)<={'race_id','request_id'}
                    or any(len(values)!=1 or not values[0] for values in query.values())):
                raise ValueError('strict single query identities required')
            checked_race_id(query['race_id'][0],utc_now())
            if 'request_id' in query:request_identifier(query['request_id'][0])
            status,data=load_name_bound_exhibition(query['race_id'][0],query.get('request_id',[None])[0])
        except ValueError:
            status,data=400,{'error':'NAME_BOUND_EXHIBITION_QUERY_INVALID'}
        body=canonical(data)
        self.send_response(status)
        for name,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex'),('Content-Length',str(len(body)))]:
            self.send_header(name,value)
        self.end_headers(); self.wfile.write(body)
