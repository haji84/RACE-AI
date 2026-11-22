"""Synthetic controls for the two observed historical evening batches.

No real plaintext, owner key, or official result is included in these tests.
The synthetic metadata and ZIP pins are replaced together only in fixtures;
the public verifier has no caller-selected policy or proof callback.
"""
from copy import deepcopy
from contextlib import redirect_stdout
from dataclasses import replace
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
import base64
import builtins
import json
import unittest

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_auto_storage as storage
from tests.test_keirin_nationwide_auto_generator import fixture, AT


ROOT = Path(__file__).resolve().parents[1]
# Historical replay requires the exact published source bytes, not whatever
# current-method functions were subsequently added to the live module.
# Public source provenance: haji84/RACE-AI@51bec791cc5be2b56f996934b4df8b51894d67d8.
SOURCE = (ROOT / "tests/fixtures/keirin_generator_source_9aa01431.txt").read_bytes()
RUN = 44290470874
API = "https://api.github.com/repos/haji84/RACE-AI"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def zip_members(members):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, raw in members.items():
            archive.writestr(name, raw)
    return output.getvalue()


def synthetic_envelope(rid):
    arms = {}
    for index, role in enumerate(("A", "B"), 1):
        ciphertext = (b"synthetic-ciphertext-only-" + role.encode()) * 2
        arms[role] = {
            "aad_ascii": f"RACE_AI_AUTO_AB_V1|{rid}|{role}|ZLIB",
            "aesgcm_nonce_b64": base64.b64encode(bytes([index]) * 12).decode(),
            "rsa_oaep_sha256_wrapped_key_b64": base64.b64encode(bytes([index]) * 384).decode(),
            "ciphertext_b64": base64.b64encode(ciphertext).decode(),
            "ciphertext_sha256": sha256(ciphertext).hexdigest(),
            "plaintext_sha256": str(index) * 64,
            "compressed_sha256": str(index + 2) * 64,
        }
    return {
        "schema": storage.SCHEMA, "race_id": rid,
        "owner_RSA_SPKI_sha256": storage.PINNED_OWNER_SPKI_SHA256,
        "generated_at": "2026-11-18T10:59:30+00:00",
        "sealed_at": "2026-11-18T10:59:31+00:00",
        "published_cutoff_at": "2026-11-18T21:05:00+09:00",
        "original_source_sha256": "a" * 64,
        "official_result_included": False,
        "official_cutoff_independently_attested": False,
        "cross_runner_RSA_decryption_attested": False,
        "research_only": True, **arms,
    }


