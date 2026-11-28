"""Aggregate field and token availability in already authenticated official result pages."""

from collections import Counter, defaultdict
from hashlib import sha256
import re
import unicodedata

from race_ai import keirin_official_form_history as form
from race_ai import keirin_official_sp_receipt as receipt


_FIELD = re.compile(r'[A-Za-z][A-Za-z0-9]{0,39}')
_AGARI = re.compile(r'[0-9]{1,3}(?:\.[0-9]{1,2})?')
_RESULT_SCRIPT = re.compile(r'/sp/static/js/SJ0326(?:_[A-Za-z0-9]{1,16})?\.js')
_RESULT_RENDERER = '/sp/static/js/SJ0326_v.js'
_REPORT_SCRIPTS = {'/sp/static/js/SJ0326.js', _RESULT_RENDERER}
_REPORT_FIELDS = {field.lower(): field for field in (
    'syaban', 'tyaku', 'kojinStateItemSubData', 'back',
    's', 'h', 'b', 'sb', 'hb', 'shb', 'sbh', 'sFlg', 'hFlg', 'bFlg',
    'sMark', 'hMark', 'bMark', 'sbMark', 'hbMark', 'shbMark', 'sbhMark',
    'mark', 'markText', 'markerText', 'agari', 'agariTime', 'agariText',
)}


def _marker_tokens(values):
    observed = Counter()
    for value in values:
        if value is None:
            continue
        if type(value) is not str or len(value) > 24:
            return {}
        token = re.sub(r'[\s,/・]+', '', unicodedata.normalize('NFKC', value).upper())
        if token in ('', '-', '―'):
            continue
        if not re.fullmatch('[SHB]{1,3}', token):
            return {}
        observed.update(token)
    return observed if all(count == 1 for count in observed.values()) else {}


def _native_observations(rows):
    # The official result renderer binds the back marker and the official
    # half-lap time directly to these two fields. Other shapes remain unbound.
    leaders, agari_count = [], 0
    back_unrecognized = False
    for row in rows:
        mark = row.get('back')
        if type(mark) is str:
            mark = unicodedata.normalize('NFKC', mark).strip()
        if mark == 'B':
            leaders.append(int(row['syaban']))
        elif mark not in (None, '', '-', '―'):
            back_unrecognized = True
        elapsed = row.get('agari')
        if type(elapsed) is str:
            elapsed = unicodedata.normalize('NFKC', elapsed).strip()
            agari_count += bool(_AGARI.fullmatch(elapsed) and float(elapsed) > 0)
    return (leaders[0] if len(leaders) == 1 and not back_unrecognized else None), agari_count


class OfficialPhaseFieldAudit:
    """Record aggregate source-shape evidence for verifying official phase field bindings."""

    def __init__(self):
        self._verified = self._unverified = 0
        self._fields = Counter()
        self._scripts = Counter()
        self._tokens = defaultdict(Counter)
        self._unlisted_fields = self._unlisted_scripts = 0
        self._unlisted_tokens = Counter()
        self._back_races = self._agari_races = self._agari_riders = 0

    def add(self, raw, final):
        try:
            if type(raw) is not bytes or sha256(raw).hexdigest() != final['source_sha256']:
                raise ValueError('RESULT_SOURCE_DIGEST')
            document = form._document(raw)
            result = receipt._embedded(document)['SJ0326']
            rows = result['tyakujyunItemSubData']
            expected = {str(row['car']): row['registration_id'] for row in final['starters']}
            if (type(result['resultCd']) is not int or result['resultCd'] != 0 or
                    type(rows) is not list or len(rows) != len(expected) or
                    not expected or {row['syaban']: row['sensyuRegistNo'] for row in rows} != expected):
                raise ValueError('RESULT_SOURCE_ROSTER')
            names = set().union(*(row.keys() for row in rows))
            fields, tokens, unlisted_tokens = set(), defaultdict(set), set()
            for name in names:
                if not _FIELD.fullmatch(name):
                    continue
                key = _REPORT_FIELDS.get(name.lower())
                marks = _marker_tokens(row.get(name) for row in rows)
                if key is None:
                    unlisted_tokens.update(marks)
                else:
                    fields.add(key)
                    tokens[key].update(marks)
            scripts = {node.attrs['src'] for node in document.nodes if node.tag == 'script' and
                       _RESULT_SCRIPT.fullmatch(node.attrs.get('src') or '')}
            back_car, agari_riders = _native_observations(rows) if _RESULT_RENDERER in scripts else (None, 0)
        except (KeyError, TypeError, ValueError):
            self._unverified += 1
            return

        self._verified += 1
        self._fields.update(fields)
        self._scripts.update(scripts & _REPORT_SCRIPTS)
        self._unlisted_scripts += bool(scripts - _REPORT_SCRIPTS)
        self._unlisted_fields += any(name.lower() not in _REPORT_FIELDS for name in names)
        self._unlisted_tokens.update(unlisted_tokens)
        for key, marks in tokens.items():
            if marks:
                self._tokens[key].update(marks)
        self._back_races += back_car is not None
        self._agari_races += agari_riders > 0
        self._agari_riders += agari_riders
        return back_car

    def report(self):
        return dict(schema='DT_R1_OFFICIAL_PHASE_FIELD_AUDIT_V2',
                    phase_semantics_verified=False,
                    native_observations=dict(source_binding='JKA_SJ0326_BACK_AND_AGARI',
                                             back_leader_races=self._back_races,
                                             agari_timed_races=self._agari_races, agari_timed_riders=self._agari_riders),
                    verified_result_shapes=self._verified, unverified_result_shapes=self._unverified,
                    row_fields=dict(self._fields), races_with_unlisted_fields=self._unlisted_fields,
                    marker_token_fields={key: dict(tokens) for key, tokens in self._tokens.items()},
                    unlisted_marker_token_races=dict(self._unlisted_tokens),
                    result_view_scripts=dict(self._scripts), races_with_unlisted_result_scripts=self._unlisted_scripts)
