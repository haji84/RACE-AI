"""Fictional HTML and mocked HTTPS. No actual network or license granted."""
import unittest
from race_ai.controlled_boat_html_capture import capture_boat_racelist,CaptureError
from tests.test_boat_official_web_adapter import HTML,URL
TIME="2030-01-15T08:00:00+09:00"
class Response:
 def __init__(self,url=URL,data=None,ctype="text/html",status=200):
    self.url=url;self.data=HTML.encode("utf-8") if data is None else data
    self.headers={"Content-Type":ctype};self.status=status
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def geturl(self):return self.url
 def read(self,n):return self.data[:n]
class Client:
 def __init__(self,response):self.calls=0;self.response=response
 def open(self,request,timeout):
    self.calls+=1;return self.response
def run(client,gate):
 return capture_boat_racelist(URL,rights_checker=gate,
              source_rights_ref="fictional-review-only",captured_at=TIME,opener=client)
class CaptureTests(unittest.TestCase):
 def test_capture_one_approved_page_returns_audit_only(self):
    client=Client(Response())
    out=run(client,lambda url,purpose:url==URL and purpose=="single_bounded_html_get")
    self.assertEqual(client.calls,1)
    self.assertEqual(len(out["records"]),3)
    self.assertFalse(out["records"][0]["cutoff_verified"])
    self.assertFalse(out["controlled_capture"]["model_ready"])
    self.assertIsNone(out["records"][0]["prediction"])
 def test_unreviewed_site_no_network(self):
    client=Client(Response())
    with self.assertRaisesRegex(CaptureError,"NOT_ADMITTED"):
        run(client,None)
    with self.assertRaisesRegex(CaptureError,"NOT_ADMITTED"):
        run(client,lambda *_:False)
    self.assertEqual(client.calls,0)
 def test_wrong_domain_no_network_even_with_permission(self):
    client=Client(Response())
    with self.assertRaisesRegex(Exception,"URL|official|non-official"):
        capture_boat_racelist(URL.replace("boatrace.jp","boatrace.jp.attacker.invalid"),
             rights_checker=lambda *_:True,
             source_rights_ref="fictional",captured_at=TIME,opener=client)
    self.assertEqual(client.calls,0)
 def test_redirect_wrong_mime_or_huge_payload_rejected(self):
    for response in (Response(url="https://other.invalid"),
                     Response(ctype="application/json"),Response(data=b"a"*1_500_001)):
        client=Client(response)
        with self.subTest(response=response),self.assertRaises(CaptureError):
            run(client,lambda *_:True)
        self.assertEqual(client.calls,1)
if __name__=="__main__":unittest.main()
