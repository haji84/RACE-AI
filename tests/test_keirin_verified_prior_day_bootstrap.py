"""Synthetic regression: prior-day manifest recovery must not forge recordings."""
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
from hashlib import sha256
import io
import json
import unittest

from race_ai.keirin_daily_public_catalog import combine, SOURCE_RACECARD, SOURCE_RESULTS
from scripts.keirin_autonomous_artifact_recovery import (
    collect, ArchiveEvidenceError
)

RUN_ID = 42584059802
SHA = "fd850df075912492a3116e71d8f89f78a52dd8da"


def artifact_bytes():
    def href(kind):
        return {"href": "https://www.winticket.jp/keirin/aomori/" + kind +
                "/2026110812/2/1", "text": "1R"}
    manifest = combine("2026-11-09", [
        {"source_url": SOURCE_RACECARD, "heading": "本日 2026年11月9日",
         "links": [href("racecard")]},
        {"source_url": SOURCE_RESULTS, "heading": "本日 2026年11月9日",
         "links": [href("raceresult")]}
    ])
    report = {
        "schema": "RACE_AI_KEIRIN_DAILY_RECORDINGS_ENCRYPTED_WAVE_V1",
        "date_jst": "2026-11-09",
        "dynamic_manifest_sha256": manifest["manifest_sha256"],
        "race_rows": [{
            "status": "ENCRYPTED_COMPLETE_PLAYER",
            "race_id": "202611091201",
            "source_video_sha256": sha256(b"synthetic-video").hexdigest(),
            "playback_ended": True,
        }]
    }
    memory = io.BytesIO()
    with ZipFile(memory, "w") as z:
        z.writestr("keirin-daily-wave.json", json.dumps(report))
        z.writestr("keirin-daily-source-inventory.json", json.dumps(manifest))
    return memory.getvalue()


def reviewed_run():
    return {
        "id": RUN_ID,
        "head_sha": SHA,
        "head_branch": "feat/keirin-matsuyama-1r-replay-pilot-20261108",
        "event": "pull_request",
        "conclusion": "success",
        "path": ".github/workflows/keirin-daily-all-races-video.yml",
        "repository": {"full_name": "haji84/RACE-AI"},
    }


class VerifiedPriorDayRecovery(unittest.TestCase):
    def test_trusted_prior_day_pr_metadata_is_source_only_not_recording(self):
        legacy = {"id": 13662681646, "expired": False,
                  "name": "keirin-daily-wave-evidence-42584059802"}
        with TemporaryDirectory() as root:
            path = Path(root)
            outcome = collect(
                "haji84/RACE-AI", "2026-11-09", mode="index",
                output_dir=path, items=[legacy],
                reader=lambda _: artifact_bytes(),
                run_reader=lambda run_id: reviewed_run())
            self.assertEqual(outcome["temporary_capture_race_ids"], [])
            source = json.loads((path / "day-source-manifest.json").read_text())
            self.assertEqual(source["date_jst"], "2026-11-09")
            self.assertEqual(source["discovered_race_count"], 1)
            self.assertFalse(outcome["readback_in_private_library_verified"])

    def test_modified_pr_sha_is_rejected_not_accepted_as_evidence(self):
        legacy = {"id": 13662681646, "expired": False,
                  "name": "keirin-daily-wave-evidence-42584059802"}
        bad = reviewed_run()
        bad["head_sha"] = "0" * 40
        with TemporaryDirectory() as root:
            with self.assertRaisesRegex(ArchiveEvidenceError,
                                        "UNTRUSTED_PRIOR_DAY"):
                collect("haji84/RACE-AI", "2026-11-09", mode="index",
                        output_dir=Path(root), items=[legacy],
                        reader=lambda _: artifact_bytes(),
                        run_reader=lambda _: bad)

    def test_metadata_only_main_wave_retains_manifest_but_no_fake_clip(self):
        metadata = {"id": 111, "expired": False,
                    "name": "keirin-github-capture-2026-11-09-metadata-998"}
        with TemporaryDirectory() as root:
            path = Path(root)
            outcome = collect("haji84/RACE-AI", "2026-11-09", mode="index",
                              output_dir=path, items=[metadata],
                              reader=lambda _: artifact_bytes())
            self.assertTrue((path / "day-source-manifest.json").is_file())
            self.assertEqual(outcome["temporary_capture_race_ids"], [])
            self.assertEqual(outcome["matching_unexpired_sealed_artifact_runs"], [])

    def test_no_evidence_never_creates_prior_day_source(self):
        with TemporaryDirectory() as root:
            path = Path(root)
            outcome = collect("haji84/RACE-AI", "2026-11-09", mode="index",
                              output_dir=path, items=[])
            self.assertFalse((path / "day-source-manifest.json").exists())
            self.assertEqual(outcome["temporary_capture_race_ids"], [])


if __name__ == "__main__":
    unittest.main()
