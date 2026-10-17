"""Generate and save research forecasts using the existing pinned Preview OIDC."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
import json
import os

from api.github_oidc import verify_github_oidc
from api.today import load_feed, create_blob_client
from api.race_store import decode, find_program
from api.prediction_store import publish_prediction


class handler(BaseHTTPRequestHandler):
    def respond(self,status,data):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        for name,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('Content-Length',str(len(body)))]:self.send_header(name,value)
        self.end_headers();self.wfile.write(body)

    def do_GET(self):self.respond(405,{'error':'POST_REQUIRED'})

    def do_POST(self):
        if os.environ.get('VERCEL_ENV')!='preview':self.respond(404,{'error':'NOT_FOUND'});return
        bearer=self.headers.get('Authorization','')
        try:
            if not bearer.startswith('Bearer '):raise ValueError
            verify_github_oidc(bearer[7:])
        except Exception:self.respond(404,{'error':'NOT_FOUND'});return
        commit=os.environ.get('VERCEL_GIT_COMMIT_SHA','')
        if len(commit)!=40 or self.headers.get('X-Race-AI-Commit')!=commit:
            self.respond(409,{'error':'DEPLOYMENT_NOT_CURRENT'});return
        client=None
        try:
            size=int(self.headers.get('Content-Length','-1'))
            if not 0<size<=8192 or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.respond(400,{'error':'BODY_INVALID'});return
            raw=self.rfile.read(size)
            if len(raw)!=size:raise ValueError
            request=decode(raw);status,feed=load_feed()
            if status!=200:self.respond(503,{'error':'DAY_PROGRAM_UNAVAILABLE'});return
            now=datetime.now(timezone.utc);race=find_program(feed,request.get('race_id'),now)
            client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
            result=publish_prediction(request,feed,race,client=client,now=now)
            self.respond(200,{**result,'commit_sha':commit})
        except (ValueError,TypeError,KeyError,AttributeError):self.respond(422,{'error':'RESEARCH_PREDICTION_REJECTED'})
        except Exception as error:
            print('PREDICTION_PUBLISH_FAILED '+type(error).__name__,flush=True)
            self.respond(503,{'error':'PREDICTION_PUBLICATION_FAILED'})
        finally:
            if client is not None:
                try:client.close()
                except Exception:pass
