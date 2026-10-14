import copy
import importlib.util
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from vercel.blob import GetBlobResult
from race_ai.day_snapshot_publisher import validate as validate_published_snapshot
from race_ai.public_day_feed import endpoint, normalize
from tests.test_public_day_feed import make_provider

MODULE = Path(__file__).resolve().parents[1] / "web/api/today.py"
spec = importlib.util.spec_from_file_location("race_today_api", MODULE)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def snapshot():
    day = api.current_day()
    return {
        "date_jst": day, "redistribution_authorized": True,
        "source_url": "https://example.org/approved", "source_sha256": "a" * 64,
        "first_observed_at": (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat(),
        "races": 1, "complete_six_boat_races": 1,
        "venues": [{"venue": "18", "races": [{
            "race_id": day.replace("-", "") + "-18-03", "preview_available": False,
            "boats": [{"lane": lane, "racer_registration_id": str(4000 + lane),
                       "motor_no": lane, "name": "Fixture"} for lane in range(1, 7)]
        }]}],
    }


class TodayBlobReaderTests(unittest.TestCase):
    def read(self, payload=None, *, content=None, result_changes=None, error=None):
        raw = content if content is not None else json.dumps(payload or snapshot()).encode()
        result = SimpleNamespace(content=raw, status_code=200,
                                 pathname="race-ai/day/" + api.current_day() + ".json",
                                 size=len(raw), content_type="application/json; charset=utf-8")
        for name, value in (result_changes or {}).items():
            setattr(result, name, value)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = result
        client.get.side_effect = error
        with patch.dict(os.environ, {
            "RACE_AI_FEED_APPROVED": "1", "BLOB_READ_WRITE_TOKEN": "fixture-blob-token",
            "VERCEL_OIDC_TOKEN": "must-not-be-used",
            "RACE_AI_BLOB_BASE_URL": "https://must-not-be-used.example",
        }, clear=True), patch.object(api, "AsyncBlobClient", return_value=client) as factory:
            status, data = api.load_feed()
        return status, data, client, factory

    def test_default_unapproved_never_reads_blob(self):
        for env in ({}, {"RACE_AI_FEED_APPROVED": "0"}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), \
                 patch.object(api, "AsyncBlobClient") as factory:
                self.assertEqual(api.load_feed(), (503, {"error": "FEED_NOT_APPROVED"}))
                factory.assert_not_called()

    def test_oidc_is_not_blob_authorization(self):
        with patch.dict(os.environ, {"RACE_AI_FEED_APPROVED": "1",
                                   "VERCEL_OIDC_TOKEN": "fixture-oidc"}, clear=True), \
             patch.object(api, "AsyncBlobClient") as factory:
            self.assertEqual(api.load_feed(), (503, {"error": "FEED_STORE_NOT_CONFIGURED"}))
            factory.assert_not_called()

    def test_current_private_sdk_content_and_exact_key(self):
        payload = snapshot()
        status, data, client, factory = self.read(payload)
        self.assertEqual((status, data), (200, payload))
        factory.assert_called_once_with(token="fixture-blob-token")
        client.get.assert_awaited_once_with("race-ai/day/" + api.current_day() + ".json",
                                          access="private", use_cache=False, timeout=8)
        client.put.assert_not_called()
        client.head.assert_not_called()
        client.__aexit__.assert_awaited_once()

    def test_actual_pinned_sdk_result_dataclass_is_supported(self):
        payload = snapshot()
        raw = json.dumps(payload).encode()
        result = GetBlobResult(url="https://unused.private.blob.vercel-storage.com/unused",
                               download_url="https://unused.example", pathname="race-ai/day/" + api.current_day() + ".json",
                               content_type="application/json", size=len(raw), content_disposition="",
                               cache_control="", uploaded_at=datetime.now(timezone.utc), etag="fixture",
                               content=raw, status_code=200)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = result
        with patch.dict(os.environ, {"RACE_AI_FEED_APPROVED": "1", "BLOB_READ_WRITE_TOKEN": "fixture"}, clear=True), \
             patch.object(api, "AsyncBlobClient", return_value=client):
            self.assertEqual(api.load_feed(), (200, payload))

    def test_normalized_publisher_snapshot_contract_is_preserved(self):
        day = datetime.fromisoformat(api.current_day()).date()
        raw = json.dumps(make_provider(day=day.isoformat(), result=True)).encode()
        source = endpoint(day)
        observed = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        normalized = normalize(raw, day=day, received_at=observed, source_url=source,
                               source_sha256=hashlib.sha256(raw).hexdigest())
        published = validate_published_snapshot(normalized, today=day, approval={
            "redistribution_authorized": True, "source_url": source,
            "evidence_reference": "synthetic-test-only", "reviewed_by": "test",
        })
        self.assertEqual(self.read(published)[:2], (200, published))

    def test_jst_day_rollover_during_read_rejected(self):
        day = api.current_day()
        payload = snapshot()
        with patch.object(api, "current_day", side_effect=[day, day, "2026-01-01"]):
            self.assertEqual(self.read(payload)[:2], (503, {"error": "FEED_STALE_OR_UNAPPROVED"}))

    def test_upstream_publication_timestamp_must_have_zone_and_not_be_future(self):
        for value in ((datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                      "2026-01-01T00:00:00", "invalid"):
            payload = snapshot()
            payload["upstream_published_at"] = value
            with self.subTest(value=value):
                self.assertEqual(self.read(payload)[:2], (503, {"error": "FEED_STALE_OR_UNAPPROVED"}))
        for value in (None, (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()):
            payload = snapshot()
            payload["upstream_published_at"] = value
            with self.subTest(value=value):
                self.assertEqual(self.read(payload)[:2], (200, payload))

    def test_racer_and_known_motor_identities_are_unique_within_race(self):
        for key in ("racer_registration_id", "motor_no"):
            payload = snapshot()
            boats = payload["venues"][0]["races"][0]["boats"]
            boats[1][key] = boats[0][key]
            with self.subTest(key=key):
                self.assertEqual(self.read(payload)[:2], (503, {"error": "FEED_STALE_OR_UNAPPROVED"}))
        payload = snapshot()
        for boat in payload["venues"][0]["races"][0]["boats"]:
            boat["motor_no"] = None
        self.assertEqual(self.read(payload)[:2], (200, payload))

    def test_result_fields_require_explicit_result_availability(self):
        for field, value in (("result_course", 1), ("result_st", .12), ("finish", 1)):
            for flag in (False, None):
                payload = snapshot()
                race = payload["venues"][0]["races"][0]
                if flag is not None:
                    race["result_available"] = flag
                race["boats"][0][field] = value
                with self.subTest(field=field, flag=flag):
                    self.assertEqual(self.read(payload)[:2], (503, {"error": "FEED_STALE_OR_UNAPPROVED"}))
        payload = snapshot()
        race = payload["venues"][0]["races"][0]
        race["result_available"] = False
        race["boats"][0].update(result_course=None, result_st=None, finish=None)
        self.assertEqual(self.read(payload)[:2], (200, payload))
        race["result_available"] = True
        race["boats"][0].update(result_course=1, result_st=.12, finish=1)
        self.assertEqual(self.read(payload)[:2], (200, payload))

    def test_preview_and_result_counts_follow_race_availability_flags(self):
        payload = snapshot()
        race = payload["venues"][0]["races"][0]
        race["result_available"] = False
        second = copy.deepcopy(race)
        second.update(race_id=api.current_day().replace("-", "") + "-18-04",
                      result_available=True, preview_available=True)
        payload["venues"][0]["races"].append(second)
        payload.update(races=2, complete_six_boat_races=2, previews=1, results=1)
        # Counts measure race flags, not number of result/preview boat values.
        self.assertEqual(self.read(payload)[:2], (200, payload))
        for field, value in (("results", 999), ("previews", -1),
                             ("results", True), ("previews", 0)):
            invalid = copy.deepcopy(payload)
            invalid[field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.read(invalid)[:2], (503, {"error": "FEED_STALE_OR_UNAPPROVED"}))

    def test_sdk_non_200_mismatch_and_failure_have_no_fallback(self):
        for changes in ({"status_code": 304}, {"status_code": 404},
                        {"pathname": "race-ai/day/old.json"}, {"content": "not-bytes"}):
            with self.subTest(changes=changes):
                status, data, client, _ = self.read(result_changes=changes)
                self.assertEqual(status, 503)
                self.assertEqual(set(data), {"error"})
                self.assertEqual(client.get.await_count, 1)
        status, data, client, _ = self.read(error=RuntimeError("secret upstream detail"))
        self.assertEqual((status, data), (503, {"error": "FEED_STORE_UNAVAILABLE"}))
        self.assertEqual(client.get.await_count, 1)

    def test_size_cap_checks_bytes_and_sdk_metadata(self):
        for content, changes in ((b" " * (api.MAX_BYTES + 1), {}),
                                 (b"{}", {"size": api.MAX_BYTES + 1})):
            with self.subTest(changes=changes):
                self.assertEqual(self.read(content=content, result_changes=changes)[:2],
                                 (503, {"error": "FEED_TOO_LARGE"}))

    def test_rejects_invalid_date_rights_and_provenance(self):
        for field, value in (("date_jst", "2026-01-01"), ("redistribution_authorized", 1),
                             ("source_url", "https:///missing-host"),
                             ("source_url", "https://user:password@example.org"),
                             ("source_sha256", "invalid"),
                             ("first_observed_at", "2026-01-01T00:00:00"),
                             ("first_observed_at", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())):
            payload = snapshot()
            payload[field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.read(payload)[0], 503)

    def test_rejects_schema_identity_and_count_conflicts(self):
        payloads = []
        base = snapshot()
        for path, value in ((["venues"], []), (["races"], True),
                            (["complete_six_boat_races"], 0),
                            (["venues", 0, "races", 0, "race_id"], "20260101-18-03"),
                            (["venues", 0, "races", 0, "boats", 0, "lane"], True),
                            (["venues", 0, "races", 0, "boats", 0, "motor_no"], 0),
                            (["venues", 0, "races", 0, "boats", 0, "racer_registration_id"], "bad")):
            payload = copy.deepcopy(base)
            target = payload
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            payloads.append(payload)
        for level in ("venue", "race", "lane"):
            payload = copy.deepcopy(base)
            if level == "venue":
                payload["venues"].append(copy.deepcopy(payload["venues"][0]))
            elif level == "race":
                payload["venues"][0]["races"].append(copy.deepcopy(payload["venues"][0]["races"][0]))
            else:
                payload["venues"][0]["races"][0]["boats"][1]["lane"] = 1
            payloads.append(payload)
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.read(payload)[0], 503)

    def test_json_malformed_nonobject_and_nonfinite_fail_closed(self):
        for raw in (b"not json", b"[]", b"null", b'{"date_jst":NaN}',
                    b'{"date_jst":"x","date_jst":"y"}'):
            with self.subTest(raw=raw):
                self.assertEqual(self.read(content=raw)[0], 503)
        payload = snapshot()
        payload["venues"][0]["races"][0]["boats"][0]["display_time"] = float("inf")
        self.assertEqual(self.read(content=json.dumps(payload).replace("Infinity", "1e1000").encode())[0], 503)

    def test_public_projection_drops_unknown_private_fields_at_each_level(self):
        payload = snapshot()
        expected = copy.deepcopy(payload)
        payload["approval"] = {"reviewed_by": "private-person"}
        payload["venues"][0]["private_notes"] = "secret"
        payload["venues"][0]["races"][0]["raw_upstream"] = "secret"
        payload["venues"][0]["races"][0]["boats"][0]["private_notes"] = "secret"
        self.assertEqual(self.read(payload)[:2], (200, expected))
