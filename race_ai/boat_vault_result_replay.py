"""Replay exact retained PC results into an existing feed, without source access."""
from copy import deepcopy
from datetime import date, datetime, timezone
import os
from pathlib import Path
import re
import stat

from . import boat_private_original_vault as V, cycle_recovery as C, saved_view_feed as F
from .boat_history_store import instant, wire
from .saved_result_sync import _merge

SCHEMA = 'RACE_AI_BOAT_VAULT_RESULT_REPLAY_INPUT_V1'
MAX_BYTES = 512*1024*1024


def _need(ok, reason):
    if not ok:
        raise ValueError('FEED_VAULT_REPLAY_'+reason)


def validate_config(value):
    _need(type(value) is dict and set(value) == {'schema','run_id','head_sha','day',
        'result_artifact_id','expected_capture_count','capture_locator'} and value['schema'] == SCHEMA,
        'CONFIG_INVALID')
    V._id(value['run_id']); V._id(value['result_artifact_id']); V._hex(value['head_sha'], V._HEAD)
    _need(type(value['day']) is str and date.fromisoformat(value['day']).isoformat() == value['day'], 'DAY_INVALID')
    _need(type(value['expected_capture_count']) is int and 1 <= value['expected_capture_count'] <= 240,
          'CAPTURE_COUNT_INVALID')
    V._validate_locator(value['capture_locator'])
    _need(value['capture_locator']['kind'] == 'SOURCE_CAPTURES', 'CAPTURE_LOCATOR_INVALID')
    return value


def read_config(repo, value):
    repo=Path(repo).resolve(); path=Path(value)
    if not path.is_absolute(): path=repo/path
    _need('..' not in path.parts and path.is_relative_to(repo/'audit'/'state') and path.suffix == '.json'
          and not any(p.is_symlink() for p in (path,*path.parents)), 'CONFIG_PATH_INVALID')
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        info=os.fstat(stream.fileno())
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 16384, 'CONFIG_BOUND')
        return validate_config(V._json(stream.read(16385),16384))


class _PinnedReads:
    def __init__(self, git):
        self._git=git; self.repo=git.repo; self.ref=git.ref; self.used=0; self.commit_id=git.head()
        V._hex(self.commit_id,V._HEAD)
    def head(self): return self.commit_id
    def fetch(self, commit): return self._git.fetch(commit)
    def exists(self, commit, path): return self._git.exists(commit,path)
    def read(self, commit, path, limit):
        _need(self.used < MAX_BYTES,'READ_BOUND')
        raw=self._git.read(commit,path,min(limit,MAX_BYTES-self.used))
        self.used+=len(raw); _need(self.used <= MAX_BYTES,'READ_BOUND')
        return raw


def _receipt_identity(observation):
    rid=observation.get('race_id'); _need(type(rid) is str and re.fullmatch(r'\d{8}-\d{2}-\d{2}',rid), 'RACE_INVALID')
    V._hex(observation.get('source_sha256'))
    _need(type(observation.get('source_url')) is str, 'SOURCE_URL_INVALID')
    return rid,instant(observation['captured_at']),observation['source_sha256'],observation['source_url']


def _pc_identity(receipt):
    from .official_race_updates import identity, endpoint
    source=receipt.get('source_url')
    _need(type(source) is str, 'SOURCE_URL_INVALID')
    day,venue,number=identity(source,path='/owpc/pc/race/raceresult')
    event=date(int(day[:4]),int(day[4:6]),int(day[6:8]))
    _need(endpoint(event,venue,number,'raceresult') == source, 'SOURCE_URL_INVALID')
    return event.isoformat(), day+'-'+venue+f'-{number:02d}'


