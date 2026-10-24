"""No-network scenarios for full-sport odds budget and shared-account hold.

The free-tier budget is never a license, a billing guarantee, or proof of
source recency.  Provider requests are per race, not per ticket.
"""
from __future__ import annotations

import unittest
from race_ai.free_tier_budget import (
    OtherAppUsage, estimate_free_capacity, CONTRACT_VERSION,
)


class FreeTierCapacityTests(unittest.TestCase):
    def test_realistic_one_race_pilot_has_small_demand_but_unknown_approval(self):
        result=estimate_free_capacity(races_per_day=1,refresh_window_minutes=60,
                                      active_users_per_day=1,minutes_open_per_user=60)
        self.assertEqual(result["projected"]["upstream_requests"],60)
        self.assertEqual(result["projected"]["d1_rows_written"],120)
        self.assertEqual(result["projected"]["viewer_api_requests"],60)
        self.assertFalse(result["free_cost_guaranteed"])
        self.assertEqual(result["account_budget_check"],"HOLD")
        self.assertIn("SHARED_CLOUDFLARE_ACCOUNT_USAGE_UNKNOWN",result["warnings"])
        self.assertIn("UPSTREAM_SOURCE_PURPOSE_AND_RATE_UNVERIFIED",result["warnings"])

    def test_three_hundred_races_one_hour_shared_uses_bounded_projected_resources(self):
        result=estimate_free_capacity(
            races_per_day=300,refresh_window_minutes=60,
            active_users_per_day=30,minutes_open_per_user=600,
            usage=OtherAppUsage(worker_requests=8000,d1_rows_written=1000,d1_rows_read=50000),
            source_rights_verified=True,provider_requests_allowed_per_day=20000)
        self.assertEqual(result["schema"],CONTRACT_VERSION)
        self.assertEqual(result["projected"]["upstream_requests"],18000)
        self.assertEqual(result["projected"]["viewer_api_requests"],18000)
        self.assertEqual(result["projected"]["worker_requests"],36000)
        self.assertEqual(result["projected"]["d1_rows_written"],36000)
        self.assertEqual(result["soft_headroom_after_other_apps"]["worker_requests"],16000)
        self.assertEqual(result["soft_headroom_after_other_apps"]["d1_rows_written"],23000)
        self.assertEqual(result["account_budget_check"],"PASS_ESTIMATE_ONLY")
        self.assertFalse(result["free_cost_guaranteed"])
        self.assertFalse(result["forecast_model_cpu_assumed_on_cloudflare"])

    def test_many_users_exceed_60_percent_workers_soft_cap(self):
        result=estimate_free_capacity(
            races_per_day=300,refresh_window_minutes=60,
            active_users_per_day=100,minutes_open_per_user=600,
            usage=OtherAppUsage(0,0,0),
            source_rights_verified=True,provider_requests_allowed_per_day=50000)
        self.assertEqual(result["projected"]["worker_requests"],78000)
        self.assertIn("CLOUDFLARE_SOFT_CAP_EXCEEDED:worker_requests",
                      result["warnings"])
        self.assertEqual(result["account_budget_check"],"HOLD")

    def test_longer_refresh_window_may_exceed_d1_write_limit(self):
        result=estimate_free_capacity(
            races_per_day=300,refresh_window_minutes=180,
            active_users_per_day=0,
            usage=OtherAppUsage(0,0,0),
            source_rights_verified=True,provider_requests_allowed_per_day=60000)
        self.assertEqual(result["projected"]["upstream_requests"],54000)
        self.assertEqual(result["projected"]["d1_rows_written"],108000)
        self.assertIn("CLOUDFLARE_SOFT_CAP_EXCEEDED:d1_rows_written",
                      result["warnings"])

    def test_unknown_shared_usage_does_not_become_zero(self):
        result=estimate_free_capacity(
            races_per_day=1,active_users_per_day=0,
            usage=OtherAppUsage(worker_requests=None,d1_rows_written=0,d1_rows_read=0),
            source_rights_verified=True,provider_requests_allowed_per_day=100)
        self.assertIsNone(result["soft_headroom_after_other_apps"]["worker_requests"])
        self.assertEqual(result["account_budget_check"],"HOLD")

    def test_provider_quota_missing_or_insufficient_is_hard_stop_for_proposal(self):
        unknown=estimate_free_capacity(
            races_per_day=10,usage=OtherAppUsage(0,0,0),
            source_rights_verified=True)
        self.assertIn("UPSTREAM_REQUEST_LIMIT_UNKNOWN",unknown["warnings"])
        too_low=estimate_free_capacity(
            races_per_day=10,usage=OtherAppUsage(0,0,0),
            source_rights_verified=True,provider_requests_allowed_per_day=20)
        self.assertIn("UPSTREAM_DAILY_REQUEST_LIMIT_EXCEEDED",too_low["warnings"])

    def test_invalid_input_and_optimistic_fractions_rejected(self):
        for opts in [
            dict(races_per_day=True),
            dict(races_per_day=-1),
            dict(races_per_day=1,refresh_window_minutes=0),
            dict(races_per_day=1,quote_update_seconds=20),
            dict(races_per_day=1,active_users_per_day=1.5),
            dict(races_per_day=1,usage=OtherAppUsage(d1_rows_written=-1)),
        ]:
            with self.subTest(opts=opts),self.assertRaises(ValueError):
                estimate_free_capacity(**opts)
