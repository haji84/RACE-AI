"""Verify retained first-P0 originals on a separate Actions run without sources.

All decryption, native forecast validation and companion authentication reuse
the existing readers. Native objects stay in memory; only counts and immutable
receipt identifiers are returned by the CLI.
"""
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from race_ai import boat_private_original_archive as native
from race_ai import boat_private_original_vault as V
from race_ai.boat_source_control import read_summary
from race_ai.frozen_day_cycle import read_p0, read_p1
from scripts import boat_private_original_vault as vaultCLI
from scripts import first_p0_bootstrap as boot


class _Rejected(ValueError):
    """Only fixed local diagnostic codes may cross the private reader boundary."""


def _need(ok, reason):
    if not ok:
        raise _Rejected('FIRST_P0_READBACK_' + reason)


def verify(repo, *, vault_commit, receipt_commit, day, p0_artifact,
           companion_artifacts, transport=None, receipt_get=None, verify_retained_p1=False):
    """Return (count report, native document, native rows, original metadata).

    ``transport`` and ``receipt_get(path, *, ref)`` replace only external Git and
    Contents reads. There is no live-artifact or provider fallback.
    """
    stage = 'OWNER_CONTEXT'
    try:
        repo = vaultCLI._environment(repo)
        stage = 'INPUT'
        _need(type(verify_retained_p1) is bool, 'P1_FLAG_INVALID')
        _need(all(type(value) is str and re.fullmatch(r'[a-f0-9]{40}', value)
                  for value in (vault_commit, receipt_commit)), 'COMMIT_INVALID')
        _need(type(day) is str and date.fromisoformat(day).isoformat() == day, 'DAY_INVALID')
        _need(type(companion_artifacts) in (list, tuple) and len(companion_artifacts) == 2,
              'ARTIFACT_SET_INVALID')
        ids = [p0_artifact, *companion_artifacts]
        _need(all(type(ident) is int and 0 < ident < 10**20 for ident in ids)
              and len(set(ids)) == 3, 'ARTIFACT_SET_INVALID')
        verification_run = os.environ.get('GITHUB_RUN_ID', '')
        _need(re.fullmatch(r'[1-9][0-9]{0,19}', verification_run), 'VERIFICATION_RUN_REQUIRED')
        verification_run = int(verification_run)
        git = V._transport(repo, transport)

        def restored(ident):
            locator = V.lookup_original(ident, repo, source_commit=vault_commit, transport=git)
            _need(locator is not None, 'ARTIFACT_MISSING')
            _need(type(locator) is dict and locator.get('artifact_id') == ident
                  and locator.get('source_commit') == vault_commit, 'LOCATOR_IDENTITY_INVALID')
            value = V.restore_original(locator, repo, transport=git)
            _need(value['metadata']['id'] == ident
                  and value['provenance']['source_commit'] == vault_commit
                  and value['provenance']['independent_git_readback_verified'] is True,
                  'RESTORED_IDENTITY_INVALID')
            return locator['kind'], value

        stage = 'VAULT'
        kind, p0 = restored(p0_artifact)
        _need(kind == 'P0', 'P0_KIND_INVALID')
        metadata = p0['metadata']
        source_run = metadata['workflow_run']['id']
        source_sha = metadata['workflow_run']['head_sha']
        _need(source_run != verification_run, 'SEPARATE_RUN_REQUIRED')
        _need(metadata['name'] == f'boat-p0-existing-{source_run}', 'FIRST_ARTIFACT_REQUIRED')

        stage = 'P0'
        document, rows = read_p0(p0['raw_zip'], metadata, expected_day=day)
        index = boot.receipt_index(p0['raw_zip'], metadata, day)
        with native._checked_zip(p0['raw_zip'], max_zip_bytes=V.MAX_ORIGINAL) as archive:
            _need(archive.namelist() == [native.CIPHER_MEMBER], 'ENCRYPTED_P0_REQUIRED')
            cipher = archive.read(native.CIPHER_MEMBER)
        header, _, _, _ = native._split(cipher)

        stage = 'VAULT'
        companions = {}
        for ident in companion_artifacts:
            kind, value = restored(ident)
            _need(kind in ('CONTINUITY', 'SOURCE_CONTROL') and kind not in companions,
                  'COMPANION_KINDS_INVALID')
            run = value['metadata']['workflow_run']
            _need(run['id'] == source_run and run['head_sha'] == source_sha,
                  'COMPANION_IDENTITY_INVALID')
            companions[kind] = value
        _need(set(companions) == {'CONTINUITY', 'SOURCE_CONTROL'}, 'COMPANION_KINDS_INVALID')
        stage = 'COMPANION_BINDING'
        continuity = companions['CONTINUITY']; control = companions['SOURCE_CONTROL']
        bound = read_summary(control['raw_zip'], control['metadata'],
            continuity['raw_zip'], continuity['metadata'], run_id=source_run, head_sha=source_sha)
        _need(bound['day_jst'] == day, 'COMPANION_DAY_INVALID')

        stage = 'RECEIPT'
        path = f'docs/evidence/{day}/p0-first-receipt.json'
        receipt = (receipt_get or boot._remote_file)(path, ref=receipt_commit)
        body = (json.dumps(index, ensure_ascii=False, sort_keys=True,
                           separators=(',', ':')) + '\n').encode('utf-8')
        _need(boot._receipt_file_matches(receipt, path, body), 'RECEIPT_MISMATCH')

        report = dict(status='FIRST_P0_INDEPENDENT_READBACK_VERIFIED',
            day_jst=day, original_id=p0_artifact, source_run_id=source_run,
            verification_run_id=verification_run, source_sha=source_sha,
            vault_commit=vault_commit, receipt_commit=receipt_commit,
            server_created_at=metadata['created_at'], json_sha256=index['json_sha256'],
            zip_sha256=index['zip_sha256'], cipher_sha256=hashlib.sha256(cipher).hexdigest(),
            inner_zip_sha256=header['plain_zip_sha256'],
            metadata_sha256=hashlib.sha256(p0['metadata_raw']).hexdigest(),
            receipt_json_sha256=hashlib.sha256(body).hexdigest(), receipt_blob_sha=receipt['sha'],
            race_count=index['race_count'], model_forecast_count=len(rows),
            distinct_model_count=len({row['model_id'] for row in rows}),
            before_cutoff_race_count=len({row['race_id'] for row in rows}),
            before_cutoff_model_forecast_count=len(rows), artifacts_verified=3, companions_verified=2,
            companion_artifact_ids=sorted(companion_artifacts),
            independent_readback_verified=True, new_forecasts_created=0,
            provider_requests=0, plaintext_published=False, scoring_performed=False)
        if verify_retained_p1:
            stage = 'P1'
            report['p1_readback'] = _retained_p1_report(repo, vault_commit=vault_commit, day=day,
                source_run=source_run, source_sha=source_sha, verification_run=verification_run,
                transport=git)
        return report, document, rows, metadata
    except _Rejected:
        raise
    except Exception:
        raise _Rejected('FIRST_P0_READBACK_' + stage + '_REJECTED') from None


