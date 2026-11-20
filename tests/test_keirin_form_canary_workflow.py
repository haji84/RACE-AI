"""Evaluate trusted-main event and dependency gates for the scoped trial."""
from types import SimpleNamespace as NS
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest

from tests.test_keirin_official_workflow import jobs


class FormCanaryWorkflow(unittest.TestCase):
    def allowed(self, name, **changes):
        _, blocks = jobs()
        self.assertTrue(name in blocks, "Scoped job missing: " + name)
        expression = blocks[name].split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
        expression = " ".join(expression.split()).replace("&&", " and ").replace("||", " or ")
        for old, new in (("source-free-tests", "tests"), ("form-canary-window", "window"),
                         ("form-canary-capture", "capture"),
                         ("form-canary-independent-readback", "readback")):
            expression = expression.replace("needs."+old, "needs."+new)
        v = dict(repo="haji84/RACE-AI", repo_id="1416489937", ref="refs/heads/main",
                 event="push", mode="form-canary", tests="success", window="success",
                 capture_window="true", settle_window="false", capture="success",
                 archived="true", readback="success")
        v.update(changes)
        context = {"github":NS(repository=v["repo"], repository_id=v["repo_id"],
                              ref=v["ref"], event_name=v["event"]),
                   "inputs":NS(mode=v["mode"]), "always":lambda:True,
                   "needs":NS(tests=NS(result=v["tests"]),
                       window=NS(result=v["window"], outputs=NS(
                           capture=v["capture_window"], settle=v["settle_window"])),
                       capture=NS(result=v["capture"], outputs=NS(archived=v["archived"])),
                       readback=NS(result=v["readback"]))}
        return bool(eval(expression, {"__builtins__":{}}, context))

    def test_scoped_window_requires_reviewed_main_and_allowed_event(self):
        for changes, expected in (({},True), ({"event":"schedule","tests":"skipped"},True),
                ({"event":"pull_request"},False), ({"repo":"fork/RACE-AI"},False),
                ({"repo_id":"999"},False), ({"ref":"refs/heads/feature"},False),
                ({"tests":"failure"},False),
                ({"event":"workflow_dispatch","mode":"saved-only"},False)):
            with self.subTest(changes=changes):
                self.assertEqual(self.allowed("form-canary-window", **changes), expected)

    def test_capture_and_reader_require_window_and_complete_pair(self):
        self.assertTrue(self.allowed("form-canary-capture"))
        self.assertFalse(self.allowed("form-canary-capture", capture_window="false"))
        self.assertFalse(self.allowed("form-canary-capture", window="failure"))
        self.assertTrue(self.allowed("form-canary-independent-readback"))
        self.assertFalse(self.allowed("form-canary-independent-readback", capture="failure"))
        self.assertFalse(self.allowed("form-canary-independent-readback", archived="false"))

    def test_settlement_can_resume_prior_pair_only_within_result_window(self):
        self.assertFalse(self.allowed("form-canary-settle"))
        self.assertTrue(self.allowed("form-canary-settle", event="schedule",
            settle_window="true", capture_window="false", capture="skipped", readback="skipped"))
        for changes in ({"ref":"refs/heads/feature"}, {"repo_id":"999"},
                        {"window":"failure"}):
            with self.subTest(changes=changes):
                self.assertFalse(self.allowed("form-canary-settle", settle_window="true", **changes))

    def test_capture_hold_keeps_safe_reason_and_failing_exit_status(self):
        _, blocks = jobs()
        capture = blocks["form-canary-capture"]
        script = textwrap.dedent(capture.split("        run: |\n", 1)[1].split(
            "      - uses: actions/upload-artifact", 1)[0])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root / "python"
            executable.write_text("""#!/bin/bash
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 0; fi
printf '%s\\n' '{"state":"HOLD_SYNTHETIC_CAPTURE_FAILURE"}'
exit 2
""")
            executable.chmod(0o700)
            summary = root / "step-summary"
            summary.write_text("")
            env = dict(os.environ, PATH=str(root)+os.pathsep+os.environ["PATH"],
                       RUNNER_TEMP=str(root), GITHUB_RUN_ID="123456",
                       GITHUB_WORKSPACE=str(root), GITHUB_STEP_SUMMARY=str(summary),
                       GITHUB_OUTPUT=str(root / "output"))
            result = subprocess.run(["bash", "-c", script], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn("HOLD_SYNTHETIC_CAPTURE_FAILURE", summary.read_text())
        upload = capture.split("      - uses: actions/upload-artifact", 1)[1].split(
            "      - name:", 1)[0]
        self.assertIn("if: always()", upload)
        self.assertIn("/safe/summary.json", upload)


if __name__ == "__main__":
    unittest.main()
