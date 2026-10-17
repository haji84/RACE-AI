"""Run synthetic end-to-end checks without using or distributing official data.

This module never contacts a data provider. It produces a temporary bundle
for local HTTP tests only; it does not deploy to Vercel or change Production.
"""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from .preview_bundle import package_preview
from .preview_deploy_gate import verify_preview_bundle

JST=ZoneInfo("Asia/Tokyo")


def run(web: Path) -> dict:
    day=datetime.now(JST).date().isoformat()
    with TemporaryDirectory() as directory:
        root=Path(directory)
        snapshot=root/"synthetic.json"
        approval=root/"synthetic-approval.json"
        bundle=root/"preview"
        snapshot.write_text(json.dumps({
            "date_jst":day,
            "source_url":"https://example.org/synthetic-test-only",
            "source_sha256":"a"*64,
            "first_observed_at":datetime.now(JST).isoformat(),
            "venues":[{"venue":"18","races":[{"race_id":day.replace("-","")+"-18-01",
                "boats":[{"lane":i,"racer_registration_id":str(4000+i),
                          "motor_no":None} for i in range(1,7)]}]}]
        }),encoding="utf-8")
        approval.write_text(json.dumps({
            "redistribution_authorized":True,
            "source_url":"https://example.org/synthetic-test-only",
            "evidence_reference":"SYNTHETIC_TEST_FIXTURE_ONLY",
            "reviewed_by":"automated-test"
        }),encoding="utf-8")
        package_preview(web,snapshot,approval,bundle)
        result=verify_preview_bundle(bundle,approval,target="preview",
                                    project="race-ai-preview")
        result["test_data"]="SYNTHETIC_ONLY_NOT_REAL_RACES"
        return result
