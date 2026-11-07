"""Guard the real composite round, not the obsolete inline workflow layout."""
import re
import os
import subprocess
import tempfile
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/boat-nationwide-ab-one-shot.yml'
ROUND = ROOT / '.github/actions/existing-model-round/action.yml'
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
RETENTION_NAMES = (
    'Retain pinned official-result originals with the existing serialized state writer',
    'Keep count-only official-result original retention status',
)


class WorkflowReferencesTest(unittest.TestCase):
    def test_viewer_checks_out_both_real_pinned_dependencies(self):
        text = (ROOT / '.github/workflows/forecast-audit-ui.yml').read_text().split('  viewer_contract:', 1)[1]
        for ref, path in [
            ('761247bee0209e37b1af6b8885e92cad3e9260a5', 'pr64-reference'),
            ('7a432e5acc4d3495a0e82bd79726929e2f8085fe', 'pr72-reference'),
        ]:
            self.assertIn(ref, text)
            self.assertIn('path: ' + path, text)
        self.assertLess(text.index('path: pr72-reference'), text.index('python -m unittest discover'))

    def assert_round_contract(self, text):
        self.assertIn('using: composite', text)
        steps = re.split(r'^    - name: ', text, flags=re.MULTILINE)[1:]
        private_steps=[step for step in steps if 'venue-research-' in step]
        model_steps=[step for step in steps if 'boat_all_model_cycle' in step or 'boat-all-model-forecasts' in step]
        protection_steps=[step for step in steps if 'boat_private_original_archive' in step]
        vault_steps=[step for step in steps if 'boat_private_original_vault' in step]
        evaluation_steps=[step for step in steps if 'boat_prospective_audit' in step or 'boat-prospective-audit' in step]
        # Keep the original nine mandatory steps separate from optional retention.
        retention_steps=[step for step in steps if step.split('\n',1)[0] in RETENTION_NAMES]
        result_retention_steps=retention_steps
        baseline_steps=[step for step in steps if step not in private_steps+model_steps+protection_steps+vault_steps+evaluation_steps+retention_steps]
        self.assertEqual(len(baseline_steps), 9)
        prepare, discovery, p0freeze, forecast, freeze, audit, result, complete, display = baseline_steps
        self.assertIn('id: ready', prepare)
        self.assertIn('github_existing_cycle.py repeat-prepare', prepare)
        self.assertIn('github_existing_cycle.py supplement --round', discovery)
        self.assertIn('id: discovery', discovery)
        self.assertIn('id: discovery_freeze', p0freeze)
        self.assertIn("steps.discovery.outputs.supplement_ready == 'true'", p0freeze)
        self.assertIn('path: ${{ runner.temp }}/boat-private-originals/p0-supplement-${{ inputs.round }}/private-original.enc', p0freeze)
        self.assertIn('steps.ready.outputs.p0_name', p0freeze)
        self.assertIn('uses: ' + UPLOAD, p0freeze)
        self.assertIn('if-no-files-found: error', p0freeze)
        self.assertNotIn('overwrite: true', p0freeze)
        self.assertIn('github_existing_cycle.py forecast', forecast)
        for step in baseline_steps[1:-1]:
            self.assertIn("if: steps.ready.outputs.active == 'true'", step)
            self.assertNotIn('continue-on-error:', step)
        for step, ident, path, name in [
            (freeze, 'freeze', '${{ runner.temp }}/boat-private-originals/p1-${{ inputs.round }}/private-original.enc', 'forecast_name'),
            (result, 'result', '${{ runner.temp }}/boat-private-originals/result-${{ inputs.round }}/private-original.enc', 'result_name'),
        ]:
            self.assertIn('id: ' + ident, step)
            self.assertIn('uses: ' + UPLOAD, step)
            self.assertIn('path: ' + path, step)
            self.assertIn('steps.ready.outputs.' + name, step)
            self.assertIn('if-no-files-found: error', step)
            self.assertNotIn('overwrite: true', step)
        self.assertIn('github_existing_cycle.py audit', audit)
        self.assertIn('P0_SUPPLEMENT_ARTIFACT: ${{ steps.discovery_freeze.outputs.artifact-id }}', audit)
        self.assertIn('supplement_args+=(--p0-supplement "$P0_SUPPLEMENT_ARTIFACT")', audit)
        self.assertIn("--p1-artifact '${{ steps.freeze.outputs.artifact-id }}'", audit)
        self.assertEqual(len(result_retention_steps), 2)
        original_retain, count_receipt = result_retention_steps
        self.assertTrue(original_retain.startswith('Retain pinned official-result originals'))
        self.assertTrue(count_receipt.startswith('Keep count-only official-result original retention status'))
        self.assertIn('scripts.all_existing_model_official_result_retain --input audit/state/official-result-retention-input.json', original_retain)
        self.assertIn("if: steps.ready.outputs.active == 'true'", original_retain)
        self.assertIn('RACE_AI_STATE_KEY: ${{ inputs.saved-view-key }}', original_retain)
        self.assertIn('continue-on-error: true', original_retain)
        self.assertIn("if: always() && steps.ready.outputs.active == 'true'", count_receipt)
        self.assertIn('audit/state/official-result-retention-input.json', count_receipt)
        self.assertIn('uses: ' + UPLOAD, count_receipt)
        self.assertIn('if-no-files-found: error', count_receipt)
        self.assertIn('continue-on-error: true', count_receipt)
        self.assertLess(text.index(complete), text.index(original_retain))
        self.assertLess(text.index(original_retain), text.index(count_receipt))
        self.assertLess(text.index(count_receipt), text.index(display))
        self.assertIn('github_existing_cycle.py repeat-complete', complete)
        self.assertIn("--p1-artifact '${{ steps.freeze.outputs.artifact-id }}'", complete)
        self.assertIn("--result-artifact '${{ steps.result.outputs.artifact-id }}'", complete)
        self.assertIn('if ! python -m scripts.boat_saved_view_feed',display)
        self.assertIn('::warning::',display)
        self.assertIn('scripts.boat_saved_view_feed --result-artifact',display)
        self.assertIn('RACE_AI_STATE_KEY: ${{ inputs.saved-view-key }}',display)
        self.assertIn("if: steps.ready.outputs.active == 'true'",display)
        self.assertEqual(len(model_steps),4)
        preload,generate,encrypted_freeze,receipt=model_steps
        self.assertIn(' prepare --round ',preload)
        self.assertLess(text.index(preload),text.index(forecast))
        self.assertLess(text.index(freeze),text.index(generate))
        self.assertIn("--baseline-artifact '${{ steps.freeze.outputs.artifact-id }}'",generate)
        self.assertLess(text.index(generate),text.index(encrypted_freeze))
        self.assertLess(text.index(encrypted_freeze),text.index(receipt))
        self.assertLess(text.index(receipt),text.index(audit))
        self.assertIn('forecasts.enc',encrypted_freeze)
        self.assertNotIn('forecasts.json',encrypted_freeze)
        self.assertIn('steps.all_models_freeze.outputs.artifact-id',receipt)
        for step in model_steps:self.assertIn('continue-on-error: true',step)
        self.assertEqual(len(protection_steps),3)
        for protected,kind,upload in zip(protection_steps,('P0','P1','RESULT'),(p0freeze,freeze,result)):
            self.assertIn('--kind '+kind,protected)
            self.assertNotIn('continue-on-error:',protected)
            self.assertIn('RACE_AI_STATE_KEY: ${{ inputs.saved-view-key }}',protected)
            self.assertLess(text.index(protected),text.index(upload))
        # Optional private work may fail independently; ordinary forecast and
        # result originals must retain their strict failure and receipt rules.
        self.assertEqual(len(private_steps),6)
        private_forecast,private_freeze,private_receipt,private_pdca,private_retain,private_result=private_steps
        for step in private_steps:self.assertIn("if: steps.ready.outputs.active == 'true'",step)
        for step in (private_freeze,private_result):
            self.assertIn('uses: '+UPLOAD,step)
            self.assertIn('continue-on-error: true',step)
            self.assertIn('path: ${{ runner.temp }}/boat-venue-research-',step)
            self.assertNotIn('overwrite: true',step)
        self.assertIn('steps.venue_research_freeze.outputs.artifact-id',private_receipt)
        for before,after in ((freeze,private_forecast),(private_forecast,private_freeze),
                             (private_freeze,private_receipt),(private_receipt,audit),
                             (audit,private_pdca),(private_pdca,private_retain),(private_retain,result)):
            self.assertLess(text.index(before),text.index(after))
        self.assert_retention_contract(text,retention_steps,complete,display)

    def assert_retention_contract(self,text,steps,complete,display):
        self.assertEqual(len(steps),2)
        retain,status=steps
        self.assertEqual([step.split('\n',1)[0] for step in steps],list(RETENTION_NAMES))
        manifest="hashFiles('audit/state/official-result-retention-input.json') != ''"
        ready="steps.ready.outputs.active == 'true'"
        condition=lambda step:next(line.strip() for line in step.splitlines() if line.strip().startswith('if:'))
        self.assertEqual(condition(retain),'if: '+ready+' && '+manifest)
        self.assertEqual(condition(status),'if: always() && '+ready+' && '+manifest)
        for step in steps:
            self.assertIn('continue-on-error: true',step)
            self.assertNotIn('overwrite: true',step)
        self.assertLess(text.index(complete),text.index(retain))
        self.assertLess(text.index(retain),text.index(status))
        self.assertLess(text.index(status),text.index(display))
        self.assertIn('shell: bash',retain)
        environment=retain.split('      env:\n',1)[1].split('      run:',1)[0]
        self.assertEqual([line.strip() for line in environment.splitlines() if line.strip()],
            ['GH_TOKEN: ${{ github.token }}','RACE_AI_STATE_KEY: ${{ inputs.saved-view-key }}'])
        command=("python -m scripts.all_existing_model_official_result_retain "
            "--input audit/state/official-result-retention-input.json "
            "--out-dir '${{ runner.temp }}/official-result-retention' "
            "> '${{ runner.temp }}/official-result-retention-status.json'")
        self.assertEqual([line.strip() for line in retain.split('      run: |\n',1)[1].splitlines() if line.strip()],
                         ['umask 077',command])
        # This optional extension cannot acquire providers or issue source
        # control from the action, and publishes only the fixed safe status.
        self.assertNotRegex(retain,r'https?://|curl\b|wget\b|gh api\b|--force\b')
        self.assertIn('uses: '+UPLOAD,status)
        fields=status.split('      with:\n',1)[1]
        self.assertEqual([line.strip() for line in fields.splitlines() if line.strip()],
            ['name: official-result-retention-${{ github.run_id }}-${{ inputs.round }}',
             'path: ${{ runner.temp }}/official-result-retention-status.json',
             'retention-days: 7','if-no-files-found: error'])
        self.assertNotIn('env:',status)
        self.assertNotIn('RACE_AI_STATE_KEY',status)
        self.assertNotIn('GH_TOKEN',status)

    def test_display_only_activation_cannot_queue_another_official_collector(self):
        text=WORKFLOW.read_text()
        display=text.split('  saved_view_publication:',1)[1].split('  official_national:',1)[0]
        self.assertIn("startsWith(github.event.head_commit.message, 'saved-view:')",display)
        self.assertIn('scripts.boat_original_maintenance backfill',display)
        self.assertNotIn('github_existing_cycle.py forecast',display)
        self.assertNotIn('github_existing_cycle.py repeat-start',display)
        self.assertEqual(re.findall(r'run: python scripts/github_existing_cycle\.py ([^\n]+)',display),[])
        self.assertIn('RACE_AI_ORIGINAL_VAULT_ENABLED:',display)
        self.assertIn('boat_saved_view_feed --hydrate-originals',display)
        self.assertNotIn('first_p0_bootstrap.py',display)
        official=text.split('  official_national:',1)[1]
        self.assertIn("!startsWith(github.event.head_commit.message, 'saved-view:')",official)
        self.assertIn("&& 'boat-saved-view-publication' || 'boat-nationwide-cutoff-20261103'",text)
        self.assertIn('cancel-in-progress: false',text)

    def test_existing_cycle_create_only_first_p0_then_reuses_original(self):
        text = WORKFLOW.read_text()
        # The existing first-receipt bootstrap now creates its metadata index;
        # recurring rounds additionally publish display-only ciphertext. Source
        # accounting starts before the missing-only supplement, not after it.
        self.assertRegex(text,r'permissions:\n  contents: write[^\n]*\n  actions: read\n')
        self.assertIn('actions: read', text)
        self.assertIn('persist-credentials: false', text)
        for marker in ('id: first_p0', 'first_p0_bootstrap.py preflight',
                       'first_p0_bootstrap.py capture', 'id: first_upload',
                       'first_p0_bootstrap.py finalize --artifact-id'):
            self.assertIn(marker, text)
        self.assertIn("if: steps.first_p0.outputs.capture != 'true'", text)
        self.assertLess(text.index('first_p0_bootstrap.py preflight'), text.index('first_p0_bootstrap.py capture'))
        self.assertLess(text.index('first_p0_bootstrap.py capture'), text.index('id: first_upload'))
        self.assertIn('first_p0_bootstrap.py capture-wait', text)
        self.assertNotIn('id: p0supplement', text)
        self.assertNotIn('run: python scripts/existing_day_program.py', text)
        self.assertIn('cancel-in-progress: false', text)
        finalize = next(step for step in re.split(r'^      - name: ', text, flags=re.MULTILINE)
                        if 'run: python scripts/first_p0_bootstrap.py finalize' in step)
        self.assertIn("if: steps.first_p0.outputs.capture == 'true'", finalize)
        self.assertIn('steps.first_upload.outputs.artifact-id', finalize)
        self.assertLess(text.index('id: first_upload'), text.index('first_p0_bootstrap.py finalize'))
        official=text.split('  official_national:',1)[1]
        self.assertLess(official.index('first_p0_bootstrap.py finalize'), official.index('github_existing_cycle.py restore'))
        self.assertLess(official.index('github_existing_cycle.py restore'), official.index('github_existing_cycle.py repeat-start'))
        self.assertIn('RACE_AI_FIRST_P0_CAPTURED: ${{ steps.first_p0.outputs.capture }}', text)
        self.assertNotIn('github_existing_cycle.py supplement', text)
        workers = [step for step in re.split(r'^      - name: ', text, flags=re.MULTILINE)
                   if 'uses: ./.github/actions/existing-model-round' in step]
        self.assertEqual(len(workers), 24)
        for worker in workers:
            self.assertIn("if: steps.repeat_start.outputs.session_ready == 'true'", worker)
        self.assertIn('timeout-minutes: 360', text)
        self.assertIn('RACE_AI_EVENT_DAY=', text)
        self.assertIn('RACE_AI_WORKER_HANDOFF_AT=', text)
        self.assertIn('datetime.now(timezone.utc)', text)
        self.assertLess(text.index('python -m unittest'), text.index('RACE_AI_EVENT_DAY='))
        self.assertLess(text.index('RACE_AI_EVENT_DAY='), text.index('first_p0_bootstrap.py preflight'))
        self.assertIn('timedelta(minutes=330)', text)
        for name in ('Save first P0 separately', 'Read back original ZIP'):
            step = next(step for step in re.split(r'^      - name: ', text, flags=re.MULTILINE)
                        if step.startswith(name))
            self.assertIn("steps.first_capture.outputs.capture_complete == 'true'", step)
        self.assertIn("if: steps.restore.conclusion == 'success'", text)
        for command in ('git push', 'gh api --method PUT', 'first_p0_bootstrap.py finalize'):
            self.assertNotIn(command, ROUND.read_text())
        self.assert_round_contract(ROUND.read_text())

    def test_private_work_before_baseline_freeze_is_rejected(self):
        text = ROUND.read_text()
        parts = re.split(r'(?=^    - name: )', text, flags=re.MULTILINE)
        left=next(i for i,p in enumerate(parts) if p.startswith('    - name: Freeze this round before'))
        right=next(i for i,p in enumerate(parts) if p.startswith('    - name: Generate private venue research'))
        parts[left],parts[right]=parts[right],parts[left]
        with self.assertRaises(AssertionError):
            self.assert_round_contract(''.join(parts))

    def test_optional_retention_cannot_fetch_by_default_leak_credentials_or_replace_originals(self):
        text=ROUND.read_text()
        retain=next(step for step in re.split(r'^    - name: ',text,flags=re.MULTILINE)
                    if step.startswith(RETENTION_NAMES[0]))
        status=next(step for step in re.split(r'^    - name: ',text,flags=re.MULTILINE)
                    if step.startswith(RETENTION_NAMES[1]))
        mutations=[
            (retain,retain.replace(" && hashFiles('audit/state/official-result-retention-input.json') != ''",'')),
            (retain,retain.replace(" != ''"," == ''")),
            (retain,retain.replace('scripts.all_existing_model_official_result_retain','scripts.all_existing_model_official_result_collect')),
            (retain,retain.replace('        umask 077\n','')),
            (retain,retain.replace('GH_TOKEN: ${{ github.token }}','GH_TOKEN: unscoped-token')),
            (retain,retain.replace('RACE_AI_STATE_KEY: ${{ inputs.saved-view-key }}','RACE_AI_STATE_KEY: public-fallback')),
            (status,status.replace('path: ${{ runner.temp }}/official-result-retention-status.json','path: ${{ runner.temp }}/official-result-retention/')),
            (status,status.replace('retention-days: 7','retention-days: 7\n        overwrite: true')),
            (status,status.replace(UPLOAD,'actions/upload-artifact@main')),
            (status,status.replace('      with:\n','      env:\n        RACE_AI_STATE_KEY: ${{ inputs.saved-view-key }}\n      with:\n')),
        ]
        for old,new in mutations:
            with self.subTest(mutation=new.splitlines()[0]),self.assertRaises(AssertionError):
                self.assert_round_contract(text.replace(old,new,1))

    def test_optional_retention_before_round_completion_is_rejected(self):
        parts=re.split(r'(?=^    - name: )',ROUND.read_text(),flags=re.MULTILINE)
        complete=next(i for i,p in enumerate(parts) if 'github_existing_cycle.py repeat-complete' in p)
        retention=next(i for i,p in enumerate(parts) if p.startswith('    - name: '+RETENTION_NAMES[0]))
        parts[complete],parts[retention]=parts[retention],parts[complete]
        with self.assertRaises(AssertionError):self.assert_round_contract(''.join(parts))

    def test_first_original_and_checkpoint_never_upload_plaintext(self):
        text=WORKFLOW.read_text().split('  official_national:',1)[1]
        steps=re.split(r'^      - name: ',text,flags=re.MULTILINE)
        first=next(p for p in steps if p.startswith('Save first P0 separately'))
        checkpoint=next(p for p in steps if p.startswith('Preserve verified continuity journal'))
        for step in (first,checkpoint):
            self.assertIn('private-original.enc',step)
            self.assertIn('path: ${{ runner.temp }}/boat-private-originals/',step)
        self.assertIn('boat_private_original_archive pack --kind P0',text)
        self.assertIn('boat_private_original_archive pack --kind CONTINUITY',text)
        self.assertIn("steps.checkpoint_private.outcome == 'success'",checkpoint)

    def test_source_window_precedes_bounded_session_and_control_has_no_original_path(self):
        text=WORKFLOW.read_text().split('  official_national:',1)[1]
        steps=re.split(r'^      - name: ',text,flags=re.MULTILINE)
        window=next(p for p in steps if p.startswith('Wait without source requests'))
        start=next(p for p in steps if p.startswith('Initialize continuous source session'))
        checkpoint=next(p for p in steps if p.startswith('Preserve verified continuity journal'))
        control=next(p for p in steps if p.startswith('Derive count-only handoff control'))
        upload=next(p for p in steps if p.startswith('Preserve count-only source control'))
        self.assertLess(text.index(window),text.index(start))
        self.assertIn('github_existing_cycle.py wait-for-window',window)
        self.assertIn("steps.exhibition_window.outputs.window_ready == 'true'",start)
        self.assertIn('id: checkpoint_upload',checkpoint)
        self.assertIn("steps.checkpoint_upload.outcome == 'success'",control)
        self.assertIn('boat_source_control pack --cipher',control)
        self.assertIn('private-original.enc',control)
        self.assertIn("steps.source_control_pack.outcome == 'success'",upload)
        self.assertIn('race-source-control-${{ github.run_id }}',upload)
        self.assertIn('path: ${{ runner.temp }}/boat-source-control/source-control.json',upload)
        self.assertIn('if-no-files-found: error',upload)
        for step in (window,start,checkpoint,control,upload):
            self.assertNotIn('continue-on-error:',step)
        self.assertNotIn('cycle_checkpoint_output',upload)
        self.assertNotIn('RACE_AI_STATE_KEY',upload)

    def test_missing_or_wrong_receipt_and_overwrite_are_rejected(self):
        text = ROUND.read_text()
        for old, new in [
            ('id: freeze', 'id: wrong'),
            ('steps.freeze.outputs.artifact-id', 'steps.result.outputs.artifact-id'),
            ('if-no-files-found: error', 'if-no-files-found: warn'),
            ('retention-days: 7', 'retention-days: 7\n        overwrite: true'),
            ("if: steps.ready.outputs.active == 'true'", 'continue-on-error: true'),
        ]:
            with self.subTest(mutation=old), self.assertRaises(AssertionError):
                self.assert_round_contract(text.replace(old, new, 1))

    def test_optional_discovery_receipt_is_omitted_when_no_new_original_exists(self):
        audit = next(step for step in re.split(r'^    - name: ', ROUND.read_text(), flags=re.MULTILINE)
                     if 'github_existing_cycle.py audit' in step)
        script = audit.split('      run: |\n', 1)[1]
        script = '\n'.join(line[8:] for line in script.splitlines())
        script = script.replace('${{ inputs.round }}', '1').replace('${{ steps.freeze.outputs.artifact-id }}', '123')
        with tempfile.TemporaryDirectory() as folder:
            executable = Path(folder) / 'python'
            executable.write_text("#!/bin/bash\n/usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\"\n")
            executable.chmod(0o700)
            for receipt in ('', '456'):
                env = dict(os.environ, PATH=folder + os.pathsep + os.environ['PATH'], P0_SUPPLEMENT_ARTIFACT=receipt)
                result = subprocess.run(['bash', '-e', '-c', script], env=env, check=True,
                                        text=True, capture_output=True)
                args = json.loads(result.stdout)
                expected = ['scripts/github_existing_cycle.py', 'audit', '--round', '1', '--p1-artifact', '123']
                self.assertEqual(args, expected + (['--p0-supplement', receipt] if receipt else []))
