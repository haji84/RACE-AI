"""Source-bound automatic A/B batch run for EVERY registered KEIRIN race.

No manual per-race prediction prompts. Consume only owner-private normalized
pre-race JSON whose associated *raw source bytes* are present and SHA matched.
Compute A and tactical B; encrypt both before source-published sales cutoff;
write a sanitized all-races summary. C remains optional HOLD.

No network calls, no API scraping, no user key in log, no public plaintext.
The normalizer/upstream collector MUST deliver real source artifacts.
A local raw-byte match cannot prove official organizer authentication.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import stat
import sys

from race_ai import keirin_nationwide_auto_generator as model
from race_ai import keirin_confidence as confidence
from race_ai import keirin_nationwide_auto_storage as seal
from race_ai import keirin_form_fall_shadow as form_shadow
from race_ai import keirin_nationwide_active_AB as country
from race_ai import keirin_dynamic_nationwide_registry as dynamic

MAX_SOURCE = 2_000_000
MAX_PAGE = 9_000_000
STATUS_SCHEMA = "RACE_AI_KEIRIN_NATIONWIDE_AUTO_GENERATION_CYCLE_V1"

def need(test, reason):
    if not test:
        raise ValueError(reason)


def private_dir(value):
    p = Path(value)
    need(p.is_absolute() and p.is_dir() and not p.is_symlink() and
         stat.S_IMODE(p.stat().st_mode) == 0o700,
         "OWNER_0700_PRIVATE_SOURCE_OR_OUTPUT_DIR_REQUIRED")
    workspace = os.getenv("GITHUB_WORKSPACE")
    if workspace:
        ws = Path(workspace).resolve()
        resolved = p.resolve()
        need(not (resolved == ws or ws in resolved.parents),
             "PRIVATE_PLAINTEXT_IN_PUBLIC_WORKSPACE_PROHIBITED")
    return p


def checked_raw_sources(snapshot, raw_pages_dir):
    """Check source bytes, not whether the source provider signed them."""
    for item in [snapshot["cutoff_source"], *snapshot["source_pages"]]:
        digest = item["bytes_sha256"]
        path = raw_pages_dir / (digest + ".html")
        need(path.is_file() and not path.is_symlink() and
             0 < path.stat().st_size <= MAX_PAGE,
             "OWNER_RAW_SOURCE_BYTES_MISSING")
        with path.open("rb") as fh:
            raw = fh.read(MAX_PAGE+1)
        need(sha256(raw).hexdigest() == digest,
             "OWNER_RAW_SOURCE_SHA_MISMATCH")
    return True


def registered_race_ids(registry):
    if registry.get("schema") == country.SCHEMA:
        country.checked_registry(registry)
        return [r["race_id"] for r in registry["records"]]
    dynamic.checked_day(registry)
    return [r["race_id"] for r in registry["races"]]


def _safe_error(code):
    # Never leak a URL, rider name, odds, source bytes or provider error string.
    return (code if isinstance(code,str) and code.isupper() and
            all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ_0123456789" for c in code)
            and len(code)<=100 else "UNVERIFIED_INPUT_OR_SOURCE_FAILURE")


def run_cycle(*,registry, private_racecards_dir, raw_pages_dir,
              private_cipher_dir, owner_public_key_pem,
              clock=None, form_evidence_loader=None):
    races=registered_race_ids(registry)
    cards=private_dir(private_racecards_dir)
    raw_pages=private_dir(raw_pages_dir)
    out=private_dir(private_cipher_dir)
    if clock is None:
        clock=lambda:datetime.now(timezone.utc)
    need(callable(clock), "RUNTIME_CLOCK_REQUIRED")
    need(type(owner_public_key_pem) is bytes,
         "OWNER_PINNED_PUBLIC_KEY_MISSING")
    # Check the pinned owner key even if there are zero actual racecards.
    seal.checked_public_key(owner_public_key_pem)
    results=[]
    pending_form = {}
    for race_id in races:
        row={"race_id":race_id,"state":"NO_FORECAST_INPUT_MISSING",
             "A_generated":False,"B_generated":False,
             "ciphertext_local_created":False,
             "cross_runner_readback":False,"C_state":"HOLD_OPTIONAL"}
        encrypted=out/(race_id+".sealed.json")
        if encrypted.exists() or encrypted.is_symlink():
            # Never overwrite a previous prediction on an updated result.
            row["state"]="HOLD_CREATE_ONCE_EXISTING_CIPHER_REQUIRES_READBACK"
            results.append(row)
            continue
        source_file=cards/(race_id+".json")
        if not source_file.is_file() or source_file.is_symlink():
            results.append(row)
            continue
        try:
            need(source_file.stat().st_size<=MAX_SOURCE,
                 "SOURCE_FILE_OVERSIZED")
            raw=source_file.read_bytes()
            snap=json.loads(raw.decode("utf-8"))
            need(type(snap) is dict,
                 "SOURCE_JSON_MUST_BE_RACE_FACTS_OBJECT")
            need(snap.get("race_id")==race_id,
                 "SOURCE_OTHER_RACE_OR_DATE")
            now=clock().astimezone(timezone.utc).isoformat()
            model.validate_snapshot(snap,computed_at=now)
            checked_raw_sources(snap,raw_pages)
            # The SHA-locked baseline is unchanged; conditions are a separate
            # independently timestamped research sidecar.
            forecast=model.generate_A_B(snap,generated_at=now)
            assessment=confidence.assess_baseline(snap,forecast,
                assessed_at=clock().astimezone(timezone.utc).isoformat())
            row["A_generated"]=True
            row["B_generated"]=True
            saved=seal.seal_once(
                snapshot=snap,prediction=forecast,
                public_key_pem=owner_public_key_pem,
                path=encrypted,
                sealed_at=clock().astimezone(timezone.utc).isoformat(),
                confidence_assessment=assessment)
            row.update({
                "state":"A_B_PRIVATE_CIPHER_CREATED_SAME_JOB_SHA_MATCH",
                "ciphertext_local_created":True,
                "cipher_file_sha256":saved["cipher_sha256"],
                "A_cipher_sha256":saved["A_cipher_sha256"],
                "B_cipher_sha256":saved["B_cipher_sha256"],
                "forecast_model_A":model.MODEL_A,
                "forecast_model_B":model.MODEL_B,
                "candidate_A_count":len(forecast["A"]["ranked_tickets"]),
                "candidate_B_count":len(forecast["B"]["ranked_tickets"]),
                "six_phase_scenarios":len(forecast["B"]["six_phase_scenarios"]),
                "real_official_cutoff_independent_proof":False,
                "confirmed_owner_source_raw_bytes_sha":True,
            })
            row["form_fall_shadow_state"] = "NO_FORM_SOURCE_BASELINE_ONLY"
            if form_evidence_loader is not None:
                pending_form[race_id] = snap, forecast
        except (ValueError,KeyError,TypeError,OSError,
                model.AutomaticForecastError,seal.AutoSealError,
                form_shadow.ConditionShadowError) as exc:
            row["state"]="HOLD_"+_safe_error(str(exc))
        results.append(row)
    # Finish all baseline saves before an optional review can consume cutoff time.
    for row in results:
        if not row["ciphertext_local_created"]:
            continue
        race_id = row["race_id"]
        if form_evidence_loader is None:
            supplement_file = cards / (race_id + ".form.json")
            if supplement_file.is_symlink() or supplement_file.exists():
                row["form_fall_shadow_state"] = "HOLD_CONDITION_SOURCE_IDENTITY_NOT_VERIFIED"
            continue
        snap, forecast = pending_form.pop(race_id)
        now = forecast["generated_at"]
        supplement = shadow_forecast = None
        # Structured car-number JSON is not an identity attestation.
        # The trusted application supplies a LOCAL source parser that
        # rebuilds evidence from original bytes and verifies official
        # roster registration IDs. CLI defaults never admit sidecars.
        try:
            need(callable(form_evidence_loader) and all(
                type(r["athlete_id"]) is str and
                model.RID.fullmatch(r["athlete_id"])
                for r in snap["riders"]),
                "CONDITION_SOURCE_IDENTITY_NOT_VERIFIED")
            supplement = form_evidence_loader(
                snapshot=snap, raw_pages_dir=raw_pages, captured_at=now)
            need(type(supplement) is dict,
                 "CONDITION_VERIFIED_SOURCE_MISSING")
            shadow_forecast = form_shadow.generate_shadow(
                snap, supplement, baseline=forecast, generated_at=now)
            checked_raw_sources({
                "cutoff_source": snap["cutoff_source"],
                "source_pages": supplement["source_pages"]}, raw_pages)
        except (ValueError, TypeError, KeyError, OSError, RecursionError, OverflowError) as exc:
            supplement = shadow_forecast = None
            row["form_fall_shadow_state"] = "HOLD_"+_safe_error(str(exc))
        if shadow_forecast is not None:
            try:
                shadow_saved = form_shadow.seal_shadow_once(
                    snapshot=snap, supplement=supplement,
                    shadow=shadow_forecast,
                    public_key_pem=owner_public_key_pem,
                    path=out/(race_id+".form.sealed.json"),
                    sealed_at=clock().astimezone(timezone.utc).isoformat())
                row["form_fall_shadow_state"] = "PRIVATE_CONDITIONED_SHADOW_SEALED"
                row["form_fall_shadow_file_sha256"] = shadow_saved["file_sha256"]
                row["form_fall_shadow_cipher_sha256"] = shadow_saved["cipher_sha256"]
                row["form_fall_baseline_sha256"] = shadow_saved["baseline_prediction_sha256"]
                interview_rows = [r["winticket_interview"] for r in shadow_forecast["rider_assessments"]
                                  if "winticket_interview" in r]
                if interview_rows:
                    row["winticket_interview_riders"] = len(interview_rows)
                    row["winticket_adjusted_riders"] = sum(
                        r["score_adjustment"] != 0 for r in interview_rows)
            except (ValueError,TypeError,KeyError,OSError,
                    form_shadow.ConditionShadowError):
                row["form_fall_shadow_state"] = "HOLD_CONDITIONED_SHADOW_SEAL"
    counts=Counter(x["state"] for x in results)
    return {
        "schema":STATUS_SCHEMA,
        "day_jst":registry["day_jst"],
        "registered_races":len(races),
        "A_generated":sum(x["A_generated"] for x in results),
        "B_generated":sum(x["B_generated"] for x in results),
        "same_job_sealed":sum(x["ciphertext_local_created"] for x in results),
        "cross_runner_RSA_decryption":0,
        "organizer_results_scored":0,
        "missing_is_not_miss":True,
        "four_model_PR71_dependency":False,
        "C_optional_not_blocking_AB":True,
        "source_provider_access_verified":False,
        "statuses":dict(sorted(counts.items())),
        "records":results,
    }


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--registry",required=True)
    parser.add_argument("--private-racecards-dir",required=True)
    parser.add_argument("--raw-pages-dir",required=True)
    parser.add_argument("--private-output-dir",required=True)
    parser.add_argument("--owner-rsa-public-pem",required=True)
    parser.add_argument("--safe-summary",required=True)
    args=parser.parse_args(argv)
    try:
        registry=json.loads(Path(args.registry).read_text(encoding="utf-8"))
        report=run_cycle(
            registry=registry,
            private_racecards_dir=args.private_racecards_dir,
            raw_pages_dir=args.raw_pages_dir,
            private_cipher_dir=args.private_output_dir,
            owner_public_key_pem=Path(args.owner_rsa_public_pem).read_bytes())
        path=Path(args.safe_summary)
        need(path.is_absolute() and path.parent.is_dir() and
             not path.exists() and not path.is_symlink(),
             "SAFE_SUMMARY_CREATE_ONCE_REQUIRED")
        raw=json.dumps(report,ensure_ascii=False,sort_keys=True,
                       separators=(",",":")).encode()+b"\n"
        flags=os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,"O_NOFOLLOW",0)
        fd=os.open(path,flags,0o600)
        with os.fdopen(fd,"wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        need(path.read_bytes()==raw,
             "SAFE_SUMMARY_READBACK_FAILED")
        print(json.dumps({k:report[k] for k in (
            "schema","day_jst","registered_races","A_generated",
            "B_generated","same_job_sealed","cross_runner_RSA_decryption",
            "organizer_results_scored","statuses")},
            sort_keys=True,ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError):
        print('{"state":"HOLD_NATIONWIDE_AUTO_PREDICTION_NOT_RUN",'
              '"real_forecasts_claimed":0}')
        return 2


if __name__=="__main__":
    raise SystemExit(main())
