"""Run pinned PR71 research delivery through existing PR72 binding.

For GitHub-hosted CI only, with FICTIONAL fixture input. No network/source
capture, real source approval, real forecast freeze, payment or deployment.
The model code is imported from a separately checked-out pinned PR71 SHA.
"""
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent.parent
# python scripts/file.py sets sys.path[0] to scripts, not the repo root.
sys.path.insert(0,str(HERE))
import race_ai
import tests

PR71=HERE/"pr71-contract-reference"
if not (PR71/"race_ai/permissioned_source_delivery.py").is_file():
    raise RuntimeError("PR71 independent pinned checkout missing")
race_ai.__path__.append(str(PR71/"race_ai"))
tests.__path__.append(str(PR71/"tests"))
sys.path.insert(0,str(PR71/"tests"))

from test_permissioned_source_delivery import raw_feed,gate,AT
from race_ai.permissioned_source_delivery import deliver
from race_ai.operator_export_intake import transform
from race_ai.pr71_delivery_binding import bind_audit_to_delivery

for sport in ("boat","keirin","autorace","horse"):
    raw=raw_feed(sport)
    data=deliver(raw,gate(),at=AT,persist=False)
    snapshot=data["snapshot"]
    race=snapshot["race"]
    model_sport=race["sport"]
    ledger_sport="horse_local" if model_sport=="horse" else model_sport
    venue=race["venue"]
    day=race["event_date_jst"]
    # PR71 test fixtures are all 1R in fictional-venue, NOT real events.
    if not race["race_id"].endswith(":1"):
        raise AssertionError("PR71 fixture changed its race ID format")
    obj={"schema":"RACE_AI_OPERATOR_EXPORT_V1","event_date_jst":day,
         "source_ref":"https://example.org/fictional",
         "source_rights_ref":"FICTIONAL_NOT_A_GRANT","captured_at":AT,
         "races":[{"sport":ledger_sport,"venue":venue,"race_no":1,
                   "sales_cutoff_at":race["sales_cutoff_at"],
                   "offering_status":"UNKNOWN"}]}
    # Horse family names differ between PR71 ("horse") and PR72 ("horse_local"),
    # so IDs must be translated explicitly, never inferred from horse number.
    if model_sport=="horse":
        from copy import deepcopy
        import race_ai.pr71_delivery_binding as binding
        audit=transform(obj,"a"*64)
        alias=audit["records"][0]["race_id"]
        if not alias.startswith("horse_local:"):
            raise AssertionError("horse alias mismatch")
        # No silent rewrite of a signed delivery object is permitted. Instead
        # explicitly signal the still-open cross-sport ID namespace blocker.
        try:
            bind_audit_to_delivery(audit,data,race_id=alias)
        except binding.BindingError as exc:
            if "identity mismatch" not in str(exc):
                raise
            print("HORSE_ID_NAMESPACE_GATE_EXPECTED: PR71 horse vs PR72 horse_local")
        else:
            raise AssertionError("horse namespace mismatch was wrongly admitted")
        continue
    audit=transform(obj,"a"*64)
    binding=bind_audit_to_delivery(audit,data,race_id=race["race_id"])
    assert len(binding["models"])==data["research_suite"]["model_count"]
    assert binding["source_access_reviewed_by_this_bridge"] is False
    assert binding["official_sales_cutoff_verified"] is False
    assert binding["external_freeze_verified"] is False
    assert binding["eligible_for_scoring"] is False
    print("PINNED_PR71_PR72_SYNTHETIC_JOIN_OK",sport,len(binding["models"]))
print("NO_REAL_FORECAST_OR_OFFICIAL_FREEZE_CLAIM")
