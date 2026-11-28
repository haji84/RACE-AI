"""Run the fixed DT-R1 official retrospective study in the existing owner job."""
import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai import keirin_official_nationwide_records as records
from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
from research.chatgpt_dt_r1 import official_holdout_study
from scripts import keirin_dt_r1_future_shadow as shadow
from scripts import keirin_official_nationwide_continuation as continuation


def run(*, repo, private_root, owner_public_pem, owner_private_pem, day=None,
        now=continuation.now_utc):
    repo, root, _, _, commit = continuation._runtime(repo=repo, private_root=private_root,
        owner_public_pem=owner_public_pem, owner_private_pem=owner_private_pem,
        day=None, clock=now, mode='study')
    trained, _ = shadow.load_frozen(repo)
    with TemporaryDirectory(prefix='dt-r1-official-holdout-', dir=root) as folder:
        work = Path(folder)
        archive._cmd(work, 'init', '--quiet', '--template=')
        archive._cmd(work, 'remote', 'add', 'origin', f'https://github.com/{archive.REPO}.git')
        archive._cmd(work, 'config', '--local', 'remote.origin.promisor', 'true')
        archive._cmd(work, 'config', '--local', 'remote.origin.partialclonefilter', 'blob:none')
        records.fetch_partial_head(work, with_ancestry=True)
        report = official_holdout_study.run_holdout(work, owner_private_pem=owner_private_pem,
            trained=trained, client=GitHubEvidenceClient(), now=now, day=day)
    return dict(report, reader_code_commit=commit, reader_run_id=os.environ['GITHUB_RUN_ID'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--private-root', type=Path, required=True)
    parser.add_argument('--owner-public-pem', type=Path, required=True)
    parser.add_argument('--day')
    args = parser.parse_args(argv)
    private = os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', '').encode()
    try:
        report = run(**vars(args), owner_private_pem=private)
    except Exception:
        print(json.dumps({'state': 'HOLD_DT_R1_OFFICIAL_HOLDOUT_UNVERIFIED',
                          'scope': 'RETROSPECTIVE_OFFICIAL_HOLDOUT', 'production_promoted': False}))
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
