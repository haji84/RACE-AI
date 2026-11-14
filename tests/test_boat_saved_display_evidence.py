from copy import deepcopy
import unittest
from scripts.boat_saved_display_evidence import verified

def counts():
    site = dict(schema='RACE_AI_LIVE_SITE_CHECK_COUNTS_V1', status='LIVE_OWNER_SITE_VERIFIED',
        active_model_families=15, widths_checked=2, removed_seller_hidden=True,
        participant_names=True, editable_daily_budget=True, per_race_1000_simulation=True,
        hit_miss_rate_roi_and_settled_pending_net_visible=True, key_in_requests_or_storage=False,
        blocked_external_requests=0, plaintext_published=False)
    audit = dict(status='SETTLED', plan_sha256='a'*64, frozen_plan_reallocated=False,
        forecasting_performed=False, actual_purchases=False, promotion_allowed=False,
        independent_pre_cutoff_receipt_verified=False, accuracy_improvement_proven=False)
    return site, audit

class DisplayEvidenceTests(unittest.TestCase):
    def check(self, site, audit, **options):
        return verified(site, audit, expected_plan_sha256='a'*64,
            site_outcome=options.get('site_outcome','success'), audit_outcome=options.get('audit_outcome','success'))

    def test_real_count_flags_accept_without_claiming_receipt_or_improvement(self):
        self.assertTrue(self.check(*counts()))

    def test_rejected_browser_report_cannot_pass_through_a_successful_tee(self):
        site,audit=counts();site['status']='LIVE_OWNER_SITE_REJECTED'
        self.assertFalse(self.check(site,audit))
        self.assertFalse(self.check({},audit))

    def test_failed_step_cannot_be_repaired_by_success_text(self):
        self.assertFalse(self.check(*counts(),site_outcome='failure'))
        self.assertFalse(self.check(*counts(),audit_outcome='failure'))

    def test_old_model_selection_and_missing_required_flags_are_rejected(self):
        site,audit=counts()
        for key,value in [('active_model_families',16),('removed_seller_hidden',False),
                          ('key_in_requests_or_storage',True),('blocked_external_requests',1)]:
            bad=deepcopy(site);bad[key]=value
            with self.subTest(key=key):self.assertFalse(self.check(bad,audit))

    def test_changed_plan_or_reallocated_budget_is_rejected(self):
        site,audit=counts()
        for key,value in [('plan_sha256','b'*64),('frozen_plan_reallocated',True),
                          ('actual_purchases',True),('forecasting_performed',True)]:
            bad=deepcopy(audit);bad[key]=value
            with self.subTest(key=key):self.assertFalse(self.check(site,bad))

    def test_truthy_strings_and_boolean_counters_are_not_attestations(self):
        site,audit=counts();site['removed_seller_hidden']='true'
        self.assertFalse(self.check(site,audit))
        site,audit=counts();site['widths_checked']=True
        self.assertFalse(self.check(site,audit))

    def test_explicit_audited_day_is_required_and_cannot_be_labelled_current_after_midnight(self):
        site,audit=counts();audit['day']='2030-04-01'
        site.update(checked_day='2030-04-01',current_day='2030-04-02',date_scope='HISTORICAL_DAY',
                    checked_day_results=98,checked_day_p1_groups=30,verified_at='2030-04-01T16:00:00Z',
                    current_day_results=None,current_day_p1_groups=None)
        def check(value):
            return verified(value,audit,expected_plan_sha256='a'*64,expected_day='2030-04-01',
                            site_outcome='success',audit_outcome='success')
        self.assertTrue(check(site))
        for key,value in (('checked_day','2030-04-02'),('date_scope','CURRENT_DAY'),
                          ('current_day_results',98),('current_day','2030-02-30')):
            bad=deepcopy(site);bad[key]=value
            with self.subTest(key=key):self.assertFalse(check(bad))

if __name__ == '__main__':
    unittest.main()
