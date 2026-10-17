"""Preview-only independent name proof publication; existing OIDC scope."""
from http.server import BaseHTTPRequestHandler
import os
import re
from api.github_oidc import verify_github_oidc
from api.today import load_feed,create_blob_client,utc_now,JST
from api.race_store import decode,find_program,canonical
from api.prediction_store import read_prediction,request_identifier
from api.name_binding_store import publish_name_binding,REQUEST,REVIEW,MAX_BYTES

class handler(BaseHTTPRequestHandler):
    def respond(self,status,data):
        body=canonical(data)
        self.send_response(status)
        for key,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex'),('Content-Length',str(len(body)))]:self.send_header(key,value)
        self.end_headers();self.wfile.write(body)
    def do_GET(self):self.respond(405,{'error':'POST_REQUIRED'})
    def do_POST(self):
        if os.environ.get('VERCEL_ENV')!='preview':self.respond(404,{'error':'NOT_FOUND'});return
        try:
            bearer=self.headers.get('Authorization','')
            if not bearer.startswith('Bearer '):raise ValueError('missing bearer')
            verify_github_oidc(bearer[7:])
        except Exception:self.respond(404,{'error':'NOT_FOUND'});return
        commit=os.environ.get('VERCEL_GIT_COMMIT_SHA','')
        if re.fullmatch('[0-9a-f]{40}',commit) is None or self.headers.get('X-Race-AI-Commit')!=commit:
            self.respond(409,{'error':'DEPLOYMENT_NOT_CURRENT'});return
        client=None
        try:
            size=int(self.headers.get('Content-Length','-1'))
            if not 0<size<=MAX_BYTES or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.respond(400,{'error':'BODY_INVALID'});return
            raw=self.rfile.read(size)
            if len(raw)!=size:raise ValueError('truncated')
            request=decode(raw)
            if not isinstance(request,dict) or set(request)!=REQUEST or request['publication_review']!=REVIEW:raise ValueError('request invalid')
            request_identifier(request['request_id']);request_identifier(request['baseline_request_id'])
            before=utc_now();status,feed=load_feed()
            if status!=200:self.respond(503,{'error':'DAY_PROGRAM_UNAVAILABLE'});return
            now=utc_now()
            if now.astimezone(JST).date()!=before.astimezone(JST).date():raise ValueError('day changed')
            race=find_program(feed,request['race_id'],now)
            client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
            baseline=read_prediction(race,client=client,now=now,request_id=request['baseline_request_id'])
            result=publish_name_binding(request,race,baseline,client=client,now=now,clock=utc_now)
            if utc_now().astimezone(JST).date()!=before.astimezone(JST).date():raise ValueError('day changed')
            self.respond(200,{**result,'commit_sha':commit})
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError):
            self.respond(422,{'error':'NAME_BINDING_PUBLICATION_REJECTED'})
        except Exception:self.respond(503,{'error':'NAME_BINDING_PUBLICATION_FAILED'})
        finally:
            if client is not None:
                try:client.close()
                except Exception:pass
