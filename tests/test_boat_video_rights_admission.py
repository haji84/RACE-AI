"""Research-only video source admission; no downloader or production writer."""
from datetime import datetime, timedelta, timezone
import unittest
from copy import deepcopy
from race_ai.actions_contract import digest

JST=timezone(timedelta(hours=9))
NOW=datetime(2030,4,1,11,40,tzinfo=JST)
CUT='2030-04-01T12:00:00+09:00'
RACE='20300401-24-12'
SHA='b'*64

def candidate(**kwargs):
    row=dict(race_id=RACE,cutoff_at=CUT,captured_at='2030-04-01T11:30:00+09:00',
             media_sha256='a'*64,source_kind='RIGHTS_HOLDER_SUPPLIED')
    row.update(kwargs)
    return row

def agreement(**kwargs):
    doc=dict(schema='RACE_AI_BOAT_PRIVATE_VIDEO_RIGHTS_V1',race_id=RACE,
             video_sha256='a'*64,grant_evidence_sha256=SHA,
             rights_source='RIGHTS_HOLDER_WRITTEN_GRANT',
             permitted_uses=['PRIVATE_COPY','AUTOMATED_FRAME_ANALYSIS','RESEARCH_FORECAST_DERIVATION'],
             begins_at='2030-03-31T12:00:00+09:00',expires_at='2030-04-03T12:00:00+09:00',
             restrictions_verified_at='2030-04-01T11:35:00+09:00',
             public_distribution_permitted=False)
    doc.update(kwargs)
    return doc

def verifier(doc,original):
    assert doc['video_sha256']==original['media_sha256']
    return dict(manifest_sha256=digest(doc),evidence_sha256=doc['grant_evidence_sha256'],
                state='INDEPENDENT_RIGHTS_RECEIPT_VERIFIED',
                verified_at='2030-04-01T11:36:00+09:00')

class RightsAdmissionTests(unittest.TestCase):
    def test_without_independently_read_rights_evidence_never_admit(self):
        from race_ai.boat_video_rights_admission import review
        before=deepcopy((candidate(),agreement()))
        out=review(before[0],before[1],now=NOW,verify_grant=None)
        self.assertEqual(out['state'],'HOLD_INDEPENDENT_RIGHTS_RECEIPT_REQUIRED')
        self.assertEqual((before[0],before[1]),before)
        self.assertFalse(out['source_fetch_performed'])
        self.assertFalse(out['production_video_forecast_proven'])

    def test_bound_grant_allows_private_research_only(self):
        from race_ai.boat_video_rights_admission import review
        out=review(candidate(),agreement(),now=NOW,verify_grant=verifier)
        self.assertEqual(out['state'],'READY_PRIVATE_RESEARCH_INPUT_ONLY')
        self.assertFalse(out['source_fetch_performed'])
        self.assertFalse(out['production_video_forecast_proven'])
        self.assertEqual(out['video_sha256'],'a'*64)
        self.assertEqual(out['race_id'],RACE)

    def test_plain_public_site_policy_does_not_authorize_video_ai_reuse(self):
        from race_ai.boat_video_rights_admission import review
        out=review(candidate(),agreement(rights_source='PUBLIC_FAQ_ONLY'),now=NOW,verify_grant=verifier)
        self.assertEqual(out['state'],'HOLD_EXPLICIT_RIGHTS_SCOPE_REQUIRED')

    def test_missing_analysis_derivation_grant_or_conflicting_bytes_is_rejected(self):
        from race_ai.boat_video_rights_admission import review
        base=agreement()
        for change in [dict(permitted_uses=['PRIVATE_COPY','AUTOMATED_FRAME_ANALYSIS']),
                       dict(video_sha256='c'*64),
                       dict(public_distribution_permitted=True),
                       dict(race_id='20300401-01-01')]:
            with self.subTest(change=change):
                out=review(candidate(),agreement(**change),now=NOW,verify_grant=verifier)
                self.assertNotEqual(out['state'],'READY_PRIVATE_RESEARCH_INPUT_ONLY')
        self.assertEqual(agreement(),base)

    def test_late_source_expired_grant_or_late_receipt_stays_hold(self):
        from race_ai.boat_video_rights_admission import review
        self.assertEqual(review(candidate(captured_at=CUT),agreement(),now=NOW,verify_grant=verifier)['state'],
                         'HOLD_PRE_CUTOFF_VIDEO_SOURCE_REQUIRED')
        self.assertEqual(review(candidate(),agreement(expires_at='2030-04-01T11:39:00+09:00'),
                                now=NOW,verify_grant=verifier)['state'],'HOLD_GRANT_NOT_VALID_AT_ANALYSIS')
        self.assertEqual(review(candidate(),agreement(),now=datetime(2030,4,1,12,1,tzinfo=JST),
                                verify_grant=verifier)['state'],'HOLD_PRE_CUTOFF_WINDOW_CLOSED')
        def late(doc,original):
            receipt=verifier(doc,original);receipt['verified_at']=CUT;return receipt
        self.assertEqual(review(candidate(),agreement(),now=NOW,verify_grant=late)['state'],
                         'HOLD_RIGHTS_RECEIPT_INVALID_OR_LATE')

    def test_production_claim_is_never_inferred_from_any_receipt(self):
        from race_ai.boat_video_rights_admission import review
        for k in ('OWNER_RECORDED','RIGHTS_HOLDER_SUPPLIED'):
            self.assertFalse(review(candidate(source_kind=k),agreement(),now=NOW,
                                    verify_grant=verifier)['production_video_forecast_proven'])

if __name__=='__main__':unittest.main()
