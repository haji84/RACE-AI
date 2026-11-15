"""A server-owned worker invokes real native code; all race facts are fictional."""
from datetime import datetime, timedelta
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from race_ai import existing_model_dispatch as native
from race_ai.local_forecast_server import make_server
from race_ai.local_forecast_service import LocalForecastService
from tests.test_local_forecast_service import Provider
from tests.test_permissioned_source_delivery import AT


class AutomaticNativeIntegration(unittest.TestCase):
    def test_server_starts_native_generation_and_refreshes_without_generation_post(self):
        now = [datetime.fromisoformat(AT)]
        class Inputs(Provider):
            def collect(self, stage="P0", **kwargs):
                d = super().collect(stage=stage, **kwargs)
                if stage == "P1":
                    for row in d["schedule"]: row["stage"] = "P1"
                    d["inputs"] = {}  # no invented exhibition
                return d
        with tempfile.TemporaryDirectory() as tmp:
            service = LocalForecastService(Path(tmp), provider=Inputs(), clock=lambda: now[0])
            with make_server(service) as server:
                self.assertEqual(service.journal.originals(), [], "construct/bind must not infer")
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                def get(route):
                    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=15)
                    try:
                        connection.request("GET", route)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 200)
                        return json.loads(response.read())
                    finally: connection.close()
                try:
                    end = time.monotonic() + 20
                    while time.monotonic() < end:
                        status = get("/api/forecast/status")
                        if status["auto"].get("state") == "WAITING" and status["auto"].get("round_no") == 1:
                            break
                        time.sleep(.02)
                    else: self.fail("server-owned automatic round did not complete")
                    latest = get("/api/forecast/latest?sport=boat&stage=P0")
                    self.assertTrue(latest["available"])
                    self.assertEqual(latest["summary"]["generated"], 4)
                    self.assertFalse(get("/api/forecast/latest?sport=boat&stage=P1")["available"])
                    originals = service.journal.originals()
                    self.assertEqual(len(originals), 4)
                    now[0] += timedelta(seconds=180)
                    with patch.object(native, "run_suite", side_effect=AssertionError("old P0 regenerated")):
                        server.automation.tick()
                    after = get("/api/forecast/latest?sport=boat&stage=P0")
                    self.assertEqual(after["revision"], latest["revision"])
                    self.assertEqual(service.journal.originals(), originals)
                    self.assertEqual(get("/api/forecast/status")["auto"]["round_no"], 2)
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
                    self.assertFalse(thread.is_alive())
