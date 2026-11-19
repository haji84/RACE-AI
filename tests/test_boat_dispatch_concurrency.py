"""Owner completion must not be coalesced behind a result-only workflow run."""
from pathlib import Path
from types import SimpleNamespace
import unittest


def configured_group(event_name, message=''):
    text = Path('.github/workflows/boat-racer-daily.yml').read_text()
    block = text.split('\nconcurrency:\n', 1)[1].split('\njobs:\n', 1)[0]
    expression = block.split('${{', 1)[1].split('}}', 1)[0]
    expression = expression.replace('&&', 'and').replace('||', 'or')
    github = SimpleNamespace(event_name=event_name,
        event=SimpleNamespace(head_commit=SimpleNamespace(message=message)))
    # This is the trusted repository's own GitHub expression, never input data.
    return eval(expression, {'__builtins__': {}}, {
        'github': github, 'startsWith': lambda a, b: a.startswith(b)})


class OwnerDispatchConcurrencyTests(unittest.TestCase):
    def test_completed_owner_cannot_be_replaced_by_pending_result_refresh(self):
        owner = configured_group('workflow_run')
        result = configured_group('workflow_dispatch')
        self.assertNotEqual(owner, result)
        self.assertEqual(result, configured_group('schedule'))

    def test_approved_release_uses_owner_queue_and_normal_push_keeps_result_queue(self):
        release = configured_group('push', 'boat-owner-release: single-real-session-20261111 | verified')
        self.assertEqual(release, configured_group('workflow_run'))
        self.assertNotEqual(release, configured_group('push', 'ordinary documentation update'))

    def test_pr_has_separate_queue_and_real_owner_mutex_is_preserved(self):
        self.assertEqual(configured_group('pull_request'), 'boat-mirror-sourcefree-pr-ci')
        text = Path('.github/workflows/boat-racer-daily.yml').read_text()
        owner = text.split('\n  owner_p0_p1_dispatch:\n', 1)[1]
        self.assertIn('group: boat-main-launcher-source-free', owner)
        self.assertIn('cancel-in-progress: false', owner)
        self.assertIn('--verify-source-handoff', owner)


if __name__ == '__main__':
    unittest.main()
