"""Test-only public aggregate assertion; no I/O or production code imports."""
import json
import re
from types import MappingProxyType

FORBIDDEN = ('top8', 'ranked', 'racername', '4001', '20300401-01-01', '架空', 'per_forecast')
FORMATS = MappingProxyType({'hex40': re.compile('[a-f0-9]{40}'),
    'hex64': re.compile('[a-f0-9]{64}'), 'sha256-prefixed': re.compile('sha256:[a-f0-9]{64}')})
# These exact paths are emitted by the pinned reconcile/readback producers.
# None in a path denotes an actual list index, never a dictionary key.
ROOT40 = ('source_sha', 'vault_commit', 'receipt_commit', 'receipt_blob_sha',
          'display_name_runtime_commit', 'results_feed_source_commit', 'results_source_commit', 'feed_commit')
ROOT64 = ('json_sha256', 'zip_sha256', 'cipher_sha256', 'inner_zip_sha256', 'metadata_sha256',
          'receipt_json_sha256', 'display_name_registry_source_sha256', 'native_evaluation_sha256',
          'retained_capture_set_sha256', 'native_result_observation_sha256',
          'results_feed_source_cipher_sha256', 'results_cipher_sha256', 'feed_cipher_sha256',
          'original_document_set_sha256')
P164 = ('zip_sha256', 'cipher_sha256', 'inner_zip_sha256', 'metadata_sha256',
        'json_sha256', 'forecast_binding_sha256')
RECONCILE_HASH_FIELDS = MappingProxyType({
    **{(name,): 'hex40' for name in ROOT40}, **{(name,): 'hex64' for name in ROOT64},
    ('model_score_counts', None, 'model_id_sha256'): 'hex64',
    ('p1_readback', 'source_sha'): 'hex40', ('p1_readback', 'vault_commit'): 'hex40',
    ('p1_readback', 'forecast_binding_sha256'): 'hex64',
    **{('p1_readback', 'artifacts', None, name): 'hex64' for name in P164},
})
NULLABLE = frozenset((('display_name_registry_source_sha256',),
    ('results_feed_source_cipher_sha256',), ('p1_readback', 'artifacts', None, 'json_sha256')))


def assert_public_report(report, *, hash_fields=None):
    """Scan every ordinary key/value; exempt only explicit path/type/format matches.

    A caller must supply reviewed schema paths. The reconcile default contains
    no prefixed-digest paths because that producer currently emits none.
    Failure messages deliberately contain neither the report nor private text.
    """
    if type(report) is not dict:
        raise AssertionError('PUBLIC_REPORT_SCHEMA_INVALID')
    fields = {} if hash_fields is None else hash_fields
    nodes = 0
    def walk(value, path=(), depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 64 or nodes > 20000:
            raise AssertionError('PUBLIC_REPORT_BOUND_EXCEEDED')
        normalized = tuple(None if type(item) is int else item for item in path)
        kind = fields.get(normalized)
        if kind is not None:
            if value is None and normalized in NULLABLE:
                return None
            if kind not in FORMATS:
                raise AssertionError('PUBLIC_REPORT_HASH_POLICY_INVALID')
            if type(value) is not str or FORMATS[kind].fullmatch(value) is None:
                raise AssertionError('PUBLIC_REPORT_HASH_FORMAT_INVALID')
            return '<HASH_FIELD>'
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise AssertionError('PUBLIC_REPORT_SCHEMA_INVALID')
            return {key: walk(item, path + (key,), depth + 1) for key, item in value.items()}
        if type(value) is list:
            return [walk(item, path + (index,), depth + 1) for index, item in enumerate(value)]
        if value is not None and type(value) not in (str, int, float, bool):
            raise AssertionError('PUBLIC_REPORT_SCHEMA_INVALID')
        return value
    try:
        public = json.dumps(walk(report), ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError, RecursionError):
        raise AssertionError('PUBLIC_REPORT_SCHEMA_INVALID') from None
    if len(public.encode('utf-8')) > 1024 * 1024:
        raise AssertionError('PUBLIC_REPORT_BOUND_EXCEEDED')
    if any(token in public for token in FORBIDDEN):
        raise AssertionError('PUBLIC_REPORT_PRIVATE_TOKEN')


def assert_public_reconcile_report(report):
    assert_public_report(report, hash_fields=RECONCILE_HASH_FIELDS)
