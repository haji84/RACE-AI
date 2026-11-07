"""Owner Actions-only preparation: encrypted plan/public request, zero authority."""
import argparse,json,os,re,stat
from copy import deepcopy
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path

from race_ai import all_existing_model_official_prepare as P
from race_ai import all_existing_model_official_issue as I
from race_ai import all_existing_model_official_recovery as R
from race_ai.boat_all_model_store import MAX_WIRE,forecast_header
from race_ai.boat_pdca_state import state_key
from race_ai.all_existing_model_official_issue_transport import GithubIssueTransport
from race_ai.permissioned_source_delivery import read_json_bytes
from scripts import all_existing_model_official_result_issue as issue
from scripts import all_existing_model_official_result_collect as collector
from scripts import all_existing_model_future_p0 as future
from scripts.boat_all_racers import _read,_write
from scripts.boat_history_collect import save

ROOT=Path(__file__).resolve().parents[1]


def utc_now():return datetime.now(timezone.utc)


class ReadOnlyGithub:
    """Only expose the four existing read methods; no POST/CAS interface."""
    def __init__(self,reader=None):self.__reader=reader if reader is not None else GithubIssueTransport()
    def json(self,path):return self.__reader.json(path)
    def archive(self,pin):return self.__reader.archive(pin)
    def head(self):return self.__reader.head()
    def read_file(self,commit,path,limit):return self.__reader.read_file(commit,path,limit)


class PrepareSnapshot(issue.GitSnapshot):
    def read(self,head,path,limit):
        if path!=P.PATH:return super().read(head,path,limit)
        P.need(I._hex(head) and type(limit) is int and 0<limit<=32768,'PREPARATION_PATH')
        row=self._git(['ls-tree',head,'--',path]).decode().strip()
        P.need(re.fullmatch('100644 blob [a-f0-9]{40}\\t'+re.escape(path),row) is not None,'PREPARATION_REGULAR_BLOB')
        size=int(self._git(['cat-file','-s',head+':'+path]));P.need(0<size<=limit,'PREPARATION_BOUND')
        raw=self._git(['show',head+':'+path]);P.need(len(raw)==size,'PREPARATION_BYTES');return raw
    def prepare_facts(self,value):
        source=value['previous_source'];parent=value['verified_parent']
        self._git(['merge-base','--is-ancestor',source['head_sha'],parent['head_sha']])
        return dict(self.facts,source_is_ancestor=True,recovery_raw=self.read(source['head_sha'],I.REQUEST_PATH,32768),
            latest_issue_raw=self.previous_issue(parent['head_sha']))


def _context(value,snapshot,prepare_run_id,reader,now):
    parent=value['verified_parent'];source=value['previous_source'];facts=snapshot.prepare_facts(value)
    context=P.admit_context(value,prepare_run=reader.json('actions/runs/'+str(prepare_run_id)),
        current_pr=reader.json('pulls/71'),snapshot=facts,
        parent_current=reader.json('actions/runs/'+str(parent['run_id'])),
        parent_first=reader.json('actions/runs/'+str(parent['run_id'])+'/attempts/1'),
        parent_jobs=reader.json('actions/runs/'+str(parent['run_id'])+'/attempts/1/jobs?per_page=100'),
        source_current=reader.json('actions/runs/'+str(source['run_id'])),
        source_first=reader.json('actions/runs/'+str(source['run_id'])+'/attempts/1'),
        source_jobs=reader.json('actions/runs/'+str(source['run_id'])+'/attempts/1/jobs?per_page=100'),now=now)
    return context,facts


