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
        if value['schema']==P.SCHEMA_V2:return self._reused_facts(value)
        source=value['previous_source'];parent=value['verified_parent']
        self._git(['merge-base','--is-ancestor',source['head_sha'],parent['head_sha']])
        return dict(self.facts,source_is_ancestor=True,recovery_raw=self.read(source['head_sha'],I.REQUEST_PATH,32768),
            latest_issue_raw=self.previous_issue(parent['head_sha']))

    def _reused_facts(self,value):
        source=value['previous_source'];code=value['verified_code_ancestor']['head_sha'];head=self.facts['head_sha']
        immediate=self.facts['parents'][0]
        parents=self._git(['show','-s','--format=%P',immediate]).decode().strip().split()
        P.need(parents==[code],'EXACT_TWO_HOP_LINEAGE')
        subject=self._git(['show','-s','--format=%s',immediate]).decode().strip()
        P.need(subject.startswith(I.PREFIX),'EXACT_ISSUE_ONLY_PARENT')
        changes=[]
        for before,after,path in ((code,immediate,I.ISSUE_PATH),(immediate,head,P.PATH)):
            raw=self._git(['diff-tree','--no-commit-id','--raw','--no-abbrev','--no-renames','-r','-z',before,after])
            parts=raw.split(b'\0');P.need(len(parts)==3 and parts[-1]==b'' and parts[1]==path.encode(),'EXACT_TWO_DATA_ONLY_CHANGES')
            fields=parts[0].decode().split()
            P.need(len(fields)==5 and fields[0] in (':100644',':000000') and fields[1]=='100644' and
                fields[4] in ('M','A') and I._hex(fields[2]) and I._hex(fields[3]),'EXACT_DATA_MODES')
            changes.append(dict(path=path,old_mode=fields[0][1:],new_mode=fields[1],status=fields[4]))
        issue_raw=self.read(immediate,I.ISSUE_PATH,16384);I.validate_issue_request(read_json_bytes(issue_raw))
        row=self._git(['ls-tree',code,'--',I.WORKFLOW_PATH]).decode().strip()
        match=re.fullmatch('100644 blob ([a-f0-9]{40})\\t'+re.escape(I.WORKFLOW_PATH),row)
        P.need(match is not None,'TESTED_WORKFLOW_REGULAR_BLOB')
        return dict(self.facts,source_is_ancestor=True,recovery_raw=self.read(code,I.REQUEST_PATH,32768),
            latest_issue_raw=self.previous_issue(immediate),tested_workflow_blob=match[1],data_only_changes=changes,
            issuer_parent=dict(head_sha=immediate,parents=parents,changed_files=[I.ISSUE_PATH],subject=subject,issue_raw=issue_raw))


