#!/usr/bin/env python3
"""Optional durable PRIVATE S3-compatible archive of RSA/AES sealed artifacts.

GitHub's public-repo Actions artifacts expire (at most 90 days). No user
storage account or AWS credentials are created by this script. It performs
a full upload -> owner-controlled object download -> SHA-256 readback, and
only then reports DURABLE_CIPHERTEXT_READBACK_VERIFIED.

It never uploads raw video, extracted image pixels or owner private keys.
"""
from __future__ import annotations
import argparse
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from zipfile import ZipFile,ZIP_STORED

SCHEMA="RACE_AI_KEIRIN_S3_PRIVATE_ARCHIVE_RECEIPT_V1"
VALID=re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,63}$")
DATE=re.compile(r"^\d{4}-\d{2}-\d{2}$")

class DurableArchiveError(ValueError):pass

def ensure(ok,msg):
    if not ok:raise DurableArchiveError(msg)

def exec_aws(args):
    argv=["aws"]
    endpoint=os.environ.get("RACE_VIDEO_S3_ENDPOINT")
    if endpoint:
        ensure(endpoint.startswith("https://"),"INSECURE_STORAGE_ENDPOINT")
        argv.extend(["--endpoint-url",endpoint])
    result=subprocess.run(argv+args,stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE,check=False)
    if result.returncode:
        raise DurableArchiveError("PRIVATE_S3_STORAGE_CALL_FAILED")
    return result.stdout

def package_cipher_only(dirs,zip_path):
    count=0
    with ZipFile(zip_path,"w",compression=ZIP_STORED) as z:
        for folder in dirs:
            p=Path(folder)
            if not p.exists():continue
            for file in sorted(p.rglob("*")):
                if not file.is_file() or file.is_symlink():continue
                if not (file.name.endswith(".aesgcm") or
                        file.name=="manifest.json" or
                        file.name.endswith(".aesgcm.json")):
                    raise DurableArchiveError("RAW_FILE_CANNOT_ENTER_PRIVATE_CIPHER_ARCHIVE")
                # JSON with .aesgcm.json is an ENCRYPTED envelope, not
                # merely a renamed plaintext feature matrix. Validate it.
                if file.name.endswith(".aesgcm.json"):
                    from race_ai.keirin_private_sealed_payload import SCHEMA
                    try:
                        envelope=json.loads(file.read_text(encoding="utf-8"))
                        payload=base64.b64decode(
                            envelope["ciphertext_b64"],validate=True)
                        valid=(envelope.get("schema")==SCHEMA and
                            envelope.get("plaintext_embedded") is False and
                            envelope.get("source_is_private") is True and
                            sha256(payload).hexdigest()==
                                envelope.get("ciphertext_sha256") and
                            str(envelope.get("context","")).startswith(
                                "RACE_AI_PRIVATE_KEIRIN:"))
                    except (ValueError,TypeError,KeyError):
                        valid=False
                    if not valid:
                        raise DurableArchiveError("INVALID_ENCRYPTED_RESEARCH_ENVELOPE")
                rel=file.relative_to(p)
                # Prevent accidental file collisions between distinct waves.
                name=f"{p.name}/{rel.as_posix()}"
                z.write(file,name)
                count+=1
    return count

def store(*,dirs,bucket,day,run_id,report):
    ensure(isinstance(bucket,str) and VALID.fullmatch(bucket),
           "PRIVATE_BUCKET_NOT_CONFIGURED")
    ensure(isinstance(day,str) and DATE.fullmatch(day),"INVALID_DAY")
    ensure(isinstance(run_id,str) and run_id.isdecimal(),"INVALID_RUN_ID")
    # Certificate store credentials must be provided via GitHub Secrets.
    ensure(bool(os.environ.get("AWS_ACCESS_KEY_ID") and
                os.environ.get("AWS_SECRET_ACCESS_KEY")) or
           bool(os.environ.get("AWS_WEB_IDENTITY_TOKEN_FILE") and
                os.environ.get("AWS_ROLE_ARN")),
           "NO_PRIVATE_STORAGE_AUTHENTICATION")
    key=f"keirin/{day}/{run_id}/rsa-aes-sealed-wave.zip"
    with TemporaryDirectory(prefix="keirin-durable-private-") as tmp:
        zipped=Path(tmp)/"ciphertext-only.zip"
        count=package_cipher_only(dirs,zipped)
        ensure(count>0,"NO_ENCRYPTED_VIDEO_OR_FEATURES_TO_ARCHIVE")
        expected=sha256(zipped.read_bytes()).hexdigest()
        exec_aws(["s3api","put-object","--bucket",bucket,"--key",key,
                  "--body",str(zipped),"--metadata",f"sha256={expected}"])
        receipt=json.loads(exec_aws(["s3api","head-object",
                                    "--bucket",bucket,"--key",key]))
        ensure(receipt.get("ContentLength")==zipped.stat().st_size and
               receipt.get("Metadata",{}).get("sha256")==expected,
               "REMOTE_STORAGE_HEAD_INTEGRITY_FAILED")
        readback=Path(tmp)/"readback.zip"
        exec_aws(["s3api","get-object","--bucket",bucket,
                  "--key",key,str(readback)])
        ensure(sha256(readback.read_bytes()).hexdigest()==expected,
               "PRIVATE_STORAGE_RETRIEVED_BYTES_NOT_EQUAL")
    out={"schema":SCHEMA,"day_jst":day,"github_run_id":run_id,
         "ciphertext_objects_in_zip":count,"bucket":bucket,
         "object_key":key,"ciphertext_zip_sha256":expected,
         "owner_private_storage_independent_get_readback_verified":True,
         "private_key_uploaded":False,"raw_video_uploaded":False,
         "actual_rider_tactics_accuracy_proven":False,
         "official_prediction_modified":False}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(out,ensure_ascii=False,indent=2))
    report.chmod(0o600)
    print(json.dumps({"status":"DURABLE_CIPHERTEXT_READBACK_VERIFIED",
        "day_jst":day,"github_run_id":run_id,
        "cipher_objects":count,"sha256":expected},
        ensure_ascii=False))
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",action="append",type=Path,required=True)
    p.add_argument("--bucket",required=True)
    p.add_argument("--date",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    store(dirs=a.source,bucket=a.bucket,day=a.date,
          run_id=a.run_id,report=a.report)
if __name__=="__main__":
    main()
