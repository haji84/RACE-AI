"""Bind *modelled* Open-Meteo weather to an existing private pre-race packet.

This never invents starters/lineup/cutoff. An owner-sourced pre-cutoff race
packet must already exist. Missing weather does not become zero. A forecast
is NOT an observed on-track value or an independent forecast timestamp.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json

from .keirin_open_meteo_weather import SOURCE
from .keirin_result_delivery import canonical, utc

SCHEMA = "RACE_AI_KEIRIN_PERMISSIONED_DELIVERY_V1"
MAPPING = {
    "air_temperature":"air_temperature",
    "humidity":"humidity",
    "rainfall":"rainfall",
    "wind_speed":"wind_speed",
    "wind_direction":"wind_direction",
}


class WeatherMergeError(ValueError):
    pass


def _need(cond, reason):
    if not cond:
        raise WeatherMergeError(reason)


def merge_weather_into_owner_packet(packet, forecast):
    _need(type(packet) is dict and packet.get("schema")==SCHEMA and
          type(packet.get("race")) is dict and
          type(packet.get("observations")) is list,
          "VALID_PRIVATE_RACE_PACKET_REQUIRED")
    _need(type(forecast) is dict and forecast.get("schema")==
          "RACE_AI_KEIRIN_NONCOMMERCIAL_MODELLED_WEATHER_V1" and
          forecast.get("value_kind")==
          "MODELLED_NUMERICAL_GRID_FORECAST_NOT_ON_SITE_MEASUREMENT" and
          forecast.get("source_rights_ref")==SOURCE and
          forecast.get("published_at_independently_verified") is False and
          forecast.get("provider_get_count")==1,
          "MODELLED_WEATHER_PROVENANCE_NOT_VERIFIED")
    race=packet["race"]
    _need(race.get("race_id")==forecast.get("race_id") and
          race.get("official_cutoff_at")==forecast.get("official_cutoff_at"),
          "WEATHER_WRONG_RACE_OR_CUTOFF")
    before=utc(race["as_of"])
    captured=utc(forecast["captured_at"])
    cutoff=utc(race["official_cutoff_at"])
    _need(before<=captured<cutoff,
          "WEATHER_RECEIVED_AFTER_CUTOFF_OR_BEFORE_RACE_SNAPSHOT")
    matches=[o for o in packet["observations"]
             if o.get("key")=="race/start_time"]
    _need(len(matches)==1 and
          matches[0].get("value")==forecast["race_start_at"] and
          utc(matches[0]["captured_at"])<=before,
          "RACE_START_NOT_INDEPENDENTLY_PRESENT_IN_OWNER_INPUT")
    keys={p.get("key") for p in packet["observations"]}
    _need(len(keys)==len(packet["observations"]),
          "DUPLICATED_PREVIOUS_OBSERVATION")
    newkeys={"race/"+k for k in MAPPING}
    _need(not (keys & newkeys),
          "WEATHER_FIELD_ALREADY_EXISTS_NO_IMMUTABLE_OVERWRITE")
    values=forecast["model_inputs"]
    _need(type(values) is dict and set(values)==set(MAPPING),
          "WEATHER_INPUT_SET_MISMATCH")
    # We conservatively set published_at to the FIRST observed/captured
    # timestamp as an upper bound; it is NOT the provider's true issue time.
    stamp=forecast["captured_at"]
    src=forecast["source_url"]
    newer=deepcopy(packet)
    newer["race"]["as_of"]=stamp
    for k in MAPPING:
        newer["observations"].append({
            "key":"race/"+MAPPING[k],
            "value":values[k],
            "source_url":src,
            "rights_ref":SOURCE,
            "published_at":stamp,
            "captured_at":stamp,
            "sample_n":1,
        })
    return {
        "schema":"RACE_AI_KEIRIN_WEATHER_MERGED_PACKET_V1",
        "race_id":race["race_id"],
        "weather_source_sha256":forecast["source_bytes_sha256"],
        "weather_value_kind":forecast["value_kind"],
        "weather_issue_timestamp_independently_verified":False,
        "original_packet_sha256":sha256(canonical(packet)).hexdigest(),
        "merged_packet_sha256":sha256(canonical(newer)).hexdigest(),
        "weather_added_items":len(newkeys),
        "non_weather_critical_items_unchanged":True,
        "packet":newer,
        "official_forecast_created":False,
    }
