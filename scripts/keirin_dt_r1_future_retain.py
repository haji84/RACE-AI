"""Archive an independently witnessed DT-R1 batch through the existing Git store."""
import argparse
import json
import os
from pathlib import Path

from race_ai import keirin_nationwide_cipher_history as archive
from race_ai.keirin_github_evidence_client import GitHubEvidenceClient
from research.chatgpt_dt_r1.future_batch_retention import append_verified_batch
from research.chatgpt_dt_r1.future_retention_gate import legacy_timely_slots
from scripts import keirin_dt_r1_future_readback as reader
from scripts import keirin_dt_r1_future_shadow as shadow


def retain(repo, producer_run, readback_run, *, client=None):
    run_id, code_commit = reader._runtime(repo)
    producer_run = reader._run_id(producer_run)
    readback_run = reader._run_id(readback_run)
    if len({run_id, producer_run, readback_run}) != 3:
        raise ValueError('DT_R1_RETENTION_DISTINCT_RUNS_REQUIRED')
    repo = archive._remote(repo, synthetic_local=False)
    client = client or GitHubEvidenceClient()
    with reader.verified_producer(producer_run, client=client) as verified:
        origin = reader.verify_readback(verified, readback_run, client=client)
        day = verified['manifest']['summary']['day_jst']
        tip = archive._refresh(repo, retry_on_timeout=True, blobless=True)
        legacy = legacy_timely_slots(repo, tip, day, model_sha256=shadow.MODEL_SHA, client=client)
        report = append_verified_batch(repo, verified, origin, legacy_accepted_slots=legacy)
    return dict(report, retention_run_id=run_id, retention_code_commit=code_commit,
                provider_source_requests=0, owner_plaintext_opened=False,
                production_promoted=False, formal_three_way_races=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--producer-run', required=True)
    parser.add_argument('--readback-run', required=True)
    args = parser.parse_args(argv)
    os.environ.pop('RACE_AI_KEIRIN_PRIVATE_RSA_PEM', None)
    try:
        report = retain(args.repo, args.producer_run, args.readback_run)
    except Exception:
        print(json.dumps(dict(state='HOLD_DT_R1_BATCH_RETENTION_UNVERIFIED',
                              provider_source_requests=0, owner_plaintext_opened=False),
                         sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
