"""Private one-real-weather-source staging, at most 1 Open-Meteo GET/tick.

Only future race packets already in a trusted owner-private inbox qualify.
Owner-supplied venue coordinates and race start/cutoff are indispensable.
This stores a modeled grid forecast, never measured on-track weather.
"""
from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path

from .keirin_open_meteo_weather import fetch_one_weather_forecast
from .keirin_weather_merge import merge_weather_into_owner_packet
from .keirin_permissioned_owner import _write_private_once
from .keirin_result_delivery import canonical, utc

VENUES_SCHEMA = "RACE_AI_KEIRIN_OWNER_VERIFIED_VENUE_GRID_V1"
MAX_RAW = 200


class WeatherStageError(ValueError):
    pass


def _need(test, reason):
    if not test:
        raise WeatherStageError(reason)


def _read_json(path, max_bytes):
    p=Path(path).expanduser()
    _need(p.is_absolute() and p.is_file() and not p.is_symlink() and
          0<p.stat().st_size<=max_bytes, "TRUSTED_PRIVATE_JSON_REQUIRED")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError,UnicodeError,ValueError) as exc:
        raise WeatherStageError("OWNER_JSON_INVALID") from exc


def _load_coords(path):
    value=_read_json(path,20_000)
    _need(type(value) is dict and set(value)=={"schema","locations"} and
          value["schema"]==VENUES_SCHEMA and
          type(value["locations"]) is list and
          1<=len(value["locations"])<=45,
          "OWNER_VENUE_LOCATIONS_MISSING")
    found={}
    for row in value["locations"]:
        _need(type(row) is dict and set(row)=={
            "venue","latitude","longitude","location_scope",
            "location_source_url"
        } and type(row["venue"]) is str and
              1<=len(row["venue"])<=120 and
              row["venue"] not in found and
              row["location_scope"] in (
                "TRACK_CENTER_EXTERNALLY_VERIFIED",
                "NEARBY_PARK_COORDINATES_APPROX_ONLY"
              ) and type(row["location_source_url"]) is str and
              row["location_source_url"].startswith("https://"),
              "COORDINATE_SOURCE_NOT_DOCUMENTED")
        found[row["venue"]]=row
    return found


def _has_weather(packet):
    return any(item.get("key") in {
        "race/wind_speed", "race/wind_direction", "race/rainfall",
        "race/air_temperature", "race/humidity"
    } for item in packet["observations"])


def stage_one_free_weather(inbox, coords_config, *, now, fetch=None):
    """Never retry a previously saved race's weather and never post deadline.

    The actual GET uses the free noncommercial API only. Tests inject a mock
    fetch(url) function and verify no external network use.
    """
    root=Path(inbox).expanduser()
    _need(root.is_absolute() and root.is_dir() and not root.is_symlink(),
          "OWNER_PRIVATE_INBOX_REQUIRED")
    locations=_load_coords(coords_config)
    raw=root/"raw"
    _need(raw.is_dir() and not raw.is_symlink(),"PRIVATE_RAW_INBOX_REQUIRED")
    source_files=sorted(raw.glob("*.json"))
    _need(len(source_files)<=MAX_RAW,"PRIVATE_SOURCE_BATCH_TOO_LARGE")
    weather=root/"weather"
    weather.mkdir(mode=0o700,exist_ok=True)
    _need(weather.is_dir() and not weather.is_symlink(),
          "PRIVATE_WEATHER_FOLDER_REQUIRED")
    t=utc(now)
    result={
        "schema":"RACE_AI_KEIRIN_WEATHER_ONE_PER_RACE_STAGE_V1",
        "eligible":0,"weather_packets_created":0,
        "skipped_missing_race_or_venue_info":0,
        "already_captured":0,"failed_and_not_substituted":0,
        "provider_get_requests":0,"official_forecasts_frozen":0,
        "only_modelled_weather":True
    }
    # One location/race per invocation, sorted by earliest official cutoff.
    candidates=[]
    for path in source_files:
        try:
            pack=_read_json(path,2_000_000)
            if (type(pack) is not dict or
                pack.get("schema")!="RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1" or
                type(pack.get("race")) is not dict or
                type(pack.get("observations")) is not list or _has_weather(pack)):
                continue
            race=pack["race"]
            if race.get("venue") not in locations:
                result["skipped_missing_race_or_venue_info"]+=1
                continue
            cutoff=utc(race["official_cutoff_at"])
            src=utc(race["as_of"])
            if not src<=t<cutoff-timedelta(seconds=65):
                continue
            starts=[o["value"] for o in pack["observations"]
                    if o.get("key")=="race/start_time"]
            if len(starts)!=1:
                result["skipped_missing_race_or_venue_info"]+=1
                continue
            start=utc(starts[0])
            if not cutoff<=start<=t+timedelta(days=2,hours=23):
                continue
            rid=race["race_id"]
            if (weather/(sha256(rid.encode()).hexdigest()+".json")).exists():
                result["already_captured"]+=1
                continue
            candidates.append((cutoff,rid,start,pack,locations[race["venue"]]))
        except (OSError,ValueError,KeyError,TypeError):
            result["skipped_missing_race_or_venue_info"]+=1
    result["eligible"]=len(candidates)
    if not candidates:
        return result
    cutoff,rid,start,pack,loc=min(candidates,key=lambda x:(x[0],x[1]))
    key=sha256(rid.encode()).hexdigest()
    try:
        response=fetch_one_weather_forecast(
            race_id=rid, latitude=loc["latitude"],
            longitude=loc["longitude"],
            race_start_at=start.isoformat(),
            official_cutoff_at=cutoff.isoformat(),
            captured_at=t.isoformat(),
            owner_noncommercial=True,fetch=fetch)
        merged=merge_weather_into_owner_packet(pack,response)
        # Immutable private weather evidence stores the full basis and SHA.
        # Coordinate verification is only owner-provided, NOT independent.
        event={**response,
               "venue_coordinate_source":loc["location_source_url"],
               "venue_location_scope":loc["location_scope"]}
        _write_private_once(weather/(key+".json"),event)
        _write_private_once(raw/(merged["merged_packet_sha256"]+".json"),
                            merged["packet"])
        result["weather_packets_created"]=1
        result["provider_get_requests"]=0 if fetch is not None else 1
    except (OSError,ValueError,KeyError,TypeError):
        result["failed_and_not_substituted"]=1
    return result
