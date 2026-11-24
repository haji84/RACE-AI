"""Recompute the public retrospective scores from checkpoint facts and hit receipts."""
import json
import math
from collections import defaultdict
from itertools import groupby
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent


def supplement_pair_transition(existing, back_pair, corner_pair):
    """Complete this race's B→4C observation, preserving its other phase observations."""
    updated = dict(existing)
    phases = dict(existing.get("phases", {}))
    for stage, observed in (("back", back_pair), ("corner", corner_pair)):
        if len(observed) != 2 or len(set(observed)) != 2:
            raise ValueError(f"Two distinct riders are required at {stage}")
        if stage in phases and list(phases[stage]["pair"]) != list(observed):
            raise ValueError(f"Conflicting rider order at {stage}")
        if stage not in phases:
            phases[stage] = {"pair": list(observed)}
    updated["phases"] = phases
    return updated


def probability(history, rider):
    population = (1 + sum(held for _, held in history)) / (2 + len(history))
    rider_records = [held for reg, held in history if reg == rider]
    return population, (4 * population + sum(rider_records)) / (4 + len(rider_records))


def compare(predicted, expected, observed):
    for position, name in enumerate(("population", "rider")):
        squared = [(p[position] - y) ** 2 for p, y in zip(predicted, observed, strict=True)]
        assert math.isclose(mean(squared), expected[name]["brier"], abs_tol=1e-12)


def main():
    archive = json.loads((HERE / "public-race-observations.json").read_text())["races"]
    report = json.loads((HERE / "local-frame-recovery.json").read_text())
    previous, initial, current = {}, {}, {}
    for row in archive:
        if not row["readable_B_to_corner"]:
            continue
        key = row["race_id"].replace("-", "")
        pair = (row["B_leader_registration"], int(row["B_car"] == row["corner_car"]))
        current[key] = pair
        if row["included_in_earlier_rider_fit"]:
            previous[key] = pair
            if "current_viewing" not in row["source_groups"] and not row["historical_purposive_win_loss_sample"]:
                initial[key] = pair
    for row in report["reread_records"]:
        if row["accepted_for_back_to_corner"]:
            key = row["race"]
            assert key not in current
            phase = row["accepted_phase"]
            current[key] = (row["back_registration"], int(phase["back"] == phase["corner"]))
    now = {k: v for k, v in current.items() if k[:8] <= "20261120"}
    assert [len(d) for d in (initial, previous, now)] == [45, 78, 88]

    for panel in report["conditional"].values():
        for mode, history in zip(("previous45", "previous78", "all_eligible"), (initial, previous, now), strict=True):
            errors, losses = [], []
            for key in panel["races"]:
                assert key[:8] > "20261120"
                rider, outcome = current[key]
                p = probability(history.values(), rider)[1]
                errors.append((p - outcome) ** 2)
                losses.append(-math.log(p if outcome else 1 - p))
            assert math.isclose(mean(errors), panel["arms"][mode]["brier"], abs_tol=1e-12)
            assert math.isclose(mean(losses), panel["arms"][mode]["logloss"], abs_tol=1e-12)

    history, predictions, outcomes = [], [], []
    dates = 0
    for _, group in groupby(sorted(current), key=lambda key: key[:8]):
        batch = [current[key] for key in group]
        predictions.extend(probability(history, rider) for rider, _ in batch)
        outcomes.extend(held for _, held in batch)
        history.extend(batch)
        dates += 1
    sequential = report["walk_forward"]
    assert (dates, len(outcomes)) == (sequential["dates"], sequential["observations"])
    compare(predictions, sequential["metrics"]["all"], outcomes)

    tested = report["trifecta"]["settlement_checks"]
    assert len(tested) == 211
    scored = [row for row in tested.values() if row is not None]
    assert len(scored) == 207
    for arm, counts in report["trifecta"]["rows"].items():
        for cap in (1, 4, 8):
            hits = sum(row[arm] is not None and row[arm] <= cap for row in scored)
            assert hits == counts[str(cap)]
    added = report["fit"]["now_pairs_new_to_16"]
    assert len(set(added)) == report["fit"]["both_pairs_now"] - 16
    print(f"Verified 24 rereads, {len(now)} training cases, {len(current)-len(now)} later cases, "
          f"{dates} daily folds and {len(scored)} trifecta settlements.")


if __name__ == "__main__":
    main()
