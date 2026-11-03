"""Read-only connectivity check: health 200, protected D1 endpoint 401."""
from __future__ import annotations
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
import sys
from scripts.keirin_d1_bridge_once import WORKER

def main():
    try:
        req=Request(WORKER+"/health",method="GET",headers={
          "Accept":"application/json",
          "User-Agent":"RACE-AI-unauthenticated-boundary-check/1",
        })
        with urlopen(req,timeout=10) as resp:
            meta=json.loads(resp.read(5000))
            if resp.status!=200 or meta.get("service")!=(
                "RACE_AI_KEIRIN_PRIVATE_STATE_V1"):
                return 2
        req=Request(WORKER+"/v1/status?day=2026-11-03",
                    method="GET",headers={"Accept":"application/json"})
        try:
            with urlopen(req,timeout=10) as response:
                # Any 200 leaks private data to an anonymous caller.
                return 3
        except HTTPError as e:
            if e.code!=401:
                return 4
        print('{"service_healthy":true,"unauthenticated_private_status_denied":true}')
        return 0
    except (OSError,ValueError,URLError):
        print('{"service_healthy":false,"private_storage_not_claimed":true}')
        return 2

if __name__=="__main__":
    sys.exit(main())
