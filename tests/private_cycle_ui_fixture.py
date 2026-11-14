"""Build an explicit synthetic browser fixture through saved-artifact read APIs.

Existing test inputs create the sealed native originals before capture. The
capture callback serves those local bytes only; restore and projection never
train or rerun a model. Nothing in this fixture is live race performance.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch
import zipfile

from race_ai.boat_ab_shadow import build_pair
from race_ai.boat_live_feature_shadow import build_live_feature_shadow
from race_ai.frozen_day_cycle import read_p0
from race_ai.private_cycle_capture import capture_artifacts
from race_ai.private_cycle_projection import project_state
from race_ai.private_cycle_restore import restore_manifest
from tests.test_frozen_day_cycle import observation, sample
from tests.test_observed_p1_connection import AT, archive, bridge, inputs


DAY = "2030-04-01"


def _zip(member, document):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as saved:
        saved.writestr(member, json.dumps(document, ensure_ascii=False))
    return stream.getvalue()


def _artifacts():
    """Use the existing sealed baseline and genuine learned-output fixtures."""
    from tests.test_private_cycle_projection import saved_learned_archive

    _, p0_raw, p0_meta = sample()
    _, p0_rows = read_p0(p0_raw, p0_meta, expected_day=DAY)
    base, extra, proof = inputs()
    bundle = bridge.build_bundle(base, extra, AT, **proof, owner_reviewed=True)
    p1_document = dict(schema="RACE_AI_NATIONWIDE_PRE_CUTOFF_AB_V1",
                       paired_forecasts=[build_pair(base, AT)],
                       additional_official_feature_shadows=[build_live_feature_shadow(base, extra, AT)],
                       observed_pairwise_p1_bundles=[bundle])
    p1_raw, p1_meta = archive(p1_document)

    learned_document, learned_raw, learned_meta = saved_learned_archive()
    learned_meta = deepcopy(learned_meta)
    learned_meta["id"] = 124

    earlier = observation(p0_rows[0])
    earlier["saved_context"] = "synthetic raw observation context " + "x" * 5000
    later = deepcopy(earlier)
    later["captured_at"] = "2030-04-01T02:20:00Z"
    later["data"]["refund_boats"] = [6]
    later["data"]["payouts"][0]["payout_per_100_yen"] = 2500
    later["source_sha256"] = sha256(json.dumps(later["data"], sort_keys=True).encode()).hexdigest()
    result_raw = _zip("official-result-observations.json", [earlier, later])
    result_meta = dict(id=701, name="race-existing-cycle-99", expired=False,
                       created_at="2030-04-01T02:30:00Z", digest="sha256:" + sha256(result_raw).hexdigest(),
                       workflow_run=dict(id=99, head_repository_id=1416489937))
    return [(p0_raw, p0_meta), (p1_raw, p1_meta), (learned_raw, learned_meta), (result_raw, result_meta)], [earlier, later], learned_document["learned_pairwise_shadows"]


def build_fixture(output_file):
    """Write one fresh synthetic JSON under an existing private temp parent."""
    out = Path(output_file).expanduser()
    if not out.is_absolute() or not out.parent.is_dir() or out.exists() or out.is_symlink():
        raise ValueError("fresh output file under an existing absolute temp directory required")
    artifacts, observations, expected_learned = _artifacts()
    responses = {}
    for raw, metadata in artifacts:
        responses[f"actions/artifacts/{metadata['id']}"] = json.dumps(metadata).encode()
        responses[f"actions/artifacts/{metadata['id']}/zip"] = raw
    requests = []

    def local_get(endpoint):
        requests.append(endpoint)
        if endpoint not in responses:
            raise AssertionError("unexpected fixture artifact request")
        return responses[endpoint]

    with tempfile.TemporaryDirectory(prefix="private-cycle-ui-", dir=out.parent) as temporary:
        capture_root = Path(temporary) / "captured"
        # Generation above is test setup. Saved-artifact readback below must
        # remain independent of inference, training, collection and settlement.
        with patch("race_ai.observed_weight_learning.make_shadows", side_effect=AssertionError("readback inference")), \
             patch("race_ai.observed_weight_learning.fit_from_verified", side_effect=AssertionError("readback training")), \
             patch("race_ai.boat_observed_pairwise_models.predict_pair", side_effect=AssertionError("readback prediction")), \
             patch("race_ai.frozen_day_cycle.settle", side_effect=AssertionError("readback scoring")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("external source request")):
            manifest = capture_artifacts(DAY, [meta["id"] for _, meta in artifacts], capture_root, github_get=local_get)
            state = restore_manifest(manifest, capture_root)
            view = project_state(state, dataset_status="SYNTHETIC_ONLY")

    predictions = [p for row in view["records"] for p in [row["prediction"], *row["comparison_predictions"]] if p]
    learned = [p for p in predictions if p.get("variant") == "LEARNED_SHADOW"]
    if ({p["stage"] for p in predictions} != {"P0", "P1"} or len(learned) != 2 or
            not any(p["model_version"] is None for p in predictions)):
        raise AssertionError("synthetic saved-model fixture is incomplete")
    for saved, original in zip(learned, expected_learned):
        if any(saved[key] != original[key] for key in ("model_id", "model_version", "ordered_top8", "prediction_sha256")):
            raise AssertionError("genuine synthetic learned original was changed during readback")
    observed_row = next(row for row in view["records"] if row["race_id"] == observations[0]["race_id"])
    if observed_row["result_observations"] != observations or observed_row["result_revisions"]:
        raise AssertionError("synthetic captures were lost or turned into official revisions")
    if any(row["scope"] != "synthetic" for row in view["records"]) or any(p["external_receipt_verified"] for p in predictions):
        raise AssertionError("synthetic fixture cannot assert official evidence")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(out, flags, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(view, stream, ensure_ascii=False)
        stream.write("\n")
    return dict(scope="SYNTHETIC_ONLY", races=len(view["records"]), saved_predictions=len(predictions),
                learned_variants=len(learned), result_observations=len(observations),
                local_artifact_reads=len(requests), source_requests=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="Fresh JSON file under an existing run-temp directory")
    args = parser.parse_args(argv)
    print(json.dumps(build_fixture(args.out), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
