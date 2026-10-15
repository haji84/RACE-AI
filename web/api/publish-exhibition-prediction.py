"""Scoped Preview-only display forecast publication; no caller model inputs."""
from http.server import BaseHTTPRequestHandler
import json
import os

from api.github_oidc import verify_github_oidc
from api.today import load_feed,create_blob_client,utc_now,JST
from api.race_store import decode,find_program,REVIEW
from api.exhibition_store import publish_exhibition_prediction,request_identifier,ExhibitionUnavailable


class handler(BaseHTTPRequestHandler):
    def respond(self,status,data):
        body=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        for name,value in [('Content-Type','application/json; charset=utf-8'),('Cache-Control','no-store'),
                ('X-Content-Type-Options','nosniff'),('X-Robots-Tag','noindex'),('Content-Length',str(len(body)))]:
            self.send_header(name,value)
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        self.respond(405,{'error':'POST_REQUIRED'})

    def do_POST(self):
        if os.environ.get('VERCEL_ENV')!='preview':
            self.respond(404,{'error':'NOT_FOUND'}); return
        try:
            bearer=self.headers.get('Authorization','')
            if not bearer.startswith('Bearer '): raise ValueError('bearer missing')
            verify_github_oidc(bearer[7:])
        except Exception:
            self.respond(404,{'error':'NOT_FOUND'}); return
        commit=os.environ.get('VERCEL_GIT_COMMIT_SHA','')
        if len(commit)!=40 or self.headers.get('X-Race-AI-Commit')!=commit:
            self.respond(409,{'error':'DEPLOYMENT_NOT_CURRENT'}); return
        client=None
        try:
            size=int(self.headers.get('Content-Length','-1'))
            if not 0<size<=8192 or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                self.respond(400,{'error':'BODY_INVALID'}); return
            raw=self.rfile.read(size)
            if len(raw)!=size: raise ValueError('body truncated')
            request=decode(raw)
            if (not isinstance(request,dict) or set(request)!={'publication_review','race_id','request_id'}
                    or request['publication_review']!=REVIEW):
                raise ValueError('exact publication request required')
            request_identifier(request['request_id'])
            before=utc_now(); status,feed=load_feed()
            if status!=200:
                self.respond(503,{'error':'DAY_PROGRAM_UNAVAILABLE'}); return
            now=utc_now()
            if now.astimezone(JST).date()!=before.astimezone(JST).date():
                raise ValueError('JST_MIDNIGHT_CROSSED')
            race=find_program(feed,request['race_id'],now)
            client=create_blob_client(os.environ['BLOB_READ_WRITE_TOKEN'])
            result=publish_exhibition_prediction(request,race,client=client,now=now,clock=utc_now)
            if utc_now().astimezone(JST).date()!=before.astimezone(JST).date():
                raise ValueError('JST_MIDNIGHT_CROSSED')
            self.respond(200,{**result,'commit_sha':commit})
        except ExhibitionUnavailable as error:
            self.respond(422,{'error':'EXHIBITION_PREDICTION_UNAVAILABLE','reason':error.reason})
        except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
            self.respond(422,{'error':'EXHIBITION_PREDICTION_REJECTED'})
        except Exception:
            self.respond(503,{'error':'EXHIBITION_PUBLICATION_FAILED'})
        finally:
            if client is not None:
                try: client.close()
                except Exception: pass