def load_evidence(repo, config, *, key=None, transport=None, now=None):
    key=V.state_key('production',key); config=validate_config(config)
    now=now or datetime.now(timezone.utc); _need(now.utcoffset() is not None,'CLOCK_INVALID')
    _need(date.fromisoformat(config['day']) <= now.astimezone(V.JST).date(),'FUTURE_DAY')
    git=_PinnedReads(V._transport(repo,transport))
    locator=V.lookup_original(config['result_artifact_id'],repo,source_commit=git.head(),key=key,transport=git)
    _need(locator is not None and locator['kind'] == 'RESULT','RESULT_ORIGINAL_REQUIRED')
    result=V.restore_original(locator,repo,key=key,transport=git); metadata=result['metadata']
    _need(metadata['id'] == config['result_artifact_id'] and metadata['workflow_run']['id'] == config['run_id']
          and metadata['workflow_run']['head_sha'] == config['head_sha'], 'RESULT_SCOPE_MISMATCH')
    created=instant(metadata['created_at']); _need(created <= now,'RESULT_CLOCK_INVALID')
    _need(C._result_day(result['raw_zip'],metadata,key=key) == config['day'],'RESULT_DAY_MISMATCH')
    journal=C.result_archive(result['raw_zip'],metadata,config['day'],key=key)
    _merge(journal)
    for observation in journal:
        _need(instant(observation['captured_at']) <= created,'OBSERVATION_CLOCK_INVALID')
    capture_locator=config['capture_locator']; git.fetch(capture_locator['source_commit'])
    _,mac=V._keys(key)
    reference={name:capture_locator[name] for name in ('batch_path','batch_sha256','entry_sha256','artifact_id','kind')}
    summary=V._batch_entry(git,capture_locator['source_commit'],reference,mac)['header']['summary']
    _need(summary['run_id'] == config['run_id'] and summary['head_sha'] == config['head_sha'], 'CAPTURE_SCOPE_MISMATCH')
    _need(summary['capture_count'] == config['expected_capture_count'],'CAPTURE_COUNT_MISMATCH')
    retained=V.restore_capture_bundle(capture_locator,repo,key=key,transport=git)['captures']
    _need(len(retained) == config['expected_capture_count'],'CAPTURE_COUNT_MISMATCH')
    captures=[]
    for raw,receipt_raw in retained:
        receipt=V._json(receipt_raw,16384)
        _need(instant(receipt['captured_at']) <= created,'CAPTURE_CLOCK_INVALID')
        captures.append((raw,receipt))
    return journal,captures,dict(journal_observations=len(journal),retained_capture_records=len(captures),
                                 vault_blob_bytes_read=git.used)


def prepare(view, journal, captures, *, day, synced_at):
    clock=instant(synced_at); before=deepcopy(view)
    selected={r['race_id']:r for r in view['records'] if r.get('sport') == 'boat' and r['event_date_jst'] == day}
    _need(bool(selected),'SAVED_DAY_REQUIRED')
    counts=dict(selected_journal_observations=0,out_of_scope_observations=0,out_of_scope_captures=0,
        unselected_captures=0,metadata_captures=0,unmatched_not_newer_captures=0,
        applied_capture_records=0,new_observations=0,duplicate_observations=0)
    old={}
    for row in selected.values():
        for item in _merge(row.get('result_observations',[])):
            old[(item['race_id'],instant(item['captured_at']))]=item
    incoming=[]; known=dict(old); new=[]
    for item in _merge(journal):
        if item['race_id'] not in selected:
            counts['out_of_scope_observations']+=1; continue
        counts['selected_journal_observations']+=1
        identity=_receipt_identity(item); _need(identity[1] <= clock,'OBSERVATION_CLOCK_INVALID')
        slot=identity[:2]; previous=old.get(slot)
        _need(previous is None or wire(previous) == wire(item),'OBSERVATION_CONFLICT')
        if previous is None:
            new.append(item);counts['new_observations']+=1
        else:counts['duplicate_observations']+=1
        known[slot]=item;incoming.append(previous if previous is not None else item)
    bound=[]; matched=set(); seen=set()
    for raw,receipt in captures:
        _need(receipt.get('http_status') == 200 and V._sha(raw) == receipt.get('source_sha256'),'CAPTURE_HASH_MISMATCH')
        at=instant(receipt['captured_at']); _need(at <= clock,'CAPTURE_CLOCK_INVALID')
        source=receipt.get('source_url')
        if type(source) is str and source.startswith('https://api.github.com/') and V._capture_url(source):
            counts['metadata_captures']+=1;continue
        capture_day,rid=_pc_identity(receipt)
        if capture_day != day:
            counts['out_of_scope_captures']+=1;continue
        if rid not in selected:
            counts['unselected_captures']+=1;continue
        identity=_receipt_identity(dict(receipt,race_id=rid))
        _need(identity not in seen,'CAPTURE_DUPLICATE');seen.add(identity)
        item=known.get(identity[:2])
        if item is None:
            latest=max((instant(o['captured_at']) for o in known.values() if o['race_id']==rid),default=None)
            _need(latest is not None and at <= latest,'NEWER_UNMATCHED_CAPTURE')
            counts['unmatched_not_newer_captures']+=1;continue
        _need(_receipt_identity(item) == identity,'CAPTURE_OBSERVATION_MISMATCH')
        matched.add(identity);bound.append((raw,receipt))
        if not any(_receipt_identity(o) == identity for o in incoming):incoming.append(item)
    _need(all(_receipt_identity(item) in matched for item in new),'NEW_OBSERVATION_CAPTURE_REQUIRED')
    counts['applied_capture_records']=len(bound)
    updated=F.update_view(view,incoming,captures=bound,synced_at=synced_at)
    _need(F.originals_sha(updated) == F.originals_sha(before)
          and F.forecast_inventory(updated) == F.forecast_inventory(before),'ORIGINAL_CHANGED')
    after={r['race_id']:r for r in updated['records']}
    for row in before['records']:
        current=after[row['race_id']]
        _need(current.get('result_revisions',[]) == row.get('result_revisions',[]),'REVISION_CHANGED')
        kept={wire(o) for o in current.get('result_observations',[])}
        _need(all(wire(o) in kept for o in row.get('result_observations',[])),'OBSERVATION_CHANGED')
        if row['race_id'] not in selected:_need(current == row,'OUT_OF_SCOPE_CHANGED')
    counts['changed_races']=sum(row != after[row['race_id']] for row in before['records'])
    if not counts['changed_races']:updated=deepcopy(before)
    return updated,counts


