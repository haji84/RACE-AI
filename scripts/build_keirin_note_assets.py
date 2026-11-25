"""Bundle the imported note into the existing allowlisted presentation assets."""
import json
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path


def reviewed_growth(root):
    evidence = root / 'docs/evidence/keirin-live-accuracy-closure-20261125'
    past = json.loads((evidence / 'retrospective-score.json').read_bytes())
    forward = json.loads((evidence / 'authenticated-automatic-forward-score.json').read_bytes())
    if (past['scope'] != 'RETROSPECTIVE_CHRONOLOGICAL_RECONSTRUCTION_NOT_FUTURE_INDEPENDENT'
            or past['selected_arm'] != 'all_96' or past['production_weights_promoted'] is not False
            or forward['comparators'] != {'published': 'baseline_B', 'trial': 'joint_comparison_B'}
            or forward['original_plaintext_authentication'] != 'INDEPENDENT_RSA_READBACK_VERIFIED'
            or forward['actual_organizer_cutoff_authenticated'] is not False
            or forward['accuracy_improvement_proven'] is not False):
        raise ValueError('growth evidence does not match the reviewed comparisons')

    def pair(baseline, challenger, total):
        if any(type(hits) is not int or not 0 <= hits <= total for hits in (baseline, challenger)):
            raise ValueError('invalid growth hit count')
        return dict(baseline=baseline, challenger=challenger)

    races, matched = past['races'], forward['matched']
    baseline, challenger = (past['metrics'][name] for name in ('saved', 'all_96'))
    if (type(races) is not int or races <= 0 or baseline['n'] != races or challenger['n'] != races
            or type(matched) is not int or type(forward['registered']) is not int
            or not 0 < matched <= forward['registered'] or forward['result_states']['matched'] != matched):
        raise ValueError('growth comparison denominators disagree')
    forward_scores = {
        'top1_3t': (1, forward['trifecta_by_points']['1']),
        'top4_3t': (4, forward['trifecta_by_points']['4']),
        'top8_3t': (8, forward['trifecta_by_points']['8']),
        'top2_2t': (2, forward['exacta_top2']),
    }
    if any(score['matched'] != matched or score['tickets_per_arm'] != points * matched
           for points, score in forward_scores.values()):
        raise ValueError('growth forward scores must use equal points and matched races')
    first, last = (datetime.strptime(day, '%Y%m%d').date().isoformat() for day in past['evaluation_dates'])
    intervals = {}
    for metric in ('top4_3t', 'top2_2t'):
        low, high = past['paired_day_bootstrap_95'][metric]
        if not -1 <= low <= high <= 1:
            raise ValueError('invalid growth comparison interval')
        intervals[metric] = [low, high]
    return {
        'historical': {'from': first, 'to': last, 'races': races, 'days': len(past['days']),
                       'hits': {key: pair(baseline[key], challenger[key], races) for key in forward_scores},
                       'intervals': intervals},
        'forward': {'day': date.fromisoformat(forward['date']).isoformat(), 'registered': forward['registered'],
                    'matched': matched, 'hits': {key: pair(score['published_hits'], score['trial_hits'], matched)
                                                 for key, (_, score) in forward_scores.items()}},
    }


def build_note_view(root):
    view = (root / 'web/keirin-note-view.js').read_bytes()
    marker = b'/* reviewed growth aggregates */ null'
    if view.count(marker) != 1:
        raise ValueError('note view needs exactly one growth aggregate placeholder')
    data = json.dumps(reviewed_growth(root), ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    return view.replace(marker, data.encode('ascii'))


def build(root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    web = root / 'web'
    parts = [web/'keirin-note-source/staking.js', web/'keirin-note-source/staking_flexible.js',
             web/'keirin-note-source/rollover.js', web/'confidence.js', web/'keirin-joint-forecast.js',
             web/'keirin-rider-history.js', web/'keirin-note-model.js', web/'keirin-note-feed.js']
    original = (web/'race-app-core.js').read_bytes()
    prefix = b"if (typeof window === 'object' && typeof location === 'object') window.RaceNoteInitialFragment = location.hash;\n"
    components = [path.read_bytes() for path in parts]
    components.append(build_note_view(root))
    bundle = prefix + original + b'\n' + b'\n'.join(components)
    (web/'app.js').write_bytes(bundle)
    css = (web/'race-style-core.css').read_bytes() + b'\n' + (web/'keirin-note.css').read_bytes()
    (web/'style.css').write_bytes(css)
    return dict(app_sha256=sha256(bundle).hexdigest(), style_sha256=sha256(css).hexdigest(),
                original_app_sha256=sha256(original).hexdigest(), additional_live_asset_paths=0)


if __name__ == '__main__':
    print(json.dumps(build(), sort_keys=True))
