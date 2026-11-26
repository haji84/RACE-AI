"""Time-bound WINTICKET interviews for the existing private form comparison."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
import re
from unicodedata import normalize

from .keirin_nationwide_auto_generator import VENUE, when

JST = timezone(timedelta(hours=9))
PRE = "PRE_RACE"
POST = "PRIOR_POST_RACE"
MAX_POST_DAYS = 14
MIN_FINISHES = 3
ROUTES = {
    ("racecard", "inspection_day_interview"): PRE,
    ("raceresult", "race_result_interview"): POST,
}
URL = re.compile(
    r"https://(?:www\.)?winticket\.jp/keirin/[a-z][a-z0-9-]*/"
    r"(racecard|raceresult)/(20[0-9]{6})([0-9]{2})/([1-7])/([1-9]|1[0-2])"
    r"\?type=(inspection_day_interview|race_result_interview)\Z"
)
SIGNALS = {
    "FORM_UP": r"(?:調子|状態|体の調子)は(?:いい|良い|いいと思う|良いと思う|良くなってきて(?:いる|います)|上向き(?:です)?)",
    "FORM_STEADY": r"(?:調子|状態)は(?:変わらず|変わりません|変わっていません|普段通り(?:です)?)",
    "FORM_DOWN": r"(?:調子|状態)は(?:良くない|良くないです|悪い|悪いです|落ちて(?:いる|います))",
    "TACTIC_LEAD": r"(?:先行|突っ張り先行)(?:したい(?:です(?:ね)?)?|します|で勝負(?:します)?)",
    "TACTIC_FOLLOW": r"(?:黙って)?[2-9]番手を固め(?:る|ます)",
    "TACTIC_FLEXIBLE": r"(?:自力自在(?:に)?|取れた位置から)(?:頑張る|頑張ります|頑張るだけです)?",
}


def need(condition, code):
    if not condition:
        raise ValueError(code)


def race_day(race_id):
    return date(int(race_id[:4]), int(race_id[4:6]), int(race_id[6:8]))


def location(source_url, race_id):
    match = URL.fullmatch(source_url) if type(source_url) is str else None
    need(match is not None, "INTERVIEW_URL_INVALID")
    route, meeting, venue, day_index, race_number, tab = match.groups()
    phase = ROUTES.get((route, tab))
    meeting_day = race_day(meeting) + timedelta(days=int(day_index) - 1)
    need(phase is not None and f"{meeting_day:%Y%m%d}{venue}{int(race_number):02d}" == race_id,
         "INTERVIEW_URL_RACE_MISMATCH")
    return phase


def validate(note, *, target_race_id, target_car, available_at, target_cutoff_at=None):
    meta = note["winticket"]
    need(type(meta) is dict and set(meta) == {"race_id", "car", "url", "observed_at", "cutoff_at"},
         "INTERVIEW_METADATA_INVALID")
    race_id = meta["race_id"]
    need(type(race_id) is str and VENUE.fullmatch(race_id) and
         type(meta["car"]) is int and 1 <= meta["car"] <= 9,
         "INTERVIEW_RACE_OR_CAR_INVALID")
    phase = location(meta["url"], race_id)
    cutoff = when(meta["cutoff_at"])
    need(cutoff.astimezone(JST).date() == race_day(race_id), "INTERVIEW_CUTOFF_WRONG_DAY")
    if race_id == target_race_id:
        need(phase == PRE, "INTERVIEW_TARGET_RESULT")
        need(meta["car"] == target_car and
             (target_cutoff_at is None or cutoff == when(target_cutoff_at)),
             "INTERVIEW_TARGET_BINDING")
    else:
        need(race_day(race_id) < race_day(target_race_id), "INTERVIEW_FUTURE_RACE")
    observed = when(meta["observed_at"])
    if phase == PRE:
        need(observed < cutoff, "INTERVIEW_PRE_RACE_TOO_LATE")
    else:
        need(cutoff < observed, "INTERVIEW_POST_RACE_TOO_EARLY")
    need(observed <= available_at, "INTERVIEW_OBSERVED_AFTER_INPUT")
    if note["published_at"] is not None:
        published = when(note["published_at"])
        need(published <= observed and (phase == PRE or published > cutoff),
             "INTERVIEW_PUBLICATION_TIME_INVALID")
    return phase, observed


def signals(text):
    """Recognize bounded self-statements. Silence or ambiguous wording stays unknown."""
    clauses = re.split(r"[。.!！\n]+", normalize("NFKC", text))
    observed = {name for name, pattern in SIGNALS.items()
                if any(re.fullmatch(pattern, item.strip()) for item in clauses)}
    labels = []
    for family in ("FORM_", "TACTIC_"):
        choices = sorted(label for label in observed if label.startswith(family))
        if len(choices) == 1:
            labels.extend(choices)
    return labels


def _versions(comments):
    notes = defaultdict(list)
    seen = {}
    for entry in comments:
        if "winticket" not in entry:
            continue
        meta = entry["winticket"]
        observed = when(meta["observed_at"])
        key = meta["race_id"], location(meta["url"], meta["race_id"])
        state = entry["text"], meta["car"], when(meta["cutoff_at"])
        timestamped = (*key, observed)
        if timestamped in seen:
            need(seen[timestamped] == state, "INTERVIEW_OBSERVATION_CONFLICT")
            continue
        seen[timestamped] = state
        notes[key].append((observed, signals(entry["text"])))
    for versions in notes.values():
        versions.sort(key=lambda note: note[0], reverse=True)
    return notes


def _available(notes, race_id, phase, before):
    return next((note for note in notes.get((race_id, phase), ()) if note[0] < before), None)


def _prior_note(notes, previous, race_id, *, before):
    if previous is None or previous["status"] == "DNS":
        return None
    origin = previous["race_id"]
    if not 0 < (race_day(race_id) - race_day(origin)).days <= MAX_POST_DAYS:
        return None
    return _available(notes, origin, POST, before)


def assess(comments, results, *, target_race_id, as_of):
    """Learn within-rider associations against prior verified finishes.

    The outcomes measure finish, even when the feature describes intended
    tactics. The next observed start can be paired with a prior post-race
    interview. Historical starts with an ambiguous same-day predecessor
    have no post-race pairing.
    """
    notes = _versions(comments)
    if not notes:
        return None
    samples = defaultdict(list)
    starts_by_day = Counter(result["race_date"] for result in results)
    previous = None
    for result in results:
        rid = result["race_id"]
        start_day = datetime.combine(race_day(rid), time.min, JST)
        pre = _available(notes, rid, PRE, when(result["published_at"]))
        post = (_prior_note(notes, previous, rid, before=start_day)
                if starts_by_day[result["race_date"]] == 1 else None)
        if result["status"] == "FINISHED":
            finish = (result["field_size"] - result["place"]) / (result["field_size"] - 1)
            for phase, note in ((PRE, pre), (POST, post)):
                if note and note[0] < when(result["published_at"]):
                    for signal in note[1]:
                        samples[phase, signal].append(finish)
        previous = result if starts_by_day[result["race_date"]] == 1 else None

    current = {PRE: next(iter(notes.get((target_race_id, PRE), ())), None),
               POST: _prior_note(notes, previous, target_race_id, before=as_of)}
    available = [(phase, signal) for phase, note in current.items() if note for signal in note[1]]
    response = dict(phase=None, signal=None, matched_finishes=0,
                    comparison_finishes=0, score_adjustment=0.0)
    for phase, signal in available:
        matched = samples[phase, signal]
        family = signal.split("_", 1)[0]
        reference = [n for (p, label), values in samples.items()
                     if p == phase and label != signal and label.startswith(family + "_")
                     for n in values]
        measured = min(len(matched), len(reference))
        adjustment = 0.0
        if measured >= MIN_FINISHES:
            difference = sum(matched)/len(matched) - sum(reference)/len(reference)
            adjustment = round(max(-.015, min(.015, .075 * difference * measured/(measured + 12))), 6)
        if response["signal"] is None or measured >= MIN_FINISHES:
            response.update(phase=phase, signal=signal, matched_finishes=len(matched),
                            comparison_finishes=len(reference), score_adjustment=adjustment)
        if measured >= MIN_FINISHES:
            break
    return response
