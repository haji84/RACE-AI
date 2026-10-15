"""Private immutable postclose labels scoped to one finalized forecast."""
from datetime import datetime, timezone
import re

from api.race_store import REVIEW, JST, canonical, decode, instant, checked_race_id
from api.name_bound_exhibition_store import bounded_read, put, request_identifier, read_name_bound_exhibition
from name_bound_prediction import validate_name_bound_envelope
from name_bound_result import (MAX_BYTES, digest, result_context, validate_name_bound_result,
    validate_name_bound_result_envelope)

REQUEST = set('publication_review race_id request_id forecast_request_id snapshot runner_saved_at'.split())
MANIFEST = set('schema_version race_id forecast_request_id request_id snapshot_id published_at'.split())


def require(value):
    if not value:
        raise ValueError('NAME_BOUND_RESULT_STORE_INVALID')


def packet_key(race_id, snapshot_id):
    require(isinstance(snapshot_id, str) and re.fullmatch('[0-9a-f]{64}', snapshot_id) is not None)
    return f'race-ai/name-bound-result-packets/{race_id}/{snapshot_id}.json'


def receipt_key(race_id, forecast_id, request_id):
    return f'race-ai/name-bound-result-receipts/{race_id}/{request_identifier(forecast_id)}/{request_identifier(request_id)}.json'


def finalization_key(race_id, forecast_id, request_id):
    return f'race-ai/name-bound-result-finalizations/{race_id}/{request_identifier(forecast_id)}/{request_identifier(request_id)}.json'


def manifest_key(race_id, forecast_id):
    return f'race-ai/name-bound-result-latest/{race_id}/{request_identifier(forecast_id)}.json'


def read_value(client, key):
    raw = bounded_read(client, key)
    if raw is None:
        return None
    value = decode(raw)
    require(value is not None and raw == canonical(value))
    return value


def _read_pinned(race, forecast, identifier, client, now):
    rid = race['race_id']; fid = forecast['receipt']['request_id']
    receipt = read_value(client, receipt_key(rid, fid, identifier))
    marker = read_value(client, finalization_key(rid, fid, identifier))
    if receipt is None:
        require(marker is None)
        return None
    require(marker is not None and isinstance(receipt, dict) and receipt.get('request_id') == identifier)
    packet = receipt['snapshot']
    require(bounded_read(client, packet_key(rid, packet['snapshot_id'])) == canonical(packet))
    return validate_name_bound_result_envelope(dict(receipt=receipt, finalization=marker), race, forecast, now=now)


def read_name_bound_result(race, forecast, *, client, now, request_id=None):
    now = instant(now); checked_race_id(race['race_id'], now)
    forecast = validate_name_bound_envelope(forecast, race, now=now)
    fid = request_identifier(forecast['receipt']['request_id'])
    if request_id is not None:
        return _read_pinned(race, forecast, request_identifier(request_id), client, now)
    latest = read_value(client, manifest_key(race['race_id'], fid))
    # Absence remains valid before close for legacy evaluation callers.
    if latest is None:
        return None
    require(isinstance(latest, dict) and set(latest) == MANIFEST
        and type(latest['schema_version']) is int and latest['schema_version'] == 1
        and latest['race_id'] == race['race_id'] and latest['forecast_request_id'] == fid)
    envelope = _read_pinned(race, forecast, request_identifier(latest['request_id']), client, now)
    require(envelope is not None)
    receipt = envelope['receipt']; published = instant(latest['published_at'])
    expected = dict(schema_version=1, race_id=race['race_id'], forecast_request_id=fid,
        request_id=receipt['request_id'], snapshot_id=receipt['snapshot']['snapshot_id'], published_at=latest['published_at'])
    require(canonical(latest) == canonical(expected) and latest['published_at'] == published.isoformat(timespec='microseconds')
        and instant(envelope['finalization']['receipt_confirmed_at']) <= published <= now
        and published.astimezone(JST).date() == now.astimezone(JST).date())
    return envelope


def position(envelope):
    receipt = envelope['receipt']; packet = receipt['snapshot']
    return (instant(packet['result_record']['captured_at']), instant(packet['generated_at']),
        instant(receipt['cloud_saved_at']), receipt['request_id'])


