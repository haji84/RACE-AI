"""Synthetic-only integration of existing manual bridge with protected receipt gate."""
from hashlib import sha256
import unittest
from unittest.mock import patch, Mock

from race_ai.official_private_receipt_link import (
    ReceiptLinkError, link_protected_receipts,
)

DAY = '2031-01-05'
CUTOFF = '2031-01-05T11:00:00+09:00'
WIRE = b'fictional-protected-byte-exact-forecast'
SPORTS = ('boat', 'keirin', 'autorace', 'horse_jra', 'horse_local')


def fixture():
    rows = [dict(race_id=f'{sport}:{DAY}:v-{sport}:1', sport=sport,
                 venue=f'v-{sport}', race_no=1, event_date_jst=DAY,
                 archive_slots=[dict(source='RETAINED_DEVELOPMENT_REPORT')],
                 ledger_no_forecast_reason=None) for sport in SPORTS]
    bridge = dict(schema='RACE_AI_FOUR_SPORT_COHORT_BRIDGE_V1',
                  mode='OFFLINE_RESEARCH_COVERAGE_LINK', event_date_jst=DAY,
                  official_completeness_verified=False, source_rights_verified=False,
                  external_pre_cutoff_receipts_verified=False, formal_hit_at_8_all=None,
                  records=rows)
    rid = rows[0]['race_id']
    source = dict(race_id=rid, source_id='provider-fake',
                  source_sha256='a'*64, permission_ref='test-only',
                  published_at='2031-01-05T08:00:00+09:00',
                  observed_at='2031-01-05T08:30:00+09:00',
                  official_cutoff_at=CUTOFF)
    anchor_name = sha256((rid + '\0m1\0' + sha256(WIRE).hexdigest()).encode()).hexdigest()
    forecast = dict(race_id=rid, model_id='m1', model_version='v1',stage='P0',
                    original_wire_sha256=sha256(WIRE).hexdigest(),
                    original_generated_at='2031-01-05T10:00:00+09:00',
                    private_persisted_at='2031-01-05T10:01:00+09:00',
                    private_ref='synthetic://owner-only/one', cutoff_at=CUTOFF,
                    github_receipt={'run_id':123,'path':f'audit/freezes/{DAY}/{anchor_name}.json'},
                    provenance='PROSPECTIVE_PROTECTED_OWNER_ORIGINAL')
    return bridge, [source], [forecast]


def attestor(src):
    return dict(race_id=src['race_id'], source_sha256=src['source_sha256'],
                permission_ref=src['permission_ref'],cutoff_at=src['official_cutoff_at'],
                admitted_uses=['schedule','pre_race','private_retention'])


def validator(raw, claim):
    return dict(race_id=claim['race_id'],model_id=claim['model_id'],
                model_version=claim['model_version'],stage=claim['stage'],
                wire_sha256=sha256(raw).hexdigest(),top8_count=8)


