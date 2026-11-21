"""Create new owner-private authored forecasts with a saved confidence sidecar.

The complete independent scenario universe is supplied before ticket selection.
Legacy authored forecasts and their ticket-derived scenarios are not upgraded.
This adapter shares the research evaluator used by automatic A/B forecasts.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import os
import stat

from . import keirin_confidence as confidence
from . import keirin_nationwide_auto_generator as model
from .keirin_note_view import MAX_FILE, MAX_VIEW

REQUEST_SCHEMA = "RACE_AI_KEIRIN_NEW_AUTHORED_FORECAST_REQUEST_V1"
ASSESSMENT_SCHEMA = "RACE_AI_KEIRIN_CONFIDENCE_ASSESSMENT_V1"
RULES_VERSION = "research-coherence-v1"
BODY_KEYS = {
    "race_id", "analysis_created_at", "deadline_jst", "market", "strategy",
    "headline", "reason", "risk", "tickets", "scenarios", "confidence_universe",
}
BUNDLE_KEYS = {
    "schema", "rules_version", "race_id", "assessed_at", "cutoff",
    "source_prediction_sha256", "source_facts_sha256", "scenario_universe_sha256",
    "evaluations",
}
SELECTION_KEYS = {"market", "strategy", "headline", "reason", "risk", "tickets"}


def need(value, code):
    if not value:
        raise ValueError("KEIRIN_AUTHORED_CONFIDENCE_" + code)


def _selection(value):
    need(type(value) is dict and set(value) == SELECTION_KEYS, "SELECTION_FIELDS")
    need(value["market"] in {"3t", "2t"} and
         value["strategy"] in {"normal", "rollover"}, "SELECTION_KIND")
    for key in ("headline", "reason", "risk"):
        need(type(value[key]) is str and 0 < len(value[key]) <= 2000,
             "SELECTION_TEXT")
    need(type(value["tickets"]) is list and value["tickets"], "TICKETS_REQUIRED")
    for ticket in value["tickets"]:
        need(type(ticket) is dict and set(ticket) == {"combo", "role"} and
             type(ticket["combo"]) is str and type(ticket["role"]) is str and
             0 < len(ticket["role"]) <= 30, "TICKET_FIELDS")
    return value


def _entry(universe, selection, at):
    return confidence.evaluate_ticket_set(
        universe, selection["tickets"], market=selection["market"],
        strategy=selection["strategy"], assessed_at=at)


def prediction_body(value):
    """Original body, including the known rollover child's original body.

    Each sidecar has its own binding and is validated separately. Excluding
    those two known metadata positions also keeps prediction JSON portable:
    its values contain no floating-point assessment metrics.
    """
    body = {k: v for k, v in value.items() if k != "confidence_assessment"}
    if "rollover" in body:
        body["rollover"] = {
            k: v for k, v in body["rollover"].items() if k != "confidence_assessment"}
    return body


def prediction_sha256(value):
    return model.digest(prediction_body(value))


def create_forecast(universe, selection, *, generated_at, rollover=None):
    """Create a fresh record; ``generated_at`` is supplied by the caller's clock.

    The CLI always uses its current clock and has no historical-time override.
    A two-car rollover child is created first, so the normal record's digest
    covers that child without a circular reference.
    """
    selection = _selection(selection)
    need(type(universe) is dict and
         universe.get("evidence_kind") == "authored_goals" and
         universe.get("candidate_origin") == "independent_preselection_v1",
         "INDEPENDENT_NEW_UNIVERSE_REQUIRED")
    at = model.when(generated_at)
    need(model.when(universe["source_as_of"]) <= at and
         (model.when(universe["cutoff"]) - at).total_seconds() >= 65,
         "PRE_CUTOFF_CREATION_REQUIRED")
    entry = _entry(universe, selection, generated_at)
    body = {
        "race_id": universe["race_id"],
        "analysis_created_at": generated_at,
        "deadline_jst": universe["cutoff"],
        **deepcopy(selection),
        "scenarios": [{"scenario_id": s["id"], "six_phases": deepcopy(s["phases"])}
                      for s in universe["scenarios"]],
        "confidence_universe": deepcopy(universe),
    }
    if selection["strategy"] == "rollover":
        body["eligible"] = True
    if rollover is not None:
        need(selection["market"] == "2t" and selection["strategy"] == "normal",
             "ROLLOVER_CHILD_CONTEXT")
        checked_forecast(rollover)
        need(rollover["market"] == "2t" and rollover["strategy"] == "rollover" and
             rollover["race_id"] == body["race_id"] and
             rollover["confidence_universe"] == universe and
             model.when(rollover["analysis_created_at"]) <= at,
             "ROLLOVER_PARENT_UNIVERSE_MISMATCH")
        body["rollover"] = deepcopy(rollover)
    body["confidence_assessment"] = {
        "schema": ASSESSMENT_SCHEMA,
        "rules_version": RULES_VERSION,
        "race_id": body["race_id"],
        "assessed_at": generated_at,
        "cutoff": universe["cutoff"],
        "source_prediction_sha256": prediction_sha256(body),
        "source_facts_sha256": universe["source_facts_sha256"],
        "scenario_universe_sha256": confidence.universe_sha256(universe),
        "evaluations": {"selected": entry},
    }
    return checked_forecast(body)


def checked_forecast(value):
    """Validate a new record, without changing or writing its assessment."""
    need(type(value) is dict, "RECORD_OBJECT")
    expected = BODY_KEYS | {"confidence_assessment"}
    if value.get("strategy") == "rollover":
        expected |= {"eligible"}
        need(value.get("eligible") is True, "ROLLOVER_ELIGIBLE")
    if "rollover" in value:
        expected |= {"rollover"}
        need(value.get("market") == "2t" and value.get("strategy") == "normal",
             "ROLLOVER_CHILD_CONTEXT")
    need(set(value) == expected, "RECORD_FIELDS")
    selection = _selection({k: value[k] for k in SELECTION_KEYS})
    universe = value["confidence_universe"]
    need(type(universe) is dict and
         universe.get("evidence_kind") == "authored_goals" and
         universe.get("candidate_origin") == "independent_preselection_v1",
         "INDEPENDENT_NEW_UNIVERSE_REQUIRED")
    bundle = value["confidence_assessment"]
    need(type(bundle) is dict and set(bundle) == BUNDLE_KEYS and
         bundle["schema"] == ASSESSMENT_SCHEMA and
         bundle["rules_version"] == RULES_VERSION and
         type(bundle["evaluations"]) is dict and
         set(bundle["evaluations"]) == {"selected"}, "ASSESSMENT_FIELDS")
    need(bundle["race_id"] == value["race_id"] == universe["race_id"] and
         bundle["cutoff"] == value["deadline_jst"] == universe["cutoff"] and
         bundle["assessed_at"] == value["analysis_created_at"], "RACE_TIME_BINDING")
    at = model.when(bundle["assessed_at"])
    need(model.when(universe["source_as_of"]) <= at and
         (model.when(bundle["cutoff"]) - at).total_seconds() >= 65,
         "PRE_CUTOFF_CREATION_REQUIRED")
    need(bundle["source_facts_sha256"] == universe["source_facts_sha256"] and
         bundle["scenario_universe_sha256"] == confidence.universe_sha256(universe) and
         bundle["source_prediction_sha256"] == prediction_sha256(value),
         "SOURCE_BINDING")
    need(value["scenarios"] == [
        {"scenario_id": s["id"], "six_phases": s["phases"]}
        for s in universe["scenarios"]], "SCENARIO_BINDING")
    need(model.canonical(bundle["evaluations"]["selected"]) ==
         model.canonical(_entry(universe, selection, bundle["assessed_at"])),
         "ASSESSMENT_MISMATCH")
    if "rollover" in value:
        child = checked_forecast(value["rollover"])
        need(child["market"] == "2t" and child["strategy"] == "rollover" and
             child["race_id"] == value["race_id"] and
             child["confidence_universe"] == universe and
             model.when(child["analysis_created_at"]) <= at,
             "ROLLOVER_PARENT_UNIVERSE_MISMATCH")
    return value


def create_files(request, *, clock=None):
    """Prepare all dated existing feed files in memory, using a live clock."""
    need(type(request) is dict and set(request) == {"schema", "races"} and
         request["schema"] == REQUEST_SCHEMA and type(request["races"]) is list and
         0 < len(request["races"]) <= 200, "REQUEST_FIELDS")
    runtime_clock = clock or (lambda: datetime.now(timezone.utc))
    files, seen = {}, set()
    for race in request["races"]:
        need(type(race) is dict and set(race) == {"universe", "selections"} and
             type(race["selections"]) is list and 0 < len(race["selections"]) <= 4,
             "RACE_FIELDS")
        universe = race["universe"]
        need(type(universe) is dict and universe.get("race_id") not in seen,
             "DUPLICATE_RACE")
        seen.add(universe.get("race_id"))
        selections = {}
        for raw in race["selections"]:
            selection = _selection(raw)
            key = (selection["market"], selection["strategy"])
            need(key not in selections, "DUPLICATE_SELECTION")
            selections[key] = selection
        need(("2t", "rollover") not in selections or ("2t", "normal") in selections,
             "TWO_CAR_ROLLOVER_REQUIRES_NORMAL")
        need(("3t", "rollover") not in selections or ("3t", "normal") in selections,
             "THREE_CAR_ROLLOVER_REQUIRES_NORMAL")
        # All markets for a race retain exactly the same parent universe.
        produced = {}
        for key in sorted(selections, key=lambda k: k[1] != "rollover"):
            now = runtime_clock()
            need(isinstance(now, datetime) and now.utcoffset() is not None, "CLOCK")
            produced[key] = create_forecast(
                universe, selections[key], generated_at=now.astimezone(timezone.utc).isoformat(),
                rollover=produced.get(("2t", "rollover")) if key == ("2t", "normal") else None)
        for key, name in [(("3t", "normal"), "forecasts.json"),
                          (("2t", "normal"), "two_car_forecasts.json"),
                          (("3t", "rollover"), "three_car_rollover_forecasts.json")]:
            if key not in produced:
                continue
            rid = produced[key]["race_id"]
            date = f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}"
            files.setdefault(f"data/{date}/{name}", []).append(produced[key])
    sizes = [len(model.canonical(rows)) + 1 for rows in files.values()]
    need(all(size <= MAX_FILE for size in sizes) and sum(sizes) <= MAX_VIEW,
         "EXISTING_FEED_SIZE_LIMIT")
    return files


def private_path(value, *, directory):
    path = Path(value)
    need(path.is_absolute(), "ABSOLUTE_PRIVATE_PATH")
    for parent in (path, *path.parents):
        need(not parent.is_symlink() and not (parent / ".git").exists(),
             "PRIVATE_PATH_OUTSIDE_CHECKOUT")
    need(path.is_dir() if directory else path.is_file(), "PRIVATE_PATH_KIND")
    need(stat.S_IMODE(path.stat().st_mode) == (0o700 if directory else 0o600),
         "PRIVATE_PATH_MODE")
    return path


def write_new_site(request, *, site_root, clock=None):
    """Create an importable private Site-data directory; never overwrite one."""
    root = private_path(site_root, directory=True)
    need(not any(root.iterdir()), "CREATE_ONCE_EMPTY_DIRECTORY")
    runtime_clock = clock or (lambda: datetime.now(timezone.utc))
    files = create_files(request, clock=runtime_clock)
    def check_save_window(rows):
        now = runtime_clock()
        need(isinstance(now, datetime) and now.utcoffset() is not None, "CLOCK")
        for row in rows:
            need(model.when(row["analysis_created_at"]) <= now and
                 (model.when(row["deadline_jst"]) - now).total_seconds() >= 65,
                 "SAVE_WINDOW_EXPIRED")
    # Batch evaluation may consume the original lead time. Read the actual
    # clock again before any output, and again before each individual write.
    check_save_window([row for rows in files.values() for row in rows])
    # No output is written until every record has passed evaluation/validation.
    for relative, rows in files.items():
        check_save_window(rows)
        target = root / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # pathlib's parents use default modes, so explicitly keep each new
        # directory inside this owner-private root private as well.
        (root / "data").chmod(0o700)
        target.parent.chmod(0o700)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(model.canonical(rows) + b"\n")
    return {"files_created": len(files),
            "forecasts_created": sum(len(rows) + sum("rollover" in r for r in rows)
                                     for rows in files.values())}
