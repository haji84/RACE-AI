"""Operator pipeline: scoped collection -> approved store -> optional private Blob.

Dry-run is the default and performs no source, filesystem or cloud mutations.
Only independently reviewed rights/approval files can authorize execution;
there is deliberately no CLI flag that manufactures those records.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import sys

from .blob_key import day_blob_key
from .blob_sdk_roundtrip import upload_and_verify
from .day_feed_store import write_day_snapshot
from .official_racelist_worker import source_scope
from .tokuyama_day_worker import collect_tokuyama_day, endpoint, SOURCE_SCOPE
from .venue_source_rights import RightsRecord


def run_pipeline(*, day: date, index_rights: list[RightsRecord],
                 detail_rights: list[RightsRecord], approval: dict, store: Path,
                 execute: bool = False, upload_blob: bool = False,
                 now: datetime | None = None, index_transport=None,
                 detail_transport=None, blob_client=None) -> dict:
    if upload_blob and not execute:
        raise ValueError('Blob upload requires explicit execution')
    report = dict(date_jst=day.isoformat(), pathname=day_blob_key(day),
                  maximum_source_requests=13, source_originals_retained=False)
    if not execute:
        return {**report, 'status': 'DRY_RUN', 'network_requests': 0,
                'index_source_scope': SOURCE_SCOPE, 'detail_source_scope': source_scope('18'),
                'publication_approval_required': True, 'cloud_upload': False}
    collected = collect_tokuyama_day(day, rights=index_rights, detail_rights=detail_rights,
        now=now, transport=index_transport, detail_transport=detail_transport)
    if 'snapshot' not in collected:
        return {**report, 'status': collected['status'], 'cloud_upload': False}
    try:
        saved = write_day_snapshot(store, collected['snapshot'], approval, today=day)
    except (ValueError, TypeError, KeyError):
        return {**report, 'status': 'PUBLICATION_BLOCKED', 'cloud_upload': False}
    report.update(local_snapshot=str(saved), cloud_upload=False)
    if not upload_blob:
        return {**report, 'status': 'APPROVED_LOCAL_SNAPSHOT'}
    owned_client = blob_client is None
    try:
        if owned_client:
            token = os.environ.get('BLOB_READ_WRITE_TOKEN')
            if not token:
                return {**report, 'status': 'BLOB_STORE_NOT_CONFIGURED'}
            from vercel.blob import BlobClient
            blob_client = BlobClient(token=token)
        uploaded = upload_and_verify(blob_client, store, day=day, execute=True)
        return {**report, 'status': uploaded['status'], 'cloud_upload': True,
                'sha256': uploaded['sha256']}
    except Exception:
        # Never serialize provider errors that may include credentials.
        return {**report, 'status': 'BLOB_UPLOAD_OR_READBACK_FAILED'}
    finally:
        if owned_client and blob_client is not None:
            try:
                blob_client.close()
            except Exception:
                pass


def read_json(path):
    if path.stat().st_size > 1_000_000:
        raise ValueError('configuration too large')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_rights(path):
    values = read_json(path)
    if not isinstance(values, list):
        raise ValueError('rights file must contain a list')
    return [RightsRecord(**value) for value in values]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, type=date.fromisoformat)
    parser.add_argument('--index-rights', required=True, type=Path)
    parser.add_argument('--detail-rights', required=True, type=Path)
    parser.add_argument('--approval', required=True, type=Path)
    parser.add_argument('--store', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--upload-blob', action='store_true')
    args = parser.parse_args()
    try:
        result = run_pipeline(day=args.date, index_rights=read_rights(args.index_rights),
            detail_rights=read_rights(args.detail_rights), approval=read_json(args.approval),
            store=args.store, execute=args.execute, upload_blob=args.upload_blob)
        print(json.dumps(result, ensure_ascii=False))
        if result['status'] not in {'DRY_RUN', 'APPROVED_LOCAL_SNAPSHOT', 'BLOB_ROUNDTRIP_VERIFIED'}:
            raise SystemExit(2)
    except (ValueError, TypeError, OSError):
        print('SAFE_STOP: invalid operator configuration', file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
