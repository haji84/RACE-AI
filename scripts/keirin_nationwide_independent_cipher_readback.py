"""Independent GitHub runner SHA check for nationwide A/B ciphertext only.

Read produced artifact in a new runner, not a shared Python process.
This verifies exact sealed file bytes, two distinct AES ciphertexts, per-arm
SHA and race_id. It does NOT possess the owner RSA private key and cannot
attest decryption, organizer cutoff or official results.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import json
import os

from race_ai import keirin_nationwide_auto_storage as storage
from scripts import keirin_nationwide_auto_forecast as producer

SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_AB_CIPHER_SECOND_RUNNER_V1"


def verify(*,producer_report, cipher_dir):
    if (type(producer_report) is not dict or
        producer_report.get("schema")!=producer.STATUS_SCHEMA or
        type(producer_report.get("records")) is not list):
        raise ValueError("PRODUCER_REPORT_SCHEMA_REQUIRED")
    out=Path(cipher_dir)
    if not out.is_dir() or out.is_symlink():
        raise ValueError("CIPHER_ARTIFACT_DIRECTORY_REQUIRED")
    records=[]
    seen=set()
    for r in producer_report["records"]:
        rid=r.get("race_id") if type(r) is dict else None
        if (type(rid) is not str or not
            storage.model.VENUE.fullmatch(rid) or rid in seen):
            raise ValueError("PRODUCER_DUPLICATE_OR_BAD_RACE")
        seen.add(rid)
        row={"race_id":rid,"state":"HOLD_NO_CIPHER_TO_VERIFY"}
        if r.get("ciphertext_local_created") is not True:
            records.append(row)
            continue
        target=out/(rid+".sealed.json")
        try:
            verified=storage.readback_file(
                target,expected_sha=r["cipher_file_sha256"])
            if (verified["race_id"]!=rid or
                verified["A_cipher_sha256"]!=r["A_cipher_sha256"] or
                verified["B_cipher_sha256"]!=r["B_cipher_sha256"]):
                raise storage.AutoSealError("INDEPENDENT_ARM_SOURCE_SHA_MISMATCH")
            row["state"]="INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK"
            row["cipher_file_sha256"]=verified["cipher_file_sha256"]
        except (ValueError,KeyError,TypeError,storage.AutoSealError):
            row["state"]="HOLD_INDEPENDENT_CIPHER_SHA_MISMATCH"
        records.append(row)
    if len(records)!=producer_report.get("registered_races"):
        raise ValueError("PRODUCER_COHORT_DENOMINATOR_MISMATCH")
    counts=Counter(r["state"] for r in records)
    return {"schema":SCHEMA,"day_jst":producer_report["day_jst"],
            "registered_races":len(records),
            "independent_cipher_file_shas_ok":counts[
                "INDEPENDENT_CIPHERTEXT_SHA_READBACK_OK"],
            "RSA_private_decryption_verified":False,
            "actual_official_result_verified":False,
            "old_four_model_PR71_required":False,
            "statuses":dict(sorted(counts.items())),
            "records":records}


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--producer-report",required=True)
    p.add_argument("--cipher-dir",required=True)
    p.add_argument("--report",required=True)
    a=p.parse_args(argv)
    try:
        previous=json.loads(Path(a.producer_report).read_text(encoding="utf-8"))
        result=verify(producer_report=previous,cipher_dir=a.cipher_dir)
        path=Path(a.report)
        if not path.is_absolute() or path.exists() or path.is_symlink():
            raise ValueError("INDEPENDENT_REPORT_CREATE_ONCE_REQUIRED")
        data=json.dumps(result,sort_keys=True,ensure_ascii=False,
                        separators=(",",":")).encode()+b"\n"
        flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0)
        fd=os.open(path,flags,0o600)
        with os.fdopen(fd,"wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        if path.read_bytes()!=data:
            raise ValueError("INDEPENDENT_REPORT_READBACK_MISMATCH")
        print(json.dumps({k:result[k] for k in (
            "day_jst","registered_races","independent_cipher_file_shas_ok",
            "RSA_private_decryption_verified","statuses")},
            sort_keys=True,ensure_ascii=False))
        return 0
    except (OSError,TypeError,ValueError,KeyError):
        print('{"state":"HOLD_INDEPENDENT_CIPHER_NOT_CONFIRMED"}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
