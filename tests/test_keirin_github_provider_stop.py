"""Fixture-only proof that provider denials persist beyond runner disk life."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from race_ai import keirin_github_provider_stop as stop
from scripts import keirin_github_only_ab_day as live


class ProviderStopGuard(unittest.TestCase):
    def test_untrusted_marker_and_wrong_day_rejected(self):
        with self.assertRaises(stop.ProviderStopError):
            stop._check({"schema":stop.SCHEMA,
                         "day_jst":"2026-11-19",
                         "code":"ANYTHING_IS_ALLOWED",
                         "observed_at":"2026-11-19T09:00:00+09:00"},
                        "2026-11-19")
        with self.assertRaises(stop.ProviderStopError):
            stop._path("2026-11-32")

    def test_refuses_provider_get_after_existing_git_stop(self):
        with TemporaryDirectory() as temp:
            repo=Path(temp)
            with patch.object(live.archive,"_remote",return_value=repo), \
                 patch.object(live.archive,"_refresh",
                              return_value="f"*40), \
                 patch.object(stop,"read",return_value={
                     "schema":stop.SCHEMA,
                     "day_jst":"2026-11-19",
                     "code":"PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                     "observed_at":"2026-11-19T00:00:00+09:00"}), \
                 patch.object(live.archive,"_cmd") as git:
                with self.assertRaisesRegex(
                        live.GitHubOnlyDayError,"PREVIOUS_DAY_DENIAL"):
                    live.archived_day(repo,"2026-11-19")
                git.assert_not_called()

    def test_complete_stop_fields_validate_without_private_data(self):
        marker=stop._check({
            "schema":stop.SCHEMA,
            "day_jst":"2026-11-19",
            "code":"PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
            "observed_at":"2026-11-19T00:00:00+09:00",
        },"2026-11-19")
        self.assertEqual(marker["code"],
                         "PROVIDER_DENIED_OR_RATE_LIMITED_STOP")
        self.assertNotIn("html",json.dumps(marker).lower())

    def test_legacy_previous_race_key_still_blocks_same_observation_day(self):
        marker = {
            "schema": stop.SCHEMA, "day_jst": "2026-11-18",
            "code": "PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
            "observed_at": "2026-11-19T00:05:00+09:00",
        }

        def show(repo, head, path):
            return ((0, json.dumps(marker)) if path ==
                    f"{stop.ROOT}/2026-11-18.json" else None)

        with TemporaryDirectory() as temp:
            repo = Path(temp)
            with patch.object(live.archive, "_remote", return_value=repo), \
                 patch.object(live.archive, "_refresh", return_value="f" * 40), \
                 patch.object(live.archive, "_show", side_effect=show), \
                 patch.object(live.archive, "_cmd", return_value=(0, "")):
                with self.assertRaisesRegex(live.GitHubOnlyDayError,
                                            "DENIAL_NO_RETRY"):
                    live.archived_day(repo, "2026-11-19")

    def test_new_stop_write_cannot_use_race_day_instead_of_observed_day(self):
        with TemporaryDirectory() as temp:
            repo = Path(temp)
            with patch.object(stop.archive, "_remote", return_value=repo), \
                 patch.object(stop.archive, "_refresh", return_value="f" * 40), \
                 patch.object(stop, "read", return_value={"already": "stopped"}):
                with self.assertRaisesRegex(stop.ProviderStopError,
                                            "OBSERVED_DAY_MISMATCH"):
                    stop.append_once(
                        repo=repo, day="2026-11-18",
                        code="PROVIDER_DENIED_OR_RATE_LIMITED_STOP",
                        observed_at="2026-11-19T00:05:00+09:00")


if __name__=="__main__":
    unittest.main()
