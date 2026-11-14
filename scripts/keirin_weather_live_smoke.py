"""Opt-in, real noncommercial weather proof for a known future race.

Retrieves only Open-Meteo modeled forecast. It cannot predict trifectas.
Never claims official weather measured at the track or race-card rights.
No persistent racer info, wagering or credential use.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from race_ai.keirin_open_meteo_weather import (
    WeatherSourceError, fetch_one_weather_forecast
)
from race_ai.keirin_result_delivery import canonical, utc


def run_once(*, race_id, latitude, longitude, race_start_at,
             official_cutoff_at, owner_noncommercial):
    captured=datetime.now(timezone.utc).isoformat()
    if utc(captured) >= utc(official_cutoff_at):
        return {
            "schema":"RACE_AI_KEIRIN_WEATHER_PROOF_STATUS_V1",
            "race_id":race_id,
            "state":"SKIPPED_VERIFIED_CUTOFF_ALREADY_PASSED",
            "provider_requests":0,
            "forecast_generated":False,
        }
    evidence=fetch_one_weather_forecast(
        race_id=race_id, latitude=latitude, longitude=longitude,
        race_start_at=race_start_at, official_cutoff_at=official_cutoff_at,
        captured_at=captured, owner_noncommercial=owner_noncommercial)
    return {
        "schema":"RACE_AI_KEIRIN_WEATHER_PROOF_STATUS_V1",
        "race_id":race_id,
        "state":"ONE_REAL_MODELLED_WEATHER_FORECAST_OBSERVED",
        "provider_requests":evidence["provider_get_count"],
        "forecast_generated":False,
        "official_trifecta_forecast_frozen":False,
        "source_sha256":evidence["source_bytes_sha256"],
        "source_attribution":evidence["attribution"],
        "license_url":evidence["license_url"],
        "basis":evidence["value_kind"],
        "captured_at":evidence["captured_at"],
        "forecast_hour_at":evidence["forecast_hour_at"],
        "coordinate_source_checked_by_owner":False,
        "weather_inputs":evidence["model_inputs"],
        "nonweather_race_inputs_available":False,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--race-id",required=True)
    p.add_argument("--latitude",required=True,type=float)
    p.add_argument("--longitude",required=True,type=float)
    p.add_argument("--start-at",required=True)
    p.add_argument("--cutoff-at",required=True)
    p.add_argument("--owner-private-noncommercial",action="store_true")
    p.add_argument("--output",help="optional no-player/public-weather proof JSON")
    args=p.parse_args(argv)
    try:
        output=run_once(
            race_id=args.race_id, latitude=args.latitude,
            longitude=args.longitude, race_start_at=args.start_at,
            official_cutoff_at=args.cutoff_at,
            owner_noncommercial=args.owner_private_noncommercial)
        if args.output:
            path=Path(args.output)
            if path.is_symlink() or path.exists():
                raise ValueError("PROOF_ALREADY_EXISTS")
            data=canonical(output)
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        print(json.dumps(output,ensure_ascii=False,sort_keys=True),flush=True)
        return 0
    except (WeatherSourceError,ValueError,TypeError,OSError,KeyError):
        print('{"state":"WEATHER_NONCOMMERCIAL_SOURCE_UNAVAILABLE_NO_FORECAST"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
