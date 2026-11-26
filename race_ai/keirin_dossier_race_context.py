"""Project public rider context from already admitted official SP receipts.

The caller supplies the result of the existing encrypted replay and independent
origin check. This module does not collect source data or reproduce forecast
weights, raw statements, request tokens or full source documents.
"""
from collections import Counter
from datetime import date
from html import unescape
from math import isfinite
import re
from unicodedata import normalize

from . import keirin_github_origin_evidence as origin
from . import keirin_nationwide_auto_generator as model
from . import keirin_official_canary_card as marks
from . import keirin_official_form_history as form
from . import keirin_official_nationwide_extension as extension


SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_DOSSIER_CONTEXT_V1'
STARTERS_SCHEMA = 'RACE_AI_KEIRIN_PUBLIC_STARTERS_V1'
REGISTRATION = re.compile(r'[0-9]{6}')
SHA = re.compile(r'[a-f0-9]{64}')
RACE_ID = re.compile(r'20[0-9]{10}')
MAX_RACES = 600
MAX_RECENT = 7
STAT_FIELDS = {
    'backCnt': 'back_count',
    'nigeCnt': 'escape_count',
    'makuriCnt': 'makuri_count',
    'sasiCnt': 'difference_count',
    'markCnt': 'mark_count',
}
COMMENT_SUMMARIES = {
    'SELF_POWER': '自分で仕掛ける方針。',
    'SELF_POWER_FLEXIBLE': '自分で動き、展開に応じて位置を選ぶ方針。',
    'FLEXIBLE': '展開に応じて走り方を選ぶ方針。',
    'SOLO': 'ラインを組まずに走る方針。',
    'FORWARD': '前方の位置を取りにいく方針。',
    'LEADING': '先頭を取る走りを考えている。',
    'POSITION_OPEN': '取れた位置から走る方針。',
    'FOLLOW': '指定した選手の後ろで走る方針。',
}
_PHRASES = {
    'SELF_POWER': ('自力', '自力で', '自力勝負', '自力基本', '自力基本で', '基本自力', '基本は自力', '自力で頑張る'),
    'SELF_POWER_FLEXIBLE': ('自力自在', '自力自在に', '自力自在で', '自在に自力'),
    'FLEXIBLE': ('自在', '自在に', '自在で', '流れを見て', '流れを見ながら'),
    'SOLO': ('単騎', '単騎で', '単騎で走る', '単騎でやる', '一人で'),
    'FORWARD': ('前々', '前々に', '前々へ', '前々で', '前々から'),
    'LEADING': ('先行したい', '先行で', '先行基本', '先行主体', '先行勝負'),
    'POSITION_OPEN': ('位置を決めず', '決めずに', '取れた位置から', '位置は決めずに'),
}


class ContextHold(ValueError):
    """A fixed rejection code without private source material."""


def _need(ok, code):
    if not ok:
        raise ContextHold('PUBLIC_DOSSIER_CONTEXT_' + code)


def _aware(value):
    return form._aware(value)


def _day(value):
    try:
        parsed = date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ContextHold('PUBLIC_DOSSIER_CONTEXT_DAY') from None
    _need(parsed == value, 'DAY')
    return parsed


def _race_day(race_id):
    _need(type(race_id) is str and RACE_ID.fullmatch(race_id) and
          1 <= int(race_id[-2:]) <= 12, 'RACE_ID')
    return _day(race_id[:4] + '-' + race_id[4:6] + '-' + race_id[6:8])


def _identity(rows, car_field, registration_field):
    _need(type(rows) is list and 1 <= len(rows) <= 9, 'ROSTER')
    pairs = {}
    for row in rows:
        car, registration = row[car_field], row[registration_field]
        _need(type(car) is int and 1 <= car <= 9 and car not in pairs and
              type(registration) is str and REGISTRATION.fullmatch(registration) and
              registration != '000000', 'IDENTITY')
        pairs[car] = registration
    _need(len(set(pairs.values())) == len(pairs), 'IDENTITY')
    return pairs


def _count(value):
    if value in ('', '-', '--'):
        return None
    _need(type(value) is str and re.fullmatch(r'[0-9]{1,3}', value) and
          int(value) <= 200, 'CARD_STATISTIC')
    return int(value)


