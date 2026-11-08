"""The existing display job can publish forecasts without starting a collector."""
import os,re,subprocess,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
import yaml

ROOT=Path(__file__).resolve().parents[1]
BRANCH='codex/forecast-first-display-20261108'
REF='refs/heads/'+BRANCH


def condition(expression,*,ref=REF,subject='saved-view: forecasts-first',actor='173585154',repo='haji84/RACE-AI'):
    expression=expression.removeprefix('${{').removesuffix('}}').strip()
    expression=re.sub(r'!(?!=)',' not ',expression).replace('&&',' and ').replace('||',' or ')
    github=N(ref=ref,repository=repo,repository_id='1416489937',actor_id=actor,event_name='push',event=N(head_commit=N(message=subject)))
    steps=N(forecast_only_publication=N(outcome='success'),saved_model_publication=N(outcome='success'),browser_tooling=N(outcome='success'))
    return eval(expression,{'__builtins__':{}},{'github':github,'steps':steps,'startsWith':lambda value,prefix:value.startswith(prefix),'always':lambda:True,'hashFiles':lambda pattern:''})


class ForecastOnlyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.w=yaml.load((ROOT/'.github/workflows/boat-nationwide-ab-one-shot.yml').read_text(),Loader=yaml.BaseLoader)
        self.steps=self.w['jobs']['saved_view_publication']['steps']
    def step(self,name):return next(s for s in self.steps if s.get('name')==name)

    def test_owner_only_isolated_branch_never_starts_the_existing_source_job(self):
        self.assertIn(BRANCH,self.w['on']['push']['branches'])
        display=self.w['jobs']['saved_view_publication']['if'];source=self.w['jobs']['official_national']['if']
        self.assertTrue(condition(display));self.assertFalse(condition(source))
        for values in (dict(actor='1'),dict(subject='unrelated update'),dict(subject='saved-view: unrelated')):
            self.assertFalse(condition(display,**values));self.assertFalse(condition(source,**values))
        self.assertTrue(condition(source,ref='refs/heads/feat/four-sport-forecast-audit-view-20261022',subject='boat-live: existing source'))
        self.assertEqual(condition(self.w['concurrency']['group'],subject='unrelated update'),'boat-saved-view-publication')

    def test_no_new_workflow_job_permission_or_source_timeout(self):
        self.assertEqual(set(self.w['jobs']),{'saved_view_publication','official_national'})
        self.assertEqual(set(self.w['on']),{'push'})
        self.assertEqual(self.w['permissions'],{'contents':'write','actions':'read'})
        self.assertEqual(self.w['concurrency']['cancel-in-progress'],'false')
        self.assertEqual(self.w['jobs']['official_national']['timeout-minutes'],'360')

    def run_publication(self,*,actor='173585154',ref=REF,subject='saved-view: forecasts-first'):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);commands=root/'bin';commands.mkdir();log=root/'calls'
            for name,body in [('git','printf "%s\\n" "$SUBJECT"'),('python','printf "%s\\n" "$*" >> "$LOG"')]:
                p=commands/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o700)
            env=dict(os.environ,PATH=str(commands)+os.pathsep+os.environ['PATH'],LOG=str(log),SUBJECT=subject,
                GITHUB_REF=ref,GITHUB_EVENT_NAME='push',GITHUB_ACTOR_ID=actor,GITHUB_REPOSITORY_ID='1416489937',
                FORECAST_DISPLAY_RUN_ID='42411771346',FORECAST_DISPLAY_DAY='2026-11-08')
            outcome=subprocess.run(['bash','-e','-o','pipefail','-c',self.step('Initialize encrypted display feed')['run']],env=env,capture_output=True,text=True)
            return outcome.returncode,log.read_text().splitlines() if log.exists() else []

    def test_mode_publishes_only_existing_forecast_originals_after_a_second_owner_guard(self):
        code,calls=self.run_publication();self.assertEqual(code,0);self.assertEqual(len(calls),1)
        self.assertIn('--forecasts-only',calls[0]);self.assertIn('--hydrate-originals',calls[0]);self.assertIn('--recover-model-run 42411771346',calls[0])
        self.assertIn('--day 2026-11-08',calls[0]);self.assertNotIn('--seed-only',calls[0]);self.assertNotIn('--result-artifact',calls[0])
        self.assertEqual(self.run_publication(actor='1'),(2,[]))
        code,calls=self.run_publication(ref='refs/heads/feat/four-sport-forecast-audit-view-20261022')
        self.assertEqual(code,0);self.assertEqual(calls,['-m scripts.boat_saved_view_feed --seed-only'])

    def test_forecast_mode_skips_training_result_recovery_and_budget_evaluation(self):
        allowed={'Exact reviewed display publisher','Pinned official parser for retained result bytes','Install pinned encrypted display dependencies',
                 'Initialize encrypted display feed','Install the existing pinned browser checker','Verify the actual private owner site without the local workspace',
                 'Require verified site display and unchanged frozen settlement'}
        for step in self.steps:
            admitted=condition(step['if']) if 'if' in step else True
            if admitted:self.assertIn(step.get('name'),allowed)
        verify=self.step('Verify the actual private owner site without the local workspace')['run']
        self.assertIn('--require-future',verify);self.assertIn('--check-current-day',verify)

    def test_early_hook_follows_retention_and_proof_but_precedes_result_reads(self):
        c=yaml.load((ROOT/'.github/actions/existing-model-round/action.yml').read_text(),Loader=yaml.BaseLoader)['runs']['steps']
        positions={s['name']:i for i,s in enumerate(c)}
        name='Publish retained forecast originals before result work';early=c[positions[name]]
        self.assertIn('--forecasts-only',early['run']);self.assertNotIn('--result-artifact',early['run'])
        for prior in ('Retain exact baseline and supplemental P0 originals beyond artifact expiry','Retain exact additional model execution beyond artifact expiry','Require exact prospective native carrier readback'):
            if prior in positions:self.assertLess(positions[prior],positions[name])
        self.assertLess(positions[name],positions['Read back original and independently check later official results'])
        late=c[positions['Automatically publish encrypted saved-forecast result comparisons']]
        self.assertIn('--result-artifact',late['run'])


if __name__=='__main__':unittest.main()