def prepare_once(*,snapshot,prepare_run_id,reader,key_loader,clock=utc_now):
    value=P.validate_prepare_request(read_json_bytes(snapshot.read(snapshot.facts['head_sha'],P.PATH,32768)))
    context,facts=_context(value,snapshot,prepare_run_id,reader,clock())
    source=value['previous_source'];original=read_json_bytes(facts['recovery_raw'])
    names={'official-result-collection-journal-'+str(source['run_id']):source['journal_artifact'],
        'all-existing-official-results-'+str(source['run_id'])+'-900005':source['result_artifact']}
    listed=issue._artifact_list(reader,source['run_id']);outputs=[]
    for name,pin in names.items():
        rows=[row for row in listed if row.get('name')==name];P.need(len(rows)==1 and rows[0]['id']==pin['id'],'EXACT_PREVIOUS_OUTPUT')
        meta=reader.json('actions/artifacts/'+str(pin['id']))
        P.need(I.pin_from_metadata(meta)==pin and meta.get('name')==name,'PREVIOUS_OUTPUT_PIN');outputs.append(meta)
    # Existing native/result/MAC admission follows, using only Actions' key.
    key=key_loader()
    manifest=deepcopy(original['manifest'])
    for field,pin in (('prior_journal_artifacts',source['journal_artifact']),('checkpoint_artifacts',source['result_artifact'])):
        P.need(pin['id'] not in {p['id'] for p in manifest[field]},'FRESH_SOURCE_OUTPUT_PIN');manifest[field].append(pin)
    I.check_pin_continuity(manifest,previous_request=original,
        previous_run=reader.json('actions/runs/'+str(source['run_id'])),previous_artifacts=outputs)
    groups={field:[reader.archive(pin) for pin in manifest[field]] for field in I.PIN_FIELDS}
    P.need(sum(len(item['raw']) for rows in groups.values() for item in rows)<=256*1024*1024,'TOTAL_EVIDENCE_BOUND')
    old_pin=next(p for p in manifest['prior_journal_artifacts'] if p['id']==R.OLD_ARTIFACT)
    old=next(item for item in groups['prior_journal_artifacts'] if item['metadata']['id']==R.OLD_ARTIFACT)
    old_body,_=R._evidence(old['raw'],old['metadata'],old_pin,clock(),key)
    def plan_bytes(m):
        raw=snapshot.read(source['head_sha'],m['plan_path'],MAX_WIRE)
        P.need(type(raw) is bytes and sha256(raw).hexdigest()==m['plan_sha256'],'IMMUTABLE_PLAN_BYTES');return raw
    run_ids=sorted({p['run_id'] for p in manifest['prior_journal_artifacts']})
    runs={n:reader.json('actions/runs/'+str(n)) for n in run_ids}
    source_first=reader.json('actions/runs/'+str(source['run_id'])+'/attempts/1')
    path=R.capsule_path(original,source['head_sha'],source['run_id'])
    consumed=reader.read_file(reader.head(),path,MAX_WIRE);P.need(consumed is not None,'PREVIOUS_OWNER_CAPSULE')
    if value['kind']==P.SINGLE:
        probe=next(p for p in original['manifest']['prior_journal_artifacts'] if p['id']==original['probe_journal_artifact_id'])
        probe_first=reader.json('actions/runs/'+str(probe['run_id'])+'/attempts/1')
        I.run_scope(probe_first)
        from scripts.all_existing_model_official_result_recovery import _full_first_attempt
        _full_first_attempt(probe_first,reader.json('actions/runs/'+str(probe['run_id'])+'/attempts/1/jobs?per_page=100'),
            dict(run_id=probe['run_id'],head_sha=probe['head_sha']))
        path='recovery/official-results/'+original['probe_request_sha256']+'/'+probe['head_sha']+'/'+str(probe['run_id'])+'/2.enc'
        probe_capsule=reader.read_file(reader.head(),path,MAX_WIRE);P.need(probe_capsule is not None,'ORIGINAL_PROBE_CAPSULE')
    else:probe_first=source_first;probe_capsule=consumed
    data=dict(groups=groups,source_request=original,source_capsule_raw=consumed,source_first_attempt=source_first,
        source_current_run=reader.json('actions/runs/'+str(source['run_id'])),old_plan_raw=plan_bytes(old_body['manifest']),
        source_plan_raw=plan_bytes(original['manifest']),probe_capsule_raw=probe_capsule,probe_first_attempt=probe_first,
        old_run=runs[R.OLD_RUN],prior_runs=[runs[n] for n in run_ids if n!=R.OLD_RUN])
    result=P.prepare_from_evidence(value,data,context=context,run_id=prepare_run_id,head_sha=snapshot.facts['head_sha'],now=clock(),key=key)
    fresh,_=_context(value,snapshot,prepare_run_id,reader,clock())
    P.need(digest_context(context)==digest_context(fresh),'PREPARATION_CONTEXT_CHANGED')
    P.need(all(R.run_receipt(reader.json('actions/runs/'+str(n)))==R.run_receipt(run) for n,run in runs.items()),'PRIOR_TERMINAL_CHANGED')
    return result


def digest_context(value):
    from race_ai.actions_contract import digest
    return digest(value)


def output_root(value,env):
    raw=Path(value);P.need(raw.is_absolute(),'ABSOLUTE_PRIVATE_OUTPUT')
    root=future.output_path(raw,env);P.need(not root.exists(),'FRESH_PRIVATE_OUTPUT');return root


COUNT_FIELDS=frozenset(('schema','state','ready','kind','prepare_run_id','prepare_head_sha','prepared_at',
    'preparation_request_sha256','previous_source','verified_parent','context_sha256','evidence_sha256',
    'source_owner_authorization_sha256','original_plan_sha256','selected_case_sha256','plan_plaintext_sha256',
    'plan_cipher_sha256','recovery_request_sha256','earliest_issue_at','case_count','maximum_new_requests',
    'previous_normal_observation_count','source_requests','grants_issued','public_files_written','old_source_requests_actual',
    'old_source_requests_upper_bound','plaintext_published','production_promoted','actual_purchases','future_selector'))


