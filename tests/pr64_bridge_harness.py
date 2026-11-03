"""Cross-branch integration smoke with REAL PR #64 implementation and synthetic Blob.

Run only with PR64_REFERENCE_ROOT pointing to an immutable checkout.
No official requests, live API writes, money, or real-race attribution.
"""
import json
import os
from pathlib import Path
import sys
import types

ROOT71 = Path(__file__).resolve().parents[1]
ROOT64 = Path(os.environ.get("PR64_REFERENCE_ROOT", "")).resolve()
if not (ROOT64 / "web" / "exhibition_contract.py").is_file():
    raise SystemExit("PINNED_PR64_CHECKOUT_REQUIRED")

# The Vercel SDK is not required to exercise the real PR64 storage engine
# against its original test Blob double. Only a not-found exception is used.
if "vercel.blob" not in sys.modules:
    v = types.ModuleType("vercel")
    b = types.ModuleType("vercel.blob")
    b.BlobNotFoundError = type("BlobNotFoundError", (Exception,), {})
    v.blob = b
    sys.modules["vercel"] = v
    sys.modules["vercel.blob"] = b

sys.path.insert(0, str(ROOT64))
sys.path.insert(0, str(ROOT64 / "web"))
from tests.test_exhibition_store import seed_baseline, seed_preview
from tests.test_exhibition_contract import fixture, NOW
from tests.test_race_cloud_store import Blob
from tests.test_live_evaluation_contract import fixture as result_fixture
from web.api.exhibition_store import (
    publish_exhibition_prediction, read_exhibition_prediction, checked_receipt, REVIEW)
from web.race_contract import validate_cloud_bundle

import race_ai
race_ai.__path__.insert(0, str(ROOT71 / "race_ai"))
from race_ai.pr64_exhibition_pipeline import tick_one, score_after_finish, daily_rollup


def check():
    baseline, before, race = fixture()
    client = Blob()
    seed_baseline(client, baseline)
    seed_preview(client, before)
    source_copy = dict(client.data)
    run_count = []
    nonce_count = []
    def readback(row, request_id=None):
        return read_exhibition_prediction(row, client=client, now=NOW, request_id=request_id)
    def exhibition_ready(row):
        payload = before["records"][0]["record"]["data"]["boats"]
        return len(payload) == 6 and all(x["display_time"] is not None for x in payload)
    def claim(row):
        nonce_count.append(row["race_id"])
        return {"state":"CREATED", "request_id":"123457-1"}
    def publish(row, rid):
        run_count.append(rid)
        return publish_exhibition_prediction(
            {"publication_review": REVIEW, "race_id":row["race_id"], "request_id":rid},
            row, client=client, now=NOW, clock=lambda: NOW)
    def verify(receipt, row, at):
        return checked_receipt(receipt, row, at, client=client) == receipt
    event = {**race, "sport":"boat", "cutoff_at":race["closed_at"],
             "cutoff_verified":True, "source_permission_approved":True}
    got = tick_one(event, clock=lambda:NOW, readback=readback,
                   exhibition_ready=exhibition_ready, claim=claim,
                   publish=publish, validate_receipt=verify)
    assert got["state"] == "PR64_CLOUD_FROZEN_VERIFIED", got
    assert len(got["ordered_top8"]) == 8
    assert len(got["all_triples"]) == 120
    assert run_count == ["123457-1"] and nonce_count == [event["race_id"]]
    assert got["cloud_saved_at"] < event["closed_at"]
    assert got["scores_calibrated"] is False
    assert all(key in client.data for key in (
        f"race-ai/post-exhibition/{race['race_id']}.json",
        f"race-ai/post-exhibition-receipts/{race['race_id']}/123457-1.json",
        f"race-ai/post-exhibition-versions/{race['race_id']}/{got['prediction_snapshot_id']}.json"))
    # PR64 baseline/preview storage must not be overwritten.
    assert all(client.data[k] == v for k, v in source_copy.items())

    # The second run must use the original immutable PR64 receipt, not
    # generate a second nonce or silently overwrite the existing top-8.
    again = tick_one(event, clock=lambda:NOW, readback=readback,
                   exhibition_ready=exhibition_ready, claim=claim,
                   publish=publish, validate_receipt=verify)
    assert again["reused_existing_receipt"] is True
    assert again["receipt_sha256"] == got["receipt_sha256"]
    assert len(run_count) == len(nonce_count) == 1
    assert again["ordered_top8"] == got["ordered_top8"]

    # The PR64 parser + record validator, not a made-up result, is used for
    # post-close scoring. This result fixture is SYNTHETIC.
    _, official_bundle, result_race = result_fixture()
    assert result_race["race_id"] == race["race_id"]
    post = score_after_finish(
        race, got, official_bundle,
        now=NOW.replace(hour=10, minute=10),
        validate_result=lambda bundle, row, now: validate_cloud_bundle(bundle, row, now))
    assert post["state"] == "RESULT_SCORED", post
    assert post["official_result"] == [1, 2, 3]
    assert post["hit_at_1"] in (0, 1) and post["hit_at_8"] in (0, 1)
    assert post["model_upgrade_approved"] is False
    assert post["model_calibrated"] is False
    assert post["winner_model_score"] > 0
    missing = score_after_finish(race, None, official_bundle,
        now=NOW.replace(hour=10, minute=10),
        validate_result=lambda bundle, row, now: validate_cloud_bundle(bundle, row, now))
    assert missing["hit_at_8"] == 0
    roll = daily_rollup([post, {**missing, "race_id": "other-test-race"}])
    assert roll["officially_scored_races"] == 2
    assert roll["hits_at_8"] == post["hit_at_8"]
    assert roll["frozen_forecasts"] == 1

    # An unreturned POST must not be retried automatically.
    another, _, other_race = fixture()
    other_client = Blob()
    seed_baseline(other_client, another)
    seed_preview(other_client, before)
    submitted = []
    def uncertain(row, rid):
        submitted.append(rid)
        raise OSError("uncertain write")
    uncertain_result = tick_one(event, clock=lambda:NOW,
        readback=lambda row, request_id=None:None, exhibition_ready=exhibition_ready,
        claim=claim, publish=uncertain, validate_receipt=verify)
    assert uncertain_result["state"] == "PR64_POST_UNCERTAIN_NO_RETRY"
    assert submitted == ["123457-1"]

    # Closing invalidates any purported early receipt.
    from copy import deepcopy
    bad = deepcopy(got)
    bad["cloud_saved_at"] = race["closed_at"]
    try:
        score_after_finish(race, bad, official_bundle,
            now=NOW.replace(hour=10, minute=10),
            validate_result=lambda bundle, row, now:validate_cloud_bundle(bundle, row, now))
    except ValueError:
        pass
    else:
        raise AssertionError("postclose frozen forecast incorrectly counted")

    return {"status":"SYNTHETIC_CROSS_BRANCH_PR64_STORAGE_PDCA_PASS",
            "pr64_source":"761247bee0209e37b1af6b8885e92cad3e9260a5",
            "blob_save_readback":True, "first_post_count":len(run_count),
            "reused_without_second_post":True, "six_boat_model_120":True,
            "postclose_result_verified":True, "actual_live_races":0,
            "actual_live_predictions":0, "actual_live_result_scores":0,
            "autonomous_live_dispatch":False}

if __name__ == "__main__":
    print(json.dumps(check(), sort_keys=True))