def _public_comment(raw, rider, roster):
    if not raw:
        return {'state': 'NOT_PUBLISHED'}
    cleaned = normalize('NFKC', unescape(raw)).strip()
    if not cleaned or cleaned in {'-', '--', '―', '—', 'なし'}:
        return {'state': 'NOT_PUBLISHED'}
    sentence = re.split('[。!！?？\\r\\n]', cleaned, maxsplit=1)[0]
    sentence = re.sub(r'\s+', '', sentence)
    for code, variants in _PHRASES.items():
        if sentence in variants:
            return {'state': 'SUMMARIZED', 'code': code, 'summary': COMMENT_SUMMARIES[code]}
    followed = re.fullmatch(r'(.+?)(?:さん|君|選手)(?:へ|に付く|に任せる|の後ろ|マーク)?', sentence)
    if followed:
        target = followed[1]
        candidates = []
        for other in roster:
            name = normalize('NFKC', other['name']).split()
            if name and (target == ''.join(name) or len(name) > 1 and target == name[0]):
                candidates.append(other['car'])
        if len(candidates) == 1 and candidates[0] != rider:
            return {'state': 'SUMMARIZED', 'code': 'FOLLOW',
                    'summary': COMMENT_SUMMARIES['FOLLOW'], 'target_car': candidates[0]}
    return {'state': 'UNINTERPRETED'}


def _recent(admitted, payload, day):
    supplement = admitted.get('supplement')
    if not supplement or admitted.get('condition_state') != 'CONDITIONED_AUTHENTICATED_PRE_CUTOFF':
        return {}
    proof = admitted['origin_receipts']['condition_origin']
    _need(supplement == payload.get('supplement') and proof and
          proof['state'] == 'GITHUB_PRE_CUTOFF_CONDITIONED_ORIGIN_VERIFIED' and
          proof['race_id'] == admitted['race_id'] and
          proof['cipher_sha256'] == admitted['conditioned_cipher_sha256'], 'CONDITION_BINDING')
    evidence = supplement['condition_evidence']
    result = {}
    for rider in evidence['riders']:
        ranks = {}
        for row in rider['results']:
            if row['place'] is not None and row['race_date'] < day:
                ranks.setdefault(row['race_date'], []).append(row['place'])
        observations = []
        for when in sorted(ranks, reverse=True)[:MAX_RECENT]:
            values = ranks[when]
            if len(values) == 1:
                observations.append(dict(day=when, rank=values[0]))
            else:
                # A date alone cannot order multiple starts on the same day.
                counts = Counter(values)
                observations.append(dict(day=when, counts=[counts[rank] for rank in range(1,10)]))
        result[rider['car']] = observations
    return result


