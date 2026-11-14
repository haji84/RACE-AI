"""Synthetic real-Git fixtures: no key, provider, GitHub or public mutation."""
import base64
from copy import deepcopy
from hashlib import sha1, sha256
import importlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ISSUE = 'audit/state/official-result-recovery-issue-request.json'
REQUEST = 'audit/state/official-result-recovery-request.json'
PREP = 'audit/state/official-result-recovery-prepare-request.json'
WORKFLOW = '.github/workflows/forecast-audit-ui.yml'
BOOTSTRAP = 'scripts/official_frozen_execution.py'
LOCATORS = 'docs/evidence/2026-11-07/official-personal-terms-cipher-locators.json'
PLAN = 'audit/state/official-result-collection-plan-' + sha256(b'sealed plan').hexdigest() + '.enc'


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


class GitFixture:
    def __init__(self, root):
        self.root = root
        self.git('init', '-q')
        self.files = {
            WORKFLOW: b'fixed workflow', BOOTSTRAP: (Path(__file__).parents[1] / BOOTSTRAP).read_bytes(),
            'requirements-history.txt': b'cryptography==46.0.3\n',
            'race_ai/manual_official_capture.py': b'fixed policy',
            'race_ai/permissioned_source_delivery.py': b'fixed delivery',
            'audit/state/official-terms-synthetic.enc': b'encrypted terms',
            LOCATORS: b'{"synthetic":true}', PLAN: b'sealed plan',
            REQUEST: wire({'schema': 'SYNTHETIC_REQUEST', 'manifest': {
                'plan_path': PLAN, 'plan_sha256': sha256(b'sealed plan').hexdigest()}}),
        }
        self.base = self.commit(self.files, [], 'official-results-collect: synthetic frozen code')
        self.tip = self.commit(dict(self.files, **{'ui.txt': b'unrelated pre-intent code'}),
                               [self.base], 'unrelated UI')
        self.issue = self.marker(self.base, self.tip)
        self.intent_files = dict(self.files, **{'ui.txt': b'unrelated pre-intent code', ISSUE: wire(self.issue)})
        self.intent = self.commit(self.intent_files, [self.tip], 'official-results-issue: synthetic')
        self.current_files = dict(self.intent_files, **{'ui.txt': b'unrelated post-intent code'})
        self.current = self.commit(self.current_files, [self.intent], 'later UI')
        self.git('update-ref', 'refs/heads/fixture', self.current)
        self.git('symbolic-ref', 'HEAD', 'refs/heads/fixture')
        self.git('reset', '--hard', '-q', self.current)

    def git(self, *args, raw=None, binary=False):
        result = subprocess.run(['git', '-c', 'user.name=Synthetic fixture',
            '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', *args],
            cwd=self.root, input=raw, capture_output=True, check=True)
        return result.stdout if binary else result.stdout.decode().strip()

    def commit(self, files, parents, subject, *, modes=None):
        self.git('read-tree', '--empty')
        for path, raw in files.items():
            blob = self.git('hash-object', '-w', '--stdin', raw=raw)
            mode = (modes or {}).get(path, '100644')
            self.git('update-index', '--add', '--cacheinfo', mode + ',' + blob + ',' + path)
        tree = self.git('write-tree')
        args = ['commit-tree', tree]
        for parent in parents:
            args.extend(('-p', parent))
        return self.git(*args, '-m', subject)

    def marker(self, base, parent, *, run=17):
        return dict(schema='RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V2',
            repository_id=1416489937, workflow_id=392270247, pull_request=71,
            target=dict(head_sha=base, run_id=run, run_attempt=2), target_first_viewer_job_id=101,
            recovery_request_sha256=sha256(self.files[REQUEST]).hexdigest(),
            recovery_request_blob_sha256=sha256(self.files[REQUEST]).hexdigest(),
            tested_execution_head_sha=base, intent_parent_sha=parent, failed_issue_dispositions=[])

    def pr(self, head=None):
        repo = dict(id=1416489937, full_name='haji84/RACE-AI')
        return dict(number=71, state='open', user=dict(id=173585154, login='haji84'),
            head=dict(sha=head or self.current, ref='feat/four-sport-forecast-audit-view-20261022', repo=repo),
            base=dict(ref='codex/actions-four-sport-e2e', repo=repo))