class _HistoricalReader:
    def __init__(self, git, commit):self.git=git;self.commit=commit
    def head(self):return self.commit
    def __getattr__(self, name):return getattr(self.git,name)


def replay(repo, config, *, day, bootstrap, feed=None, vault=None, readback=None, key=None, now=None, validate_view):
    key=V.state_key('production',key); config=validate_config(config)
    _need(day == config['day'],'EXPLICIT_DAY_REQUIRED')
    now=now or datetime.now(timezone.utc)
    git=feed or F.FeedRepository(repo)
    parent,previous,generation,before=F.current_view(git,bootstrap,day=day)
    _need(parent is not None and generation > 0,'EXISTING_FEED_REQUIRED')
    journal,captures,evidence=load_evidence(repo,config,key=key,transport=vault,now=now)
    updated,counts=prepare(before,journal,captures,day=day,synced_at=now.isoformat())
    try:validate_view(updated)
    except Exception:raise ValueError('FEED_VAULT_REPLAY_READER_REJECTED') from None
    publication=None
    if counts['changed_races']:
        publication=F.publish_view(git,bootstrap,updated,parent=parent,previous=previous,generation=generation)
    reader=readback or F.FeedRepository(repo)
    restored_parent,_,restored_generation,restored=F.current_view(reader,bootstrap,day=day)
    expected_parent=publication['commit'] if publication else parent
    _need(restored_parent == expected_parent and restored_generation == generation+bool(publication)
          and wire(restored) == wire(updated),'READBACK_MISMATCH')
    retained=F.current_view(_HistoricalReader(reader,parent),bootstrap,day=day)[3]
    _need(wire(retained) == wire(before),'PREVIOUS_GENERATION_CHANGED')
    return dict(schema='RACE_AI_BOAT_VAULT_RESULT_REPLAY_COUNTS_V1',status='VAULT_RESULTS_REPLAYED',
        **evidence,**counts,generation=restored_generation,readback_verified=True,
        previous_generation_verified=True,original_observations_preserved=True,originals_changed=False,
        source_requests=0,live_artifact_requests=0,forecasting_performed=False,
        source_state_saved=False,plaintext_published=False,capture_completeness_claimed=False)
