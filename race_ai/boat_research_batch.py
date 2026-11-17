"""Bounded immutable transfer batches; callers authenticate every input first."""
from pathlib import Path
import re

from .boat_pdca_github_handoff import TRANSFER_REF
from .boat_private_original_vault import VaultGitRepository, _independent_reader
from .boat_venue_dataset import _sha
from .teiai_history import need
from scripts.boat_all_racers import _read


PREFIX = 'state/boat-venue-history/v1/'
_REMOTE = re.compile(re.escape(PREFIX) + r'(?:learning/[a-f0-9]{64}/(?:learning\.json|learning\.enc|summary\.json)'
                     r'|research-archives/[a-f0-9]{64}/(?:archive\.zip|metadata\.json|manifest\.json))\Z')


def file_snapshot(path, limit, raw):
    """Bind a bounded, already authenticated local file without retaining its bytes."""
    return (Path(path), limit, len(raw), _sha(raw))


def _body(source):
    if type(source) is bytes:
        return source
    path, limit, size, digest = source
    absolute = path.absolute()
    need('..' not in absolute.parts and not any(p.is_symlink() for p in (absolute, *absolute.parents)),
         'VENUE_RESEARCH_BATCH_SOURCE_PATH_INVALID')
    raw = _read(path, limit)
    need(len(raw) == size and _sha(raw) == digest, 'VENUE_RESEARCH_BATCH_SOURCE_CHANGED')
    return raw


def _size(source):
    return len(source) if type(source) is bytes else source[2]


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
            for item in group:
                for path, body in item.items():
                    need(reader.read(commit, path, maximum_bytes) == body,
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
