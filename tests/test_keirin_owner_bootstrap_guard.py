"""Security invariants for the owner Windows runner, no real registration."""
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
FLOW=ROOT/".github/workflows/keirin-pr71-owner-autonomous.yml"
BOOT=ROOT/"scripts/setup_keirin_owner_runner_windows.ps1"


class WindowsOwnerRuntimeSafetyTests(unittest.TestCase):
    def test_private_job_must_not_run_on_public_or_pr_branches(self):
        workflow=FLOW.read_text(encoding="utf-8")
        private=workflow.split("\n  private-owner-PR71:\n",1)[1]
        self.assertIn("github.event.repository.private == true",private)
        self.assertIn("github.ref == 'refs/heads/main'",private)
        self.assertIn("github.event_name == 'schedule'",private)
        self.assertIn("github.event_name == 'workflow_dispatch'",private)
        self.assertIn("vars.RACE_AI_KEIRIN_OWNER_RUNTIME_ENABLED == 'true'",private)
        self.assertIn("runs-on: [self-hosted, Windows, X64, keirin-owner-private]",private)
        self.assertIn("permissions:\n  contents: read",workflow)
        self.assertIn("cancel-in-progress: false",workflow)
        self.assertIn("ref: 60b739bfb9861cbc48864b83651cfc2fb89c0fe7",
                      workflow)
        self.assertNotIn("pull_request_target",workflow)
        self.assertNotIn("actions/upload-artifact",private)
        self.assertNotIn("git push",private)

    def test_registration_script_validates_repo_private_and_existing_sqlite_first(self):
        code=BOOT.read_text(encoding="utf-8")
        self.assertIn("PUBLIC_REPOSITORY_UNSAFE_FOR_PRIVATE_SELF_HOSTED_RUNNER",code)
        self.assertIn('if (($privacy | Out-String)',code)
        self.assertIn('EXISTING_PRIVATE_PATH_REQUIRED',code)
        self.assertIn('OWNER_SQLITE_PREEXISTING_SCHEMA_OR_INTEGRITY_FAILED',code)
        self.assertIn('mode=ro',code)
        self.assertIn('keirin-owner-private',code)
        self.assertIn('RUNNER_NOT_YET_ONLINE',code)
        self.assertIn('OWNER_PRIVATE_DATA_INSIDE_RUNNER_WORK_DIRECTORY',code)
        self.assertIn('RUN_POWERSHELL_AS_ADMINISTRATOR',code)
        self.assertLess(
            code.index("PUBLIC_REPOSITORY_UNSAFE_FOR_PRIVATE_SELF_HOSTED_RUNNER"),
            code.index("gh secret set RACE_AI_KEIRIN_OWNER_DB"))
        self.assertLess(code.index("RUNNER_NOT_YET_ONLINE"),
                        code.index("gh variable set RACE_AI_KEIRIN_OWNER_RUNTIME_ENABLED"))
        self.assertNotIn("gh secret set RACE_AI_STATE_KEY",code)
        self.assertNotIn("Write-Output $token",code)

    def test_public_ci_never_requires_private_secrets_or_windows_runner(self):
        code=FLOW.read_text(encoding="utf-8")
        public=code.split("\n  public-preflight:\n",1)[1].split(
            "\n  private-owner-PR71:\n",1)[0]
        self.assertIn("runs-on: ubuntu-24.04",public)
        self.assertNotIn("secrets.",public)
        self.assertNotIn("keirin-owner-private",public)
        self.assertNotIn("RACE_AI_KEIRIN_OWNER_DB",public)
        self.assertNotIn("owner.csv",public.lower())


if __name__=="__main__":
    unittest.main()
