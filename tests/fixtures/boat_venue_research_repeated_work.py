# Verbatim isolated public functions from pinned A74; synthetic bindings only.
# scripts/github_existing_cycle.py blob5050704a1ca3a087154b59ccaecbc07b20739d18
# race_ai/boat_venue_research_retention.py blob6caf3fbc2cef217736df775e04e344f1bc823c15
# race_ai/boat_research_batch.py blob2f2cd3cde621ff051ca29cc6fa7d00b6be52c3f5
# No private archives, keys, models, provider pages or result records are included.

def venue_research_pdca(day,round_no):
    """Revisit all retained private handles using already-observed official results."""
    import tempfile
    from race_ai.boat_venue_research_receipt import validate_research_refs
    from race_ai.boat_venue_research_pdca import score_private_p1_artifact
    from race_ai.boat_pdca_state import state_key
    result=dict(status='PRIVATE_VENUE_PDCA_NOT_RUN',archives_processed=0,paired_forecasts=0,rejected_archives=0,
        production_promoted=False,plaintext_published=False,actual_purchases=False)
    try:
        state_key('production')
        need(type(round_no) is int and round_no>0,'VENUE_RESEARCH_ROUND_REQUIRED')
        continuity=load_state(ROOT/'cycle_recovery_output/continuity.json',day)
        references=validate_research_refs(continuity.get('venue_research_artifact_refs',[]))
        if references:
            observations=json.loads((ROOT/'existing_cycle_output/official-result-observations.json').read_text())
            latest,_=latest_result_observations(observations)
            private_base=Path(os.environ.get('RUNNER_TEMP',tempfile.gettempdir()))
            root=private_base/'boat-venue-research-pdca'/f'cycle-{round_no}'
            from scripts.boat_history_collect import private_root
            private_root(root)
            for reference in references:
                try:
                    ident=reference['artifact_id'];meta=json.loads(gh(f'actions/artifacts/{ident}'))
                    need(meta['digest']==reference['digest'],'VENUE_RESEARCH_ORIGINAL_DIGEST_CHANGED')
                    raw=gh(f'actions/artifacts/{ident}/zip')
                    archive_base=private_root(private_base/'boat-venue-research-archives')
                    archive=private_root(archive_base/str(ident))
                    from scripts.boat_history_collect import save
                    save(archive/'archive.zip',raw)
                    save(archive/'metadata.json',json.dumps(meta,sort_keys=True).encode())
                    if meta.get('name','').startswith('all-existing-model-pairs-'):
                        from race_ai.all_existing_model_pdca import _score_verified_private_pairs,RESULT_FIELDS
                        from race_ai.all_existing_model_receipt import _verified_private_pairs_artifact
                        from race_ai.all_existing_model_intake import _results
                        from race_ai.existing_model_dispatch import _race_key
                        now=datetime.now(timezone.utc)
                        admission,records=_verified_private_pairs_artifact(raw,meta,now=now,
                            expected_run_id=reference['run_id'],expected_head_sha=reference['head_sha'])
                        forecasts=[record for record in records if 'pair' in record]
                        wanted={(record['pair']['sport'],_race_key(record['pair']['race_id'],record['pair']['sport']))
                                for record in forecasts}
                        converted,_=_results(latest,now)
                        labels=[{key:item['result'][key] for key in RESULT_FIELDS} for identity,item in converted.items()
                                if identity in wanted and item['result']['status']!='pending']
                        scored=_score_verified_private_pairs(admission,records,labels,root/str(ident),now=now)
                    else:
                        scored=score_private_p1_artifact(raw,meta,latest,root/str(ident),now=datetime.now(timezone.utc),
                            expected_run_id=reference['run_id'],expected_head_sha=reference['head_sha'])
                    result['archives_processed']+=1
                    result['paired_forecasts']+=scored['paired_forecasts']
                except Exception:result['rejected_archives']+=1
        result['status']='PRIVATE_VENUE_PDCA_CIPHERTEXT_PREPARED'
    except Exception:result['status']='HOLD_PRIVATE_VENUE_PDCA'
    print(json.dumps(result,sort_keys=True));return result


