"""No-network D+1 route E2E: pinned PR64 + actual PR71 scoring code.

This harness is synthetic. It does not establish official result availability.
Run only in a job with the pinned pr64-reference checkout.
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import os
import tempfile

from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
from scripts import boat_nationwide_result_audit as audit

RACE='20261103-17-08'
CUTOFF='2026-11-03T13:35:00+09:00'
SAVED='2026-11-03T04:24:58Z'
RESULT_AT='2026-11-04T02:10:00+09:00'


def build_frozen(with_shadow=True):
    boats=[dict(lane=i,racer_id=f'{5000+i}',national_win_rate=5.0,
                exhibition_time_seconds=6.80,motor_two_place_rate_percent=30.0)
           for i in range(1,7)]
    source=dict(race_id=RACE,cutoff_at=CUTOFF,
                captured_at='2026-11-03T13:19:00+09:00',
                program_source_sha256='a'*64,
                beforeinfo_source_sha256='b'*64,boats=boats)
    pair=build_pair(source,'2026-11-03T13:20:00+09:00')
    extra=dict(race_id=RACE,observed_at='2026-11-03T13:19:30+09:00',
               source_sha256='c'*64,participants=[
               dict(lane=i,racer_id=f'{5000+i}',local_win_rate=5.0,
                    average_st=0.15,exhibition_st=0.13,exhibition_st_status='OK')
               for i in range(1,7)])
    shadow=build_live_feature_shadow(source,extra,'2026-11-03T13:20:01+09:00')
    return dict(schema='RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1',
                state='FORECASTS_GENERATED_NEED_ARTIFACT_CLOCK_VERIFICATION',
                paired_forecasts=[pair],
                additional_official_feature_shadows=[shadow] if with_shadow else [])


class FrozenClock:
    @classmethod
    def now(cls,tz=None):
        t=datetime.fromisoformat('2026-11-04T02:50:00+09:00')
        return t.astimezone(tz or timezone.utc)

    fromisoformat=staticmethod(datetime.fromisoformat)


def check(with_shadow):
    frozen=build_frozen(with_shadow)
    raw=json.dumps(frozen,ensure_ascii=False,separators=(',',':')).encode()
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);(root/'national_source').mkdir()
        (root/'national_source'/'national.json').write_bytes(raw)
        seen=[]
        def fake_get(url):
            assert '/raceresult?' in url, f'unwanted D+1 racelist fetch: {url}'
            seen.append(url)
            audit.requests_used += 1
            return b'SYNTHETIC_PARSER_MOCK',datetime.fromisoformat(RESULT_AT),'d'*64
        def fake_parse(source,*,kind,day,venue,race_no,source_url,captured_at,entries):
            assert entries is None and kind=='raceresult' and venue=='17' and race_no==8
            return dict(race_id=RACE,kind='raceresult',body_identity_verified=True,
                        closed_at=CUTOFF,captured_at=captured_at,status='AVAILABLE',
                        data=dict(status='settled',finish_confirmed=True,refund_boats=[],
                            refunds=[],top3=[1,2,3],
                            payouts=[dict(bet_type='trifecta',combination=[1,2,3],
                                          payout_per_100_yen=1230)],
                            results=[dict(lane=i,racer_registration_id=f'{5000+i}',
                                          finish_status='FINISHED') for i in range(1,7)]))
        env={'RACE_AI_NATIONAL_RESULT_OWNER_REVIEWED':'true',
             'RACE_AI_NATIONAL_GITHUB_CREATED_AT':SAVED}
        with patch.dict(os.environ,env), patch.multiple(audit,
                ROOT=root,OUT=root/'out',FORECAST_SHA=hashlib.sha256(raw).hexdigest(),
                get=fake_get,parse_update=fake_parse,datetime=FrozenClock):
            result=audit.run()
        assert len(result['official_results'])==1, result
        row=result['official_results'][0]
        if with_shadow:
            assert row['state']=='INDEPENDENT_AB_RESULT_VERIFIED',row
            assert row['historical_roster_identity']['roster_source']=='SEALED_PRE_CUTOFF_C_LITE'
            assert len(seen)==1,seen
            assert len(row['paired_comparison']['models'])==2
        else:
            assert row['state']=='HISTORIC_PRE_CLOSE_ROSTER_MISSING',row
            assert not seen,seen
        return row['state'],len(seen)


if __name__=='__main__':
    print('OFFLINE_D_PLUS_ONE_ROUTE_SYNTHETIC',check(True),check(False))