class FrozenPrepareSnapshot:
    """Read intent data separately from the whole tested package executing us."""
    def __init__(self,git_root,intent_head,execution_head,*,reader):
        from scripts.official_frozen_execution import FrozenGitSnapshot
        self._git_root=Path(git_root);self._intent_head=intent_head;self._execution_head=execution_head
        self._source=FrozenGitSnapshot(git_root,intent_head,execution_head,reader=reader,kind='prepare')
        self.facts=self._source.facts
    def read(self,head,path,limit):return self._source.read(head,path,limit)
    def commit_facts(self,head):return self._source.commit_facts(head)
    def is_ancestor(self,before,after):return self._source.is_ancestor(before,after)
    def issue_history(self,head):return self._source.issue_history(head)
    def refresh(self,current_pr):
        self.facts=self._source.refresh(current_pr);return self.facts
    def execution_witness(self,reader):
        from scripts.official_frozen_execution import execution_witness
        proof=execution_witness(self._git_root,ROOT,self._intent_head,self._execution_head,reader=reader)
        self._source.facts.update(proof);self.facts=self._source.facts;return proof
    def prepare_facts(self,value):
        P.need(value['schema']==P.SCHEMA_V3,'FROZEN_REQUEST_REQUIRED')
        head=self.facts['head_sha'];code=value['verified_code_ancestor']['head_sha']
        binding=self.facts.get('frozen_binding');P.need(type(binding) is dict,'FROZEN_BINDING_FIELDS')
        source=self.facts.get('source_issue_head');P.need(I._hex(source),'FROZEN_SOURCE_ISSUE')
        current=self.commit_facts(head);anchor=self.commit_facts(source);history=self.issue_history(head)
        P.need(type(current.get('parents')) is list and len(current['parents'])==1 and
            type(anchor.get('parents')) is list and len(anchor['parents'])==1 and
            type(history) is list and history and history[0]==source,'FROZEN_PREPARATION_LINEAGE')
        raw=self.read(source,I.ISSUE_PATH,16384)
        P.need(type(raw) is bytes and raw==self.facts.get('latest_issue_raw'),'FROZEN_ACTIVE_ISSUE_BYTES')
        return dict(self.facts,**{k:current[k] for k in ('parents','subject','changed_files')},
            source_issue_head=source,latest_issue_head_sha=source,source_issue_commit=anchor,
            preparation_raw=self.read(head,P.PATH,32768),
            source_is_ancestor=self.is_ancestor(code,head),source_issue_is_ancestor=self.is_ancestor(source,current['parents'][0]),
            source_parent_is_code_descendant=self.is_ancestor(code,anchor['parents'][0]))


def executed_workflow(reader,head,tested_blob):
    """Bind actual PR-merge workflow to the tested code using existing GETs."""
    commit=os.environ.get('GITHUB_WORKFLOW_SHA')
    P.need(I._hex(commit) and commit==os.environ.get('GITHUB_SHA') and I._hex(head) and I._hex(tested_blob),
        'ACTUAL_WORKFLOW_ENVIRONMENT')
    value=reader.json('git/commits/'+commit);parents=value.get('parents');tree=value.get('tree')
    P.need(value.get('sha')==commit and type(parents) is list and 0<=len(parents)<=2 and
        all(type(p) is dict and I._hex(p.get('sha')) for p in parents) and
        (commit==head or any(p['sha']==head for p in parents)) and type(tree) is dict and I._hex(tree.get('sha')),
        'ACTUAL_WORKFLOW_COMMIT')
    tree=tree['sha']
    for index,name in enumerate(('.github','workflows','forecast-audit-ui.yml')):
        value=reader.json('git/trees/'+tree);rows=value.get('tree')
        P.need(value.get('sha')==tree and value.get('truncated') is False and type(rows) is list and
            1<=len(rows)<=32768 and all(type(r) is dict and type(r.get('path')) is str and
                0<len(r['path'])<=255 and '/' not in r['path'] and '\0' not in r['path'] and r['path'] not in ('.','..')
                for r in rows) and len({r['path'] for r in rows})==len(rows),'ACTUAL_WORKFLOW_TREE')
        matches=[r for r in rows if r['path']==name];P.need(len(matches)==1,'ACTUAL_WORKFLOW_PATH');row=matches[0]
        P.need(I._hex(row.get('sha')),'ACTUAL_WORKFLOW_OBJECT')
        if index<2:
            P.need(row.get('type')=='tree' and row.get('mode')=='040000','ACTUAL_WORKFLOW_TREE_MODE');tree=row['sha']
        else:
            P.need(row.get('type')=='blob' and row.get('mode')=='100644' and row['sha']==tested_blob and
                type(row.get('size')) is int and 0<row['size']<=1024*1024,'ACTUAL_WORKFLOW_BLOB')
    return dict(commit_sha=commit,head_sha=head,blob_sha=tested_blob)