def project_sp_context(payload, admitted):
    """Re-read bound official card and marks against the independently admitted record."""
    rid = admitted['race_id']
    snapshot = admitted['snapshot']
    baseline = admitted['baseline']
    day = _race_day(rid)
    generated = _aware(baseline['generated_at'])
    cutoff = _aware(baseline['published_cutoff_at'])
    proof = admitted['origin_receipts']['baseline_origin']
    proof_fields = {key: value for key, value in proof.items() if key != 'evidence_sha256'}
    _need(day == admitted['day_jst'] == payload['day_jst'] == cutoff.astimezone(form.JST).date().isoformat() and
          rid == payload['race_id'] == snapshot['race_id'] == baseline['race_id'] == proof['race_id'] and
          snapshot == payload['snapshot'] and baseline == payload['baseline'] and
          baseline['source_facts_sha256'] == model.digest(snapshot) and
          _aware(snapshot['published_cutoff_at']) == cutoff == _aware(proof['official_cutoff_at']) and
          proof['schema'] == origin.SCHEMA and proof['state'] == 'GITHUB_PRE_CUTOFF_ORIGIN_VERIFIED' and
          proof['cipher_sha256'] == payload['baseline_cipher_sha256'] == admitted['baseline_cipher_sha256'] and
          proof['evidence_sha256'] == model.digest(proof_fields) and
          generated <= _aware(admitted['baseline_sealed_at']) <= _aware(proof['latest_server_evidence_at']) < cutoff,
          'ORIGINAL_BINDING')
    args = payload['baseline_arguments']
    card_args = args['card_arguments']
    card = extension.parse_extension_card(**card_args, now=generated)
    prediction = args['prediction_source']
    tab = marks.parse_prediction_tab(raw_bytes=prediction['raw_bytes'],
        expected_sha256=prediction['expected_sha256'], observed_at=_aware(prediction['observed_at']),
        now=generated, card=card, detail_raw=card_args['detail_raw'],
        scripts=args['prediction_scripts'], request_url=prediction['request_url'],
        minimum_margin_seconds=65)
    card_at = _aware(card['source_observed_at'])
    comments_at = _aware(tab['source_observed_at'])
    updated = _aware(tab['publisher_updated_at'])
    _need(rid == card['race_id'] == tab['race_id'] and _aware(card['official_cutoff_at']) == cutoff and
          card_at <= comments_at <= generated and updated <= comments_at and
          snapshot['cutoff_source']['bytes_sha256'] == card['source_sha256'] and
          _aware(snapshot['cutoff_source']['captured_at']) == card_at and
          sum(page['kind']=='MARKS' and page['bytes_sha256']==tab['source_sha256'] and
              _aware(page['captured_at'])==comments_at for page in snapshot['source_pages']) == 1,
          'CAPTURE_BINDING')
    snapshot_riders = snapshot['riders']
    starters = card['riders']
    roster = _identity(starters, 'car', 'registration_id')
    _need(roster == _identity(snapshot_riders, 'car', 'athlete_id') ==
          _identity(tab['riders'], 'car', 'registration_id'), 'CAPTURE_ROSTER')
    by_car = {row['car']: row for row in snapshot_riders}
    by_comment = {row['car']: row['comment_raw'] for row in tab['riders']}
    recent = _recent(admitted, payload, day)
    riders = []
    for row in sorted(starters, key=lambda row: row['car']):
        car = row['car']
        frozen = by_car[car]
        counts = {key: _count(row['statistics_raw'][field]) for field, key in STAT_FIELDS.items()}
        _need(counts['back_count'] == frozen['b_count'] and
              float(row['score_raw']) == frozen['competition_points'], 'CAPTURE_STATISTIC')
        stats = dict(competition_points=frozen['competition_points'],
                     win_rate_percent=round(frozen['recent_form_score'] * 100, 8),
                     home_count=frozen['h_count'], **counts)
        riders.append(dict(number=car, registration=roster[car], stats=stats,
                           comment=_public_comment(by_comment[car], car, starters),
                           recent_results=recent.get(car, [])))
    return dict(race_id=rid, cutoff_at=cutoff.isoformat(),
                card_at=card_at.isoformat(), card_sha256=card['source_sha256'],
                comments_at=comments_at.isoformat(), comments_updated_at=updated.isoformat(),
                comments_sha256=tab['source_sha256'], riders=riders)


def _checked_race(row, day, published):
    _need(type(row) is dict and set(row) == {
        'race_id', 'cutoff_at', 'card_at', 'card_sha256', 'comments_at',
        'comments_updated_at', 'comments_sha256', 'riders'}, 'RACE_FIELDS')
    rid = row['race_id']
    cutoff, captured, comments_at, updated = map(_aware, (
        row['cutoff_at'], row['card_at'], row['comments_at'], row['comments_updated_at']))
    _need(_race_day(rid) == day == cutoff.astimezone(form.JST).date().isoformat() and
          updated <= comments_at <= published and captured <= comments_at < cutoff and
          all(type(row[key]) is str and SHA.fullmatch(row[key]) for key in
              ('card_sha256','comments_sha256')), 'RACE_CLOCK')
    identities = _identity(row['riders'], 'number', 'registration')
    _need(5 <= len(identities) <= 9, 'FIELD_SIZE')
    for item in row['riders']:
        _need(set(item) == {'number','registration','stats','comment','recent_results'}, 'RIDER_FIELDS')
        stats = item['stats']
        _need(type(stats) is dict and set(stats) == {'competition_points','win_rate_percent',
            'home_count', *STAT_FIELDS.values()}, 'STATS_FIELDS')
        for key, value in stats.items():
            if key in ('competition_points', 'win_rate_percent'):
                _need(type(value) in (int,float) and isfinite(value) and
                      0 <= value <= (150 if key == 'competition_points' else 100), 'STATISTIC')
            else:
                _need((value is None and key not in ('home_count', 'back_count')) or
                      type(value) is int and 0 <= value <= 200, 'STATISTIC')
        comment = item['comment']
        _need(type(comment) is dict and comment.get('state') in
              ('SUMMARIZED','UNINTERPRETED','NOT_PUBLISHED'), 'COMMENT')
        if comment['state'] == 'SUMMARIZED':
            code = comment.get('code')
            follow = code == 'FOLLOW'
            _need(set(comment) == {'state','code','summary'} | ({'target_car'} if follow else set()) and
                  code in COMMENT_SUMMARIES and comment['summary'] == COMMENT_SUMMARIES[code] and
                  (not follow or type(comment['target_car']) is int and
                   comment['target_car'] in identities and comment['target_car'] != item['number']),
                  'COMMENT')
        else:
            _need(set(comment) == {'state'}, 'COMMENT')
        prior = item['recent_results']
        _need(type(prior) is list and len(prior) <= MAX_RECENT, 'RECENT')
        before = day
        for entry in prior:
            _need(type(entry) is dict and set(entry) in ({'day','rank'}, {'day','counts'}) and
                  _day(entry['day']) < before, 'RECENT')
            if 'rank' in entry:
                _need(type(entry['rank']) is int and 1 <= entry['rank'] <= 9, 'RECENT')
            else:
                counts = entry['counts']
                _need(type(counts) is list and len(counts) == 9 and
                      all(type(value) is int and 0 <= value <= 40 for value in counts) and
                      2 <= sum(counts) <= 40, 'RECENT')
            before = entry['day']
    return identities


