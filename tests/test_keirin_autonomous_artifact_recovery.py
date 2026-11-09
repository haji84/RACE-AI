"""Synthetic GitHub API ZIP fixtures, never real user footage or token."""
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile
from race_ai.keirin_daily_public_catalog import (
    combine,SOURCE_RACECARD,SOURCE_RESULTS
)
from scripts.keirin_autonomous_artifact_recovery import (
    collect,valid_metadata,ArchiveEvidenceError,PROGRESS_SCHEMA
)
def zip_bytes(files):
    buf=io.BytesIO()
    with ZipFile(buf,"w") as z:
        for name,payload in files.items():
            z.writestr(name,payload if isinstance(payload,bytes) else json.dumps(payload))
    return buf.getvalue()

def fixtures():
    links=lambda kind:[{"href":
        "https://www.winticket.jp/keirin/aomori/"+kind+"/2026110812/2/1",
        "text":"1R"}]
    m=combine("2026-11-09",[
      {"source_url":SOURCE_RACECARD,
       "heading":"本日 2026年11月9日","links":links("racecard")},
      {"source_url":SOURCE_RESULTS,
       "heading":"本日 2026年11月9日","links":links("raceresult")}])
    rawsha=sha256(b"IMAGINARY_SCREEN_NOT_A_REAL_MOVIE").hexdigest()
    report={
        "schema":"RACE_AI_KEIRIN_DAILY_RECORDINGS_ENCRYPTED_WAVE_V1",
        "date_jst":"2026-11-09",
        "dynamic_manifest_sha256":m["manifest_sha256"],
        "race_rows":[{
            "race_id":"202611091201",
            "source_video_sha256":rawsha,
            "status":"ENCRYPTED_COMPLETE_PLAYER",
            "playback_ended":True,
            "cohort":m["races"][0]["cohort"],
        }]
    }
    fake_cipher=b"FAKE-CIPHER-NOT-CRYPTO"
    ci={
       "schema":"RACE_AI_REPLAY_CIPHER_MANIFEST_V1",
       "race_id":"202611091201",
       "files":[{"file":"capture-0.webm.aesgcm",
          "plaintext_sha256":rawsha,
          "ciphertext_sha256":sha256(fake_cipher).hexdigest()}]
    }
    metadata=zip_bytes({"keirin-daily-wave.json":report,
                         "keirin-daily-source-inventory.json":m})
    sealed=zip_bytes({"202611091201/manifest.json":ci,
                      "202611091201/capture-0.webm.aesgcm":fake_cipher})
    arts=[
        {"id":100,"name":"keirin-github-capture-2026-11-09-metadata-123",
         "expired":False},
        {"id":101,"name":"keirin-github-capture-2026-11-09-sealed-123",
         "expired":False}
    ]
    return arts,{100:metadata,101:sealed},rawsha

class GithubArtifactResearchReceiptsTests(unittest.TestCase):
    def test_unexpired_artifact_is_temp_duplicate_only_not_durable(self):
        arts,data,source=fixtures()
        with TemporaryDirectory() as t:
            row=collect("haji84/RACE-AI","2026-11-09",
               mode="index",output_dir=Path(t),items=arts,
               reader=lambda a:data[a["id"]])
            self.assertEqual(row["temporary_capture_race_ids"],["202611091201"])
            self.assertFalse(row["readback_in_private_library_verified"])
            self.assertTrue(row["github_action_artifacts_only_not_durable_private_storage"])
            self.assertEqual(row["source_rows"][0]["source_sha256"],source)
            self.assertTrue((Path(t)/"temporary-artifact-receipts.json").exists())
    def test_expired_or_missing_cipher_cannot_stop_retry(self):
        arts,data,_=fixtures()
        arts[1]["expired"]=True
        with TemporaryDirectory() as t:
            row=collect("haji84/RACE-AI","2026-11-09",
                mode="index",output_dir=Path(t),items=arts,
                reader=lambda a:data[a["id"]])
            self.assertEqual(row["temporary_capture_race_ids"],[])
    def test_archive_verifies_per_race_sha_and_manifest(self):
        arts,data,source=fixtures()
        with TemporaryDirectory() as t:
            row=collect("haji84/RACE-AI","2026-11-09",
                mode="archive",output_dir=Path(t),items=arts,
                reader=lambda a:data[a["id"]])
            archive=Path(t)/"2026-11-09-sealed-unique-race-archive.zip"
            self.assertTrue(archive.is_file())
            with ZipFile(archive) as z:
                self.assertEqual(len(z.namelist()),2)
                manifest=json.loads(z.read("202611091201/manifest.json"))
                self.assertEqual(manifest["files"][0]["plaintext_sha256"],source)
    def test_mismatching_caption_is_never_silent(self):
        arts,data,_=fixtures()
        bad=bytearray(data[101]);bad[-1]^=1
        data[101]=bytes(bad)
        with TemporaryDirectory() as t:
            with self.assertRaises(Exception):
                collect("haji84/RACE-AI","2026-11-09",
                    mode="archive",output_dir=Path(t),items=arts,
                    reader=lambda a:data[a["id"]])
    def test_cannot_accept_wrong_calendar_or_after_midnight_artifact(self):
        arts,data,_=fixtures()
        with TemporaryDirectory() as t:
            with self.assertRaisesRegex(ArchiveEvidenceError,"DATE"):
                collect("haji84/RACE-AI","2026-11-08",
                    mode="index",output_dir=Path(t),items=arts,
                    reader=lambda a:data[a["id"]])
if __name__=="__main__":unittest.main()
