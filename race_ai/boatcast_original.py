"""Offline SourceError API for the shared standalone original timing contract."""
from .core import SourceError
from web import original_exhibition_contract as contract

MAX_BYTES=contract.MAX_BYTES
FIELDS=contract.FIELDS
LABELS=contract.LABELS
TOP=contract.TOP


def _call(function,*args,**kwargs):
    try:
        return function(*args,**kwargs)
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,OverflowError) as exc:
        raise SourceError(str(exc)) from exc


def endpoint(race_id,component):
    return _call(contract.endpoint,race_id,component)


def parse_original(raw,companion_raw,**kwargs):
    return _call(contract.parse_original,raw,companion_raw,**kwargs)


def validate_original_observation(value,race,now):
    return _call(contract.validate_original_observation,value,race,now)
