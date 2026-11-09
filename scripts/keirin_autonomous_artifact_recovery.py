#!/usr/bin/env python3
"""Get recent GitHub Actions AES clip artifact receipts for autonomous waves.

No video data is decrypted by this utility. A matching, unexpired Actions
artifact is **temporary evidence**, never independent private Library
retention. The day’s research labels remain UNKNOWN pending review.
"""
from __future__ import annotations
import argparse
from datetime import date
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from zipfile import ZipFile,ZIP_DEFLATED

META="keirin-github-capture-{day}-metadata-"
SEALED="keirin-github-capture-{day}-sealed-"
PROGRESS_SCHEMA="RACE_AI_KEIRIN_GH_TEMP_CIPHERTEXT_RECEIPTS_V1"
VIDEO_SHA=re.compile(r"^[a-f0-9]{64}$")
RID=re.compile(r"^\d{12}$")

class ArchiveEvidenceError(ValueError):pass

def ensure(c,msg):
    if not c:raise ArchiveEvidenceError(msg)

def gh_api(path):
    result=subprocess.run(["gh","api","-H","Accept: application/vnd.github+json",
                           path],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          check=False)
    if result.returncode!=0:
        raise ArchiveEvidenceError("GITHUB_ACTIONS_ARTIFACT_API_FAILED")
    return result.stdout

def list_artifacts(repo,day,*,limit_pages=35):
    items=[]
    for page in range(1,limit_pages+1):
        raw=json.loads(gh_api(f"/repos/{repo}/actions/artifacts?per_page=100&page={page}"))
        batch=raw.get("artifacts")
        ensure(type(batch) is list,"INVALID_GITHUB_ARTIFACT_RESPONSE")
        items.extend(batch)
        if len(batch)<100:break
        # The API is newest-first. Stop after day before the target.
        if all(str(a.get("created_at",""))[:10]<day for a in batch[-10:]):
            break
    return items

def valid_metadata(zipbytes,day,*,expected_run):
    with ZipFile(io.BytesIO(zipbytes)) as z:
        names=z.namelist()
        f=next((name for name in names
                if name.endswith("keirin-daily-wave.json")),None)
        ensure(bool(f),"GITHUB_METADATA_NO_WAVE_JSON")
        document=json.loads(z.read(f))
        m=next((name for name in names
                if name.endswith("keirin-daily-source-inventory.json")),None)
        ensure(bool(m),"GITHUB_METADATA_NO_DAY_MANIFEST")
        manifest=json.loads(z.read(m))
    ensure(document.get("schema")=="RACE_AI_KEIRIN_DAILY_RECORDINGS_ENCRYPTED_WAVE_V1"
           and document.get("date_jst")==day,
           "GITHUB_METADATA_WRONG_DATE_OR_VERSION")
    ensure(manifest.get("date_jst")==day and
           manifest.get("discovered_race_count")==len(manifest.get("races",[])),
           "GITHUB_MANIFEST_DATE_OR_RACE_COUNT_INVALID")
    ensure(document.get("dynamic_manifest_sha256")==manifest.get("manifest_sha256"),
           "GITHUB_WAVE_MANIFEST_SHA_MISMATCH")
    from race_ai.keirin_daily_public_catalog import assess_daily_manifest
    assess_daily_manifest(manifest,target_day_jst=day)
    race_keys={r["race_id"] for r in manifest["races"]}
    records=[]
    for row in document.get("race_rows",[]):
        if row.get("status")!="ENCRYPTED_COMPLETE_PLAYER":
            continue
        rid=row.get("race_id");h=row.get("source_video_sha256")
        ensure(bool(RID.fullmatch(str(rid))) and rid in race_keys,
               "GITHUB_COMPLETED_CLIP_NOT_ON_DAY_MANIFEST")
        ensure(bool(VIDEO_SHA.fullmatch(str(h))) and
               row.get("playback_ended") is True,
               "GITHUB_CLIP_HAS_NO_FRAME_SHA_OR_PLAYER_END")
        records.append({"race_id":rid,"source_sha256":h,
                        "run_id":expected_run,
                        "cohort":row.get("cohort")})
    return records,manifest