def _context(value,snapshot,prepare_run_id,reader,now):
    frozen=value['schema']==P.SCHEMA_V3;reused=value['schema'] in (P.SCHEMA_V2,P.SCHEMA_V3)
    current_pr=reader.json('pulls/71') if frozen else None
    if frozen:
        snapshot.refresh(current_pr);witness=snapshot.execution_witness(reader)
        P.need(type(witness) is dict and set(witness)=={'frozen_code_execution','current_pr_code_executed','executed_workflow'} and
            witness['frozen_code_execution'] is True and witness['current_pr_code_executed'] is False,'FROZEN_RUNTIME_WITNESS')
    parent=value['verified_code_ancestor' if reused else 'verified_parent'];source=value['previous_source'];facts=snapshot.prepare_facts(value)
    extra=({'executed_workflow':witness['executed_workflow']} if frozen else
        {'executed_workflow':executed_workflow(reader,facts['head_sha'],facts['tested_workflow_blob'])} if reused else {})
    if frozen:extra['source_second_jobs']=reader.json('actions/runs/'+str(source['run_id'])+'/attempts/2/jobs?per_page=100')
    context=P.admit_context(value,prepare_run=reader.json('actions/runs/'+str(prepare_run_id)),
        current_pr=current_pr if frozen else reader.json('pulls/71'),snapshot=facts,
        parent_current=reader.json('actions/runs/'+str(parent['run_id'])),
        parent_first=reader.json('actions/runs/'+str(parent['run_id'])+'/attempts/1'),
        parent_jobs=reader.json('actions/runs/'+str(parent['run_id'])+'/attempts/1/jobs?per_page=100'),
        source_current=reader.json('actions/runs/'+str(source['run_id'])),
        source_first=reader.json('actions/runs/'+str(source['run_id'])+'/attempts/1'),
        source_jobs=reader.json('actions/runs/'+str(source['run_id'])+'/attempts/1/jobs?per_page=100'),now=now,**extra)
    if frozen:
        latest=I.validate_issue_request(read_json_bytes(facts['latest_issue_raw']))
        failed=issue.failed_dispositions(snapshot,latest,reader,now=now,published=True)
        context['failed_issue_dispositions']=failed
        context['source_issue_continuity']=issue.source_continuity(snapshot,latest,
            read_json_bytes(facts['recovery_raw']),reader,verified_failed=failed)
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
    if value['schema']==P.SCHEMA_V3:
        result['counts']['admitted_current_pr_head']=fresh['admitted_current_pr_head'];P.validate_frozen_counts(result['counts'])
    P.need(all(R.run_receipt(reader.json('actions/runs/'+str(n)))==R.run_receipt(run) for n,run in runs.items()),'PRIOR_TERMINAL_CHANGED')
    return result


def digest_context(value):
    return P.context_digest(value)


def output_root(value,env):
    raw=Path(value);P.need(raw.is_absolute(),'ABSOLUTE_PRIVATE_OUTPUT')
    root=future.output_path(raw,env);P.need(not root.exists(),'FRESH_PRIVATE_OUTPUT');return root


def frozen_options(args,env):
    values=(args.frozen_git_root,args.frozen_intent_head,args.frozen_execution_head)
    if not any(value is not None for value in values):return None
    P.need(all(type(value) is str and value for value in values) and I._hex(args.frozen_intent_head) and
        I._hex(args.frozen_execution_head) and args.frozen_intent_head==env['head_sha'],'FROZEN_OPTIONS')
    data=Path(args.frozen_git_root);code=ROOT.resolve();temp=Path(env['temp']).resolve()
    P.need(data.is_absolute() and '..' not in data.parts and data.is_dir() and
        not any(p.is_symlink() for p in (data,*data.parents)) and data.resolve()!=code and
        code.is_relative_to(temp) and not any(p.is_symlink() for p in (ROOT,*ROOT.parents)) and
        stat.S_ISDIR(ROOT.lstat().st_mode) and ROOT.lstat().st_uid==os.getuid() and
        stat.S_IMODE(ROOT.lstat().st_mode)==0o700,'PRIVATE_FROZEN_CODE_ROOT')
    result=issue.subprocess.run(['git','--no-replace-objects','rev-parse','HEAD'],cwd=code,capture_output=True,
        check=False,timeout=30,env=dict(PATH=os.environ.get('PATH',''),GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull))
    P.need(result.returncode==0 and result.stdout.strip()==args.frozen_execution_head.encode(),'FROZEN_EXECUTION_HEAD')
    return dict(git_root=data.resolve(),intent_head=args.frozen_intent_head,execution_head=args.frozen_execution_head)


