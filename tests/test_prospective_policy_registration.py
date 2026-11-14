"""Execute the real count-only witness guard, including the wrong-schema bug."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
PLAN='docs/evidence/2026-11-07/prospective-evaluation-plan.json'


def guard():
    text=(ROOT/'.github/workflows/boat-nationwide-ab-one-shot.yml').read_text()
    step=next(s for s in re.split(r'^      - name: ',text,flags=re.MULTILINE)
              if s.startswith('Verify public prospective policy'))
    return '\n'.join(line[10:] for line in step.split('        run: |\n',1)[1].splitlines())


class PolicyRegistrationTests(unittest.TestCase):
    def test_actual_public_declaration_runs_without_exposing_private_plan(self):
        document=json.loads((ROOT/PLAN).read_text())
        self.assertEqual(document['schema'],'RACE_AI_PROSPECTIVE_EVALUATION_REGISTRATION_V1')
        self.assertFalse({'tickets','cohort','plans','participants','ordered_top8'} & set(document))
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'outputs'
            result=subprocess.run(['bash','-e','-c',guard()],cwd=ROOT,
                env=dict(os.environ,GITHUB_OUTPUT=str(output)),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout)
            self.assertIn(report['status'],('PROSPECTIVE_POLICY_WINDOW_OPEN','PROSPECTIVE_POLICY_WINDOW_CLOSED'))
            self.assertFalse(report['private_plan_uploaded'])
            self.assertIn(output.read_text(),('ready=true\n','ready=false\n'))

    def test_counts_document_cannot_overwrite_the_declaration_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/PLAN;path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'schema':'RACE_AI_PRE_OUTCOME_BUDGET_PLAN_COUNTS_V1'}))
            result=subprocess.run(['bash','-e','-c',guard()],cwd=folder,
                env=dict(os.environ,GITHUB_OUTPUT=str(Path(folder)/'out')),capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse((Path(folder)/'out').exists())


if __name__=='__main__':unittest.main()
