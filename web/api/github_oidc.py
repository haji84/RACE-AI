"""Verify GitHub Actions OIDC for a single RACE AI Preview probe workflow.

Reject unsigned, untrusted, or mismatched claims. GitHub JWKS verification
uses PyJWT cryptography backend. No shared secret or repository token needed.
"""
from __future__ import annotations
import jwt

ISSUER="https://token.actions.githubusercontent.com"
AUDIENCE="race-ai-preview-blob-probe"
REPOSITORY="haji84/RACE-AI"
REF="refs/heads/feat/boat-oidc-probe-auth"
WORKFLOW=".github/workflows/boat-blob-e2e.yml"


def verify_github_oidc(token: str, *, jwks_client=None) -> dict:
    if not isinstance(token,str) or len(token)>8192:
        raise ValueError("invalid OIDC token")
    client=jwks_client or jwt.PyJWKClient(ISSUER+"/.well-known/jwks")
    key=client.get_signing_key_from_jwt(token).key
    claims=jwt.decode(token,key,algorithms=["RS256"],audience=AUDIENCE,
                      issuer=ISSUER,options={"require":["iss","aud","exp","iat","sub"]},
                      leeway=30)
    if (claims.get("repository")!=REPOSITORY or
        claims.get("repository_id")!="1416489937" or
        claims.get("repository_owner_id")!="173585154" or
        claims.get("sub")!="repo:haji84/RACE-AI:environment:blob-e2e-preview" or
        claims.get("ref")!=REF or
        claims.get("repository_owner")!="haji84" or
        claims.get("event_name") not in ("push","workflow_dispatch") or
        claims.get("workflow_ref")!=REPOSITORY+"/"+WORKFLOW+"@"+REF or
        claims.get("environment")!="blob-e2e-preview"):
        raise ValueError("untrusted GitHub Actions identity")
    return claims