def _retained_p1_report(repo, *, vault_commit, day, source_run, source_sha,
                        verification_run, transport):
    """Read this producer's existing encrypted P1s, never infer or fetch sources."""
    from race_ai.first_receipt_continuity import first_receipt_rows
    locators = V.list_originals(day[:7], repo, source_commit=vault_commit,
                               run_id=source_run, transport=transport)
    proofs = []; all_rows = []; empty = 0
    fields = ('race_id', 'stage', 'model_id', 'as_of', 'cutoff_at', 'server_saved_at',
              'artifact_id', 'original_json_sha256', 'model_sha256')
    selected = [locator for locator in locators if locator['kind'] == 'P1']
    for locator in sorted(selected, key=lambda item: item['artifact_id']):
        _need(locator['source_commit'] == vault_commit, 'P1_LOCATOR_COMMIT_INVALID')
        value = V.restore_original(locator, repo, transport=transport)
        metadata = value['metadata']; run = metadata['workflow_run']
        _need(metadata['id'] == locator['artifact_id'] and run['id'] == source_run
              and run['head_sha'] == source_sha and source_run != verification_run
              and value['provenance']['source_commit'] == vault_commit
              and value['provenance']['independent_git_readback_verified'] is True,
              'P1_SOURCE_IDENTITY_INVALID')
        document, rows = read_p1(value['raw_zip'], metadata)
        _need(document.get('event_day') == day
              and V._time(metadata['created_at']).astimezone(V.JST).date().isoformat() == day,
              'P1_DAY_INVALID')
        for row in rows:
            _need(row['stage'] == 'P1' and type(row['race_id']) is str
                  and re.fullmatch(day.replace('-', '') + r'-\d{2}-\d{2}', row['race_id'])
                  and 1 <= int(row['race_id'][9:11]) <= 24
                  and 1 <= int(row['race_id'][12:14]) <= 12,
                  'P1_RACE_DAY_INVALID')
        with native._checked_zip(value['raw_zip'], max_zip_bytes=V.MAX_ORIGINAL) as archive:
            _need(archive.namelist() == [native.CIPHER_MEMBER], 'P1_ENCRYPTED_ORIGINAL_REQUIRED')
            cipher = archive.read(native.CIPHER_MEMBER)
        header, _, _, _ = native._split(cipher)
        bindings = [{field: row[field] for field in fields} for row in rows]
        proofs.append(dict(artifact_id=metadata['id'], server_created_at=metadata['created_at'],
            zip_sha256=hashlib.sha256(value['raw_zip']).hexdigest(),
            cipher_sha256=hashlib.sha256(cipher).hexdigest(),
            inner_zip_sha256=header['plain_zip_sha256'],
            metadata_sha256=hashlib.sha256(value['metadata_raw']).hexdigest(),
            json_sha256=rows[0]['original_json_sha256'] if rows else None,
            model_forecast_count=len(rows),
            forecast_binding_sha256=hashlib.sha256(V._wire(bindings)).hexdigest()))
        empty += not rows
        all_rows.extend(rows)
    rows, excluded = first_receipt_rows(all_rows)
    proven = len(rows) > 0
    status = ('P1_INDEPENDENT_READBACK_VERIFIED' if proven else
              'P1_EMPTY_ORIGINALS_ONLY' if proofs else 'P1_NOT_RETAINED')
    bindings = [{field: row[field] for field in fields} for row in rows]
    return dict(status=status, coverage_scope='SAME_RUN_RETAINED_BASELINE_P1_ONLY',
        day_jst=day, source_run_id=source_run, source_sha=source_sha,
        verification_run_id=verification_run, vault_commit=vault_commit,
        artifacts_verified=len(proofs), empty_artifacts=empty, artifacts=proofs,
        race_count=len({row['race_id'] for row in rows}), model_forecast_count=len(rows),
        distinct_model_count=len({row['model_id'] for row in rows}),
        excluded_repeat_forecasts=len(excluded),
        forecast_binding_sha256=hashlib.sha256(V._wire(bindings)).hexdigest(),
        before_cutoff_model_forecast_count=len(rows), generation_storage_proven=proven,
        independent_readback_verified=proven, new_forecasts_created=0,
        provider_requests=0, plaintext_published=False, scoring_performed=False)


