"""Offline admission checks for one selected KEIRIN acquisition path."""
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import os
import re
import unittest

from race_ai import keirin_daily_ledger as daily
from scripts.keirin_cloud_owner_inputs import SourceSession


ROOT = Path(__file__).resolve().parents[1]
SELECTED = {
    "RACE_AI_KEIRIN_AB_AUTOGEN_ENABLED": "true",
    "RACE_AI_AB_PUBLIC_CAPTURE_ENABLED": "true",
    "RACE_AI_KEIRIN_AB_GIT_STORE_ENABLED": "true",
    "RACE_AI_AB_SOURCE_S3_PREFIX": "",
}


def job_condition(filename, job):
    source = (ROOT / ".github/workflows" / filename).read_text()
    section = source.split("\n  " + job + ":\n", 1)[1]
    section = re.split(r"\n  [a-zA-Z][a-zA-Z0-9_-]*:\n", section, 1)[0]
    match = re.search(r"^    if: (.+)$", section, re.M)
    expression = match.group(1)
    if expression in (">-", ">", "|", "|-"):
        expression = section[match.end():].split("\n    runs-on:", 1)[0]
        expression = expression.split("\n    uses:", 1)[0]
        expression = " ".join(line.strip() for line in expression.splitlines()
                              if line.strip() and not line.lstrip().startswith("#"))
    return expression


def admitted(expression, *, env=None, event="schedule", schedule="3,33 * * * *",
             mode="run", committed="false", manual=False):
    variables = {name: "" for name in SELECTED}
    variables.update(env or {})
    context = {
        "vars": NS(**variables),
        "github": NS(repository="haji84/RACE-AI", ref="refs/heads/main",
                     event_name=event,
                     event=NS(schedule=schedule, head_commit=NS(message=""))),
        "inputs": NS(mode=mode, manual71_pilot=manual),
        "needs": NS(config_readiness=NS(outputs=NS(eligible="true")),
                    pr71=NS(outputs=NS(committed=committed)),
                    fallback_scheduling_gate=NS(outputs=NS(should_capture="true"))),
        "true": True, "false": False,
        "always": lambda: True, "cancelled": lambda: False,
        "startsWith": lambda text, prefix: text.startswith(prefix),
    }
    expression = expression.replace("needs.github-hosted-pr71-cycle", "needs.pr71")
    expression = expression.replace("&&", " and ").replace("||", " or ")
    expression = re.sub(r"!(?!=)", " not ", expression).strip()
    return bool(eval(expression, {"__builtins__": {}}, context))


class RuntimeSelectionTests(unittest.TestCase):
    def test_ab_opt_in_stops_legacy_source_before_each_transport_call(self):
        # Removing the per-request selection check must expose a second GET.
        calls = []
        session = SourceSession(lambda url: calls.append(url) or b"fixture",
                                monotonic=lambda: 0, budget_seconds=240)
        url = "https://www.winticket.jp/keirin/odds/20300115"
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(session(url), b"fixture")
        with patch.dict(os.environ, SELECTED, clear=True):
            with self.assertRaisesRegex(ValueError, "SUPERSEDED_BY_NATIONWIDE_AB"):
                session(url)
        self.assertEqual(calls, [url])
        self.assertEqual(session.requests, 1)

    def test_partial_opt_in_keeps_the_existing_source_path(self):
        for missing in SELECTED:
            env = dict(SELECTED)
            env[missing] = "false" if missing != "RACE_AI_AB_SOURCE_S3_PREFIX" else "configured"
            with self.subTest(missing=missing), patch.dict(os.environ, env, clear=True):
                session = SourceSession(lambda _: b"fixture", monotonic=lambda: 0,
                                        budget_seconds=240)
                self.assertEqual(session("https://www.winticket.jp/keirin/odds/20300115"),
                                 b"fixture")
                self.assertEqual(session.requests, 1)

    def test_selected_ab_prevents_duplicate_daily_discovery(self):
        calls = []

        def collect(day):
            calls.append(day)
            return {"races": [], "source_url": "fixture://day", "source_sha256": "a" * 64}

        with patch.dict(os.environ, SELECTED, clear=True):
            with self.assertRaisesRegex(daily.DiscoveryError, "SUPERSEDED_BY_NATIONWIDE_AB"):
                daily.daily_run(today="2030-01-15", collector=collect)
        self.assertEqual(calls, [])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(daily.daily_run(today="2030-01-15", collector=collect)["discovered_count"], 0)
        self.assertEqual(calls, ["2030-01-15"])