def retain_private_source_archives(archives, repo, *, token=None, now=None, readback_transport=None):
    """Append original ciphertext ZIPs and cached actual metadata on TRANSFER_REF.

    Cached metadata must be the caller's actual GitHub response. Every archive
    undergoes the existing owner-decryption/native replay and external-clock
    checks before any Git operation. Expired receipts remain inadmissible;
    preserving their earlier evidence never creates a new GitHub receipt.
    """
    key = state_key('production')
    token = os.environ.get('GH_TOKEN', '') if token is None else token
    _need(type(token) is str and re.fullmatch('[A-Za-z0-9_.-]{20,512}', token), 'GITHUB_TOKEN_REQUIRED')
    now = datetime.now(timezone.utc) if now is None else now
    _need(type(now) is datetime and now.utcoffset() is not None, 'AWARE_CLOCK_REQUIRED')
    roots = _folders(archives, files=ARCHIVE_FILES)
    records = [_source_intake(root, now, key) for root in roots]
    from .boat_research_batch import publish_immutable_items
    items = []
    for record in records:
        prefix = PREFIX+'research-archives/'+record['archive_sha256']+'/'
        items.append({
            prefix+'archive.zip': (record['root']/'archive.zip', ARCHIVE_FILES['archive.zip'],
                                  record['archive_size_bytes'], record['archive_sha256']),
            prefix+'metadata.json': (record['root']/'metadata.json', ARCHIVE_FILES['metadata.json'],
                                    record['metadata_size_bytes'], record['metadata_sha256']),
            prefix+'manifest.json': record['manifest']})
    with _git_auth(token):
        git = GitStateRepository(repo, ref=TRANSFER_REF) if records else None
        commits = publish_immutable_items(items, repo, maximum_bytes=MAX_SOURCE_BATCH_BYTES,
            transport=git, readback_transport=readback_transport)
    pointers = []
    for record, commit in zip(records, commits):
        prefix = PREFIX+'research-archives/'+record['archive_sha256']+'/'
        pointers.append(dict(schema='RACE_AI_PRIVATE_SOURCE_ARCHIVE_INPUT_V1', status='READY',
            repository_id='1416489937', source_commit=commit, source_artifact_id=record['artifact_id'],
            archive_path=prefix+'archive.zip', archive_sha256=record['archive_sha256'],
            metadata_path=prefix+'metadata.json', metadata_sha256=record['metadata_sha256'],
            manifest_path=prefix+'manifest.json', manifest_sha256=_sha(record['manifest'])))
    return dict(status='OWNER_PRIVATE_SOURCE_ARCHIVES_RETENTION_VERIFIED', requested_archives=len(archives),
                retained_archives=len(pointers), pointers=pointers, plaintext_published=False, production_promoted=False)

def publish_immutable_items(items, repo, *, maximum_bytes, transport=None, readback_transport=None):
    """Append all authenticated items in bounded groups, never a total-count quota.

    Each item is a mapping of permitted immutable paths to frozen file snapshots
    or small manifest bytes. Existing rows and unrelated tree objects are kept.
    An independent object database reads every selected committed byte, including
    idempotent publications. Returned commits correspond to the original items.
    """
    need(type(items) is list and type(maximum_bytes) is int and maximum_bytes > 0,
         'VENUE_RESEARCH_BATCH_INPUT_INVALID')
    for item in items:
        need(type(item) is dict and bool(item) and all(type(path) is str and _REMOTE.fullmatch(path)
             for path in item), 'VENUE_RESEARCH_BATCH_NAMESPACE_INVALID')
        need(0 < sum(_size(body) for body in item.values()) <= maximum_bytes,
             'VENUE_RESEARCH_BATCH_ITEM_BOUND')
    if not items:
        return []
    writer = transport if transport is not None else VaultGitRepository(repo, ref=TRANSFER_REF)
    need(getattr(writer, 'ref', None) == TRANSFER_REF, 'VENUE_RESEARCH_BATCH_TRANSFER_REF_REQUIRED')
    commits = []
    with _independent_reader(writer, readback_transport) as reader:
        def publish(group):
            parent = writer.head()
            need(type(parent) is str and re.fullmatch('[a-f0-9]{40}', parent),
                 'VENUE_EXISTING_TRANSFER_REF_REQUIRED')
            writer.fetch(parent)
            additions = {}
            for item in group:
                for path, body in item.items():
                    if writer.exists(parent, path):
                        need(writer.read(parent, path, maximum_bytes) == body,
                             'VENUE_RESEARCH_BATCH_IMMUTABLE_FILE_CHANGED')
                    else:
                        need(path not in additions or additions[path] == body,
                             'VENUE_RESEARCH_BATCH_IMMUTABLE_FILE_CHANGED')
                        additions[path] = body
            commit = parent
            if additions:
                commit = writer.commit(additions, parent)
                need(type(commit) is str and re.fullmatch('[a-f0-9]{40}', commit),
                     'VENUE_RESEARCH_BATCH_COMMIT_INVALID')
                writer.push(commit, parent)
            reader.fetch(commit)
            read = reader.read
            prefetch = getattr(reader, 'prefetch_selected', None)
            if prefetch is not None:
                selected = {path: body for item in group for path, body in item.items()}
                read = prefetch(commit, selected, maximum_bytes=maximum_bytes)
            for item in group:
                for path, body in item.items():
                    need(read(commit, path, maximum_bytes) == body,
                         'VENUE_RESEARCH_BATCH_INDEPENDENT_READBACK_MISMATCH')
                commits.append(commit)

        group, size = [], 0
        for item in items:
            item_size = sum(_size(body) for body in item.values())
            if group and size + item_size > maximum_bytes:
                publish(group)
                group, size = [], 0
            group.append({path: _body(body) for path, body in item.items()})
            size += item_size
        if group:
            publish(group)
    return commits
