"""Read-only reference PDCA for 83 owner-private frozen picks.

Example (all arguments are absolute private paths):
 python -m scripts.keirin_83_reference_pdca \
   --manifest /private/keirin_20261109_8venues_83r_external_research_predictions.json \
   --results /private/settled_reference_results_20261109.json \
   --output /private/reports/20261109_reference_run_01.json

Never infer individual source rights, official result finality, a live PR71
four-model prediction, actual purchases, or a pre-cutoff receipt. Uses the
original PR71 payout calculator through race_ai.keirin_83_reference_pdca_bridge.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

from race_ai.keirin_83_reference_pdca_bridge import (
    ReferencePDCAError, reference_scoreboard
)

ORIGINAL_SHA256 = "9712049006185d633ecb5220017fe2bcf54348c859839a124bdd8f68db5f1160"


def _strict_json(raw):
    def unique(items):
        d={}
        for k,v in items:
            if k in d:
                raise ReferencePDCAError("DUPLICATE_JSON_OBJECT_KEY")
            d[k]=v
        return d
    return json.loads(
        raw,object_pairs_hook=unique,
        parse_constant=lambda bad: (_ for _ in ()).throw(
            ReferencePDCAError("NONFINITE_JSON_NUMBER")))


def _private(path,*,must_exist):
    p=Path(path).expanduser()
    if not p.is_absolute() or p.is_symlink():
        raise ReferencePDCAError("OWNER_PRIVATE_ABSOLUTE_UNSYMLINKED_REQUIRED")
    workspace=os.getenv("GITHUB_WORKSPACE")
    if workspace:
        root=Path(workspace).resolve()
        if root==p.resolve() or root in p.resolve().parents:
            raise ReferencePDCAError("PUBLIC_REPO_OWNER_FILE_FORBIDDEN")
    if must_exist:
        if not p.is_file() or p.stat().st_size>2_000_000:
            raise ReferencePDCAError("SOURCE_PRIVATE_FILE_MISSING_OR_LARGE")
    return p


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--results",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args(argv)
    try:
        manifest=_private(args.manifest,must_exist=True)
        result_path=_private(args.results,must_exist=True)
        output_path=_private(args.output,must_exist=False)
        raw=manifest.read_bytes()
        if sha256(raw).hexdigest()!=ORIGINAL_SHA256:
            raise ReferencePDCAError("ORIGINAL_83R_SHA_CHANGED")
        doc=_strict_json(raw)
        results=_strict_json(result_path.read_bytes())
        report=reference_scoreboard(
            doc,results,original_bytes=raw,
            original_sha256=ORIGINAL_SHA256)
        body=(json.dumps(report,sort_keys=True,ensure_ascii=False,
                         indent=2,allow_nan=False)+"\n").encode("utf-8")
        if len(body)>1_000_000:
            raise ReferencePDCAError("PDCA_OUTPUT_TOO_LARGE")
        if output_path.exists() or output_path.parent.is_symlink():
            raise ReferencePDCAError("OUTPUT_ALREADY_EXISTS_NO_REWRITE")
        output_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with os.fdopen(os.open(output_path,
             os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),
             0o600),"wb") as fp:
            fp.write(body)
            fp.flush()
            os.fsync(fp.fileno())
        if sha256(output_path.read_bytes()).digest()!=sha256(body).digest():
            raise ReferencePDCAError("PRIVATE_PDCA_READBACK_FAILED")
        print(json.dumps({
          "state":"PRIVATE_REFERENCE_PDCA_FROZEN_AND_READ_BACK",
          "reference_evaluable_published_results":
              report["reference_evaluable_published_results"],
          "reference_hits":report["reference_hits"],
          "reference_investment_yen":report["reference_investment_yen"],
          "reference_payout_yen":report["reference_payout_yen"],
          "formal_Hit8":None,
          "four_pr71_models_scored":0,
          "source_manifest_sha256":ORIGINAL_SHA256,
          "report_sha256":sha256(body).hexdigest(),
        },ensure_ascii=False,sort_keys=True))
        return 0
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,
            ReferencePDCAError):
        print('{"state":"REFERENCE_83R_PDCA_HOLD_OR_INVALID"}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
