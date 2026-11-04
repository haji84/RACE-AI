"""Guard the real composite round, not the obsolete inline workflow layout."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/boat-nationwide-ab-one-shot.yml'
ROUND = ROOT / '.github/actions/existing-model-round/action.yml'
UPLOAD = 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'


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
        self.assertEqual(len(steps), 6)
        prepare, forecast, freeze, audit, result, complete = steps
        self.assertIn('id: ready', prepare)
        self.assertIn('github_existing_cycle.py repeat-prepare', prepare)
        self.assertIn('github_existing_cycle.py forecast', forecast)
        for step in steps[1:]:
            self.assertIn("if: steps.ready.outputs.active == 'true'", step)
            self.assertNotIn('continue-on-error:', step)
        for step, ident, path, name in [
            (freeze, 'freeze', 'boat_nationwide_output/national.json', 'forecast_name'),
            (result, 'result', 'existing_cycle_output/', 'result_name'),
        ]:
            self.assertIn('id: ' + ident, step)
            self.assertIn('uses: ' + UPLOAD, step)
            self.assertIn('path: ' + path, step)
            self.assertIn('steps.ready.outputs.' + name, step)
            self.assertIn('if-no-files-found: error', step)
            self.assertNotIn('overwrite: true', step)
        self.assertIn('github_existing_cycle.py audit', audit)
        self.assertIn("--p1-artifact '${{ steps.freeze.outputs.artifact-id }}'", audit)
        self.assertIn('github_existing_cycle.py repeat-complete', complete)
        self.assertIn("--p1-artifact '${{ steps.freeze.outputs.artifact-id }}'", complete)
        self.assertIn("--result-artifact '${{ steps.result.outputs.artifact-id }}'", complete)

    def test_existing_cycle_is_read_only_and_keeps_first_original(self):
        text = WORKFLOW.read_text()
        self.assertIn('contents: read', text)
        self.assertIn('actions: read', text)
        self.assertNotIn('contents: write', text)
        self.assertNotIn('run: python scripts/existing_day_program.py', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertLess(text.index('github_existing_cycle.py restore'), text.index('github_existing_cycle.py supplement'))
        self.assertLess(text.index('id: p0supplement'), text.index('github_existing_cycle.py repeat-start'))
        self.assertLess(text.index('github_existing_cycle.py repeat-start'), text.index('uses: ./.github/actions/existing-model-round'))
        self.assert_round_contract(ROUND.read_text())

    def test_result_before_forecast_freeze_is_rejected(self):
        text = ROUND.read_text()
        parts = re.split(r'(?=^    - name: )', text, flags=re.MULTILINE)
        parts[3], parts[4] = parts[4], parts[3]
        with self.assertRaises(AssertionError):
            self.assert_round_contract(''.join(parts))

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