class LinkTests(unittest.TestCase):
    def run_link(self, bridge=None, sources=None, forecasts=None, **kwargs):
        b,s,p=fixture()
        with patch('race_ai.race_bound_freeze_receipt.verify_bound_receipt',return_value=True) as verifier:
            report=link_protected_receipts(b if bridge is None else bridge,
                s if sources is None else sources,p if forecasts is None else forecasts,
                source_attestor=kwargs.get('source_attestor',attestor),
                protected_reader=kwargs.get('protected_reader',lambda ref: WIRE),
                forecast_validator=kwargs.get('forecast_validator',validator),
                trusted_legacy_verifier=kwargs.get('trusted_legacy_verifier',lambda *a,**kw:True),
                github_fetch=kwargs.get('github_fetch',lambda url: {}))
        return report,verifier

    @staticmethod
    def boat(report):
        return next(r for r in report['records'] if r['sport'] == 'boat')

    def test_all_five_category_rows_remain_and_forecast_only_one(self):
        report,verifier=self.run_link()
        self.assertEqual(len(report['records']),5)
        self.assertEqual({x['sport'] for x in report['records']},set(SPORTS))
        self.assertEqual(report['private_forecast_records'],1)
        self.assertEqual(report['external_receipts_checked'],1)
        self.assertEqual(self.boat(report)['private_checks'][0]['status'],
                         'CALLBACK_BOUND_PROOFS_REQUIRE_INDEPENDENT_OPERATOR_AUDIT')
        self.assertEqual(sum('NO_PROSPECTIVE_PRIVATE_PREDICTION' in r['unresolved'] for r in report['records']),4)
        self.assertIsNone(report['formal_hit_at_8_all'])
        self.assertIsNone(report['official_complete_denominator'])
        self.assertEqual(verifier.call_args.kwargs['expected_race_id'],fixture()[2][0]['race_id'])
        self.assertFalse(any(WIRE.decode() in str(r) for r in report['records']))

    def test_missing_permission_blocks_private_storage_read(self):
        reader=Mock(side_effect=AssertionError('private read must not happen'))
        result,v=self.run_link(source_attestor=None,protected_reader=reader)
        self.assertEqual(result['external_receipts_checked'],0)
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],'SOURCE_GATE_BLOCKED')
        reader.assert_not_called();v.assert_not_called()

    def test_invalid_rights_scope_cannot_set_approval(self):
        denied=lambda src:dict(attestor(src),admitted_uses=['schedule'])
        result,v=self.run_link(source_attestor=denied)
        self.assertFalse(self.boat(result)['source_admitted_by_callback'])
        v.assert_not_called()

    def test_no_forecast_from_original_ledger_never_backfilled(self):
        b,s,p=fixture();b['records'][0]['ledger_no_forecast_reason']='SOURCE_PERMISSION_NOT_VERIFIED'
        reader=Mock(side_effect=AssertionError('should not call'))
        result,v=self.run_link(bridge=b,protected_reader=reader)
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],'ORIGINAL_LEDGER_DECLARED_NO_FORECAST')
        reader.assert_not_called();v.assert_not_called()

    def test_original_private_bytes_must_match(self):
        result,v=self.run_link(protected_reader=lambda ref:b'other')
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],'PROTECTED_ORIGINAL_BYTES_MISMATCH')
        v.assert_not_called()

    def test_model_semantics_must_be_independently_validated(self):
        bad=lambda raw,p:dict(validator(raw,p),model_id='wrong')
        result,v=self.run_link(forecast_validator=bad)
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],'ORIGINAL_FORECAST_CONTENT_NOT_VALIDATED')
        v.assert_not_called()

    def test_official_cutoff_mismatch_rejected_without_private_io(self):
        b,s,p=fixture();p[0]['cutoff_at']='2031-01-05T10:59:00+09:00'
        result,v=self.run_link(bridge=b,sources=s,forecasts=p)
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],'OFFICIAL_CUTOFF_OR_SOURCE_TIME_MISMATCH')
        v.assert_not_called()

    def test_foreign_model_bound_anchor_path_is_rejected_before_private_io(self):
        b,s,p=fixture();p[0]['github_receipt']['path']='audit/freezes/2031-01-05/foreign.json'
        reader=Mock(side_effect=AssertionError('do not access private bytes'))
        result,v=self.run_link(bridge=b,sources=s,forecasts=p,protected_reader=reader)
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],
                         'MODEL_BOUND_EXTERNAL_ANCHOR_PATH_MISMATCH')
        reader.assert_not_called();v.assert_not_called()

    def test_external_verifier_false_is_not_a_success(self):
        b,s,p=fixture()
        with patch('race_ai.race_bound_freeze_receipt.verify_bound_receipt',return_value=False):
            result=link_protected_receipts(b,s,p,source_attestor=attestor,
                protected_reader=lambda _:WIRE, forecast_validator=validator,
                trusted_legacy_verifier=lambda *a,**k:True,github_fetch=lambda u:{})
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],
                         'GITHUB_RACE_BOUND_RECEIPT_NOT_VERIFIED')

    def test_late_or_reordered_forecast_rejected(self):
        b,s,p=fixture();p[0]['private_persisted_at']=CUTOFF
        with self.assertRaisesRegex(ReceiptLinkError,'LATE_OR_REORDERED'):
            self.run_link(bridge=b,sources=s,forecasts=p)

    def test_duplicate_forecast_rejected(self):
        b,s,p=fixture()
        with self.assertRaisesRegex(ReceiptLinkError,'PRIVATE_IDENTITY_OR_DUPLICATE'):
            self.run_link(bridge=b,sources=s,forecasts=p+p)

    def test_duplicate_source_rejected(self):
        b,s,p=fixture()
        with self.assertRaisesRegex(ReceiptLinkError,'SOURCE_IDENTITY_COLLISION'):
            self.run_link(bridge=b,sources=s+s,forecasts=p)

    def test_legacy_git_verified_function_failure_is_not_a_pass(self):
        b,s,p=fixture()
        with patch('race_ai.race_bound_freeze_receipt.verify_bound_receipt',side_effect=ValueError('wrong race')):
            result=link_protected_receipts(b,s,p,source_attestor=attestor,
                protected_reader=lambda _:WIRE,forecast_validator=validator,
                trusted_legacy_verifier=lambda *a,**k:True,github_fetch=lambda u:{})
        self.assertFalse(self.boat(result)['private_checks'][0]['external_receipt_checked'])
        self.assertEqual(self.boat(result)['private_checks'][0]['status'],
                         'GITHUB_RACE_BOUND_RECEIPT_NOT_VERIFIED')

    def test_uncertified_manual_bridge_cannot_become_formal_even_with_all_fixture_callbacks(self):
        r,v=self.run_link()
        self.assertFalse(r['all_official_races_verified'])
        self.assertIsNone(r['formal_capture_rate'])
        self.assertIsNone(r['actual_purchase_roi'])
        self.assertIsNone(r['brier'])
        self.assertIsNone(r['log_loss'])

if __name__=='__main__':
    unittest.main()