def build_day(starters, rows, *, published_at):
    """Join admitted contexts to the existing complete daily public starter field."""
    published = _aware(published_at)
    day = _day(starters['day'])
    expected = starters['races']
    _need(starters['schema'] == STARTERS_SCHEMA and starters['day'] == day <= published.astimezone(form.JST).date().isoformat() and
          _aware(starters['published_at']) <= published and type(expected) is list and
          0 <= len(expected) <= MAX_RACES and type(rows) is list and len(rows) <= len(expected), 'DAY')
    fields = {}
    for race in expected:
        rid = race['race_id']
        _need(_race_day(rid) == day and rid not in fields, 'REGISTRY_RACE')
        fields[rid] = _identity(race['riders'],'number','registration')
    selected = {}
    counts = Counter()
    for row in rows:
        identity = _checked_race(row,day,published)
        rid = row['race_id']
        _need(rid not in selected and fields.get(rid) == identity, 'REGISTRY_ROSTER')
        selected[rid] = row
        counts.update(entry['comment']['state'] for entry in row['riders'])
    observed = sum(counts.values())
    registered = sum(map(len,fields.values()))
    coverage = dict(registered_races=len(fields),verified_races=len(selected),
                    registered_riders=registered,verified_riders=observed,
                    comments_confirmed=counts['SUMMARIZED'],comments_held=counts['UNINTERPRETED'],
                    comments_missing=counts['NOT_PUBLISHED']+registered-observed)
    return checked_day(dict(schema=SCHEMA,day=day,published_at=published.isoformat(),coverage=coverage,
                            races=[selected[key] for key in sorted(selected)]))


def checked_day(packet):
    """Validate the exact persisted public fields and recompute observed coverage."""
    _need(type(packet) is dict and set(packet) == {'schema','day','published_at','coverage','races'} and
          packet['schema'] == SCHEMA, 'PACKET_FIELDS')
    day = _day(packet['day'])
    published = _aware(packet['published_at'])
    coverage = packet['coverage']
    races = packet['races']
    coverage_fields = {'registered_races','verified_races','registered_riders','verified_riders',
                       'comments_confirmed','comments_held','comments_missing'}
    _need(day <= published.astimezone(form.JST).date().isoformat() and type(coverage) is dict and
          set(coverage) == coverage_fields and all(type(v) is int and v >= 0 for v in coverage.values()) and
          type(races) is list and len(races) <= coverage['registered_races'] <= MAX_RACES and
          coverage['registered_races'] <= coverage['registered_riders'] <= 9 * coverage['registered_races'],
          'PACKET_COVERAGE')
    previous = ''
    counts = Counter()
    for race in races:
        _checked_race(race, day, published)
        _need(previous < race['race_id'], 'RACE_ORDER')
        previous = race['race_id']
        counts.update(row['comment']['state'] for row in race['riders'])
    observed = sum(counts.values())
    _need(coverage['verified_races'] == len(races) and coverage['verified_riders'] == observed <= coverage['registered_riders'] and
          coverage['comments_confirmed'] == counts['SUMMARIZED'] and coverage['comments_held'] == counts['UNINTERPRETED'] and
          coverage['comments_missing'] == counts['NOT_PUBLISHED'] + coverage['registered_riders'] - observed,
          'PACKET_COVERAGE')
    return packet
