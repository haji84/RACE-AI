"""Read exact video contexts from independently authenticated existing-run ZIPs.

The caller supplies its normal authenticated GitHub API reader. A local JSON
receipt, a context seal, and a producer's claim do not authenticate storage.
This adapter reads artifact metadata, the producer run, and the actual bytes.
It neither captures video nor uploads an artifact or certifies field accuracy.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import io
import json
import re
import zipfile

from .boat_video_model_context import validate_video_context
from .boat_observed_pairwise_models import MODEL_IDS
from .frozen_day_cycle import check_clock, official_id, ts
from .repeated_cycle import matches


SCHEMA = 'RACE_AI_BOAT_VIDEO_CONTEXT_ARCHIVE_V1'
MEMBER = 'video-contexts.json'
REPOSITORY_ID = 1416489937
WORKFLOW_IDS = (405276784,392270247)
BRANCH = 'feat/four-sport-forecast-audit-view-20261022'
MAX_BYTES = 32 * 1024 * 1024
_ERROR = 'BOAT_VIDEO_ARCHIVE_REJECTED'
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_HEAD = re.compile(r'[a-f0-9]{40}\Z')
_VIDEO_SHADOW = 'RACE_AI_EXISTING_OBSERVED_VIDEO_SHADOW_V1'


def _need(ok):
    if not ok:
        raise ValueError(_ERROR)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result)
        result[key] = value
    return result


def _json(raw, limit=MAX_BYTES):
    _need(type(raw) is bytes and 0 < len(raw) <= limit)
    def reject_constant(_):
        raise ValueError(_ERROR)
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=reject_constant)


def _context(value):
    return validate_video_context(value, race_id=value['race_id'],
        cutoff_at=value['cutoff_at'], as_of=value['as_of'],
        roster=[dict(lane=p['lane'], registration_number=p['registration_number'])
                for p in value['participants']])


def read_optional_video_shadows(document, receipt, baseline_rows, *, receipt_verifier):
    """Keep mandatory originals strict; isolate rejected optional video rows.

    Existing non-video candidates are replayed strictly first. The full replay
    still checks mixed/duplicate family claims, but a video-source failure must
    not discard separately authenticated baseline or non-video originals.
    """
    from .observed_weight_learning import read_shadow_rows
    records=document.get('learned_pairwise_shadows',[])
    videos=[record for record in records if type(record) is dict and record.get('schema')==_VIDEO_SHADOW]
    if not videos:
        return read_shadow_rows(document,receipt,baseline_rows),[]
    nonvideo=deepcopy(document)
    nonvideo['learned_pairwise_shadows']=[record for record in records
        if not (type(record) is dict and record.get('schema')==_VIDEO_SHADOW)]
    strict_rows=read_shadow_rows(nonvideo,receipt,baseline_rows)
    try:
        return read_shadow_rows(document,receipt,baseline_rows,
            video_receipt_verifier=receipt_verifier),[]
    except (ValueError,KeyError,TypeError):
        return strict_rows,[dict(forecast_artifact_id=receipt['id'],rejected_shadows=len(videos),
                                 reason='VIDEO_SHADOW_REPLAY_REJECTED')]


def validate_optional_video_training(rows, proofs):
    """A missing optional-video training parent cannot suppress baseline rows."""
    from .observed_weight_learning import validate_shadow_training
    ordinary=[row for row in rows if row.get('variant')!='LEARNED_VIDEO_EXPERIMENTAL']
    validate_shadow_training(ordinary,proofs)
    accepted,rejected=[],[]
    for row in rows:
        if row.get('variant')=='LEARNED_VIDEO_EXPERIMENTAL':
            try:
                validate_shadow_training([row],proofs)
            except (ValueError,KeyError,TypeError):
                rejected.append(dict(forecast_artifact_id=row['artifact_id'],rejected_shadows=1,
                                     reason='VIDEO_SHADOW_TRAINING_RECEIPT_REJECTED'))
                continue
        accepted.append(row)
    return accepted,rejected


class VideoContextArchiveReader:
    """Invocation-local authenticated cache, never a serialized verifier.

    ``load`` accepts artifact IDs, not local verification declarations. Source
    producers must use an already authorized existing workflow/branch and save
    ``video-contexts.json`` in ``race-video-context-<run>[-cycle-N]``. No such
    producer is started or installed by this reader. An optional source remains
    inactive until those actual pre-cutoff artifacts exist.
    """
    def __init__(self, get, *, clock=None, allowed_workflow_ids=WORKFLOW_IDS,owner_key=None):
        _need(callable(get) and type(allowed_workflow_ids) is tuple and
              0 < len(allowed_workflow_ids) <= 8 and
              all(type(value) is int and value in WORKFLOW_IDS for value in allowed_workflow_ids))
        self.get, self.clock = get, clock or (lambda: datetime.now(timezone.utc))
        self.workflow_ids = allowed_workflow_ids
        self._owner_key=owner_key
        self._archives = {}

    @property
    def artifact_ids(self):
        return sorted(self._archives)

    def _now(self):
        value = self.clock()
        _need(type(value) is datetime and value.utcoffset() is not None)
        return value

    def _load(self, ident):
        _need(type(ident) is int and ident > 0)
        if ident in self._archives:
            return self._archives[ident]
        meta = _json(self.get(f'actions/artifacts/{ident}'), 2*1024*1024)
        _need(type(meta) is dict and type(meta.get('id')) is int and
              meta['id'] == ident and meta.get('expired') is False)
        # Reject a known oversized object before the callback buffers its ZIP.
        # API declaration, returned ZIP length and decompressed member size are
        # separate admission bounds; do not assume their size semantics equal.
        _need(type(meta.get('size_in_bytes')) is int and 0 < meta['size_in_bytes'] <= MAX_BYTES)
        source = meta['workflow_run']; run_id = source['id']
        _need(type(run_id) is int and run_id > 0 and
              source.get('head_repository_id') == REPOSITORY_ID and
              source.get('head_branch') == BRANCH and
              type(source.get('head_sha')) is str and _HEAD.fullmatch(source['head_sha']) and
              matches(meta.get('name'), f'race-video-context-{run_id}'))
        producer = _json(self.get(f'actions/runs/{run_id}'), 2*1024*1024)
        _need(type(producer) is dict and type(producer.get('id')) is int and producer['id'] == run_id and
              producer.get('workflow_id') in self.workflow_ids and
              producer.get('repository', {}).get('id') == REPOSITORY_ID and
              producer.get('head_repository', {}).get('id') == REPOSITORY_ID and
              producer.get('head_branch') == BRANCH and
              producer.get('head_sha') == source['head_sha'] and
              producer.get('status') in ('in_progress', 'completed'))
        encrypted=producer['workflow_id']==392270247
        _need(producer.get('event')=='workflow_dispatch' if encrypted else
              producer.get('event') in ('push','workflow_dispatch'))
        saved = ts(meta['created_at'])
        _need(ts(producer['created_at']) <= saved <= self._now())
        raw = self.get(f'actions/artifacts/{ident}/zip')
        _need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and
              meta.get('digest') == 'sha256:'+hashlib.sha256(raw).hexdigest())
        with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
            member='video-context.enc' if encrypted else MEMBER
            _need(bundle.namelist() == [member])
            info = bundle.getinfo(member)
            _need(0 < info.file_size <= MAX_BYTES and not info.flag_bits & 1 and
                  (info.external_attr >> 16) & 0o170000 != 0o120000)
            _need(bundle.testzip() is None)
            body=bundle.read(info)
            if encrypted:
                # Public-repository artifacts keep ciphertext. Actual API run
                # HEAD and receipt time supply the decryption/authentication
                # scope; caller/embedded JSON claims cannot replace them.
                from .boat_video_publication import decrypt_publication
                document,_=decrypt_publication(body,expected_head_sha=producer['head_sha'],
                    key=self._owner_key,available_at=meta['created_at'])
            else:
                document = _json(body)
        _need(type(document) is dict and set(document) == {'schema', 'contexts'} and
              document['schema'] == SCHEMA and type(document['contexts']) is list and
              0 < len(document['contexts']) <= 2048)
        contexts = {}
        for candidate in document['contexts']:
            context = _context(candidate)
            key = context['context_sha256']
            _need(key not in contexts)
            check_clock(context['as_of'], context['cutoff_at'], meta['created_at'])
            contexts[key] = context
        entry = dict(receipt=deepcopy(meta), contexts=contexts)
        self._archives[ident] = entry
        return entry

    def load(self, artifact_ids):
        """Authenticate all requested source archives, returning no raw summary."""
        try:
            _need(type(artifact_ids) in (list, tuple) and len(artifact_ids) <= 10000 and
                  all(type(ident) is int and ident > 0 for ident in artifact_ids))
            for ident in sorted(set(artifact_ids)):
                self._load(ident)
            return self
        except Exception:
            # API/ZIP/decoder failures can contain private URLs or paths.
            raise ValueError(_ERROR) from None

    def verify(self, receipt, context_sha256, as_of):
        """Re-read API/bytes on first use; return the exact four-field proof."""
        try:
            _need(type(receipt) is dict and type(context_sha256) is str and
                  _SHA.fullmatch(context_sha256))
            entry = self._load(receipt['id'])
            _need(receipt == entry['receipt'] and context_sha256 in entry['contexts'])
            context = entry['contexts'][context_sha256]
            instant, saved = ts(as_of), ts(receipt['created_at'])
            _need(ts(context['as_of']) <= instant and
                  saved+timedelta(seconds=1) <= instant <= self._now())
            _need(instant < ts(context['cutoff_at']))
            return dict(context_sha256=context_sha256, id=receipt['id'],
                        digest=receipt['digest'], created_at=receipt['created_at'])
        except Exception:
            raise ValueError(_ERROR) from None

    def select(self, snapshot):
        """Select only a matching context independently stored before input.

        Newer contexts are never rebound to an older training snapshot. P0 has
        no current-exhibition video input. A missing eligible source is None.
        """
        try:
            if snapshot['stage'] != 'P1':
                return None
            race = official_id(snapshot['race_id'])
            roster = {p['lane']: p['registration_no'] for p in snapshot['participants']}
            instant = ts(snapshot['as_of'])
            _need(instant <= self._now())
            options = []
            for entry in self._archives.values():
                receipt = entry['receipt']
                saved = ts(receipt['created_at'])
                if saved+timedelta(seconds=1) > instant:
                    continue
                for context in entry['contexts'].values():
                    if (context['eligible_for_research'] is True and context['race_id'] == race and
                        ts(context['cutoff_at']) == ts(snapshot['sales_cutoff_at']) and
                        {p['lane']:p['registration_number'] for p in context['participants']} == roster and
                        ts(context['as_of']) <= instant < ts(context['cutoff_at'])):
                        # The full validator uses the original exact cutoff
                        # string, so a time-equivalent but rebound input is not
                        # quietly accepted by the model's stricter contract.
                        if context['cutoff_at'] != snapshot['sales_cutoff_at']:
                            continue
                        options.append((ts(context['as_of']), saved, receipt['id'],
                            context['context_sha256'], context, receipt))
            if not options:
                return None
            *_, context, receipt = max(options, key=lambda value:value[:4])
            return dict(video_context=deepcopy(context), receipt=deepcopy(receipt))
        except Exception:
            raise ValueError(_ERROR) from None

    def contexts_for_rows(self, rows):
        """Match the existing fit's latest snapshot per race; do not fit here."""
        try:
            selected = {}
            for row in rows:
                snapshot = row.get('learning_snapshot')
                if snapshot is None or row.get('model_id') not in MODEL_IDS:
                    continue
                old = selected.get(row['race_id'])
                order = (ts(row['as_of']), row['stage'])
                if old is None or order > (ts(old['as_of']), old['stage']):
                    selected[row['race_id']] = row
            out = {}
            for race, row in selected.items():
                envelope = self.select(row['learning_snapshot'])
                if envelope is not None:
                    out[race] = envelope
            return out
        except Exception:
            raise ValueError(_ERROR) from None