def write_outputs(root,value):
    from race_ai.actions_contract import digest
    P.need(type(value) is dict and set(value)=={'plan_cipher','request','counts'},'EXACT_PREPARATION_OUTPUTS')
    counts=value['counts'];raw=value['plan_cipher'];request=value['request']
    P.need(type(counts) is dict and set(counts)<=COUNT_FIELDS and counts.get('schema')==P.COUNTS and
        counts.get('ready') is True and type(raw) is bytes and 0<len(raw)<=MAX_WIRE and
        counts.get('plan_cipher_sha256')==request['manifest']['plan_sha256']==sha256(raw).hexdigest() and
        counts.get('recovery_request_sha256')==digest(request),'OUTPUT_HASHES_OR_FIELDS')
    if 'future_selector' in counts:
        from race_ai.keirin_future_selector import validate_metadata
        selector=validate_metadata(counts['future_selector'])
        P.need(counts.get('kind')==P.EIGHT and selector['source_journal']==counts.get('previous_source',{}).get(
            'journal_artifact') and selector['checked_at']==counts.get('prepared_at'),'SELECTOR_OUTPUT_SCOPE')
    header=forecast_header(raw)
    P.need(header['round_no']==P.ROUND and header['run_id']==str(counts['prepare_run_id']),'PREPARATION_PLAN_ENVELOPE')
    I.authority_for(request).validate_request(request,R.clock(counts['prepared_at']))
    P.need(not root.exists(),'FRESH_PRIVATE_OUTPUT');root.mkdir(mode=0o700)
    _write(root/'sealedplan.enc',raw);_write(root/'request.json',collector.future.wire(request));_write(root/'counts.json',collector.future.wire(counts))


def hold_counts(root,status):
    """Never leave a ready artifact after a late write/fsync/close failure."""
    path=root/'counts.json';exists=os.path.lexists(path)
    if exists:
        info=path.lstat()
        P.need(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and
            stat.S_IMODE(info.st_mode)==0o600 and info.st_size<=65536,'PRIVATE_COUNTS_FILE')
    try:save(path,collector.future.wire(status),replace=exists)
    except Exception:
        # If even the atomic HOLD write fails, absence cannot be mistaken for
        # a successful three-member preparation. Preserve the encrypted plan.
        if os.path.lexists(path):
            current=path.lstat()
            if stat.S_ISREG(current.st_mode) and current.st_uid==os.getuid() and current.st_nlink==1 and stat.S_IMODE(current.st_mode)==0o600:
                path.unlink()
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out-dir',required=True);args=parser.parse_args(argv)
    status=dict(schema=P.COUNTS,state='HOLD_SOURCE_FREE_PREPARATION',ready=False,source_requests=0,grants_issued=0,
        public_files_written=0,old_source_requests_actual=None,old_source_requests_upper_bound=32,
        plaintext_published=False,production_promoted=False,actual_purchases=False);trusted=False;root=None
    try:
        env=issue.trusted_environment();trusted=True
        env['temp']=Path(os.environ['RUNNER_TEMP']).resolve();root=output_root(args.out_dir,env)
        snapshot=PrepareSnapshot(ROOT,env['head_sha'])
        # Working input must still be the sole committed intent byte-for-byte.
        P.need(snapshot.read(env['head_sha'],P.PATH,32768)==_read(ROOT/P.PATH,32768),'IMMUTABLE_PREPARATION_INTENT')
        result=prepare_once(snapshot=snapshot,prepare_run_id=env['run_id'],reader=ReadOnlyGithub(),
            key_loader=lambda:state_key('production'),clock=utc_now)
        write_outputs(root,result);status=result['counts']
    except Exception as exc:
        reason=str(exc);status['reason']=reason if re.fullmatch(r'(?:OFFICIAL_(?:ISSUE|PREPARE)|ALL_MODEL_[A-Z_]+)_[A-Z0-9_]{1,120}',reason) else 'PREPARATION_UNAVAILABLE'
        if trusted and root is not None:
            try:
                future.output_path(root,env)
                if not root.exists():root.mkdir(mode=0o700)
                P.need(root.is_dir() and not root.is_symlink() and root.stat().st_uid==os.getuid() and
                    root.stat().st_mode&0o777==0o700,'PRIVATE_PREPARATION_OUTPUT')
                hold_counts(root,status)
            except Exception:status['reason']='PREPARATION_OUTPUT_UNAVAILABLE'
    print(json.dumps(status,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