def main(argv=None, *, transport=None, receipt_get=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT))
    parser.add_argument('--vault-commit', required=True)
    parser.add_argument('--receipt-commit', required=True)
    parser.add_argument('--day', required=True)
    parser.add_argument('--p0-artifact', type=int, required=True)
    parser.add_argument('--companion-artifact', type=int, action='append', required=True)
    parser.add_argument('--verify-retained-p1', action='store_true',
                        help='Also authenticate same-run retained baseline P1 without any source requests')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        report, _, _, _ = verify(args.repo_root, vault_commit=args.vault_commit,
            receipt_commit=args.receipt_commit, day=args.day, p0_artifact=args.p0_artifact,
            companion_artifacts=args.companion_artifact, transport=transport, receipt_get=receipt_get,
            verify_retained_p1=args.verify_retained_p1)
        output = vaultCLI._private_path(args.output, Path(args.repo_root).resolve(), exists=False)
        vaultCLI._write(output, V._wire(report) + b'\n')
        print(V._wire(report).decode('utf-8'))
        return 0
    except Exception as exc:
        reason = str(exc) if isinstance(exc, _Rejected) else 'FIRST_P0_READBACK_OPERATION_REJECTED'
        print(V._wire(dict(status='FIRST_P0_READBACK_REJECTED', reason=reason,
            new_forecasts_created=0, provider_requests=0, plaintext_published=False)).decode('utf-8'))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
