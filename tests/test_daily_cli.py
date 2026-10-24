import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DailyCLITests(unittest.TestCase):
    def test_missing_licenced_source_safe_stop_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'daily.json'
            html=Path(tmp)/'daily.html'
            result=subprocess.run(
                [sys.executable,'-m','race_ai.daily','--input-dir',tmp,
                 '--asof','2026-10-14T23:00:00+09:00',
                 '--output',str(out),'--html-output',str(html)],
                text=True,capture_output=True)
            self.assertEqual(result.returncode,2)
            self.assertTrue(out.exists())
            self.assertTrue(html.exists())
            report=json.loads(out.read_text(encoding='utf-8'))
            self.assertEqual(report['status'],'SAFE_STOP_MISSING_OR_INVALID_SOURCE')
            self.assertIn('検証停止',html.read_text(encoding='utf-8'))

    def test_partial_inventory_creates_report_but_not_green_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'inventory.json').write_text(json.dumps({
                'rights_confirmed':True,
                'published_at':'2026-10-14T22:00:00+09:00',
                'captured_at':'2026-10-14T22:01:00+09:00',
                'venues':[{'venue':'19','motor_cycle':'2026-A',
                           'motors':[11,12]}]}),encoding='utf-8')
            output=root/'out.json'
            html=root/'out.html'
            result=subprocess.run(
                [sys.executable,'-m','race_ai.daily','--input-dir',tmp,
                 '--asof','2026-10-14T23:00:00+09:00',
                 '--output',str(output),'--html-output',str(html)],
                text=True,capture_output=True)
            self.assertEqual(result.returncode,3)
            report=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(report['inventory_count'],2)
            self.assertEqual(report['status'],'PARTIAL_VENUE_SCOPE')
            self.assertTrue(html.exists())


if __name__=='__main__':
    unittest.main()