COUNT_FIELDS=frozenset(('schema','state','ready','kind','prepare_run_id','prepare_head_sha','prepared_at',
    'preparation_request_sha256','previous_source','verified_parent','context_sha256','evidence_sha256',
    'source_owner_authorization_sha256','original_plan_sha256','selected_case_sha256','plan_plaintext_sha256',
    'plan_cipher_sha256','recovery_request_sha256','earliest_issue_at','case_count','maximum_new_requests',
    'previous_normal_observation_count','source_requests','grants_issued','public_files_written','old_source_requests_actual',
    'old_source_requests_upper_bound','plaintext_published','production_promoted','actual_purchases','future_selector'))
REUSED_COUNT_FIELDS=frozenset(('verified_code_ancestor','immediate_issuer_parent','reused_code_ancestor',
    'parent_whole_first_verified','executed_workflow'))


def write_outputs(root,value):
    from race_ai.actions_contract import digest
    P.need(type(value) is dict and set(value)=={'plan_cipher','request','counts'},'EXACT_PREPARATION_OUTPUTS')
    counts=value['counts'];raw=value['plan_cipher'];request=value['request']
    frozen=type(counts) is dict and counts.get('schema')==P.COUNTS_V3
    reused=type(counts) is dict and counts.get('schema')==P.COUNTS_V2
    extra=P.FROZEN_COUNT_FIELDS if frozen else REUSED_COUNT_FIELDS if reused else frozenset()
    P.need(type(counts) is dict and set(counts)<=COUNT_FIELDS|extra|({'verified_code_ancestor'} if frozen else set()) and
        counts.get('schema') in (P.COUNTS,P.COUNTS_V2,P.COUNTS_V3) and
        counts.get('ready') is True and type(raw) is bytes and 0<len(raw)<=MAX_WIRE and
        counts.get('plan_cipher_sha256')==request['manifest']['plan_sha256']==sha256(raw).hexdigest() and
        counts.get('recovery_request_sha256')==digest(request),'OUTPUT_HASHES_OR_FIELDS')
    if frozen:P.validate_frozen_counts(counts)
    if reused:
        P.need(REUSED_COUNT_FIELDS<=set(counts) and 'verified_parent' not in counts and
            counts['reused_code_ancestor'] is True and counts['parent_whole_first_verified'] is False,
            'REUSED_CODE_OUTPUT_SCOPE')
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
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out-dir',required=True)
    parser.add_argument('--frozen-git-root');parser.add_argument('--frozen-intent-head');parser.add_argument('--frozen-execution-head')
    args=parser.parse_args(argv)
    status=dict(schema=P.COUNTS,state='HOLD_SOURCE_FREE_PREPARATION',ready=False,source_requests=0,grants_issued=0,
        public_files_written=0,old_source_requests_actual=None,old_source_requests_upper_bound=32,
        plaintext_published=False,production_promoted=False,actual_purchases=False);trusted=False;root=None
    try:
        env=issue.trusted_environment();trusted=True
        env['temp']=Path(os.environ['RUNNER_TEMP']).resolve();root=output_root(args.out_dir,env)
        options=frozen_options(args,env)
        if options is None:
            snapshot=PrepareSnapshot(ROOT,env['head_sha'])
            # Legacy working input remains the sole committed intent.
            P.need(snapshot.read(env['head_sha'],P.PATH,32768)==_read(ROOT/P.PATH,32768),'IMMUTABLE_PREPARATION_INTENT')
            reader=ReadOnlyGithub()
        else:
            reader=ReadOnlyGithub();snapshot=FrozenPrepareSnapshot(**options,reader=reader)
        result=prepare_once(snapshot=snapshot,prepare_run_id=env['run_id'],reader=reader,
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
