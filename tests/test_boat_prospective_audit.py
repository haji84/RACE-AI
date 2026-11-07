"""Actions fixtures use real Node readers and mocked authenticated feed transport."""
import base64
from contextlib import redirect_stdout
from copy import deepcopy
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from race_ai.boat_history_store import wire

try:
    cli = importlib.import_module('scripts.boat_prospective_audit')
except ModuleNotFoundError:
    cli = None

ROOT = Path(__file__).resolve().parents[1]
DAY = '2030-04-01'
KEY = bytes(range(32))
FIXTURE = r"""
const B=require('./scripts/boat_budget_plan.cjs');
const top=[[1,2,3],[1,2,4],[1,3,2],[1,3,4],[1,4,2],[1,4,3],[2,1,3],[2,1,4]],day='2030-04-01';
const p={model_id:'invented-family',model_version:'v1',stage:'P0',ordered_top8:top,prediction_sha256:'a'.repeat(64),output_sha256:'b'.repeat(64),original_json_sha256:'c'.repeat(64),as_of:day+'T07:00:00+09:00',generated_at:day+'T07:00:00+09:00',persisted_at:day+'T07:01:00+09:00',cutoff_at:day+'T12:00:00+09:00'};
const row={race_id:'20300401-01-01',sport:'boat',scope:'research',venue:'SECRET-VENUE',race_no:1,event_date_jst:day,cutoff_at:p.cutoff_at,saved_cutoff_variants:[p.cutoff_at],offering_status:'UNKNOWN',prediction:p,comparison_predictions:[{...structuredClone(p),model_id:'invented-peer'}],participants:Array.from({length:6},(_,j)=>({number:j+1,registration_no:String(4000+j),name:'SECRET-NAME'})),result:null,result_observations:[],result_revisions:[],missing_reasons:[]};
const view={schema:'RACE_AI_PRIVATE_CYCLE_VIEW_V1',dataset_status:'REAL_REPORTED',event_date_jst:day,records:[row],secret_key:'SECRET-KEY'};
const frozen=B.freezePlan(view,{day,createdAt:day+'T07:30:00+09:00',policyCommit:'1'.repeat(40),dailyBudgets:[1000],raceBudgets:[1000]});
function c(v){return Array.isArray(v)?'['+v.map(c).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+c(v[k])).join(',')+'}':JSON.stringify(v);}
const registration={...frozen.safeSummary,schema:'RACE_AI_PROSPECTIVE_EVALUATION_REGISTRATION_V1',evaluation:{hit_denominator:'NORMAL_MATCHED_SETTLED_RACES_EXCLUDING_VOID_AND_PARTIAL_REFUND',promotion_allowed:false,improvement_proven:false}};
process.stdout.write(JSON.stringify({plan_raw:c(frozen.privateBundle),registration,view}));
"""


class ProspectiveAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        generated = subprocess.run(['node', '-e', FIXTURE], cwd=ROOT, capture_output=True, text=True, timeout=15)
        if generated.returncode:
            raise AssertionError('fictional pre-result plan generation failed')
        cls.fixture = json.loads(generated.stdout)

    def setUp(self):
        self.assertIsNotNone(cli, 'private scheduled prospective audit caller is absent')
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.repo = self.base/'repo'; self.repo.mkdir(mode=0o700)
        for name in ('web/product-data.js', 'web/saved-performance.js', 'web/forecast-audit-model.js',
                     'web/existing-model-catalog.js', 'scripts/boat_budget_plan.cjs',
                     'scripts/boat_frozen_plan_settlement.cjs', 'scripts/saved_performance_report.cjs'):
            target = self.repo/name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/name, target)
        self.private = self.base/'private'; self.private.mkdir(mode=0o700)
        self.plan = self.private/'plan.json'; self.plan.write_bytes(self.fixture['plan_raw'].encode()); self.plan.chmod(0o600)
        declaration = self.repo/'docs/evidence'/DAY/'prospective-evaluation-plan.json'
        declaration.parent.mkdir(parents=True); declaration.write_text(wire(self.fixture['registration']))
        bootstrap = b'fictional encrypted bootstrap'
        config = self.repo/'audit/state/boat-saved-view-input.json'; config.parent.mkdir(parents=True)
        config.write_text(wire(dict(schema='RACE_AI_SAVED_VIEW_INPUT_V1', bootstrap=base64.b64encode(bootstrap).decode(),
            bootstrap_sha256=sha256(bootstrap).hexdigest(), catchup_artifact_id=1, catchup_sha256='a'*64)))
        self.view = deepcopy(self.fixture['view'])
        other = json.loads(json.dumps(self.view['records'][0]).replace('2030-04-01', '2030-04-02').replace('20300401', '20300402'))
        self.view['records'].append(other); self.view['event_date_jst'] = None
        self.marker = dict(runtime_files={'prospective-budget-plan.json': str(self.plan)})
        self.environment = dict(GITHUB_ACTIONS='true', GITHUB_REPOSITORY='haji84/RACE-AI', GITHUB_REPOSITORY_ID='1416489937',
            GITHUB_RUN_ID='42', GITHUB_SHA='a'*40, GH_TOKEN='fixture-token-only-not-a-credential',
            RUNNER_TEMP=str(self.private), RACE_AI_STATE_KEY=base64.b64encode(KEY).decode(), PATH=os.environ['PATH'])
        patches = [patch.object(cli, 'ROOT', self.repo), patch.dict(os.environ, self.environment, clear=True),
            patch('scripts.boat_saved_view_feed.git_auth'), patch.object(cli.CLI, 'restore_ready', return_value=self.marker),
            patch.object(cli.F, 'open_bootstrap', return_value={'fixture': True}), patch.object(cli.F, 'FeedRepository', return_value=object()),
            patch.object(cli.F, 'current_view', return_value=('a'*40, 'b'*64, 8, self.view))]
        self.patches = [p.start() for p in patches]
        for p in patches: self.addCleanup(p.stop)
        self.output = self.private/'audit-001.json'

    def run_audit(self):
        output = io.StringIO()
        with redirect_stdout(output): code = cli.main(['--output', str(self.output)])
        text = output.getvalue()
        for secret in ('SECRET-', self.environment['RACE_AI_STATE_KEY'], self.environment['GH_TOKEN'], 'race_id', 'ordered_top8', 'combination'):
            self.assertNotIn(secret, text)
        return code, json.loads(text)

    def test_real_node_pending_report_keeps_plan_bytes_and_saves_one_private_day_view(self):
        before = self.plan.read_bytes(); view_before = deepcopy(self.view)
        code, report = self.run_audit()
        self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'PENDING')
        self.assertEqual(report['frozen_settlement']['scenarios'][0]['pendingStake'], 1000)
        self.assertEqual(report['frozen_settlement']['scenarios'][0]['misses'], 0)
        self.assertIsNone(report['frozen_settlement']['scenarios'][0]['net'])
        self.assertEqual(report['descriptive']['coverage']['races'], 1)
        self.assertEqual(report['descriptive']['coverage']['days'][0]['day'], DAY)
        self.assertFalse(report['independent_pre_cutoff_receipt_verified'])
        self.assertFalse(report['frozen_plan_reallocated'])
        self.assertEqual(json.loads(self.output.read_text()), report)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        views = list(self.private.glob('audit-001.saved-view-*.json')); self.assertEqual(len(views), 1)
        filtered = dict(view_before, event_date_jst=DAY, records=[view_before['records'][0]])
        self.assertEqual(views[0].read_bytes(), wire(filtered).encode())
        self.assertEqual(views[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.plan.read_bytes(), before); self.assertEqual(self.view, view_before)
        self.patches[3].assert_called_once_with()
        self.patches[6].assert_called_once_with(self.patches[5].return_value, {'fixture': True}, day=DAY)

    def test_missing_optional_plan_does_not_create_empty_report_or_view(self):
        self.marker['runtime_files'] = {}
        code, report = self.run_audit(); self.assertEqual(code, 0)
        self.assertEqual(report['status'], 'PROSPECTIVE_PLAN_NOT_CONFIGURED')
        self.assertFalse(self.output.exists()); self.assertFalse(list(self.private.glob('*.saved-view-*.json')))
        self.patches[6].assert_not_called()

    def test_missing_owner_key_or_actions_context_stops_before_runtime_or_private_io(self):
        for field in ('RACE_AI_STATE_KEY', 'GITHUB_ACTIONS'):
            with patch.dict(os.environ, {k:v for k,v in self.environment.items() if k!=field}, clear=True), \
                    patch.object(cli.CLI, 'restore_ready', side_effect=AssertionError('runtime read before owner context')), \
                    patch.object(cli, '_read', side_effect=AssertionError('file read before owner context')):
                code, report = self.run_audit()
            self.assertEqual(code, 2); self.assertEqual(report['status'], 'PROSPECTIVE_AUDIT_REJECTED')
            self.assertFalse(self.output.exists())

    def test_wrong_private_plan_hash_rejects_before_node_or_owner_feed(self):
        plan = json.loads(self.plan.read_text()); plan['plans'][0]['races'][0]['tickets'][0]['amount_yen'] += 100
        self.plan.write_text(wire(plan))
        with patch.object(cli, '_run_node', side_effect=AssertionError('bad plan launched Node')):
            code, report = self.run_audit()
        self.assertEqual(code, 2); self.assertEqual(report['reason'], 'PROSPECTIVE_AUDIT_PLAN_HASH_MISMATCH')
        self.patches[6].assert_not_called(); self.assertFalse(self.output.exists())

    def test_node_hold_returns_safe_aggregate_without_refreezing_missing_originals(self):
        self.view['records'][0]['prediction']['prediction_sha256'] = 'f'*64
        code, report = self.run_audit(); self.assertEqual(code, 2)
        self.assertEqual(report['status'], 'HOLD'); self.assertEqual(report['frozen_settlement']['scenarios'], [])
        self.assertTrue(self.output.exists()); self.assertFalse(report['accuracy_improvement_proven'])

    def test_nested_receipt_or_improvement_claim_is_rejected_before_report_write(self):
        code, initial = self.run_audit(); self.assertEqual(code, 0); self.output.unlink()
        settlement = initial['frozen_settlement']; settlement['independent_pre_cutoff_receipt_verified'] = True
        (self.repo/'scripts/boat_frozen_plan_settlement.cjs').write_text('process.stdout.write('+json.dumps(wire(settlement))+');')
        code, report = self.run_audit(); self.assertEqual(code, 2)
        self.assertEqual(report['reason'], 'PROSPECTIVE_AUDIT_NODE_AGGREGATE_INVALID')
        self.assertFalse(self.output.exists())

    def test_real_node_children_do_not_inherit_owner_key_or_github_token(self):
        code, initial = self.run_audit(); self.assertEqual(code, 0); self.output.unlink()
        body = json.dumps(wire(initial['frozen_settlement']))
        (self.repo/'scripts/boat_frozen_plan_settlement.cjs').write_text(
            "if(process.env.RACE_AI_STATE_KEY||process.env.GH_TOKEN)process.exit(9);else process.stdout.write("+body+");")
        code, report = self.run_audit(); self.assertEqual(code, 0); self.assertEqual(report['status'], 'PENDING')

    def test_github_denial_propagates_before_writes_without_fallback(self):
        with patch.object(cli.F, 'current_view', side_effect=RuntimeError('GITHUB_API_READ_HTTP_403_HALT')) as current, \
                patch.object(cli, '_run_node', side_effect=AssertionError('denied view launched Node')):
            code, report = self.run_audit()
        self.assertEqual(code, 2); self.assertEqual(report['reason'], 'GITHUB_API_READ_HTTP_403_HALT')
        current.assert_called_once(); self.assertFalse(self.output.exists())
        self.assertFalse(list(self.private.glob('*.saved-view-*.json')))

    def test_preexisting_output_and_public_plan_permissions_fail_without_overwrite(self):
        self.output.write_bytes(b'preserve old output'); self.output.chmod(0o600)
        code, _ = self.run_audit(); self.assertEqual(code, 2); self.assertEqual(self.output.read_bytes(), b'preserve old output')
        self.output.unlink(); self.plan.chmod(0o644)
        code, _ = self.run_audit(); self.assertEqual(code, 2); self.assertFalse(self.output.exists())

    def test_node_stream_bounds_and_timeout_never_echo_raw_stderr_or_write_report(self):
        script = self.repo/'scripts/boat_frozen_plan_settlement.cjs'
        for channel in ('stdout','stderr'):
            script.write_text(f"process.{channel}.write('SECRET-'+ 'x'.repeat(4096));")
            with patch.object(cli, 'MAX_NODE_STDOUT', 1024), patch.object(cli, 'MAX_NODE_STDERR', 1024):
                code, report = self.run_audit()
            self.assertEqual(code, 2); self.assertEqual(report['reason'], 'PROSPECTIVE_AUDIT_NODE_OUTPUT_BOUND_INVALID')
            self.assertFalse(self.output.exists())
        script.write_text('setTimeout(()=>{},10000);')
        with patch.object(cli, 'NODE_TIMEOUT_SECONDS', .05): code, report = self.run_audit()
        self.assertEqual(code, 2); self.assertEqual(report['reason'], 'PROSPECTIVE_AUDIT_NODE_TIMEOUT')
        self.assertFalse(self.output.exists())


if __name__ == '__main__': unittest.main()