class WorkflowSelectionTests(unittest.TestCase):
    def test_selected_ab_and_legacy_acquisition_are_mutually_exclusive(self):
        # Evaluate the actual GitHub conditions: a missing guard or misplaced
        # OR would admit duplicate provider work, even if the source is pinned.
        selected = job_condition("keirin-nationwide-ab-auto.yml", "github-only-owner-capture")
        routes = (
            ("keirin-pr71-owner-autonomous.yml", "public-preflight", "3,33 * * * *", "run"),
            ("keirin-pr71-owner-autonomous.yml", "github-hosted-pr71-cycle", "8,13,18,23,28,38,43,48,53,58 * * * *", "run"),
            ("keirin-daily-discovery.yml", "daily_live_once", "8 5,7 * * *", "run"),
            ("keirin-github-autonomous.yml", "capture-completed-races", "21 0-19 * * *", "capture"),
        )
        for filename, job, cron, mode in routes:
            condition = job_condition(filename, job)
            for event in ("schedule", "workflow_dispatch"):
                with self.subTest(job=job, event=event):
                    self.assertTrue(admitted(selected, env=SELECTED, event=event))
                    self.assertFalse(admitted(condition, env=SELECTED, event=event,
                                              schedule=cron, mode=mode))
                    self.assertTrue(admitted(condition, event=event, schedule=cron, mode=mode))
            for missing in SELECTED:
                env = dict(SELECTED)
                env[missing] = "false" if missing != "RACE_AI_AB_SOURCE_S3_PREFIX" else "configured"
                with self.subTest(job=job, missing=missing):
                    self.assertFalse(admitted(selected, env=env))
                    self.assertTrue(admitted(condition, env=env, schedule=cron, mode=mode))

    def test_fallbacks_cannot_restart_superseded_legacy_capture(self):
        for filename, job in (
            ("keirin-pr71-watchdog.yml", "trusted-fallback"),
            ("keirin-personal-hourly-canary.yml", "fallback_scheduling_gate"),
            ("keirin-personal-hourly-canary.yml", "fallback_nationwide_capture"),
        ):
            condition = job_condition(filename, job)
            with self.subTest(job=job):
                self.assertFalse(admitted(condition, env=SELECTED))
                self.assertTrue(admitted(condition))

    def test_prior_archive_readback_requires_dispatch_when_ab_supersedes_the_writer(self):
        condition = job_condition("keirin-pr71-owner-autonomous.yml", "independent-cloud-readback")
        self.assertTrue(admitted(condition, env=SELECTED, event="workflow_dispatch"))
        self.assertFalse(admitted(condition, env=SELECTED, event="schedule"))
        self.assertTrue(admitted(condition, committed="true"))
        self.assertFalse(admitted(condition))
        self.assertFalse(admitted(condition, env=SELECTED, event="pull_request"))
        self.assertFalse(admitted(condition, env=SELECTED, event="workflow_dispatch", manual=True))

    def test_existing_nightly_archive_research_remains_readable(self):
        condition = job_condition("keirin-github-autonomous.yml", "nightly-unattended-owner-research")
        self.assertTrue(admitted(condition, env=SELECTED, schedule="50 19 * * *"))
        self.assertTrue(admitted(condition, env=SELECTED, event="workflow_dispatch", mode="nightly"))


if __name__ == "__main__":
    unittest.main()