def metadata(envelope, race):
    receipt = envelope['receipt']
    return dict(status='verified', race_id=race['race_id'], request_id=receipt['request_id'],
        forecast_request_id=receipt['forecast_request_id'], snapshot_id=receipt['snapshot']['snapshot_id'],
        cloud_saved_at=receipt['cloud_saved_at'], receipt_confirmed_at=envelope['finalization']['receipt_confirmed_at'],
        sha256=digest(envelope), research_only=True, validation_status='UNVALIDATED',
        purchase_decision='skip', purchase_recommendations=[])


class _PublicationIO:
    """Check the real clock on both sides of every parent/store operation."""
    def __init__(self, client, tick):
        self.client, self.tick = client, tick

    def get(self, *args, **kwargs):
        self.tick()
        try:
            return self.client.get(*args, **kwargs)
        finally:
            self.tick()

    def put(self, *args, **kwargs):
        self.tick()
        try:
            return self.client.put(*args, **kwargs)
        finally:
            self.tick()


def publish_name_bound_result(request, race, *, client, now, clock=None):
    now = instant(now); rid = checked_race_id(race['race_id'], now)
    closed = instant(race['closed_at']); day = now.astimezone(JST).date()
    require(now >= closed and isinstance(request, dict) and set(request) == REQUEST
        and len(canonical(request)) <= MAX_BYTES and request['publication_review'] == REVIEW
        and request['race_id'] == rid)
    identifier = request_identifier(request['request_id']); fid = request_identifier(request['forecast_request_id'])
    clock = clock or (lambda:datetime.now(timezone.utc))
    last = now
    def tick():
        nonlocal last
        measured = instant(clock())
        require(closed <= last <= measured and measured.astimezone(JST).date() == day)
        last = measured
        return measured
    io = _PublicationIO(client, tick)
    forecast = read_name_bound_exhibition(race, client=io, now=tick(), request_id=fid)
    require(forecast is not None)
    result_context(race, forecast, tick())
    packet = validate_name_bound_result(request['snapshot'], race, forecast, now=tick())
    runner = instant(request['runner_saved_at'])
    require(request['runner_saved_at'] == runner.isoformat(timespec='microseconds')
        and instant(packet['generated_at']) <= runner <= tick() and runner.astimezone(JST).date() == day)
    receipt_path = receipt_key(rid, fid, identifier); marker_path = finalization_key(rid, fid, identifier)
    existing = bounded_read(io, receipt_path)
    if existing is not None:
        envelope = read_name_bound_result(race, forecast, client=io, now=tick(), request_id=identifier)
        require(envelope is not None and canonical(envelope['receipt']['snapshot']) == canonical(packet)
            and envelope['receipt']['runner_saved_at'] == request['runner_saved_at']
            and envelope['receipt']['forecast_request_id'] == fid)
        require(read_name_bound_result(race, forecast, client=io, now=tick()) is not None)
        validate_name_bound_result_envelope(envelope, race, forecast, now=tick())
        return metadata(envelope, race)
    require(bounded_read(io, marker_path) is None)
    packet_path = packet_key(rid, packet['snapshot_id'])
    require(bounded_read(io, packet_path) is None)
    previous = read_name_bound_result(race, forecast, client=io, now=tick())
    put(io, packet_path, packet)
    saved = tick()
    receipt = dict(schema_version=1, request_id=identifier, forecast_request_id=fid, snapshot=packet,
        runner_saved_at=request['runner_saved_at'], cloud_saved_at=saved.isoformat(timespec='microseconds'),
        cloud_eligible_pre_race=False)
    put(io, receipt_path, receipt)
    confirmed = tick()
    marker = dict(schema_version=1, race_id=rid, request_id=identifier, forecast_request_id=fid,
        snapshot_id=packet['snapshot_id'], receipt_sha256=digest(receipt),
        receipt_confirmed_at=confirmed.isoformat(timespec='microseconds'))
    envelope = validate_name_bound_result_envelope(dict(receipt=receipt, finalization=marker), race, forecast, now=confirmed)
    put(io, marker_path, marker)
    if previous is None or position(envelope) > position(previous):
        published = tick()
        latest = dict(schema_version=1, race_id=rid, forecast_request_id=fid, request_id=identifier,
            snapshot_id=packet['snapshot_id'], published_at=published.isoformat(timespec='microseconds'))
        put(io, manifest_key(rid, fid), latest, overwrite=True)
    served = read_name_bound_result(race, forecast, client=io, now=tick(), request_id=identifier)
    validate_name_bound_result_envelope(served, race, forecast, now=tick())
    return metadata(served, race)
