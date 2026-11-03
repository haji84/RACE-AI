import unittest
from pathlib import Path
class WorkflowReferencesTest(unittest.TestCase):
 def test_viewer_checks_out_both_real_pinned_dependencies(self):
  text=Path('.github/workflows/forecast-audit-ui.yml').read_text().split('  viewer_contract:',1)[1]
  for ref,path in [('761247bee0209e37b1af6b8885e92cad3e9260a5','pr64-reference'),('7a432e5acc4d3495a0e82bd79726929e2f8085fe','pr72-reference')]:
   self.assertIn(ref,text);self.assertIn('path: '+path,text)
  self.assertLess(text.index('path: pr72-reference'),text.index('python -m unittest discover'))
 def test_existing_cycle_is_read_only_and_keeps_first_original(self):
  text=Path('.github/workflows/boat-nationwide-ab-one-shot.yml').read_text()
  self.assertIn('contents: read',text);self.assertNotIn('contents: write',text)
  self.assertIn('github_existing_cycle.py restore',text)
  self.assertNotIn('run: python scripts/existing_day_program.py',text)
  self.assertLess(text.index('id: p1freeze'),text.index('github_existing_cycle.py audit'))
