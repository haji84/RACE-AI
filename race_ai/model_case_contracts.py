"""Two reviewed local contracts, never a caller-supplied runtime registry."""
from typing import NamedTuple

LEGACY = 'EXACT8_LEGACY'
MAX8 = 'MAX8_COMPLETE_UNIVERSE'
OLD_PIN = 'ebe93f13062cf0461b81b924a5dc0482ada37b56'
NEW_PIN = 'db075c203704d2b30df5742ce8458a43932696a4'


class Contract(NamedTuple):
    version: int
    schema: str
    pin: str
    cardinality: str
    result_schema: str
    checkpoint_domain: bytes


V1 = Contract(1, 'RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V1', OLD_PIN, LEGACY,
              'RACE_AI_PERMISSIONED_MODEL_CASE_RESULT_V1',
              b'RACE_AI_PERMISSIONED_MODEL_CASE_CHECKPOINT_V1\0')
V2 = Contract(2, 'RACE_AI_PERMISSIONED_MODEL_CASE_REQUEST_V2', NEW_PIN, MAX8,
              'RACE_AI_PERMISSIONED_MODEL_CASE_RESULT_V2',
              b'RACE_AI_PERMISSIONED_MODEL_CASE_CHECKPOINT_V2\0')


def select(schema, pin):
    for value in (V1, V2):
        if type(schema) is str and type(pin) is str and (schema, pin) == (value.schema, value.pin):
            return value
    raise ValueError('fixed model contract rejected') from None


def cardinality(value):
    if type(value) is not str or value not in (LEGACY, MAX8):
        raise ValueError('fixed cardinality contract rejected') from None
    return value
