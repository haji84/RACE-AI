#!/usr/bin/env python3
"""RSA-seal private nightly scene/holdout research before exporting via Actions.

Owner-specific decryption and training occur in a scratch directory. This
helper ONLY emits a public-key-encrypted envelope and a nonsecret count receipt.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re

from race_ai.keirin_private_sealed_payload import seal_json

NAME=re.compile(r"^[a-zA-Z0-9_.-]+\.json$")
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--private-input",type=Path,required=True)
    p.add_argument("--public-key",type=Path,required=True)
    p.add_argument("--day-jst",required=True)
    p.add_argument("--sealed-output",type=Path,required=True)
    a=p.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",a.day_jst):
        raise SystemExit("INVALID_NIGHTLY_RESEARCH_DATE")
    files={}
    for path in sorted(a.private_input.glob("*.json")):
        if not NAME.fullmatch(path.name):
            raise SystemExit("BAD_RESEARCH_JSON_NAME")
        if path.is_symlink() or path.stat().st_size>24_000_000:
            raise SystemExit("PRIVATE_OUTPUT_INVALID_SIZE_OR_SYMLINK")
        files[path.name]=json.loads(path.read_text(encoding="utf-8"))
    if "daily_private_research_summary.json" not in files:
        raise SystemExit("PRIVATE_DAILY_RESEARCH_NOT_FINISHED")
    report=files["daily_private_research_summary.json"]
    if report.get("date_jst")!=a.day_jst:
        raise SystemExit("NIGHTLY_MODEL_TIME_MISMATCH")
    payload={
        "schema":"RACE_AI_KEIRIN_NIGHTLY_OWNER_PRIVATE_RESEARCH_V1",
        "day_jst":a.day_jst,"files":files,
        "source_type":"DECRYPTED_REAL_OR_AUTHENTICATED_AES_VIDEO",
        "research_model_promotion_allowed":False,
        "independently_verified_rider_tactics":0,
        "official_top8_improvement_proven":False,
    }
    encoded=seal_json(payload,a.public_key,
        aad=f"RACE_AI_PRIVATE_KEIRIN:{a.day_jst}:NIGHTLY_OWNER_RESEARCH_V1")
    a.sealed_output.parent.mkdir(parents=True,exist_ok=True)
    a.sealed_output.write_text(json.dumps(encoded,ensure_ascii=False))
    a.sealed_output.chmod(0o600)
    print(json.dumps({
       "encrypted_research_files":len(files),
       "source_video_races":report.get("decoded_and_sha_verified_races",0),
       "review_candidates":report.get("scene_review_candidates",0),
       "model_status":report.get("self_supervised_model_status"),
       "cipher_sha256":encoded["ciphertext_sha256"],
       "actual_top8_lift_proven":False
    },ensure_ascii=False))
if __name__=="__main__":
    main()
