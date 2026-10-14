"""Real RS256/JWT checks with local keys, not mocked decode outcomes."""
import importlib.util
from pathlib import Path
import time
import types
import unittest

try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    jwt=None

@unittest.skipIf(jwt is None,'JWT dependency not installed; separate dependency run required')
class SignedOidcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path(__file__).resolve().parents[1]/'web/api/github_oidc.py'
        spec=importlib.util.spec_from_file_location('real_github_verifier',path)
        cls.verifier=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.verifier)
        cls.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.jwks=types.SimpleNamespace(get_signing_key_from_jwt=lambda token:types.SimpleNamespace(key=cls.key.public_key()))

    def claims(self):
        now=int(time.time())
        return dict(iss=self.verifier.ISSUER,aud=self.verifier.AUDIENCE,iat=now,exp=now+300,
                    sub='repo:haji84@173585154/RACE-AI@1416489937:environment:blob-e2e-preview',repository='haji84/RACE-AI',
                    repository_id='1416489937',repository_owner='haji84',repository_owner_id='173585154',
                    ref=self.verifier.REF,event_name='push',workflow_ref='haji84/RACE-AI/'+self.verifier.WORKFLOW+'@'+self.verifier.REF,
                    environment='blob-e2e-preview')

    def verify(self,claims):
        return self.verifier.verify_github_oidc(jwt.encode(claims,self.key,algorithm='RS256'),jwks_client=self.jwks)

    def test_valid_scoped_signature(self):
        self.assertEqual(self.verify(self.claims())['repository_id'],'1416489937')

    def test_mutable_name_only_subject_is_rejected(self):
        claims = self.claims()
        claims['sub'] = 'repo:haji84/RACE-AI:environment:blob-e2e-preview'
        with self.assertRaises(ValueError):
            self.verify(claims)

    def test_pinned_ids_and_subject(self):
        for field in ['repository_id','repository_owner_id','sub']:
            with self.subTest(field=field):
                c=self.claims(); c[field]='wrong'
                with self.assertRaises((ValueError,jwt.InvalidTokenError)):self.verify(c)

    def test_bad_claims_expiration_and_signature(self):
        for field,value in [('aud','wrong'),('iss','wrong'),('ref','refs/heads/main'),('environment','production'),('workflow_ref','wrong'),('event_name','pull_request'),('exp',1)]:
            with self.subTest(field=field):
                c=self.claims(); c[field]=value
                with self.assertRaises((ValueError,jwt.InvalidTokenError)):self.verify(c)
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        token=jwt.encode(self.claims(),other,algorithm='RS256')
        with self.assertRaises((ValueError,jwt.InvalidTokenError)):self.verifier.verify_github_oidc(token,jwks_client=self.jwks)
