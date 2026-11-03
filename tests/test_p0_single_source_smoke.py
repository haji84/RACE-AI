"""All response bytes/headers mocked. Zero network, zero real credentials."""
import unittest
from scripts.p0_single_source_smoke import smoke,TARGET
ENV={"GITHUB_EVENT_NAME":"push","GITHUB_REF":"refs/heads/p0-source-smoke-20261024",
     "RACE_AI_SINGLE_GET_ALLOWED":"20261025-jcd11-rno1","GITHUB_SHA":"a"*40}
class Response:
 def __init__(self,raw=b"test",mime="text/html",target=TARGET):
    self.raw=raw;self.status=200;self.url=target
    self.headers={"Content-Type":mime,"Date":"Sat, 24 Oct 2026 00:00:00 GMT",
                  "Last-Modified":"Fri, 23 Oct 2026 01:00:00 GMT"}
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def geturl(self):return self.url
 def read(self,n):return self.raw[:n]
class Opener:
 def __init__(self,response):self.response=response;self.calls=0
 def open(self,request,timeout):
    self.calls+=1
    assert request.full_url==TARGET
    assert timeout==8
    return self.response
class SmokeTests(unittest.TestCase):
 def test_only_explicit_ci_ref_can_request(self):
    for k,v in (("GITHUB_REF","refs/heads/main"),
                ("RACE_AI_SINGLE_GET_ALLOWED",""),
                ("GITHUB_EVENT_NAME","workflow_dispatch")):
      env=dict(ENV);env[k]=v;client=Opener(Response())
      with self.assertRaisesRegex(RuntimeError,"one-shot"):
        smoke(opener=client,env=env)
      self.assertEqual(client.calls,0)
 def test_single_readback_and_unknown_publication_time(self):
    html=b"<html><table><tr><td>nothing parsed</td></tr></table></html>"
    client=Opener(Response(raw=html))
    report=smoke(opener=client,env=ENV)
    self.assertEqual(client.calls,1)
    self.assertEqual(report["status"],"HTTP_OK_SCHEMA_NOT_ACCEPTED")
    self.assertFalse(report["schema_parse_ok"])
    self.assertFalse(report["provider_publication_time_proven"])
    self.assertFalse(report["source_rights_admitted"])
    self.assertNotIn("raw_html",report)
    self.assertTrue(report["sha256"])
 def test_wrong_mime_no_schema_elevation(self):
    client=Opener(Response(mime="application/json"))
    result=smoke(opener=client,env=ENV)
    self.assertEqual(client.calls,1)
    self.assertEqual(result["status"],"CONNECTIVITY_OR_RESPONSE_FAILED")
    self.assertNotIn("sha256",result)
if __name__=="__main__":unittest.main()