def origin_fixture(legacy):
    spec = legacy.BATCHES[RUN]
    cohort = json.loads((ROOT / "docs/evidence/2026-11-18/keirin_all79_nationwide_AB_registered_v1.json").read_text())
    ids = sorted(row["race_id"] for row in cohort["records"])
    selected = dict(spec.cipher_shas)
    envelopes = {rid: synthetic_envelope(rid) for rid in selected}
    originals = {rid: canonical(document) for rid, document in envelopes.items()}
    hashes = {rid: sha256(raw).hexdigest() for rid, raw in originals.items()}
    producer_rows, readback_rows, safe_rows = [], [], []
    for rid in ids:
        first = {"race_id": rid, "ciphertext_local_created": rid in selected}
        second = {"race_id": rid, "state": "HOLD_NO_CIPHER_TO_VERIFY"}
        safe = {"race_id": rid, "state": "NO_FORECAST_NO_VALID_PRE_RACE_INPUT"}
        if rid in selected:
            env = envelopes[rid]
            first.update(cipher_file_sha256=hashes[rid],
                         A_cipher_sha256=env["A"]["ciphertext_sha256"],
                         B_cipher_sha256=env["B"]["ciphertext_sha256"])
            second.update(state="INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK", cipher_file_sha256=hashes[rid])
            safe.update(state="REAL_A_B_RSA_AES_SEALED_SAME_JOB",
                        public_source_facts_sha256=env["original_source_sha256"],
                        cutoff_at=env["published_cutoff_at"], A_tickets=12, B_tickets=8,
                        B_six_phase_scenarios=12, ciphertext_file_sha256=hashes[rid],
                        A_cipher_sha256=first["A_cipher_sha256"], B_cipher_sha256=first["B_cipher_sha256"])
        producer_rows.append(first)
        readback_rows.append(second)
        safe_rows.append(safe)
    producer_report = {"schema": "RACE_AI_KEIRIN_NATIONWIDE_AUTO_GENERATION_CYCLE_V1",
                       "day_jst": "2026-11-18", "registered_races": 79, "records": producer_rows}
    safe_report = {"schema": "RACE_AI_KEIRIN_REAL_20261118_EVENING_AB_AUTO_BATCH_V1",
                   "day_jst": "2026-11-18", "registered_races": 79,
                   "new_A_B_same_job_encrypted": 7, "previously_sealed_A_B_do_not_recreate": 2,
                   "official_result_scored": 0, "organizer_actual_sales_close_independently_verified": False,
                   "source_html_and_plain_predictions_not_in_this_report": True,
                   "C_optional_HOLD": True, "four_model_PR71_dependency": False,
                   "records": safe_rows,
                   "statuses": {"REAL_A_B_RSA_AES_SEALED_SAME_JOB": 7, "NO_FORECAST_NO_VALID_PRE_RACE_INPUT": 72}}
    readback_report = {"schema": "RACE_AI_KEIRIN_NATIONWIDE_AB_CIPHER_SECOND_RUNNER_V1",
                       "day_jst": "2026-11-18", "registered_races": 79,
                       "independent_cipher_file_shas_ok": 7,
                       "RSA_private_decryption_verified": False, "actual_official_result_verified": False,
                       "old_four_model_PR71_required": False, "records": readback_rows,
                       "statuses": {"HOLD_NO_CIPHER_TO_VERIFY": 72, "INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK": 7}}
    members = {f"sealed/{rid}.sealed.json": raw for rid, raw in originals.items()}
    members.update({"producer-summary.json": canonical(producer_report), spec.safe_member: canonical(safe_report)})
    archives = (zip_members(members), zip_members({spec.readback_member: canonical(readback_report)}))
    run = {"id": RUN, "url": f"{API}/actions/runs/{RUN}", "head_sha": spec.commit,
           "head_branch": "research/keirin-six-phase-score-20261114", "event": "pull_request",
           "path": ".github/workflows/keirin-nationwide-ab-auto.yml", "run_attempt": 1,
           "created_at": "2026-11-18T10:59:12Z",
           "repository": {"id": 1416489937, "full_name": "haji84/RACE-AI"},
           "head_repository": {"id": 1416489937, "full_name": "haji84/RACE-AI"}}
    packets = []
    for index, role in enumerate(("producer", "readback")):
        job_id = getattr(spec, role + "_job_id")
        artifact_id = getattr(spec, role + "_artifact_id")
        start, created, end = (("10:59:14", "10:59:47", "10:59:49") if index == 0
                               else ("10:59:52", "11:00:07", "11:00:10"))
        stamp = lambda value: "2026-11-18T" + value + "Z"
        job = {"id": job_id, "url": f"{API}/actions/jobs/{job_id}", "run_id": RUN,
               "run_url": run["url"], "head_sha": spec.commit, "head_branch": run["head_branch"],
               "name": getattr(spec, role + "_job_name"), "status": "completed", "conclusion": "success",
               "started_at": stamp(start), "completed_at": stamp(end), "runner_id": 1000 + index,
               "run_attempt": 1}
        artifact = {"id": artifact_id, "url": f"{API}/actions/artifacts/{artifact_id}",
                    "archive_download_url": f"{API}/actions/artifacts/{artifact_id}/zip",
                    "name": getattr(spec, role + "_artifact_name"), "created_at": stamp(created),
                    "size_in_bytes": len(archives[index]), "digest": "sha256:" + sha256(archives[index]).hexdigest(),
                    "workflow_run": {"id": RUN, "repository_id": 1416489937, "head_repository_id": 1416489937,
                                     "head_branch": run["head_branch"], "head_sha": spec.commit}}
        packets.append({"run": deepcopy(run), "job": job, "artifact": artifact, "archive_bytes": archives[index]})
    spec = replace(spec, cipher_shas=tuple(sorted(hashes.items())),
                   producer_zip_sha256=sha256(archives[0]).hexdigest(),
                   readback_zip_sha256=sha256(archives[1]).hexdigest())
    return spec, packets, originals