class ObjectReader:
    """GitHub-shaped immutable JSON from actual local Git objects."""
    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.overrides = {}

    def json(self, path):
        self.calls.append(path)
        if path in self.overrides:
            return deepcopy(self.overrides[path])
        if path == 'pulls/71':
            return self.fixture.pr()
        if path.startswith('actions/runs/17'):
            first = dict(id=17, head_sha=self.fixture.base, run_attempt=1,
                status='completed', conclusion='success', updated_at='2026-11-08T00:20:00+00:00',
                run_started_at='2026-11-08T00:00:00+00:00', workflow_id=392270247,
                path=WORKFLOW, head_branch='feat/four-sport-forecast-audit-view-20261022', event='pull_request',
                repository=dict(id=1416489937, full_name='haji84/RACE-AI'),
                head_repository=dict(id=1416489937, full_name='haji84/RACE-AI'), pull_requests=[dict(number=71)],
                actor=dict(id=173585154, login='haji84'), triggering_actor=dict(id=173585154, login='haji84'))
            if path == 'actions/runs/17/attempts/1':
                return first
            if path == 'actions/runs/17':
                return dict(first, run_attempt=2, status='in_progress', conclusion=None)
            if path == 'actions/runs/17/attempts/1/jobs?per_page=100':
                return dict(total_count=1, jobs=[dict(id=101, run_id=17, run_attempt=1, head_sha=self.fixture.base,
                    name='Viewer audit contract', status='completed', conclusion='success', steps=[
                        dict(name=name, number=i + 1, status='completed', conclusion='success',
                             started_at=first['run_started_at'], completed_at=first['updated_at'])
                        for i, name in enumerate(('Python synthetic journal to viewer projection tests',
                            'Verify isolated experimental video decoding and measurements'))])])
        kind, ident = path.rsplit('/', 1)
        git = self.fixture.git
        if kind == 'git/commits':
            return dict(sha=ident, tree=dict(sha=git('show', '-s', '--format=%T', ident)),
                parents=[dict(sha=p) for p in git('show', '-s', '--format=%P', ident).split()],
                message=git('show', '-s', '--format=%B', ident))
        if kind == 'git/trees':
            rows = []
            for line in git('ls-tree', '-z', ident, binary=True).split(b'\0'):
                if not line:
                    continue
                attrs, name = line.split(b'\t', 1)
                mode, typ, sha = attrs.decode().split()
                row = dict(path=name.decode(), mode=mode, type=typ, sha=sha)
                if typ == 'blob':
                    row['size'] = int(git('cat-file', '-s', sha))
                rows.append(row)
            return dict(sha=ident, truncated=False, tree=rows)
        if kind == 'git/blobs':
            raw = git('cat-file', 'blob', ident, binary=True)
            return dict(sha=ident, size=len(raw), encoding='base64', content=base64.b64encode(raw).decode())
        raise AssertionError('Unexpected metadata route ' + path)


class FrozenSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.official_frozen_execution'),
                             'The stdlib-only frozen provenance module is not implemented')
        self.module = importlib.import_module('scripts.official_frozen_execution')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = GitFixture(self.root)
        self.reader = ObjectReader(self.fixture)

    def snapshot(self, *, intent=None, kind='issue', root=None):
        f = self.fixture
        return self.module.FrozenGitSnapshot(root or self.root, intent or f.intent, f.base,
                                            reader=self.reader, kind=kind)

    def test_unrelated_descendants_preserve_true_parent_and_stable_binding(self):
        f = self.fixture
        snap = self.snapshot()
        first = snap.refresh(f.pr())
        self.assertEqual(first['parents'], [f.tip])
        self.assertEqual(first['head_sha'], f.intent)
        self.assertEqual(first['execution_head_sha'], f.base)
        self.assertEqual(first['current_head_sha'], f.current)
        self.assertEqual(first['source_issue_head'], f.intent)
        self.assertEqual(first['source_frozen_binding']['intent_parent_sha'], f.tip)
        later = f.commit(dict(f.current_files, **{'video.txt': b'new unrelated code'}), [f.current], 'later video')
        second = snap.refresh(f.pr(later))
        self.assertEqual(first['frozen_binding'], second['frozen_binding'])
        self.assertEqual(first['source_frozen_binding'], second['source_frozen_binding'])
        self.assertNotEqual(first['current_admission'], second['current_admission'])

    def test_no_project_import_or_current_worktree_bytes_are_used(self):
        f = self.fixture
        (self.root / 'race_ai' / '__init__.py').write_text("raise AssertionError('must never import current code')")
        (self.root / REQUEST).write_bytes(b'changed uncommitted request')
        snap = self.snapshot()
        self.assertEqual(snap.refresh(f.pr())['current_recovery_raw'], f.files[REQUEST])

    def test_each_protected_current_blob_change_or_mode_change_holds(self):
        f = self.fixture
        for path in f.files:
            with self.subTest(path=path):
                changed = f.commit(dict(f.current_files, **{path: b'changed authority'}), [f.current], 'authority change')
                with self.assertRaises(ValueError):
                    self.snapshot().refresh(f.pr(changed))
        changed = f.commit(f.current_files, [f.current], 'policy executable mode',
                           modes={'race_ai/manual_official_capture.py': '100755'})
        with self.assertRaises(ValueError):
            self.snapshot().refresh(f.pr(changed))

    def test_newer_issue_then_reversion_is_not_an_active_original_intent(self):
        f = self.fixture
        newer_issue = f.marker(f.base, f.current, run=18)
        newer = f.commit(dict(f.current_files, **{ISSUE: wire(newer_issue)}), [f.current], 'official-results-issue: newer')
        reverted = f.commit(f.current_files, [newer], 'restore original issue bytes')
        with self.assertRaises(ValueError):
            self.snapshot().refresh(f.pr(reverted))

    def test_deletion_and_readd_are_not_hidden(self):
        f = self.fixture
        deleted_files = dict(f.current_files)
        del deleted_files[ISSUE]
        deleted = f.commit(deleted_files, [f.current], 'delete active issue')
        restored = f.commit(f.current_files, [deleted], 're-add original issue')
        with self.assertRaises(ValueError):
            self.snapshot().refresh(f.pr(restored))

    def test_intent_must_be_actual_single_file_child_and_parent_field_truthful(self):
        f = self.fixture
        wrong = deepcopy(f.issue)
        wrong['intent_parent_sha'] = f.base
        cases = [f.commit(dict(f.intent_files, **{ISSUE: wire(wrong)}), [f.tip], 'official-results-issue: forged parent'),
                 f.commit(dict(f.intent_files, **{'other.txt': b'extra'}), [f.tip], 'official-results-issue: extra code'),
                 f.commit(f.intent_files, [f.tip, f.base], 'official-results-issue: merge')]
        for head in cases:
            with self.subTest(head=head), self.assertRaises(ValueError):
                self.snapshot(intent=head)

    def test_intervening_undeclared_issue_epoch_holds(self):
        f = self.fixture
        old = f.commit(dict(f.files, **{ISSUE: wire(f.marker(f.base, f.base, run=18))}),
                       [f.base], 'official-results-issue: omitted prior epoch')
        parent = f.commit(dict(f.files, **{'ui.txt': b'later'}), [old], 'delete old marker')
        issue = f.marker(f.base, parent)
        head = f.commit(dict(f.files, **{ISSUE: wire(issue), 'ui.txt': b'later'}),
                        [parent], 'official-results-issue: omits source epoch')
        with self.assertRaises(ValueError):
            self.snapshot(intent=head)

    def test_prepare_uses_own_true_intent_and_original_source_binding(self):
        f = self.fixture
        prepare = dict(schema='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V3',
            verified_code_ancestor=dict(head_sha=f.base, run_id=17), previous_source=dict(head_sha=f.base, run_id=17))
        files = dict(f.current_files, **{PREP: wire(prepare)})
        head = f.commit(files, [f.current], 'official-results-prepare: synthetic')
        snap = self.snapshot(intent=head, kind='prepare')
        facts = snap.refresh(f.pr(head))
        self.assertEqual(facts['head_sha'], head)
        self.assertEqual(facts['parents'], [f.current])
        self.assertEqual(facts['source_issue_head'], f.intent)
        self.assertEqual(facts['source_frozen_binding'], self.snapshot().refresh(f.pr())['source_frozen_binding'])
        changed = f.commit(dict(files, **{PREP: wire(dict(prepare, extra='revocation'))}), [head], 'revoke prepare')
        with self.assertRaises(ValueError):
            snap.refresh(f.pr(changed))

    def test_source_history_transparent_adoption_preserves_real_epoch(self):
        f = self.fixture
        side = f.commit(f.files, [f.base], 'UI branch without marker')
        merge = f.commit(f.current_files, [f.current, side], 'merge unrelated marker-free branch')
        snap = self.snapshot()
        self.assertEqual(snap.issue_history(merge), [f.intent])
        self.assertEqual(snap.refresh(f.pr(merge))['latest_issue_head_sha'], f.intent)

    def test_side_issue_then_deletion_remains_in_history_and_holds(self):
        f = self.fixture
        side = f.commit(dict(f.files, **{ISSUE: wire(f.marker(f.base, f.base, run=18))}),
                        [f.base], 'official-results-issue: side source epoch')
        deleted = f.commit(f.files, [side], 'delete side marker')
        merge = f.commit(f.current_files, [f.current, deleted], 'merge apparently transparent issue')
        snap = self.snapshot()
        history = snap.issue_history(merge)
        self.assertIn(side, history)
        self.assertIn(deleted, history)
        with self.assertRaises(ValueError):
            snap.refresh(f.pr(merge))

    def test_remote_descendant_graph_and_blobs_are_read_without_fetch_or_checkout(self):
        f = self.fixture
        second = self.root / 'isolated'
        second.mkdir()
        subprocess.run(['git', 'init', '-q', str(second)], check=True, capture_output=True)
        pack = f.git('pack-objects', '--stdout', '--revs', raw=(f.base + '\n').encode(), binary=True)
        subprocess.run(['git', 'unpack-objects', '-q'], cwd=second, input=pack, check=True, capture_output=True)
        subprocess.run(['git', 'update-ref', 'refs/heads/frozen', f.base], cwd=second, check=True)
        snap = self.snapshot(root=second)
        facts = snap.refresh(f.pr())
        self.assertEqual(facts['latest_issue_head_sha'], f.intent)
        self.assertIn('git/commits/' + f.current, self.reader.calls)
        self.assertEqual(subprocess.run(['git', 'rev-parse', 'refs/heads/frozen'], cwd=second,
                                       check=True, capture_output=True).stdout.decode().strip(), f.base)
        self.assertNotEqual(subprocess.run(['git', 'cat-file', '-e', f.current], cwd=second,
                                          capture_output=True).returncode, 0)

    def test_scope_drift_and_arbitrary_path_reads_hold(self):
        for change in ('closed', 'owner', 'base', 'repo', 'branch'):
            pr = self.fixture.pr()
            if change == 'closed': pr['state'] = 'closed'
            if change == 'owner': pr['user']['id'] = 1
            if change == 'base': pr['base']['ref'] = 'main'
            if change == 'repo': pr['head']['repo'] = dict(id=1, full_name='fork/RACE-AI')
            if change == 'branch': pr['head']['ref'] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.snapshot().refresh(pr)
        snap = self.snapshot()
        for path in ('secrets.txt', '../requirements-history.txt', 'race_ai/__init__.py'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                snap.read(self.fixture.base, path, 1024)

    def test_source_admission_discovers_active_issue_and_own_full_first_without_key(self):
        f = self.fixture
        f.git('update-ref', 'refs/heads/fixture', f.base)
        f.git('reset', '--hard', '-q', f.base)
        self.assertTrue(callable(getattr(self.module, 'source_admission', None)),
                        'Keyless source admission must discover its real issuer')
        snap = self.module.source_admission(self.root, f.base, 17, reader=self.reader)
        self.assertEqual(snap.facts['source_frozen_binding'], self.snapshot().refresh(f.pr())['source_frozen_binding'])
        self.assertEqual(snap.facts['prior_full_verification']['verified_first_head_sha'], f.base)
        self.assertEqual(snap.facts['prior_full_verification']['verified_first_attempt'], 1)
        self.assertIn('actions/runs/17/attempts/1/jobs?per_page=100', self.reader.calls)

    def test_source_admission_rejects_missing_heavy_step_or_target_run_drift(self):
        f = self.fixture
        f.git('update-ref', 'refs/heads/fixture', f.base)
        f.git('reset', '--hard', '-q', f.base)
        self.assertTrue(callable(getattr(self.module, 'source_admission', None)))
        route = 'actions/runs/17/attempts/1/jobs?per_page=100'
        jobs = self.reader.json(route)
        jobs['jobs'][0]['steps'][1]['conclusion'] = 'skipped'
        self.reader.overrides[route] = jobs
        with self.assertRaises(ValueError):
            self.module.source_admission(self.root, f.base, 17, reader=self.reader)
        self.reader.overrides.clear()
        actual = self.reader.json('actions/runs/17')
        actual['run_attempt'] = 3
        self.reader.overrides['actions/runs/17'] = actual
        with self.assertRaises(ValueError):
            self.module.source_admission(self.root, f.base, 17, reader=self.reader)

    def test_same_b2_replacement_intent_has_distinct_source_binding(self):
        f = self.fixture
        original = self.snapshot().refresh(f.pr())['source_frozen_binding']
        replacement = f.marker(f.base, f.current)
        # An intervening issuer is explicit and remains pending the caller's
        # independent terminal-HOLD/capability-absence disposition checks.
        replacement['failed_issue_dispositions'] = [dict(intent_head_sha=f.intent,
            issue_blob_sha256=sha256(wire(f.issue)).hexdigest())]
        head = f.commit(dict(f.current_files, **{ISSUE: wire(replacement)}), [f.current], 'official-results-issue: replacement')
        snap = self.snapshot(intent=head)
        changed = snap.refresh(f.pr(head))
        self.assertEqual(changed['intervening_issue_heads'], [f.intent])
        self.assertNotEqual(changed['source_frozen_binding'], original)
        self.assertEqual(changed['source_frozen_binding']['intent_head_sha'], head)

    def test_source_admission_rejects_mutable_checkout_even_with_correct_run_metadata(self):
        with self.assertRaisesRegex(ValueError, 'SOURCE_CHECKOUT_HEAD'):
            self.module.source_admission(self.root, self.fixture.base, 17, reader=self.reader)
        self.assertEqual(self.reader.calls, [])

    def test_declared_baseline_unused_anchor_is_retained_pending_actual_disposition(self):
        f = self.fixture
        code = f.commit(f.current_files, [f.current], 'official-results-collect: new frozen B2')
        issue = f.marker(code, code)
        issue['failed_issue_dispositions'] = [dict(intent_head_sha=f.intent,
            issue_blob_sha256=sha256(wire(f.issue)).hexdigest())]
        head = f.commit(dict(f.current_files, **{ISSUE: wire(issue)}), [code], 'official-results-issue: new B2')
        snap = self.module.FrozenGitSnapshot(self.root, head, code, reader=self.reader)
        facts = snap.refresh(f.pr(head))
        self.assertEqual(facts['intervening_issue_heads'], [])
        self.assertIn(f.intent, facts['issue_history'])
        self.assertEqual(snap.issue['failed_issue_dispositions'], issue['failed_issue_dispositions'])

    def test_protected_revocation_then_restoration_after_active_intent_holds(self):
        f = self.fixture
        for path in ('race_ai/permissioned_source_delivery.py', BOOTSTRAP, WORKFLOW, PLAN):
            revoked = f.commit(dict(f.current_files, **{path: b'revoked'}), [f.current], 'revoke source authority')
            restored = f.commit(f.current_files, [revoked], 'restore source authority bytes')
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.snapshot().refresh(f.pr(restored))

    def test_remote_protected_reversion_is_detected_without_fetching(self):
        f = self.fixture
        revoked = f.commit(dict(f.current_files, **{'race_ai/permissioned_source_delivery.py': b'revoked'}),
                           [f.current], 'remote revoke')
        restored = f.commit(f.current_files, [revoked], 'remote restore')
        second = self.root / 'frozen-local-objects'
        second.mkdir()
        subprocess.run(['git', 'init', '-q', str(second)], check=True, capture_output=True)
        pack = f.git('pack-objects', '--stdout', '--revs', raw=(f.base + '\n').encode(), binary=True)
        subprocess.run(['git', 'unpack-objects', '-q'], cwd=second, input=pack, check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, 'PROTECTED_AUTHORITY_HISTORY_CHANGED'):
            self.snapshot(root=second).refresh(f.pr(restored))

    def test_remote_json_cannot_substitute_blob_bytes_under_a_claimed_hash(self):
        f = self.fixture
        second = self.root / 'remote-byte-check'
        second.mkdir()
        subprocess.run(['git', 'init', '-q', str(second)], check=True, capture_output=True)
        pack = f.git('pack-objects', '--stdout', '--revs', raw=(f.base + '\n').encode(), binary=True)
        subprocess.run(['git', 'unpack-objects', '-q'], cwd=second, input=pack, check=True, capture_output=True)
        blob = f.git('rev-parse', f.intent + ':' + ISSUE)
        value = self.reader.json('git/blobs/' + blob)
        raw = bytearray(base64.b64decode(value['content']))
        raw[-1] ^= 1
        value['content'] = base64.b64encode(raw).decode()
        self.reader.overrides['git/blobs/' + blob] = value
        with self.assertRaisesRegex(ValueError, 'BLOB_IMMUTABLE_BYTES'):
            self.snapshot(root=second)

    def test_previous_issue_preserves_original_actual_commit_lineage_guard(self):
        f = self.fixture
        self.assertEqual(self.snapshot().previous_issue(f.current), wire(f.issue))
        newer = f.commit(dict(f.current_files, **{ISSUE: wire(f.marker(f.base, f.current, run=18))}),
                         [f.current], 'official-results-issue: newer')
        restored = f.commit(f.current_files, [newer], 'restore older valid issue marker')
        with self.assertRaises(ValueError):
            self.snapshot().previous_issue(restored)

    def test_previous_legacy_v1_issue_retains_exact_direct_parent_requirement(self):
        f = self.fixture
        legacy = {name: value for name, value in f.issue.items()
                  if name not in ('tested_execution_head_sha', 'intent_parent_sha', 'failed_issue_dispositions')}
        legacy['schema'] = 'RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1'
        files = dict(f.files, **{ISSUE: wire(legacy)})
        valid = f.commit(files, [f.base], 'official-results-issue: original V1')
        self.assertEqual(self.snapshot().previous_issue(valid), wire(legacy))
        invalid = f.commit(dict(files, **{'ui.txt': b'unrelated pre-intent code'}),
                           [f.tip], 'official-results-issue: not a direct V1 child')
        with self.assertRaises(ValueError):
            self.snapshot().previous_issue(invalid)

    def legacy_epoch_pair(self, *, incomparable=False):
        """Actual d143 shape: one parent retains an older comparable V1 epoch."""
        f = self.fixture
        def marker(head, run):
            value = f.marker(head, head, run=run)
            value['schema'] = 'RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1'
            for key in ('tested_execution_head_sha', 'intent_parent_sha', 'failed_issue_dispositions'):
                del value[key]
            return wire(value)
        old_raw = marker(f.base, 31)
        old_files = dict(f.files, **{ISSUE: old_raw})
        old = f.commit(old_files, [f.base], 'official-results-issue: older actual epoch')
        old_parent = f.commit(dict(old_files, **{'ui.txt': b'older branch UI'}), [old], 'older UI branch')
        code_files = dict(old_files, **{'ui.txt': b'new source code'})
        code = f.commit(code_files, [f.base if incomparable else old], 'official-results-collect: newer source code')
        # In the incomparable case the source-code commit does not itself carry
        # an authored issue marker; the two valid epochs are separate branches.
        if incomparable:
            code_files.pop(ISSUE)
            code = f.commit(code_files, [f.base], 'official-results-collect: incomparable newer source code')
        new_raw = marker(code, 32)
        new_files = dict(code_files, **{ISSUE: new_raw})
        new = f.commit(new_files, [code], 'official-results-issue: newer actual epoch')
        new_parent = f.commit(dict(new_files, **{'ui.txt': b'newer branch UI'}), [new], 'newer UI branch')
        return dict(old=old, new=new, old_parent=old_parent, new_parent=new_parent,
                    old_files=old_files, new_files=new_files, old_raw=old_raw, new_raw=new_raw)

    def test_merge_inheriting_unique_newest_comparable_epoch_keeps_both_real_epochs(self):
        f = self.fixture
        pair = self.legacy_epoch_pair()
        merge = f.commit(dict(pair['new_files'], **{'pilot.txt': b'unrelated merge data'}),
                         [pair['old_parent'], pair['new_parent']], 'merge older and newer current marker branches')
        snap = self.snapshot()
        self.assertEqual(snap.issue_history(merge), [pair['new'], pair['old']])
        self.assertEqual(snap.previous_issue(merge), pair['new_raw'])

    def test_merge_cannot_adopt_older_epoch_when_parent_contains_newer_epoch(self):
        f = self.fixture
        pair = self.legacy_epoch_pair()
        merge = f.commit(pair['old_files'], [pair['old_parent'], pair['new_parent']], 'merge rolls back newest epoch')
        history = self.snapshot().issue_history(merge)
        self.assertIn(merge, history)
        self.assertIn(pair['new'], history)
        with self.assertRaises(ValueError):
            self.snapshot().previous_issue(merge)

    def test_merge_cannot_choose_between_incomparable_actual_epochs(self):
        f = self.fixture
        pair = self.legacy_epoch_pair(incomparable=True)
        merge = f.commit(pair['new_files'], [pair['old_parent'], pair['new_parent']], 'merge incomparable issue branches')
        history = self.snapshot().issue_history(merge)
        self.assertIn(merge, history)
        self.assertIn(pair['old'], history)
        self.assertIn(pair['new'], history)
        with self.assertRaises(ValueError):
            self.snapshot().previous_issue(merge)

    def test_newer_side_epoch_then_marker_restoration_is_never_hidden_by_adoption(self):
        f = self.fixture
        pair = self.legacy_epoch_pair()
        code = f.commit(pair['old_files'], [pair['old_parent']], 'official-results-collect: hidden side target')
        side_issue = {name: value for name, value in f.marker(code, code, run=33).items()
                      if name not in ('tested_execution_head_sha', 'intent_parent_sha', 'failed_issue_dispositions')}
        side_issue['schema'] = 'RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1'
        hidden = f.commit(dict(pair['old_files'], **{ISSUE: wire(side_issue)}), [code], 'official-results-issue: hidden side epoch')
        reverted = f.commit(pair['old_files'], [hidden], 'restore old marker after side source')
        merge = f.commit(pair['new_files'], [reverted, pair['new_parent']], 'merge apparently newer adopted marker')
        history = self.snapshot().issue_history(merge)
        self.assertIn(merge, history)
        self.assertIn(hidden, history)
        self.assertIn(reverted, history)
        with self.assertRaises(ValueError):
            self.snapshot().previous_issue(merge)

    def test_comparable_epoch_adoption_does_not_accept_nonregular_parent_marker(self):
        f = self.fixture
        pair = self.legacy_epoch_pair()
        changed_mode = f.commit(pair['old_files'], [pair['old_parent']], 'change old marker executable mode',
                                modes={ISSUE: '100755'})
        merge = f.commit(pair['new_files'], [changed_mode, pair['new_parent']], 'merge with nonregular inherited marker')
        with self.assertRaises(ValueError):
            self.snapshot().issue_history(merge)

    def test_nested_missing_marker_cannot_normalize_an_incomparable_epoch_frontier(self):
        f = self.fixture
        pair = self.legacy_epoch_pair()
        code = f.commit(pair['old_files'], [pair['old_parent']], 'official-results-collect: incomparable side target')
        side = {name: value for name, value in f.marker(code, code, run=34).items()
                if name not in ('tested_execution_head_sha', 'intent_parent_sha', 'failed_issue_dispositions')}
        side['schema'] = 'RACE_AI_OFFICIAL_RESULT_RECOVERY_ISSUE_REQUEST_V1'
        side_files = dict(pair['old_files'], **{ISSUE: wire(side)})
        hidden = f.commit(side_files, [code], 'official-results-issue: incomparable side epoch')
        del side_files[ISSUE]
        deleted = f.commit(side_files, [hidden], 'delete incomparable side marker')
        inner = f.commit(pair['new_files'], [deleted, pair['new_parent']], 'merge marker from only present parent')
        snap = self.snapshot()
        self.assertEqual(snap.issue_history(inner)[0], pair['new'])
        outer = f.commit(pair['new_files'], [inner, pair['old_parent']], 'merge apparently newer current marker')
        history = snap.issue_history(outer)
        self.assertIn(outer, history, 'The selected epoch must dominate every retained parent history entry')
        self.assertIn(hidden, history)
        self.assertIn(deleted, history)


class FrozenBootstrapTests(unittest.TestCase):
    """Actual private checkout and workflow provenance, with synthetic metadata."""
    def setUp(self):
        FrozenSnapshotTests.setUp(self)
        f = self.fixture
        # The event checkout stays C while current PR H has already advanced.
        f.git('update-ref', 'refs/heads/fixture', f.intent)
        f.git('reset', '--hard', '-q', f.intent)
        private_temp = tempfile.TemporaryDirectory()
        self.addCleanup(private_temp.cleanup)
        self.private = Path(private_temp.name)
        self.out = self.private / 'frozen'
        workflow_commit = f.commit(f.intent_files, [f.tip, f.intent], 'synthetic PR merge workflow')
        event = dict(number=71, sender=dict(id=173585154, login='haji84'),
            repository=dict(id=1416489937, full_name='haji84/RACE-AI'), pull_request=f.pr(f.intent))
        event_path = self.private / 'event.json'
        event_path.write_bytes(wire(event))
        self.env = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI',
            GITHUB_REPOSITORY_ID='1416489937', GITHUB_EVENT_NAME='pull_request', GITHUB_RUN_ATTEMPT='1',
            GITHUB_ACTOR='haji84', GITHUB_ACTOR_ID='173585154', GITHUB_TRIGGERING_ACTOR='haji84',
            GITHUB_REF='refs/pull/71/merge',
            GITHUB_WORKFLOW_REF='haji84/RACE-AI/.github/workflows/forecast-audit-ui.yml@refs/pull/71/merge',
            GITHUB_WORKFLOW_SHA=workflow_commit, GITHUB_SHA=workflow_commit, GITHUB_EVENT_PATH=str(event_path),
            GITHUB_RUN_ID='99', RUNNER_TEMP=str(self.private))
        first = self.reader.json('actions/runs/17/attempts/1')
        self.reader.overrides['actions/runs/17'] = first
        self.reader.overrides['actions/runs/99'] = dict(first, id=99, head_sha=f.intent, status='in_progress', conclusion=None)
        self.reference = self.root / 'pr64-reference'
        self.reference.mkdir()
        self.ref_git('init', '-q')
        (self.reference / 'race_ai').mkdir()
        (self.reference / 'race_ai' / 'parser.py').write_bytes(b'# synthetic immutable parser\n')
        self.ref_git('add', 'race_ai/parser.py')
        self.ref_git('commit', '-q', '-m', 'synthetic pinned parser')
        self.reference_head = self.ref_git('rev-parse', 'HEAD')
        pinned = patch.object(self.module, 'PR64_HEAD', self.reference_head)
        pinned.start()
        self.addCleanup(pinned.stop)

    def ref_git(self, *args):
        result = subprocess.run(['git', '-c', 'user.name=Synthetic fixture',
            '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false', *args],
            cwd=self.reference, capture_output=True, check=True)
        return result.stdout.decode().strip()

    def prepare(self):
        self.assertTrue(callable(getattr(self.module, 'prepare_execution', None)),
                        'A keyless bootstrap must materialize only the verified B2 tree')
        return self.module.prepare_execution(self.root, self.fixture.intent, reader=self.reader,
            kind='issue', out_dir=self.out, environment=self.env)

    def test_actual_whole_frozen_checkout_and_private_provenance_exclude_current_code(self):
        f = self.fixture
        result = self.prepare()
        execution = Path(result['execution_root'])
        self.assertTrue(execution.is_relative_to(self.private))
        self.assertFalse((execution / 'ui.txt').exists())
        self.assertFalse((execution / ISSUE).exists())
        self.assertEqual((execution / BOOTSTRAP).read_bytes(), f.files[BOOTSTRAP])
        self.assertEqual((execution / 'requirements-history.txt').read_bytes(), f.files['requirements-history.txt'])
        private_reference = execution.parent / 'pr64-reference'
        self.assertTrue((private_reference / 'race_ai/parser.py').is_file(), 'Bootstrap must materialize private pinned PR64')
        self.assertEqual((private_reference / 'race_ai/parser.py').read_bytes(), b'# synthetic immutable parser\n')
        reference_head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=private_reference,
                                        check=True, capture_output=True).stdout.decode().strip()
        self.assertEqual(reference_head, self.reference_head)
        self.assertEqual(private_reference.stat().st_mode & 0o777, 0o700)
        actual_head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=execution, check=True,
                                    capture_output=True).stdout.decode().strip()
        self.assertEqual(actual_head, f.base)
        proof_path = Path(result['provenance_path'])
        proof = json.loads(proof_path.read_bytes())
        self.assertEqual(proof['executed_workflow']['commit_sha'], self.env['GITHUB_WORKFLOW_SHA'])
        self.assertEqual(proof['source_frozen_binding']['intent_head_sha'], f.intent)
        self.assertEqual(proof['current_admission']['current_head_sha'], f.current)
        self.assertEqual(proof_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o700)
        self.assertEqual(f.git('rev-parse', 'HEAD'), f.intent)

    def test_failed_full_first_blocks_before_private_checkout(self):
        first = self.reader.json('actions/runs/17/attempts/1')
        first['conclusion'] = 'failure'
        self.reader.overrides['actions/runs/17/attempts/1'] = first
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.out.exists())

    def test_actual_executed_workflow_must_equal_tested_workflow(self):
        f = self.fixture
        bad = f.commit(dict(f.intent_files, **{WORKFLOW: b'untested workflow'}),
                       [f.tip, f.intent], 'different workflow merge')
        self.env.update(GITHUB_WORKFLOW_SHA=bad, GITHUB_SHA=bad)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.out.exists())

    def test_wrong_event_actor_or_private_output_symlink_blocks_without_reader_calls(self):
        self.env['GITHUB_ACTOR_ID'] = '1'
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.out.exists())
        self.env['GITHUB_ACTOR_ID'] = '173585154'
        outside = self.root / 'outside'
        outside.mkdir()
        self.out.symlink_to(outside, target_is_directory=True)
        self.reader.calls.clear()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.reader.calls, [])

    def test_module_loads_with_isolated_python_and_no_current_project_imports(self):
        f = self.fixture
        (self.root / 'race_ai' / '__init__.py').write_text("raise AssertionError('current project import')")
        path = Path(self.module.__file__).resolve()
        result = subprocess.run(['python', '-I', '-c',
            'import runpy,sys;runpy.run_path(sys.argv[1],run_name="isolated_test");'
            'assert not any(k=="race_ai" or k.startswith("race_ai.") for k in sys.modules)', str(path)],
            cwd=self.root, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def witness(self, prepared, *, poisoned=None):
        self.assertTrue(callable(getattr(self.module, 'execution_witness', None)),
                        'Runtime must independently witness the actual executed tree')
        path = Path(prepared['execution_root']) / BOOTSTRAP
        spec = importlib.util.spec_from_file_location('frozen_witness_fixture', path)
        executed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(executed)
        executed.PR64_HEAD = self.reference_head  # Literal pin replaced only in this synthetic Git fixture.
        isolated_modules = {name: value for name, value in sys.modules.items()
                            if name not in ('scripts', 'race_ai') and not name.startswith(('scripts.', 'race_ai.'))}
        if poisoned is not None:
            isolated_modules[poisoned.__name__] = poisoned
        with patch.dict('os.environ', self.env, clear=True), patch.dict('sys.modules', isolated_modules, clear=True):
            return executed.execution_witness(self.root, prepared['execution_root'], self.fixture.intent,
                                               self.fixture.base, reader=self.reader)

    def test_runtime_witness_is_from_actual_clean_b2_worktree(self):
        prepared = self.prepare()
        proof = self.witness(prepared)
        self.assertTrue(proof['frozen_code_execution'])
        self.assertFalse(proof['current_pr_code_executed'])
        self.assertEqual(proof['executed_workflow']['head_sha'], self.fixture.intent)
        path = Path(prepared['execution_root']) / 'race_ai/manual_official_capture.py'
        path.write_bytes(b'changed after bootstrap')
        with self.assertRaises(ValueError):
            self.witness(prepared)

    def test_runtime_witness_rejects_an_already_loaded_current_project_module(self):
        prepared = self.prepare()
        poisoned = types.ModuleType('race_ai.frozen_test_current_module')
        poisoned.__file__ = str(self.root / 'race_ai/manual_official_capture.py')
        with self.assertRaises(ValueError):
            self.witness(prepared, poisoned=poisoned)

    def test_runtime_witness_validates_namespace_package_paths_without_file(self):
        prepared = self.prepare()
        namespace = types.ModuleType('scripts')
        namespace.__path__ = [str(Path(prepared['execution_root']) / 'scripts')]
        self.assertTrue(self.witness(prepared, poisoned=namespace)['frozen_code_execution'])
        namespace.__path__.append(str(self.root / 'scripts'))
        with self.assertRaisesRegex(ValueError, 'CURRENT_PROJECT_MODULE_LOADED'):
            self.witness(prepared, poisoned=namespace)

    def test_prepare_bootstrap_preserves_true_d_and_source_c_roles(self):
        f = self.fixture
        prepare = dict(schema='RACE_AI_OFFICIAL_RESULT_PLAN_PREPARE_REQUEST_V3',
            verified_code_ancestor=dict(head_sha=f.base, run_id=17), previous_source=dict(head_sha=f.base, run_id=17))
        files = dict(f.current_files, **{PREP: wire(prepare)})
        head = f.commit(files, [f.current], 'official-results-prepare: synthetic P3')
        f.git('update-ref', 'refs/heads/fixture', head)
        f.git('reset', '--hard', '-q', head)
        merge = f.commit(files, [f.current, head], 'actual P3 merge workflow')
        event = json.loads(Path(self.env['GITHUB_EVENT_PATH']).read_bytes())
        event['pull_request'] = f.pr(head)
        Path(self.env['GITHUB_EVENT_PATH']).write_bytes(wire(event))
        self.env.update(GITHUB_WORKFLOW_SHA=merge, GITHUB_SHA=merge)
        self.reader.overrides['pulls/71'] = f.pr(head)
        self.reader.overrides['actions/runs/99']['head_sha'] = head
        self.reader.overrides['actions/runs/17'] = dict(self.reader.json('actions/runs/17'), run_attempt=2)
        result = self.module.prepare_execution(self.root, head, reader=self.reader,
            kind='prepare', out_dir=self.out, environment=self.env)
        proof = json.loads(Path(result['provenance_path']).read_bytes())
        self.assertEqual(proof['intent_head_sha'], head)
        self.assertEqual(proof['source_frozen_binding']['intent_head_sha'], f.intent)
        self.assertEqual(proof['executed_workflow']['head_sha'], head)
        self.assertEqual(result['execution_head'], f.base)

    def test_cli_emits_only_validated_private_outputs_after_actual_bootstrap(self):
        output = self.private / 'github-output'
        with patch.dict('os.environ', dict(self.env, GITHUB_OUTPUT=str(output)), clear=True), \
                patch.object(self.module, '_GithubJsonReader', return_value=self.reader):
            code = self.module.main(['--git-root', str(self.root), '--intent-head', self.fixture.intent,
                                     '--kind', 'issue', '--out-dir', str(self.out)])
        self.assertEqual(code, 0)
        fields = dict(row.split('=', 1) for row in output.read_text().splitlines())
        self.assertEqual(fields['ready'], 'true')
        self.assertEqual(fields['execution_head'], self.fixture.base)
        self.assertTrue(Path(fields['provenance_path']).is_file())

    def test_bootstrap_rejects_dirty_wrong_head_and_symlink_reference_before_checkout(self):
        parser = self.reference / 'race_ai/parser.py'
        parser.write_bytes(b'dirty untested parser')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.out.exists())
        self.ref_git('add', 'race_ai/parser.py')
        self.ref_git('commit', '-q', '-m', 'wrong reference HEAD')
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.out.exists())
        self.ref_git('reset', '--hard', '-q', self.reference_head)
        moved = self.root / 'moved-reference'
        self.reference.rename(moved)
        self.reference.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.out.exists())

    def test_shallow_exact_pinned_reference_is_materialized_and_runtime_admitted(self):
        (self.reference / '.git/shallow').write_text(self.reference_head + '\n')
        self.assertEqual(self.ref_git('rev-parse', '--is-shallow-repository'), 'true')
        result = self.prepare()
        parser = types.ModuleType('race_ai.synthetic_fixed_parser')
        parser.__file__ = str(Path(result['execution_root']).parent / 'pr64-reference/race_ai/parser.py')
        self.assertTrue(self.witness(result, poisoned=parser)['frozen_code_execution'])


if __name__ == '__main__':
    unittest.main()
