"""The isolated Node resolver receives one fixed verified tooling directory."""
import os
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import all_existing_model_future_source_capture as worker


class FutureNodePathTests(unittest.TestCase):
    def test_real_node_resolves_only_the_authored_isolated_module(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)/'runner temp';modules=root/'race-ai-future-ui-tools'/'node_modules'
            package=modules/'playwright';package.mkdir(parents=True)
            (package/'index.js').write_text('module.exports={fixture:true};')
            env=dict(PATH=os.environ['PATH'],GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',
                GITHUB_REPOSITORY_ID='1416489937',RUNNER_TEMP=str(root),NODE_PATH=str(modules))
            with patch.dict(os.environ,env,clear=True):filtered=worker._node_environment()
            result=subprocess.run(['node','-e','process.stdout.write(String(require("playwright").fixture))'],
                env=filtered,capture_output=True,timeout=5,check=False,cwd=root)
            self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stdout,b'true')

    def test_only_fixed_real_runner_tooling_path_is_forwarded_without_secrets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);modules=root/'race-ai-future-ui-tools'/'node_modules';modules.mkdir(parents=True)
            browser=root/'browser';browser.mkdir(mode=0o700)
            index=browser/'capture-index.json';index.write_text('{}');index.chmod(0o600)
            env=dict(GITHUB_ACTIONS='true',GITHUB_REPOSITORY='haji84/RACE-AI',GITHUB_REPOSITORY_ID='1416489937',
                RUNNER_TEMP=str(root),NODE_PATH=str(modules),NODE_OPTIONS='private',RACE_AI_STATE_KEY='private',
                GH_TOKEN='private',PNPM_HOME='private',ARBITRARY_SECRET='private')
            with patch.dict(os.environ,env,clear=True),patch.object(worker.subprocess,'run',return_value=
                SimpleNamespace(returncode=0,stdout=b'{}',stderr=b'')) as launch:
                worker.capture_browser({},browser)
            actual=launch.call_args.kwargs['env']
            self.assertEqual(actual['NODE_PATH'],str(modules))
            self.assertFalse({'NODE_OPTIONS','RACE_AI_STATE_KEY','GH_TOKEN','PNPM_HOME','ARBITRARY_SECRET'}&set(actual))

    def test_relative_multiple_repo_arbitrary_or_escaping_paths_stop_before_node(self):
        for change in ('relative','multiple','other','repo','symlink','not_actions','missing'):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);modules=root/'race-ai-future-ui-tools'/'node_modules';modules.mkdir(parents=True)
                browser=root/'browser';browser.mkdir(mode=0o700)
                index=browser/'capture-index.json';index.write_text('{}');index.chmod(0o600)
                path=str(modules)
                if change=='relative':path='race-ai-future-ui-tools/node_modules'
                elif change=='multiple':path+=os.pathsep+'/other/modules'
                elif change=='other':path=str(root/'other'/'node_modules')
                elif change=='repo':path=str(Path(__file__).resolve().parents[1]/'node_modules')
                elif change=='symlink':
                    modules.rmdir();outside=root/'outside';outside.mkdir();modules.symlink_to(outside,target_is_directory=True)
                elif change=='missing':modules.rmdir()
                env=dict(GITHUB_ACTIONS='false' if change=='not_actions' else 'true',GITHUB_REPOSITORY='haji84/RACE-AI',
                    GITHUB_REPOSITORY_ID='1416489937',RUNNER_TEMP=str(root),NODE_PATH=path)
                with patch.dict(os.environ,env,clear=True),patch.object(worker.subprocess,'run') as launch:
                    with self.subTest(change=change),self.assertRaises(ValueError):worker.capture_browser({},browser)
                launch.assert_not_called()


if __name__=='__main__':unittest.main()
