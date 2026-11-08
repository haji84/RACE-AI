"""One bounded, public noncommercial Open-Meteo weather forecast read.

This is a REAL available non-Rakuten weather source, but it is a MODELLED
FORECAST for an hourly grid cell. It is NOT measured at a keirin velodrome,
and it cannot provide riders, lineups, official cutoffs or event outcomes.

Open-Meteo free API: noncommercial/no key, attribution required, data CC BY 4.0.
No automatic betting, commercial use, provider scraping, or forecast output.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
import json
import math

from .keirin_result_delivery import canonical, utc

API = "https://api.open-meteo.com/v1/forecast"
SOURCE = "OPEN_METEO_CC_BY_4_0_NONCOMMERCIAL_FORECAST_V1"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
WEATHER_KEYS = (
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "wind_speed_10m", "wind_direction_10m",
)
OUTPUT_KEYS = {
    "temperature_2m": "air_temperature",
    "relative_humidity_2m": "humidity",
    "precipitation": "rainfall",
    "wind_speed_10m": "wind_speed",
    "wind_direction_10m": "wind_direction",
}
RANGES = {
    "temperature_2m": (-30, 55),
    "relative_humidity_2m": (0, 100),
    "precipitation": (0, 150),
    "wind_speed_10m": (0, 40),
    "wind_direction_10m": (0, 360),
}
UNITS = {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "precipitation": "mm",
    "wind_speed_10m": "m/s",
    "wind_direction_10m": "°",
}
MAX_BODY = 100_000
JST = timezone(timedelta(hours=9))


class WeatherSourceError(ValueError):
    pass


def _need(good, code):
    if not good:
        raise WeatherSourceError(code)


def _time(x):
    _need(type(x) is str, "WEATHER_TIME_MUST_HAVE_OFFSET")
    try:
        d=datetime.fromisoformat(x.replace("Z", "+00:00"))
        _need(d.utcoffset() is not None, "WEATHER_TIME_MUST_HAVE_OFFSET")
        return d.astimezone(timezone.utc)
    except ValueError as exc:
        raise WeatherSourceError("WEATHER_TIME_INVALID") from exc


def request_url(latitude, longitude):
    """Use only pre-verified owner-supplied venue coordinates."""
    for n, low, high in ((latitude,-90,90),(longitude,-180,180)):
        _need(type(n) in (int,float) and math.isfinite(n) and low<=n<=high,
              "VERIFIED_VENUE_COORDINATES_REQUIRED")
    # Do not infer or fabricate a venue's location from its race code.
    q = urlencode({
        "latitude": round(latitude, 5),
        "longitude": round(longitude, 5),
        "hourly": ",".join(WEATHER_KEYS),
        "timezone": "Asia/Tokyo",
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
        "forecast_days": 3,
    })
    return API + "?" + q


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _get_once(url):
    client=build_opener(_NoRedirect(), HTTPSHandler())
    req=Request(url,method="GET",headers={
        "Accept":"application/json",
        "User-Agent":"RACE-AI-private-noncommercial-weather/1",
    })
    with client.open(req,timeout=12) as resp:
        _need(resp.status==200 and
              "application/json" in resp.headers.get("Content-Type","").lower(),
              "WEATHER_PROVIDER_STATUS_OR_MIME_INVALID")
        raw=resp.read(MAX_BODY+1)
    _need(0<len(raw)<=MAX_BODY,"WEATHER_RESPONSE_NOT_BOUNDED")
    return raw


def parse_one_forecast(raw, *, latitude, longitude, race_id,
                       race_start_at, official_cutoff_at, captured_at):
    """Verified schema + provenance, but NO independent publishing timestamp.

    The selected hourly model output describes a time interval around the
    racing start. Never call it observed at the track.
    """
    captured=_time(captured_at)
    start=_time(race_start_at)
    cutoff=_time(official_cutoff_at)
    _need(type(race_id) is str and 8<=len(race_id)<=200,
          "WEATHER_RACE_ID_INVALID")
    _need(captured < cutoff <= start and
          start - captured <= timedelta(days=2, hours=23),
          "WEATHER_ALREADY_AFTER_CUTOFF_OR_OUT_OF_HORIZON")
    _need(type(raw) is bytes and 0<len(raw)<=MAX_BODY,
          "WEATHER_RESPONSE_NOT_BOUNDED")
    try:
        doc=json.loads(raw.decode("utf-8"), parse_constant=lambda x: (
            _ for _ in ()).throw(ValueError("nonfinite")))
    except (UnicodeError,ValueError) as exc:
        raise WeatherSourceError("WEATHER_JSON_INVALID") from exc
    _need(type(doc) is dict and
          doc.get("timezone")=="Asia/Tokyo" and
          type(doc.get("hourly")) is dict and
          type(doc.get("hourly_units")) is dict and
          type(doc.get("latitude")) in (float,int) and
          type(doc.get("longitude")) in (float,int) and
          abs(doc["latitude"]-latitude)<0.15 and
          abs(doc["longitude"]-longitude)<0.15,
          "WEATHER_GRID_OR_TIMEZONE_MISMATCH")
    hours=doc["hourly"]
    stamps=hours.get("time")
    _need(type(stamps) is list and 2<=len(stamps)<=100,
          "WEATHER_HOURLY_TIMES_INVALID")
    times=[]
    for stamp in stamps:
        try:
            # Open-Meteo's local ISO hourly timestamps have no offset.
            t=datetime.fromisoformat(stamp).replace(tzinfo=JST).astimezone(
                timezone.utc)
        except (TypeError,ValueError,AttributeError) as exc:
            raise WeatherSourceError("WEATHER_HOUR_INVALID") from exc
        times.append(t)
    _need(times==sorted(set(times)), "WEATHER_HOURS_DUPLICATE_OR_UNSORTED")
    # Select closest forecast slot; don't pass old measured weather as future.
    options=[(abs((s-start).total_seconds()),i)
             for i,s in enumerate(times) if abs((s-start).total_seconds())<=3600]
    _need(bool(options), "WEATHER_NO_RACE_START_TIME_BIN")
    _,pos=min(options)
    values={}
    for k in WEATHER_KEYS:
        arr=hours.get(k)
        unit=doc["hourly_units"].get(k)
        _need(type(arr) is list and len(arr)==len(times) and
              unit==UNITS[k],"WEATHER_FIELD_OR_UNITS_INVALID")
        v=arr[pos]
        lo,hi=RANGES[k]
        _need(type(v) in (int,float) and math.isfinite(v) and
              lo<=v<=hi, "WEATHER_VALUE_OUTSIDE_MEANINGFUL_RANGE")
        values[OUTPUT_KEYS[k]]=v
    return {
        "schema":"RACE_AI_KEIRIN_NONCOMMERCIAL_MODELLED_WEATHER_V1",
        "race_id":race_id,
        "venue_coordinates_supplied_by_owner":[latitude,longitude],
        "source_url":request_url(latitude,longitude),
        "captured_at":captured_at,
        "race_start_at":race_start_at,
        "official_cutoff_at":official_cutoff_at,
        "forecast_hour_at":times[pos].astimezone(JST).isoformat(),
        "value_kind":"NUMERICAL_GRID_FORECAST_NOT_ON_SITE_MEASUREMENT",
        "published_at_independently_verified":False,
        "source_bytes_sha256":sha256(raw).hexdigest(),
        "model_inputs":values,
        "source_rights_ref":SOURCE,
        "attribution":"Weather data by Open-Meteo.com",
        "license_url":LICENSE,
        "provider_get_count":1,
        "rider_data_present":False,
        "lineup_data_present":False,
        "official_forecast_frozen":False,
    }


def fetch_one_weather_forecast(*, race_id, latitude, longitude,
                              race_start_at, official_cutoff_at,
                              captured_at, owner_noncommercial,
                              fetch=None):
    """One forecast GET; the caller must supply verified race/venue details.

    Production mode never uses a synthetic callback. In tests a mock fetch
    callback proves parser semantics only, not real weather access.
    """
    _need(owner_noncommercial is True,"NONCOMMERCIAL_ONLY_FREE_WEATHER")
    now=_time(captured_at)
    cutoff=_time(official_cutoff_at)
    start=_time(race_start_at)
    _need(now<cutoff<=start and start-now<=timedelta(days=2,hours=23),
          "WEATHER_CUTOFF_TOO_LATE")
    url=request_url(latitude,longitude)
    body=_get_once(url) if fetch is None else fetch(url)
    return parse_one_forecast(
        body,latitude=latitude,longitude=longitude,race_id=race_id,
        race_start_at=race_start_at,official_cutoff_at=official_cutoff_at,
        captured_at=captured_at)
