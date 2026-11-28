"""Decompose little-ticket DT-R1 errors on the existing July development cohort."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import permutations
from pathlib import Path
import subprocess
from time import monotonic

import numpy as np

from research.chatgpt_dt_r1 import ranking_objective_study as reference
from research.chatgpt_dt_r1.data import PINNED_SOURCE_SHA256, SOURCE_COMMIT, load_archives
from research.chatgpt_dt_r1.frozen_followup import OLD_DATASET, ROOT, check
from research.chatgpt_dt_r1.historical_replay import digest_file
from research.chatgpt_dt_r1.pipeline import write_private_json
from scripts.keirin_dt_r1_future_shadow import MODEL_FILE_SHA, MODEL_SHA, load_frozen


def diagnose(rows, size):
    group = reference.batch(rows)
    probabilities = reference.probabilities(group, np.zeros(len(reference.BASIS)))
    ticket_cube = probabilities.reshape(-1, size, size - 1, size - 2)
    true_exacta = group.truth // (size - 2)
    true_winner = true_exacta // (size - 1)
    true_second_index = true_exacta % (size - 1)
    race = np.arange(len(group.truth))

    tri = probabilities.argmax(axis=1)
    tri_exacta = tri // (size - 2)
    first_ok = tri_exacta // (size - 1) == true_winner
    first_two_ok = tri_exacta == true_exacta
    tri_ok = tri == group.truth
    ex_ok = reference.exactas(probabilities, size).argmax(axis=1) == true_exacta
    unordered_sets = np.sort(np.asarray(list(permutations(range(size), 3))), axis=1)
    unordered_ok = (unordered_sets[tri] == unordered_sets[group.truth]).all(axis=1)

    # Conditioning on official placings isolates each stage. These are
    # retrospective diagnostics, since that prefix is unknown before the race.
    forced_second = ticket_cube[race, true_winner].sum(axis=2).argmax(axis=1)
    forced_third = ticket_cube[race, true_winner, true_second_index].argmax(axis=1)
    counts = dict(races=len(race), trifecta_one_point=int(tri_ok.sum()), exacta_one_point=int(ex_ok.sum()),
        joint_trifecta_wrong_first=int((~first_ok).sum()),
        joint_trifecta_first_correct_second_wrong=int((first_ok & ~first_two_ok).sum()),
        joint_trifecta_first_two_correct_third_wrong=int((first_two_ok & ~tri_ok).sum()),
        joint_trifecta_unordered_set_correct_but_wrong_order=int((unordered_ok & ~tri_ok).sum()),
        marginal_winner_correct=int((ticket_cube.sum(axis=(2, 3)).argmax(axis=1) == true_winner).sum()),
        second_correct_given_official_winner=int((forced_second == true_second_index).sum()),
        third_correct_given_official_first_two=int((forced_third == group.truth % (size - 2)).sum()))
    check(sum(counts[key] for key in ('trifecta_one_point', 'joint_trifecta_wrong_first',
        'joint_trifecta_first_correct_second_wrong', 'joint_trifecta_first_two_correct_third_wrong')) ==
        counts['races'], 'TRIFECTA_PREFIX_PARTITION')
    return counts


def run(archives):
    started = monotonic()
    records, audit = load_archives(archives)
    check({path.name for path in archives} == PINNED_SOURCE_SHA256.keys() and
          audit['dataset_sha256'] == OLD_DATASET, 'PINNED_ARCHIVE_MISMATCH')
    model, venues = load_frozen(ROOT.parents[1])
    check(model is not None, 'FROZEN_MODEL_UNAVAILABLE')
    date = datetime.now(timezone.utc).isoformat()
    by_size, cards, excluded = defaultdict(Counter), 0, 0
    for _, registered, missing, sizes in reference._period(records, 'july', model, venues, date):
        cards += registered
        excluded += missing
        for size, rows in sizes.items():
            by_size[str(size)].update(diagnose(rows, size))
    total = Counter()
    for counts in by_size.values():
        total.update(counts)
    check(total['races'] == reference.EXPECTED_JULY == cards - excluded and
          total['trifecta_one_point'] == 252 and total['exacta_one_point'] == 522, 'FROZEN_BASELINE_REPLAY')
    return dict(schema='DT_R1_FIXED_POINT_FAILURE_STUDY_V1', recorded_at=date,
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        study_source_sha256=digest_file(Path(__file__)),
        archive=dict(commit=SOURCE_COMMIT, files=PINNED_SOURCE_SHA256, dataset_sha256=OLD_DATASET),
        model_sha256=MODEL_SHA, model_file_sha256=MODEL_FILE_SHA,
        period=list(reference.PERIODS['july']), prior_days=reference.specification()['prior_days'],
        scope='RETROSPECTIVE_DEVELOPMENTAL_NO_CANDIDATE_SELECTION',
        known_prefix_scope='OFFICIAL_PLACINGS_USED_ONLY_FOR_DIAGNOSIS',
        registered_races=cards, excluded_nonunique_top3=excluded,
        counts=dict(total), by_starter_count={key: dict(value) for key, value in sorted(by_size.items())},
        elapsed_seconds=round(monotonic() - started, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('archives', type=Path, nargs=2)
    args = parser.parse_args()
    write_private_json(args.output.resolve(), run(args.archives))


if __name__ == '__main__':
    main()
