"""Native research coefficients for the existing AUTO, seller and PDCA models.

These adapters only run the existing local kernels. Source and race/time
binding is performed by the shared dispatcher before research admission. No
receipt, provider request, bet, file write or promotion occurs here. Seller
returns its native daily ticket batch and has no probability surrogate.
"""
from datetime import date, datetime
import json
import math
from pathlib import Path
import subprocess

from .autorace_personal_baseline import (
    MODEL_ID as AUTO, RESEARCH_PARAMETER_SPECS as AUTO_SPECS, predict_personal,
)
from research.seller_shadow_v1.model import (
    VERSION as SELLER, RESEARCH_PARAMETER_SPECS as SELLER_SPECS, generate as seller_generate,
)

PDCA = "boat-pdca-lane-shadow-v1"
_MAX_WIRE = 2 * 1024 * 1024


def specs(model_id, sport):
    """Bounded native coefficients, without changing phases or ticket policy."""
    if model_id == AUTO and sport == "autorace":
        return dict(AUTO_SPECS)
    if model_id == SELLER and sport == "boat":
        return dict(SELLER_SPECS)
    if model_id == PDCA and sport == "boat":
        return {"lane_pseudocount": (12., 1., 48.)}
    raise ValueError("unknown specialty model/sport cell")


def validate_parameters(model_id, parameters):
    """Resolve optional native coefficients locally; never change constants."""
    specification = specs(model_id, "autorace" if model_id == AUTO else "boat")
    if type(parameters) is not dict or set(parameters) - set(specification):
        raise ValueError("native research parameter names required")
    resolved = {}
    for name, (default, low, high) in specification.items():
        value = parameters.get(name, default)
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError("finite bounded native research parameters required")
        resolved[name] = float(value)
    return resolved


def _clock(at):
    try:
        clock = at if isinstance(at, datetime) else datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("aware native execution time required") from None
    if clock.utcoffset() is None:
        raise ValueError("aware native execution time required")
    return clock


def _pdca(payload, parameters, clock):
    data = {"facts": payload["facts"], "rows": payload["rows"], "now": clock.isoformat()}
    if parameters is not None:
        data["parameters"] = parameters
    try:
        wire = json.dumps(data, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError):
        raise ValueError("PDCA native input rejected") from None
    if len(wire) > _MAX_WIRE:
        raise ValueError("PDCA bounded input exceeded")
    script = Path(__file__).resolve().parents[1] / "scripts" / "existing_pdca_offline.mjs"
    try:
        process = subprocess.run(["node", str(script)], input=wire, capture_output=True,
                                 timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("PDCA native runtime unavailable") from None
    if process.returncode != 0 or len(process.stdout) > _MAX_WIRE:
        raise ValueError("PDCA native input rejected")
    try:
        report = json.loads(process.stdout)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("PDCA native response invalid") from None
    if type(report) is not dict:
        raise ValueError("PDCA native response invalid")
    if report.get("status") == "PDCA_NOT_ENOUGH_EARLIER_RESULTS":
        raise ValueError("PDCA requires 24 earlier same-venue ordinary results")
    if report.get("status") != "PDCA_CHALLENGER_READY" or type(report.get("candidate")) is not dict:
        raise ValueError("PDCA native response invalid")
    return report["candidate"]


def predict(model_id, payload, parameters=None, *, at, allow_source=None):
    """Return one unchanged native output shape using optional coefficients."""
    specs(model_id, "autorace" if model_id == AUTO else "boat")
    checked = None if parameters is None else validate_parameters(model_id, parameters)
    if type(payload) is not dict:
        raise ValueError("native input mapping required")
    required = (("snapshot",) if model_id == AUTO else ("cards", "waku", "day")
                if model_id == SELLER else ("facts", "rows"))
    if any(not payload.get(field) for field in required):
        raise ValueError("genuine native input missing")
    clock = _clock(at)
    if model_id == AUTO:
        return predict_personal(payload["snapshot"], generated_at=clock.isoformat(), parameters=checked)
    if model_id == SELLER:
        try:
            day = date.fromisoformat(payload["day"])
        except (TypeError, ValueError):
            raise ValueError("native seller day required") from None
        return seller_generate(payload["cards"], payload["waku"], day, clock, parameters=checked)
    return _pdca(payload, checked, clock)


def probability(model_id, payload, parameters, winning, *, at, allow_source=None):
    """Exact native order likelihood for AUTO/PDCA; seller has ticket loss."""
    if model_id == SELLER:
        raise ValueError("seller uses native three/five-ticket selection loss, not probability")
    if (type(winning) not in (list, tuple) or len(winning) != 3
            or any(type(n) is not int for n in winning) or len(set(winning)) != 3):
        raise ValueError("three distinct native winning entrants required")
    output = predict(model_id, payload, parameters, at=at, allow_source=allow_source)
    if model_id == AUTO:
        rows, ticket_key, score_key = output["ranked_relative_weights"], "combination", "relative_weight"
    else:
        rows, ticket_key, score_key = output["all120"], "ticket", "score"
    for row in rows:
        if row[ticket_key] == list(winning):
            return row[score_key]
    raise ValueError("native candidate distribution missing winning order")
