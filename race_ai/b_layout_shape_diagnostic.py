"""Aggregate-only, read-only shape diagnostics for an extracted official B file.

Never return or log entrant identities, rows, dates or source excerpts.
This is not a successful parse, official provenance, or usage permission.
"""
from __future__ import annotations
import re
import unicodedata

MAX_TEXT_BYTES = 4_000_000
_HEADER = re.compile(r'^\s*(\d{1,2})R\s+.*?H\s*\d{3,4}m', re.I)
_CUTOFF = re.compile(r'電話投票締切予定\s*((?:[01]\d|2[0-3]):[0-5]\d)\s*$')
_ENTRY = re.compile(r'^\s*[1-6]\s+\d{4}(?!\d)')
# Pinned PR64 27f3df1: diagnostic mirror only, never parser fallback.
_DETAILS = re.compile(
    r'^\s*([1-6])\s+(\d{4})(.+?)(\d{2})(\D{2})(\d{2})([AB][12])\s+'
    r'(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+(\d+\.\d{2})\s+'
    r'(\d+)\s+(\d+\.\d{2})\s*(\d+)\s+(\d+\.\d{2})(?:\s|$)'
)
_BLOCK = re.compile(r'^\s*\d{1,2}BBGN\s*$', re.M)
_END = re.compile(r'^\s*(?:\d{1,2})?BEND\s*$', re.M)


_PREFIX = re.compile(r'^\s*[1-6]\s+\d{4}.+?\d{2}\D{2}\d{2}[AB][12]\s+')
_BRANCH3 = re.compile(_DETAILS.pattern.replace(r'(\D{2})(\d{2})([AB][12])', r'(\D{3})(\d{2})([AB][12])'))
_BRANCH4 = re.compile(_DETAILS.pattern.replace(r'(\D{2})(\d{2})([AB][12])', r'(\D{4})(\d{2})([AB][12])'))
_WIDER_DECIMAL = re.compile(_DETAILS.pattern.replace(r'\d+\.\d{2}', r'(?:\d+\.\d{1,3}|--|---)'))


def summarize_b_layout(raw: bytes) -> dict:
    """Return only aggregate structural counts, not source content."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_TEXT_BYTES:
        raise ValueError('bounded extracted B bytes required')
    try:
        data = unicodedata.normalize('NFKC', raw.decode('cp932'))
    except UnicodeError as exc:
        raise ValueError('CP932 decoding failed') from exc
    counts = {
        'venue_blocks': 0,
        'recognized_race_headers': 0,
        'headers_without_same_line_cutoff': 0,
        'entry_like_rows': 0,
        'entry_like_rows_before_header': 0,
        'strict_detail_regex_matches': 0,
        'strict_detail_regex_mismatches_after_header': 0,
        'mismatches_with_strict_demographics_prefix': 0,
        'mismatches_accepting_3_char_branch': 0,
        'mismatches_accepting_4_char_branch': 0,
        'mismatches_accepting_variable_decimal_fields': 0,
        'mismatches_with_fewer_than_6_decimal_tokens': 0,
        'mismatches_with_dash_placeholders': 0,
    }
    # Each suffix contains numeric/statistical fields only after validated
    # identity/grade prefix. Mask all digits; unknown text becomes "OTHER".
    numeric_suffix_shapes = {}
    for mark in _BLOCK.finditer(data):
        close = _END.search(data, mark.end())
        if close is None:
            raise ValueError('B block has no end')
        counts['venue_blocks'] += 1
        seen_header = False
        for line in data[mark.end():close.start()].splitlines():
            if _HEADER.match(line):
                seen_header = True
                counts['recognized_race_headers'] += 1
                if not _CUTOFF.search(line):
                    counts['headers_without_same_line_cutoff'] += 1
                continue
            if _ENTRY.match(line):
                counts['entry_like_rows'] += 1
                if not seen_header:
                    counts['entry_like_rows_before_header'] += 1
                elif _DETAILS.match(line):
                    counts['strict_detail_regex_matches'] += 1
                else:
                    counts['strict_detail_regex_mismatches_after_header'] += 1
                    counts['mismatches_with_strict_demographics_prefix'] += int(bool(_PREFIX.match(line)))
                    prefix = _PREFIX.match(line)
                    if prefix:
                        shapes = []
                        for token in line[prefix.end():].strip().split():
                            if re.fullmatch(r'[0-9.-]+', token):
                                shapes.append(re.sub(r'\d', '#', token))
                            else:
                                shapes.append('OTHER')
                        key = ' '.join(shapes[:12]) if len(shapes) <= 12 else 'TOO_MANY_TOKENS'
                        numeric_suffix_shapes[key] = numeric_suffix_shapes.get(key, 0) + 1
                    counts['mismatches_accepting_3_char_branch'] += int(bool(_BRANCH3.match(line)))
                    counts['mismatches_accepting_4_char_branch'] += int(bool(_BRANCH4.match(line)))
                    counts['mismatches_accepting_variable_decimal_fields'] += int(bool(_WIDER_DECIMAL.match(line)))
                    counts['mismatches_with_fewer_than_6_decimal_tokens'] += int(
                        len(re.findall(r'\d+\.\d+', line)) < 6
                    )
                    counts['mismatches_with_dash_placeholders'] += int(
                        bool(re.search(r'(?<!\S)-{2,}(?!\S)', line))
                    )
    if counts['entry_like_rows_before_header']:
        classification = 'POSSIBLE_ENTRY_BEFORE_HEADER'
    elif counts['strict_detail_regex_mismatches_after_header']:
        classification = 'DETAIL_ROW_PATTERN_MISMATCH_DETECTED'
    elif counts['headers_without_same_line_cutoff']:
        classification = 'HEADER_CUTOFF_LAYOUT_DIFFERS'
    else:
        classification = 'NOT_IDENTIFIED_BY_AGGREGATE_SHAPE'
    return {
        'schema': 'RACE_AI_OFFICIAL_B_REDACTED_SHAPE_DIAGNOSTIC_V1',
        'scope': 'SYNTAX_DIAGNOSTIC_ONLY_NOT_REAL_PARSE_PASS',
        'counts': counts,
        'masked_numeric_suffix_shapes': numeric_suffix_shapes,
        'classification': classification,
        'raw_text_retained': False,
        'individual_rows_or_races_exposed': False,
    }
