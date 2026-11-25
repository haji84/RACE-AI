"""Prepare a private fixed-budget comparison from existing B and a saved 3T board.

Only the conditional third-place mass changes. Callers retain the original
forecast and use the existing independent Git witness and scoring paths.
"""
from collections import defaultdict
from collections.abc import Mapping
from hashlib import sha256
from math import fsum, isfinite
from unicodedata import normalize
import re

from race_ai.keirin_joint_finish import JointFinish, _distribution
from race_ai.keirin_joint_forecast import META, build_forecast, validate_forecast
from race_ai.keirin_nationwide_auto_generator import digest, when
from race_ai.keirin_public_two_source_normalizer import _page
from scripts.keirin_capture_public_two_sources import MAX_BYTES
from scripts.keirin_joint_forward_score import _json, _ranked
from scripts.keirin_note_collect_inputs import JST, _text, verify_trifecta_market


class MarketThirds(JointFinish):
    """Reuse the original conditional fourth-and-later law and exacta mass."""

    def __init__(self, original, odds):
        if not isinstance(original, JointFinish):
            raise ValueError('A verified original JointFinish is required.')
        base = original.trifectas()
        if (not isinstance(odds, Mapping) or set(odds) != set(base)
                or any(type(order) is not tuple or any(type(car) is not int for car in order) for order in odds)
                or any(type(value) not in (int, float) or not 0 < value < 9999.9 or not isfinite(value)
                       for value in odds.values())):
            raise ValueError('A complete numeric market board below the quote cap is required.')

        supported = defaultdict(list)
        for order, probability in base.items():
            if probability > 0:
                supported[order[:2]].append(order)
        self._preserved_exactas = original.exactas()
        adjusted = dict.fromkeys(base, 0.)
        for pair, orders in supported.items():
            smallest = min(odds[order] for order in orders)
            ratios = [smallest / odds[order] for order in orders]
            total = fsum(ratios)
            for order, ratio in zip(orders, ratios, strict=True):
                probability = (ratio / total) * self._preserved_exactas[pair]
                if not probability:
                    raise ValueError('Market reweighting would underflow an original positive outcome.')
                adjusted[order] = probability
        self._cars, self._trifectas = _distribution(original._cars, adjusted)
        # Calling JointFinish.__init__ again would refit the rider inputs to
        # its existing tail coefficients from the new podium probabilities.
        self._score = original._score.copy()
        self._first_two = {car: ranks[:2] for car, ranks in original.marginals().items()}

    def exactas(self):
        return dict(self._preserved_exactas)

    def marginals(self):
        # Accumulation across a reweighted pair can put a deterministic rank
        # a few ulps above one. Keep the original top-two values exactly and
        # bound rounding at one after the parent's row/column checks.
        return {car: tuple(min(1., value) for value in (*self._first_two[car], *ranks[2:]))
                for car, ranks in super().marginals().items()}


def _source_cutoff(soup, cutoff):
    headers = soup.select('div.racecard_header')
    if len(headers) != 1:
        return False
    values = []
    for cell in headers[0].select('dl.time > dt'):
        if normalize('NFKC', _text(cell)) in {'締切', '投票締切'}:
            value = cell.find_next_sibling()
            if value is None or value.name != 'dd':
                return False
            values.append(normalize('NFKC', _text(value)))
    if len(values) != 1 or re.fullmatch(r'[0-9]{1,2}:[0-9]{2}', values[0]) is None:
        return False
    hour, minute = map(int, values[0].split(':'))
    cutoff = cutoff.astimezone(JST)
    return (hour, minute, 0, 0) == (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond)


def prepare_trial(original, joint, *, expected_original_sha256, generated_at,
                  market_raw=None, receipt_raw=None, expected_receipt_sha256=None):
    """Prepare a row for keirin_research_cohort_score and the private joint comparison.

    The forecast digest is the verified record's canonical SHA. An eligible
    board also needs the independently retained byte SHA of the capture receipt.
    A later Git witness establishes the actual pre-cutoff preservation time.
    """
    validate_forecast(original)
    cutoff = when(original['cutoff_at'])
    generated = when(generated_at)
    if (original['scope'] != 'PROSPECTIVE_RESEARCH' or digest(original) != expected_original_sha256
            or not when(original['generated_at']) <= generated < cutoff or len(original['cars']) < 4):
        raise ValueError('An unchanged, earlier prospective original is required.')
    before = _ranked(original, 'trifectas', 8)
    row = dict(race_id=original['race_id'], cutoff_at=original['cutoff_at'],
               starter_cars=original['cars'][:], published=before, trial=[order[:] for order in before])
    packet = dict(row=row, comparison=None, state='MARKET_UNAVAILABLE')
    if market_raw is None and receipt_raw is None:
        return packet

    # Verify the released board from exact source bytes, independently of the
    # legacy display table. Invalid/partial quotes leave the paired row intact.
    try:
        if (type(market_raw) is not bytes or not 0 < len(market_raw) <= MAX_BYTES
                or type(receipt_raw) is not bytes or not 0 < len(receipt_raw) <= 8192
                or sha256(receipt_raw).hexdigest() != expected_receipt_sha256):
            raise ValueError
        receipt = _json(receipt_raw)
        if (type(receipt['status']) is not int or receipt['status'] != 200
                or type(receipt['bytes']) is not int or receipt['bytes'] != len(market_raw)
                or sha256(market_raw).hexdigest() != receipt['bytes_sha256']
                or not when(receipt['captured_at']) <= generated):
            raise ValueError
        soup = _page(market_raw)[3]
        if soup is None or not _source_cutoff(soup, cutoff):
            raise ValueError
        headline = _text(soup.select_one('h1.raceinfo_headline'))
        title = re.match(r'^(.{1,20}?)競輪', headline)
        if title is None:
            raise ValueError
        riders = [dict(number=r['car'], name=r['name']) for r in original['riders']]
        prices, proof = verify_trifecta_market(soup, race_id=original['race_id'], venue=title[1], riders=riders,
                                               receipt=receipt, published_cutoff_at=original['cutoff_at'])
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return dict(packet, state='MARKET_SOURCE_UNVERIFIED')
    if not proof['eligible_full_priority']:
        return dict(packet, state='MARKET_BOARD_INELIGIBLE')

    # Reuse the very same fitted tail object. A serialized V1 record has
    # marginals, but no conditional tail parameters from which to rebuild it.
    metadata = {key: original[key] for key in META}
    identities = original['riders']
    verified_original = build_forecast(joint, **metadata, riders=identities)
    if any(verified_original[key] != original[key] for key in ('trifectas', 'exactas', 'cars', 'riders')):
        raise ValueError('The original fitted joint law does not match the saved forecast.')
    evidence = dict(original_forecast_sha256=expected_original_sha256,
                    capture_receipt_sha256=expected_receipt_sha256, market=proof)
    # The source forecast clocks still identify the original model run. The
    # later market clock is retained in the separate, SHA-bound evidence.
    metadata.update(generated_at=generated_at, input_sha256=digest(evidence))
    try:
        market = MarketThirds(joint, {tuple(map(int, key.split('-'))): price for key, price in prices.items()})
        trial = build_forecast(market, **metadata, riders=identities)
    except (ValueError, ArithmeticError):
        return dict(packet, state='MARKET_REWEIGHTING_UNAVAILABLE')
    row['trial'] = _ranked(trial, 'trifectas', 8)
    return dict(row=row, state='MARKET_THIRD_COMPARISON_READY', comparison=trial, evidence=evidence)
