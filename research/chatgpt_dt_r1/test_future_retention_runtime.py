"""Control-flow tests for the explicit protected, ciphertext-only retention mode."""
from contextlib import nullcontext
import unittest
from unittest.mock import patch


class FutureRetentionRuntimeTests(unittest.TestCase):
    def test_the_witness_cannot_be_the_producer_or_the_retention_run(self):
        from scripts import keirin_dt_r1_future_retain as command

        with (patch.object(command.reader, '_runtime', return_value=('303', 'f' * 40)),
              patch.object(command.archive, '_remote') as open_git):
            for producer, readback in (('101', '101'), ('303', '202'), ('101', '303')):
                with self.subTest(producer=producer, readback=readback):
                    with self.assertRaisesRegex(ValueError, 'DISTINCT_RUNS_REQUIRED'):
                        command.retain('/protected/runner', producer, readback)
        open_git.assert_not_called()

    def test_failed_independent_server_authentication_never_opens_archive_writer(self):
        from scripts import keirin_dt_r1_future_retain as command

        client = object()
        with (patch.object(command.reader, '_runtime', return_value=('303', 'f' * 40)),
              patch.object(command.archive, '_remote', return_value='/protected/runner'),
              patch.object(command.reader, 'verified_producer', return_value=nullcontext({})),
              patch.object(command.reader, 'verify_readback', side_effect=ValueError('witness hold')),
              patch.object(command.archive, '_refresh') as refresh,
              patch.object(command, 'append_verified_batch') as append):
            with self.assertRaisesRegex(ValueError, 'witness hold'):
                command.retain('/protected/runner', '101', '202', client=client)
        refresh.assert_not_called()
        append.assert_not_called()