def collect(repo,day,*,mode,output_dir,items=None,reader=None):
    date.fromisoformat(day)
    ensure(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo)),
           "INVALID_GITHUB_REPO")
    metadata_prefix=META.format(day=day)
    sealed_prefix=SEALED.format(day=day)
    all_items=list_artifacts(repo,day) if items is None else items
    sealed={}
    metadata=[]
    for a in all_items:
        if a.get("expired"):continue
        name=a.get("name")
        if not isinstance(name,str):continue
        if name.startswith(sealed_prefix):
            run=name.removeprefix(sealed_prefix)
            if run.isdecimal():
                sealed[int(run)]=a
        if name.startswith(metadata_prefix):
            run=name.removeprefix(metadata_prefix)
            if run.isdecimal():
                metadata.append((int(run),a))
    source_rows={}
    manifests=[]
    selected_zips={}
    for run,art in sorted(metadata):
        if run not in sealed:continue
        zipdata=(reader(art) if reader is not None else
                 gh_api(f"/repos/{repo}/actions/artifacts/{art['id']}/zip"))
        rows,m=valid_metadata(zipdata,day,expected_run=run)
        manifests.append((run,m))
        for row in rows:
            rid=row["race_id"]
            if rid in source_rows:continue
            source_rows[rid]=row
            selected_zips[run]=sealed[run]
    output_dir.mkdir(parents=True,exist_ok=True)
    target={
        "schema":PROGRESS_SCHEMA,"date_jst":day,
        "github_action_artifacts_only_not_durable_private_storage":True,
        "temporary_capture_race_ids":sorted(source_rows),
        "source_rows":list(source_rows.values()),
        "trusted_source_scope":"GITHUB_EXPIRED_ARTIFACTS_NEVER_COUNT_AS_DURABLE",
        "matching_unexpired_sealed_artifact_runs":sorted(selected_zips),
        "readback_in_private_library_verified":False,
        "rider_tactics_independently_verified":False
    }
    (output_dir/"temporary-artifact-receipts.json").write_text(
        json.dumps(target,ensure_ascii=False,indent=2))
    if mode=="archive":
        # Download selected SEALED artifacts without decrypting, then
        # assemble a single owner-private bundle with each unique race once.
        out=output_dir/f"{day}-sealed-unique-race-archive.zip"
        chosen=set()
        with ZipFile(out,"w",compression=ZIP_DEFLATED,compresslevel=0) as dst:
            for run,a in sorted(selected_zips.items()):
                zipdata=(reader(a) if reader is not None else
                         gh_api(f"/repos/{repo}/actions/artifacts/{a['id']}/zip"))
                with ZipFile(io.BytesIO(zipdata)) as z:
                    byrace={}
                    for n in z.namelist():
                        parts=Path(n).parts
                        if len(parts)!=2 or not RID.fullmatch(parts[0]):
                            continue
                        rid=parts[0]
                        if rid not in source_rows or source_rows[rid]["run_id"]!=run:
                            continue
                        byrace.setdefault(rid,set()).add(parts[1])
                    for rid,names in byrace.items():
                        if "manifest.json" not in names or "capture-0.webm.aesgcm" not in names:
                            continue
                        cm=json.loads(z.read(f"{rid}/manifest.json"))
                        ensure(cm.get("schema")=="RACE_AI_REPLAY_CIPHER_MANIFEST_V1"
                               and cm.get("race_id")==rid and
                               type(cm.get("files")) is list and
                               len(cm["files"])==1,
                               "CIPHERTEXT_MANIFEST_NOT_VERIFIED")
                        item=cm["files"][0]
                        ciphertext=z.read(f"{rid}/capture-0.webm.aesgcm")
                        ensure(item.get("file")=="capture-0.webm.aesgcm"
                               and sha256(ciphertext).hexdigest()==item.get("ciphertext_sha256")
                               and item.get("plaintext_sha256")==
                                   source_rows[rid]["source_sha256"],
                               "CIPHERTEXT_INTEGRITY_NOT_VERIFIED")
                        dst.writestr(f"{rid}/manifest.json",z.read(f"{rid}/manifest.json"))
                        dst.writestr(f"{rid}/capture-0.webm.aesgcm",ciphertext)
                        chosen.add(rid)
        ensure(chosen==set(source_rows),
               "NO_MATCHING_ENCRYPTED_ASSET_FOR_CAPTURE")
        if manifests:
            most_recent=max(manifests,key=lambda x:x[0])[1]
            (output_dir/"day-source-manifest.json").write_text(
               json.dumps(most_recent,ensure_ascii=False,indent=2))
    print(json.dumps({
        "date_jst":day,"temporary_github_unique_races":len(source_rows),
        "completed_wave_runs":len(selected_zips),
        "mode":mode,
        "durable_retention_attested":False,
        "real_rider_tactics_labeled":False,
    },ensure_ascii=False))
    return target

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo",required=True)
    p.add_argument("--date",required=True)
    p.add_argument("--mode",choices=("index","archive"),default="index")
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    if not os.getenv("GH_TOKEN") and not os.getenv("GITHUB_TOKEN"):
        raise SystemExit("GITHUB_ACTIONS_TOKEN_REQUIRED")
    collect(args.repo,args.date,mode=args.mode,output_dir=args.out)
if __name__=="__main__":main()
