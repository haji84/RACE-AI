"""New forecast archives must be durable before the encrypted feed moves."""
from contextlib import redirect_stdout
from copy import deepcopy
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import boat_saved_view_feed as cli
from scripts import boat_original_maintenance as maintenance


class OriginalProtectionPublicationTests(unittest.TestCase):
    def execute(self, *, report=None, failure=None, enabled=True, mutate=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);state=root/'audit/state';state.mkdir(parents=True)
            raw=b'invented-bootstrap'
            (state/'boat-saved-view-input.json').write_text(json.dumps(dict(
                schema='RACE_AI_SAVED_VIEW_INPUT_V1',bootstrap=base64.b64encode(raw).decode(),
                bootstrap_sha256=hashlib.sha256(raw).hexdigest(),catchup_artifact_id=1,
                catchup_sha256='a'*64)))
            before=dict(records=[dict(sport='boat',race_id='20261107-01-01',
                event_date_jst='2026-11-07',prediction=dict(artifact_id='101'),
                comparison_predictions=[],result=dict(status='pending'))])
            original=deepcopy(before);events=[];observed=[]
            def intake(value, **_):
                value=value if mutate else deepcopy(value)
                value['records'][0]['comparison_predictions'].append(dict(artifact_id='102'))
                return value
            def protect(old,new,repo):
                events.append('protect');observed.append((deepcopy(old),deepcopy(new),repo))
                if failure is not None:raise failure
                return report if report is not None else dict(complete=True,status='BOAT_FORECAST_ORIGINALS_PROTECTED')
            def publish(*_, **__):
                events.append('publish');return dict(status='ENCRYPTED_VIEW_PUBLISHED')
            output=io.StringIO();git=SimpleNamespace(_saved_history_context=None)
            with patch.object(cli,'ROOT',root),patch.object(cli,'git_auth'),\
                 patch.object(cli.F,'open_bootstrap',return_value={}),\
                 patch.object(cli.F,'FeedRepository',return_value=git),\
                 patch.object(cli.F,'current_view',return_value=('b'*40,'c'*64,11,before)),\
                 patch.object(cli,'intake_saved_models',side_effect=intake),\
                 patch.object(cli,'observations',return_value=[]),\
                 patch.object(cli.F,'load_captures',return_value=[]),\
                 patch.object(cli.F,'update_view',side_effect=lambda view,*_,**__:view),\
                 patch.object(cli.F,'publish_view',side_effect=publish),\
                 patch.object(maintenance,'protect_new_forecast_originals',side_effect=protect),\
                 patch.dict(os.environ,dict(RUNNER_TEMP=folder,
                     RACE_AI_ORIGINAL_VAULT_ENABLED='true' if enabled else 'false')),redirect_stdout(output):
                code=cli.main([])
            return code,events,observed,[json.loads(line) for line in output.getvalue().splitlines()],original

    def test_new_recovered_archive_is_protected_before_publication(self):
        code,events,observed,output,original=self.execute()
        self.assertEqual(code,0);self.assertEqual(events,['protect','publish'])
        self.assertEqual(observed[0][0],original)
        self.assertEqual(observed[0][1]['records'][0]['comparison_predictions'],[dict(artifact_id='102')])
        self.assertEqual(output[0]['status'],'BOAT_FORECAST_ORIGINALS_PROTECTED')

    def test_bounded_deferred_prefix_does_not_publish_a_partial_view(self):
        code,events,_,output,_=self.execute(report=dict(complete=False,status='BOAT_FORECAST_ORIGINALS_DEFERRED',remaining=1))
        self.assertEqual(code,2);self.assertEqual(events,['protect'])
        self.assertEqual(output[-1]['reason'],'FEED_NEW_FORECAST_ORIGINALS_INCOMPLETE')

    def test_denied_or_invalid_original_stops_without_publication(self):
        for reason in ('GITHUB_HTTP_403','VAULT_INDEX_AUTHENTICATION_FAILED'):
            with self.subTest(reason=reason):
                code,events,_,output,_=self.execute(failure=ValueError(reason))
                self.assertEqual(code,2);self.assertEqual(events,['protect'])
                self.assertEqual(output[-1]['reason'],reason)

    def test_an_in_place_intake_cannot_hide_the_new_archive_from_the_guard(self):
        code,events,observed,_,original=self.execute(mutate=True)
        self.assertEqual(code,0);self.assertEqual(events,['protect','publish'])
        self.assertEqual(observed[0][0],original)
        self.assertEqual(len(observed[0][1]['records'][0]['comparison_predictions']),1)

    def test_legacy_opt_out_does_not_change_the_existing_publisher(self):
        code,events,observed,_,_=self.execute(enabled=False)
        self.assertEqual(code,0);self.assertEqual(events,['publish']);self.assertEqual(observed,[])


if __name__=='__main__':unittest.main()