class LegacyEveningReplay(unittest.TestCase):
    def implementation(self):
        try:
            from race_ai import keirin_legacy_evening_replay
        except ImportError:
            self.fail("SHA-bound historical batch replay is not implemented")
        return keirin_legacy_evening_replay

    def test_historical_source_fixture_is_exact_and_current_source_is_rejected(self):
        legacy = self.implementation()
        self.assertEqual(sha256(SOURCE).hexdigest(), legacy.MODEL_SOURCE_SHA256)
        current = (ROOT / "race_ai/keirin_nationwide_auto_generator.py").read_bytes()
        self.assertNotEqual(sha256(current).hexdigest(), legacy.MODEL_SOURCE_SHA256)
        with self.assertRaisesRegex(ValueError, "MODEL_SOURCE"):
            legacy.generate_legacy_A_B(fixture(), generated_at=AT, generator_source_bytes=current)

    def test_original_python311_prediction_digest_is_reproduced_exactly(self):
        result = self.implementation().generate_legacy_A_B(
            fixture(), generated_at=AT, generator_source_bytes=SOURCE)
        self.assertEqual(result["prediction_sha256"],
                         "a746a7b4bd68ae2f3f3da4d93a6c4e301c7d157a350601384e300e889adb20f8")

    def test_legacy_replay_does_not_mutate_current_generator_or_global_sum(self):
        function, summation = model.generate_A_B, builtins.sum
        before = model.generate_A_B(fixture(), generated_at=AT)
        self.implementation().generate_legacy_A_B(fixture(), generated_at=AT, generator_source_bytes=SOURCE)
        self.assertIs(model.generate_A_B, function)
        self.assertIs(builtins.sum, summation)
        self.assertEqual(model.generate_A_B(fixture(), generated_at=AT), before)

    def test_unbound_or_modified_source_is_rejected_before_execution(self):
        legacy = self.implementation()
        for source in (b"", SOURCE + b"\nraise RuntimeError('must never execute')\n"):
            with self.subTest(source_length=len(source)), self.assertRaisesRegex(ValueError, "MODEL_SOURCE"):
                legacy.generate_legacy_A_B(fixture(), generated_at=AT, generator_source_bytes=source)

    def test_strict_crypto_and_original_prediction_hash_survive_runtime_compatibility(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        legacy = self.implementation()
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        pin = sha256(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()
        original = legacy.generate_legacy_A_B(fixture(), generated_at=AT, generator_source_bytes=SOURCE)
        with TemporaryDirectory() as tmp, patch.object(storage, "PINNED_OWNER_SPKI_SHA256", pin):
            path = Path(tmp) / "synthetic.sealed.json"
            receipt = storage.seal_once(snapshot=fixture(), prediction=original, public_key_pem=pub,
                                       path=path, sealed_at="2026-11-18T09:01:05+09:00")
            args = dict(raw_cipher=path.read_bytes(), expected_cipher_sha256=receipt["cipher_sha256"],
                        owner_private_pem=pem, generator_source_bytes=SOURCE)
            _, replayed, _ = legacy.decrypt_legacy_original_pair(**args)
            self.assertEqual(replayed["prediction_sha256"], "a746a7b4bd68ae2f3f3da4d93a6c4e301c7d157a350601384e300e889adb20f8")
            for change in ({"raw_cipher": args["raw_cipher"] + b"changed"},
                           {"owner_private_pem": b"not a private key"},
                           {"generator_source_bytes": SOURCE + b"\n"}):
                with self.subTest(change=next(iter(change))), self.assertRaises(ValueError):
                    legacy.decrypt_legacy_original_pair(**dict(args, **change))


class LegacyEveningOrigin(unittest.TestCase):
    implementation = LegacyEveningReplay.implementation
    def setUp(self):
        self.legacy = self.implementation()
        self.spec, (self.producer, self.readback), self.originals = origin_fixture(self.legacy)
        self.patcher = patch.object(self.legacy, "BATCHES", {RUN: self.spec})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def verify(self, **changes):
        args = dict(run_id=RUN, producer=self.producer, readback=self.readback,
                    official_cutoffs_by_race={rid: "2026-11-18T12:00:00Z" for rid in self.originals},
                    generator_source_bytes=SOURCE)
        return self.legacy.verify_known_batch(**dict(args, **changes))

    def test_legacy_reports_without_new_schema_counters_bind_seven_exact_originals(self):
        before = deepcopy((self.producer, self.readback))
        result = self.verify()
        self.assertEqual(len(result["originals_by_race"]), 7)
        self.assertEqual(len(result["proofs_by_race"]), 7)
        self.assertEqual(len(result["cohort_race_ids"]), 79)
        self.assertEqual((self.producer, self.readback), before)
        for rid, original in result["originals_by_race"].items():
            self.assertEqual(original["raw_cipher"], self.originals[rid])
            self.assertEqual(result["proofs_by_race"][rid]["latest_server_evidence_at"], "2026-11-18T11:00:10+00:00")
            self.assertFalse(result["proofs_by_race"][rid]["RSA_decryption_verified"])

    def test_commit_time_cannot_replace_server_completion_margin(self):
        rid = next(iter(self.originals))
        cutoffs = {race: "2026-11-18T12:00:00Z" for race in self.originals}
        self.producer["run"]["head_commit"] = {"timestamp": "2020-01-01T00:00:00Z"}
        cutoffs[rid] = "2026-11-18T11:01:14Z"
        with self.assertRaisesRegex(ValueError, "PRE_CUTOFF"):
            self.verify(official_cutoffs_by_race=cutoffs)
        cutoffs[rid] = "2026-11-18T11:01:15Z"
        self.assertEqual(len(self.verify(official_cutoffs_by_race=cutoffs)["proofs_by_race"]), 7)

    def test_fork_unlisted_run_failed_job_and_same_runner_are_rejected(self):
        before = deepcopy((self.producer, self.readback))
        mutations = (("producer", "run", "head_sha", "f" * 40),
                     ("producer", "run", "head_repository", {"id": 1, "full_name": "other/repo"}),
                     ("producer", "job", "conclusion", "failure"),
                     ("readback", "job", "runner_id", 1000),
                     ("readback", "artifact", "id", 1))
        for which, section, key, value in mutations:
            with self.subTest(mutation=(which, section, key)):
                self.producer, self.readback = deepcopy(before)
                getattr(self, which)[section][key] = value
                with self.assertRaises(ValueError):
                    self.verify()
        with self.assertRaisesRegex(ValueError, "ALLOWLIST"):
            self.verify(run_id=999999)

    def test_zip_bytes_and_api_digest_are_both_required(self):
        self.readback["archive_bytes"] += b"changed"
        with self.assertRaisesRegex(ValueError, "ZIP"):
            self.verify()
        self.readback["artifact"]["digest"] = "sha256:" + sha256(self.readback["archive_bytes"]).hexdigest()
        with self.assertRaisesRegex(ValueError, "ZIP"):
            self.verify()

    def test_extra_zip_member_is_rejected_even_with_matching_metadata_digest(self):
        with ZipFile(BytesIO(self.producer["archive_bytes"])) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        members["unexpected.json"] = b"{}"
        raw = zip_members(members)
        self.producer["archive_bytes"] = raw
        self.producer["artifact"].update(digest="sha256:" + sha256(raw).hexdigest(), size_in_bytes=len(raw))
        changed = replace(self.spec, producer_zip_sha256=sha256(raw).hexdigest())
        with patch.object(self.legacy, "BATCHES", {RUN: changed}), self.assertRaisesRegex(ValueError, "MEMBER"):
            self.verify()

    def test_missing_cutoff_never_inherits_a_published_envelope_clock(self):
        with self.assertRaisesRegex(ValueError, "CUTOFF"):
            self.verify(official_cutoffs_by_race={})

    def test_later_day_cannot_supply_a_fictitious_cutoff_margin(self):
        with self.assertRaisesRegex(ValueError, "CUTOFF_DAY"):
            self.verify(official_cutoffs_by_race={rid: "2026-11-19T12:00:00+09:00"
                                                 for rid in self.originals})

    def test_independent_wrong_sha_duplicate_race_and_counter_cannot_be_relabelled(self):
        with ZipFile(BytesIO(self.readback["archive_bytes"])) as archive:
            saved = json.loads(archive.read(self.spec.readback_member))
        for change in ("sha", "duplicate", "counter"):
            with self.subTest(change=change):
                doc = deepcopy(saved)
                if change == "sha":
                    next(row for row in doc["records"] if "cipher_file_sha256" in row)["cipher_file_sha256"] = "f" * 64
                elif change == "duplicate":
                    doc["records"][-1] = deepcopy(doc["records"][0])
                else:
                    doc["independent_cipher_file_shas_ok"] = 8
                raw = zip_members({self.spec.readback_member: canonical(doc)})
                changed = deepcopy(self.readback)
                changed["archive_bytes"] = raw
                changed["artifact"].update(digest="sha256:" + sha256(raw).hexdigest(), size_in_bytes=len(raw))
                spec = replace(self.spec, readback_zip_sha256=sha256(raw).hexdigest())
                with patch.object(self.legacy, "BATCHES", {RUN: spec}), self.assertRaises(ValueError):
                    self.verify(readback=changed)


class LegacyAuditCLI(unittest.TestCase):
    def implementation(self):
        try:
            from scripts import keirin_legacy_evening_audit
        except ImportError:
            self.fail("The offline historical audit CLI is not implemented")
        return keirin_legacy_evening_audit

    def arguments(self, directory, output):
        return ["--evidence-dir", str(directory), "--schedule-json", str(directory / "schedule.json"),
                "--owner-private-key", str(directory / "owner.pem"), "--output", str(output)]

    def test_repository_output_is_rejected_before_key_read(self):
        cli = self.implementation()
        with TemporaryDirectory() as tmp, redirect_stdout(StringIO()) as stream:
            directory = Path(tmp)
            output = ROOT / "must-not-create-legacy-audit.json"
            self.assertFalse(output.exists())
            code = cli.main(self.arguments(directory, output))
        self.assertEqual(code, 2)
        self.assertFalse(output.exists())
        self.assertEqual(json.loads(stream.getvalue())["state"], "HOLD_LEGACY_PRIVATE_AUDIT_FAILED")

    def test_existing_audit_is_never_overwritten(self):
        cli = self.implementation()
        with TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            directory = Path(tmp)
            output = directory / "prior.json"
            output.write_bytes(b"exact prior audit bytes\n")
            self.assertEqual(cli.main(self.arguments(directory, output)), 2)
            self.assertEqual(output.read_bytes(), b"exact prior audit bytes\n")

    def test_unreadable_input_stays_hold_without_echoing_secret_or_creating_output(self):
        cli = self.implementation()
        with TemporaryDirectory() as tmp, redirect_stdout(StringIO()) as stream:
            directory = Path(tmp)
            (directory / "schedule.json").write_bytes(b"not valid JSON")
            (directory / "schedule.json").chmod(0o600)
            (directory / "owner.pem").write_bytes(b"PRIVATE-SYNTHETIC-MARKER-MUST-NOT-BE-PRINTED")
            (directory / "owner.pem").chmod(0o600)
            output = directory / "result.json"
            self.assertEqual(cli.main(self.arguments(directory, output)), 2)
            self.assertFalse(output.exists())
        self.assertNotIn("PRIVATE-SYNTHETIC-MARKER", stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue())["origin_and_replay_verified"], 0)


if __name__ == "__main__":
    unittest.main()
