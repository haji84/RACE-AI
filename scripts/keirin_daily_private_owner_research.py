#!/usr/bin/env python3
"""Owner-only daily video decryption, feature analysis, and scene self-learning.

Requires the RSA private key from owner PRIVATE Library, never GitHub Actions
secrets, source, or artifacts. AES-GCM authenticity, source SHA, manifest
cohort, and frame hashes are checked. Decrypts to ephemeral private tempfile;
no original video or frames are exported. Produces a PRIVATE candidate-review
queue + uncalibrated self-supervised model; no automatic rider identity,
捲り/差し, Top8 KPI improvement, official prediction rewrite, or purchases.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from race_ai.keirin_daily_public_catalog import assess_daily_manifest
from race_ai.keirin_daily_video_research import (
    FEATURE_SCHEMA,read_private_video,make_review_queue,
    fit_private_representation,digest
)

RACE=re.compile(r"^\d{12}$")
NAME=re.compile(r"^capture-\d+\.webm\.aesgcm$")

class OwnerPrivateError(ValueError):pass

def need(ok,msg):
    if not ok:raise OwnerPrivateError(msg)

def _decrypt_archive(zpath,private,rows,*,temp):
    details=[]
    with ZipFile(zpath) as z:
        names=set(z.namelist())
        manifests=[n for n in names if re.fullmatch(
            r"\d{12}/manifest\.json",n)]
        need(bool(manifests),"NO_DAILY_RACE_CIPHER_MANIFEST")
        for mf in sorted(manifests):
            m=json.loads(z.read(mf))
            race_id=m.get("race_id")
            need(bool(RACE.fullmatch(race_id)) and race_id in rows,
                 "ENCRYPTED_RACE_NOT_IN_SOURCE_MANIFEST")
            need(m.get("schema")=="RACE_AI_REPLAY_CIPHER_MANIFEST_V1",
                 "UNKNOWN_CIPHER_MANIFEST_VERSION")
            files=m.get("files")
            need(type(files) is list and len(files)==1,
                 "EXPECTED_ONE_SEALED_CAPTURE_PER_RACE")
            item=files[0]
            name=item["file"]
            need(bool(NAME.fullmatch(name)),"INVALID_CIPHER_FILENAME")
            cipher_name=f"{race_id}/{name}"
            need(cipher_name in names,"CIPHERTEXT_NOT_PRESENT")
            cipher=z.read(cipher_name)
            need(sha256(cipher).hexdigest()==item["ciphertext_sha256"],
                 "CIPHERTEXT_TAMPERED")
            key=private.decrypt(base64.b64decode(item["wrapped_key"]),
                   padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                        algorithm=hashes.SHA256(),label=None))
            aad=base64.b64decode(item["aad"])
            need(aad==f"{race_id}:webm:0".encode("ascii"),
                 "CIPHERTEXT_RACE_AAD_MISMATCH")
            plain=AESGCM(key).decrypt(base64.b64decode(item["nonce"]),cipher,aad)
            source_hash=sha256(plain).hexdigest()
            need(source_hash==item["plaintext_sha256"],
                 "ORIGINAL_VIDEO_HASH_MISMATCH")
            private_video=Path(temp)/f"{race_id}.webm"
            private_video.write_bytes(plain)
            private_video.chmod(0o600)
            doc=read_private_video(private_video,race_id=race_id,
                                   cohort=rows[race_id]["cohort"])
            need(doc["browser_video_sha256"]==source_hash,
                 "RESEARCH_EXTRACTED_DIFFERENT_SOURCE")
            details.append(doc)
            del plain
    return details

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source-manifest",required=True,type=Path)
    ap.add_argument("--cipher-artifact",required=True,type=Path,action="append")
    ap.add_argument("--owner-private-key",required=True,type=Path)
    ap.add_argument("--out-private",required=True,type=Path)
    ap.add_argument("--previous-features",action="append",type=Path,default=[])
    ap.add_argument("--min-train-races",type=int,default=2)
    args=ap.parse_args()
    if os.environ.get("GITHUB_ACTIONS")=="true" and (
       os.environ.get("RACE_AI_PRIVATE_ACTIONS_RESEARCH_CONSENT") !=
       "OWNER_SET_SECRET_TRUSTED_DEFAULT_BRANCH_ONLY"):
        raise SystemExit("OWNER_PRIVATE_KEY_ACTIONS_OPT_IN_REQUIRED")
    # Never print or publish decrypted images/features. In Actions the
    # owner provides their RSA key through a repository secret and the
    # default-branch schedule checks out the pinned, reviewed source SHA.
    need(args.owner_private_key.is_file(),"OWNER_PRIVATE_KEY_REQUIRED")
    need(args.out_private.is_absolute(),"OWNER_PRIVATE_OUTPUT_MUST_BE_ABSOLUTE")
    private=serialization.load_pem_private_key(
        args.owner_private_key.read_bytes(),password=None)
    manifest=json.loads(args.source_manifest.read_text(encoding="utf-8"))
    assess_daily_manifest(manifest,target_day_jst=manifest["date_jst"])
    by_id={x["race_id"]:x for x in manifest["races"]}
    with TemporaryDirectory(prefix="keirin-daily-plaintext-owner-") as t:
        docs=[]
        for path in args.cipher_artifact:
            docs.extend(_decrypt_archive(path,private,by_id,temp=t))
    # No date-labeled video may be counted twice, even if recorded in two waves.
    races=set();sources=set()
    for d in docs:
        need(d["race_id"] not in races,"REPEATED_DAILY_RACE_IN_WAVES")
        need(d["browser_video_sha256"] not in sources,
             "SAME_BROWSER_SOURCE_USED_FOR_MULTIPLE_RACES")
        races.add(d["race_id"]);sources.add(d["browser_video_sha256"])
    for path in args.previous_features:
        old=json.loads(path.read_text())
        need(old.get("schema")==FEATURE_SCHEMA and
             old.get("feature_sha256")==digest({
                 k:v for k,v in old.items() if k!="feature_sha256"}),
             "PAST_TRAINING_FEATURES_NOT_HASH_VERIFIED")
        need(old["race_id"] not in races,"HISTORICAL_VIDEO_RETRAIN_DUPLICATE")
        docs.append(old);races.add(old["race_id"])
    review=make_review_queue(docs)
    model=fit_private_representation(
        docs,min_train_races=args.min_train_races,min_holdout_races=1)
    out=args.out_private
    out.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(out,0o700)
    for doc in docs:
        file=out/f"private_features_{doc['race_id']}.json"
        if file.exists():raise OwnerPrivateError("FEATURES_EXIST_NO_OVERWRITE")
        file.write_text(json.dumps(doc,ensure_ascii=False,indent=2))
        file.chmod(0o600)
    for name,obj in [
        ("private_unreviewed_motion_scene_queue.json",review),
        ("private_daily_self_supervised_model.json",model),
    ]:
        file=out/name
        if file.exists():raise OwnerPrivateError("RESEARCH_FILE_EXISTS_NO_OVERWRITE")
        file.write_text(json.dumps(obj,ensure_ascii=False,indent=2))
        file.chmod(0o600)
    summary={
      "schema":"RACE_AI_KEIRIN_DAILY_PRIVATE_RESEARCH_SUMMARY_V1",
      "date_jst":manifest["date_jst"],
      "decoded_and_sha_verified_races":len(docs),
      "source_races":[{"race_id":d["race_id"],"cohort":d["cohort"],
             "source_sha256":d["browser_video_sha256"],
             "feature_sha256":d["feature_sha256"],
             "sampled_frames":len(d["frames"])} for d in docs],
      "scene_review_candidates":review["candidate_count"],
      "self_supervised_model_status":model["status"],
      "self_supervised_model_sha256":model.get("model_sha256"),
      "verified_rider_attack_or_sashi_labels":0,
      "supervised_tactics_accuracy":None,
      "official_forecast_model_updated":False,
      "official_top8_improvement":None,
      "private_output_directory":str(out),
    }
    p=out/"daily_private_research_summary.json"
    p.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    p.chmod(0o600)
    print(json.dumps({k:summary[k] for k in [
       "date_jst","decoded_and_sha_verified_races",
       "scene_review_candidates","self_supervised_model_status",
       "verified_rider_attack_or_sashi_labels",
       "official_forecast_model_updated"]},ensure_ascii=False))
if __name__=="__main__":main()
