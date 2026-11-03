"""No-network tests of signed GitHub OIDC JWK update bridge."""
from __future__ import annotations
import json
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError
from scripts.keirin_oidc_jwks_refresh import (
    parse_official_public_jwks, refresh, JwksRefreshError, JWKS, REFRESH_URL
)

RSA_KEY={"kid":"github-official-rotation-1","kty":"RSA","alg":"RS256",
         "use":"sig","n":"q"*342,"e":"AQAB"}
BLOB=json.dumps({"keys":[RSA_KEY]}).encode()


class Response:
    def __init__(self, body, url, status=200):
        self.body=body
        self.url=url
        self.status=status
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.body[:n]
    def geturl(self):return self.url


class TestJwksRefresh(unittest.TestCase):
    def test_normalize_public_rsa_keys_only(self):
        raw=json.dumps({"keys":[RSA_KEY,
            {"kid":"ec-pub","kty":"EC","crv":"P-256","x":"abc","y":"abc"}]}).encode()
        self.assertEqual(parse_official_public_jwks(raw),[RSA_KEY])

    def test_reject_duplicate_or_invalid_jwks(self):
        cases=[b'{}',b'{"keys":[]}',b'{invalid}',
               json.dumps({"keys":[RSA_KEY,RSA_KEY]}).encode(),
               json.dumps({"keys":[{**RSA_KEY,"e":"Aw"}]}).encode()]
        for value in cases:
            with self.subTest(value=value[:32]):
                with self.assertRaises(JwksRefreshError):
                    parse_official_public_jwks(value)

    def test_real_signed_request_shape_without_network(self):
        calls=[]
        def fake_http(req,timeout):
            calls.append((req.full_url,req.get_method()))
            if req.full_url==JWKS:
                self.assertEqual(req.get_method(),"GET")
                return Response(BLOB,JWKS)
            self.assertEqual(req.full_url,REFRESH_URL)
            self.assertEqual(req.get_method(),"POST")
            self.assertEqual(req.get_header("Authorization"),"Bearer abc.def.ghi")
            posted=json.loads(req.data.decode("utf-8"))
            self.assertEqual(posted["keys"],[RSA_KEY])
            ack={
                "schema":"RACE_AI_GITHUB_OIDC_JWKS_REFRESH_ACK_V1",
                "source_sha256":posted["source_sha256"],
                "retrieved_at":posted["retrieved_at"],
                "key_count":len(posted["keys"]),
                "authenticated_update":True,
                "private_forecast_data_returned":False
            }
            return Response(json.dumps(ack).encode(),REFRESH_URL)
        result=refresh(http=fake_http,jwt_minter=lambda:"abc.def.ghi",
            clock=lambda:datetime.fromisoformat("2026-11-03T06:00:00+00:00"))
        self.assertEqual(result["status"],"SIGNED_PUBLIC_JWKS_REFRESH_VERIFIED")
        self.assertEqual(result["key_count"],1)
        self.assertFalse(result["token_or_private_forecast_logged"])
        self.assertEqual(calls,[(JWKS,"GET"),(REFRESH_URL,"POST")])

    def test_wrong_readback_fails_closed(self):
        def bad_http(req,timeout):
            if req.full_url==JWKS:return Response(BLOB,JWKS)
            ack={"schema":"RACE_AI_GITHUB_OIDC_JWKS_REFRESH_ACK_V1",
                 "source_sha256":"f"*64,"retrieved_at":"2026-11-03T06:00:00Z",
                 "key_count":1,"authenticated_update":True,
                 "private_forecast_data_returned":False}
            return Response(json.dumps(ack).encode(),REFRESH_URL)
        with self.assertRaisesRegex(JwksRefreshError,"ACK_IDENTITY_MISMATCH"):
            refresh(http=bad_http,jwt_minter=lambda:"abc.def.ghi",
                clock=lambda:datetime.fromisoformat("2026-11-03T06:00:00+00:00"))

    def test_http_denial_leaks_no_private_key_or_response(self):
        def forbidden(req,timeout):
            if req.full_url==JWKS:return Response(BLOB,JWKS)
            raise HTTPError(req.full_url,403,"sensitive",None,None)
        with self.assertRaisesRegex(JwksRefreshError,"JWK_REFRESH_HTTP_403") as caught:
            refresh(http=forbidden,jwt_minter=lambda:"abc.def.ghi")
        self.assertNotIn("sensitive",str(caught.exception))


if __name__=="__main__":
    unittest.main()
