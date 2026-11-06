"""Nested runtime/feed writers share one repository-scoped credential header."""
import os
import unittest
from unittest.mock import patch
from scripts.boat_saved_view_feed import git_auth

class GitAuthTests(unittest.TestCase):
 def test_repeated_runtime_preparation_does_not_send_duplicate_authorization(self):
  with patch.dict(os.environ,{'GH_TOKEN':'fictional-only','GIT_CONFIG_COUNT':'0'},clear=True):
   git_auth();first=dict(os.environ);git_auth();self.assertEqual(dict(os.environ),first)
   self.assertEqual(os.environ['GIT_CONFIG_COUNT'],'1')
 def test_unrelated_process_configuration_is_preserved(self):
  env={'GH_TOKEN':'fictional-only','GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'core.quotepath','GIT_CONFIG_VALUE_0':'false'}
  with patch.dict(os.environ,env,clear=True):
   git_auth();git_auth();self.assertEqual(os.environ['GIT_CONFIG_COUNT'],'2')
   self.assertEqual(os.environ['GIT_CONFIG_VALUE_0'],'false')
 def test_conflicting_credential_halts_without_echoing_either_value(self):
  env={'GH_TOKEN':'fictional-only','GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'http.https://github.com/haji84/RACE-AI.extraheader','GIT_CONFIG_VALUE_0':'unrelated-private-header'}
  with patch.dict(os.environ,env,clear=True):
   with self.assertRaisesRegex(ValueError,'^FEED_GIT_CREDENTIAL_SCOPE_CONFLICT$'):git_auth()
