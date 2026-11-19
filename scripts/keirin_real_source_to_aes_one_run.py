"""One *real* pre-cutoff race: live sources -> A/B -> owner-RSA/AES seal.

The source pages are queried at most once each, without hidden endpoints.
This script has no RSA private key. It uses the existing owner PUBLIC key,
keeps captured racecards in a 0700 private temporary directory, and emits
ONLY encrypted A/B and sanitized SHA receipts. Another GitHub job must
validate the encrypted file independently. An organizer's exact final
sales-closing instant remains independently UNVERIFIED.

Never invoke after cutoff or overwrite a previously sealed race.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import stat

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_nationwide_auto_storage as storage
from scripts import keirin_capture_public_two_sources as collector
from scripts import keirin_nationwide_auto_forecast as batch

SCHEMA="RACE_AI_KEIRIN_REAL_SOURCE_ONE_RUN_AB_AES_RECEIPT_V1"
RACE_ID="202611182401"
DATE="2026-11-18"
CUTOFF="2026-11-18T20:45:00+09:00"
NET="https://keirin.netkeiba.com/race/entry/?race_id=202611182401"
KD="https://keirin.kdreams.jp/utsunomiya/racedetail/2420261117020001/"
SOURCE_MANIFEST={
  "schema":collector.SCHEMA,
  "day_jst":DATE,
  "races":[{"race_id":RACE_ID,"netkeirin_url":NET,
            "kdreams_url":KD,"cutoff_hint":CUTOFF}],
  "source_use_scope":"OWNER_PERSONAL_RESEARCH_ONLY",
}


def need(ok,reason):
    if not ok:
        raise ValueError(reason)


def _utc_time():
    return datetime.now(timezone.utc)


def _write_once(path,record):
    path=Path(path)
    need(not path.exists() and not path.is_symlink() and
         path.parent.is_dir(),"SAFE_RECEIPT_ALREADY_EXISTS")
    payload=json.dumps(record,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"),allow_nan=False).encode("utf-8")+b"\n"
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|
               getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    need(path.read_bytes()==payload,"RECEIPT_READBACK_FAIL")


def create_once(*,root,registry,owner_public_key_pem,clock=None,
                provider_fetch=None):
    clock=clock or _utc_time
    current=clock().astimezone(timezone.utc)
    if (model.when(CUTOFF)-current).total_seconds()<65:
        return {"schema":SCHEMA,"state":"HOLD_NO_FUTURE_PRE_CUTOFF",
                "race_id":RACE_ID,"actual_forecasts_saved":0,
                "real_result_scored":False}
    root=Path(root)
    need(root.is_absolute() and root.is_dir() and
         not root.is_symlink() and
         stat.S_IMODE(root.stat().st_mode)==0o700,
         "PRIVATE_ROOT_0700_REQUIRED")
    for name in ("cards","raw","sealed"):
        folder=root/name
        need(folder.is_dir() and not folder.is_symlink() and
             stat.S_IMODE(folder.stat().st_mode)==0o700,
             "PRIVATE_SUBDIR_0700_REQUIRED")
    storage.checked_public_key(owner_public_key_pem)
    registered=batch.registered_race_ids(registry)
    need(RACE_ID in registered,"PILOT_RACE_NOT_IN_REGISTERED_COHORT")
    prior=root/"sealed"/(RACE_ID+".sealed.json")
    need(not prior.exists() and not prior.is_symlink(),
         "OWNER_IMMUTABLE_RACE_ALREADY_SEALED")
    result=collector.capture_cycle(
        day_manifest=SOURCE_MANIFEST,
        registered_ids=registered,
        private_cards_dir=root/"cards",private_raw_dir=root/"raw",
        clock=clock,fetch=provider_fetch,max_races=1)
    if result["normalized_private_cards"]!=1:
        return {
            "schema":SCHEMA,"state":"HOLD_SOURCE_OR_SOURCE_FORMAT_UNAVAILABLE",
            "race_id":RACE_ID,
            "source_states":result["states"],
            "public_page_pairs_attempted":result["GET_pair_attempts"],
            "actual_forecasts_saved":0,
            "real_result_scored":False,
        }
    # Real model invocation and real cryptography happen in ONE Python run.
    report=batch.run_cycle(
        registry=registry,
        private_racecards_dir=root/"cards",
        raw_pages_dir=root/"raw",
        private_cipher_dir=root/"sealed",
        owner_public_key_pem=owner_public_key_pem,
        clock=clock)
    successful=[r for r in report["records"]
                if r["race_id"]==RACE_ID and
                r["state"]=="A_B_PRIVATE_CIPHER_CREATED_SAME_JOB_SHA_MATCH"]
    if len(successful)!=1:
        return {
            "schema":SCHEMA,"state":"HOLD_REAL_SOURCE_A_B_NOT_SEALED",
            "race_id":RACE_ID,
            "model_states":report["statuses"],
            "actual_forecasts_saved":0,
            "real_result_scored":False,
        }
    receipt=successful[0]
    envelope=json.loads(prior.read_text(encoding="utf-8"))
    storage.validate_cipher(envelope)
    source=json.loads((root/"cards"/(RACE_ID+".json")).read_text(encoding="utf-8"))
    # Cross-check semantic SHA and the exact predicted/created cutoff time.
    need(envelope["original_source_sha256"]==model.digest(source) and
         envelope["A"]["ciphertext_sha256"]==receipt["A_cipher_sha256"] and
         envelope["B"]["ciphertext_sha256"]==receipt["B_cipher_sha256"],
         "REAL_SOURCE_AND_AES_CHAIN_DIVERGED")
    return {
        "schema":SCHEMA,"state":"REAL_ONE_RUN_A_B_AES_CREATED",
        "race_id":RACE_ID,
        "source_captured_from_actual_public_HTML":True,
        "two_public_page_originals_sha256_rechecked":True,
        "private_racecard_source_sha256":model.digest(source),
        "published_cutoff_at":envelope["published_cutoff_at"],
        "prediction_generated_at":envelope["generated_at"],
        "sealed_at":envelope["sealed_at"],
        "cipher_sha256":receipt["cipher_file_sha256"],
        "A_cipher_sha256":receipt["A_cipher_sha256"],
        "B_cipher_sha256":receipt["B_cipher_sha256"],
        "A_ticket_count":receipt["candidate_A_count"],
        "B_ticket_count":receipt["candidate_B_count"],
        "B_six_phase_scenarios":receipt["six_phase_scenarios"],
        "source_bytes_and_forecasts_private":True,
        "owner_rsa_private_key_not_used_in_this_job":True,
        "same_job_AES_created":True,
        "second_runner_independent_ciphertext_SHA":False,
        "organizer_actual_cutoff_independently_verified":False,
        "actual_result_scored":False,
        "C_state":"HOLD_NO_AUTHENTICATED_FOLLOW_LABELS",
        "national_79_races_generated":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--root",required=True)
    p.add_argument("--registry",required=True)
    p.add_argument("--rsa-public-pem",required=True)
    args=p.parse_args(argv)
    try:
        root=Path(args.root)
        registry=json.loads(Path(args.registry).read_text(encoding="utf-8"))
        key=Path(args.rsa_public_pem).read_bytes()
        result=create_once(root=root,registry=registry,
                           owner_public_key_pem=key)
        _write_once(root/"one-run-safe-summary.json",result)
        # For independent second runner, the producer report lists the full
        # fixed 79 denominator. No rider name, 3-ren-tan picks, or raw HTML.
        if result["state"]=="REAL_ONE_RUN_A_B_AES_CREATED":
            sealed=Path(args.root)/"sealed"/(RACE_ID+".sealed.json")
            manifest={
              "schema":batch.STATUS_SCHEMA,
              "day_jst":DATE,"registered_races":79,
              "A_generated":1,"B_generated":1,"same_job_sealed":1,
              "cross_runner_RSA_decryption":0,"organizer_results_scored":0,
              "statuses":{"A_B_PRIVATE_CIPHER_CREATED_SAME_JOB_SHA_MATCH":1,
                          "NO_FORECAST_INPUT_MISSING":78},
              "records":[]}
            for item in registry["records"]:
                rid=item["race_id"]
                if rid==RACE_ID:
                    manifest["records"].append({
                     "race_id":rid,"ciphertext_local_created":True,
                     "cipher_file_sha256":result["cipher_sha256"],
                     "A_cipher_sha256":result["A_cipher_sha256"],
                     "B_cipher_sha256":result["B_cipher_sha256"]})
                else:
                    manifest["records"].append({
                     "race_id":rid,"ciphertext_local_created":False})
            _write_once(root/"producer-summary.json",manifest)
        print(json.dumps(result,sort_keys=True,ensure_ascii=False))
        return 0
    except (ValueError,KeyError,TypeError,OSError,
            collector.SourceCaptureError,model.AutomaticForecastError,
            storage.AutoSealError) as exc:
        # Do not echo raw source/parser exception details if unclassified.
        status=str(exc)
        if (not status.isascii() or len(status)>80 or
            not status.replace("_","").isalnum()):
            status="SOURCE_OR_ENCRYPTION_NOT_VERIFIED"
        safe={"schema":SCHEMA,"state":"HOLD_"+status,
              "race_id":RACE_ID,"actual_forecasts_saved":0}
        print(json.dumps(safe,sort_keys=True))
        return 0


if __name__=="__main__":
    raise SystemExit(main())
