"""Two authored fresh cards, real fixture codec/baseline, no source/key lookup."""
from copy import deepcopy
import io,json,unittest,zipfile
from hashlib import sha256
from datetime import timedelta
from unittest.mock import patch
from tests import test_jra_future_source_capture as fixtures
from tests.test_manual_official_capture import Response
from tests.test_all_existing_model_future_source_capture import archive_directory
from tests.test_all_existing_model_source_packet_freeze import KEY
from race_ai.boat_all_model_store import open_forecasts,seal_forecasts

CARD=fixtures.CARD
NOW=fixtures.NOW
cards=fixtures.cards


class ExplicitTargetTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.JraFutureIntegrationTests('runTest');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.target=CARD.replace('1120301109/','1220301109/');self.assertNotEqual(CARD,self.target)
        early=f.bodies[CARD].decode('cp932')
        f.bodies={CARD:(early.replace('</body>',f'<a href="{self.target}">創作12Rの公開リンク</a></body>')).encode('cp932'),
            self.target:early.replace('11レース','12レース').replace('15時20分','16時00分').encode('cp932'),
            cards.RULE_URL:f.bodies[cards.RULE_URL]}
        f.input.update(discovery_url=CARD,card_url=self.target,race_id=f.input['race_id'].rsplit(':',1)[0]+':12',
            cutoff_at='2030-11-09T15:59:00+09:00')
        f.input['terms_manifest']['terms'][0]['source_urls']=[CARD,self.target,cards.RULE_URL]
    def get(self,request,timeout):
        f=self.fixture;url=request.full_url;f.requested.append(url);f.advance(.1)
        return Response(f.bodies[url],url=url,headers={'Content-Type':'text/html; charset='+('shift_jis' if 'accessD' in url else 'UTF-8')})
    def test_manifest_target12_wins_over_earlier_discovery11_and_preserves_dual_source_readback(self):
        f=self.fixture;output=f.root/'target12'
        with f.patches():
            result=f.wrapper.generate(f.input,output,f.env,marker_transport=f.transport,
                opener=self.get,sleeper=f.advance,monotonic=lambda:f.clock.timestamp())
        self.assertTrue(result['ready'],result)
        self.assertEqual(f.requested,[CARD,self.target,cards.RULE_URL])
        records=f.wrapper.freeze.local_records(output/'native')
        self.assertEqual([r['race_id'] for r in records],[f.input['race_id']])
        journal=f.wrapper.common._open((output/'source/collection.enc').read_bytes(),f.env,KEY)
        self.assertEqual(set(journal['capture_cache']['captures']),{CARD,self.target,cards.RULE_URL})
        for ident,folder,name in ((800,output/'native',result['artifact_name']),(801,output/'source',result['source_artifact_name'])):
            if folder.name=='native':
                stream=io.BytesIO()
                with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(folder.rglob('*')):
                        if path.is_file():archive.writestr(path.relative_to(folder).as_posix(),path.read_bytes())
                raw=stream.getvalue()
            else:raw=archive_directory(folder)
            actual=dict(id=ident,name=name,expired=False,size_in_bytes=len(raw),digest='sha256:'+sha256(raw).hexdigest(),
                created_at=(f.clock+timedelta(seconds=1)).isoformat(),expires_at=(NOW+timedelta(days=1)).isoformat(),
                workflow_run=dict(id=42,head_sha='a'*40,repository_id=1416489937,head_repository_id=1416489937))
            f.mapping[ident]=(raw,actual)
        f.advance(5)
        with f.patches():checked=f.wrapper.readback(800,801,output,f.env,f.input,marker_transport=f.transport)
        self.assertTrue(checked['independent_pre_cutoff_receipt_verified']);self.assertEqual(len(f.requested),3)
        fm=journal['freeze_manifest'];source={p.name:p.read_bytes() for p in (output/'source').iterdir()}
        with f.patches():stage=f.wrapper._staging(source,fm,f.root/'target-staging')
        for index,change in enumerate(('missing_race','wrong_cutoff','wrong_card')):
            target={k:f.input[k] for k in ('race_id','cutoff_at','card_url')}
            if change=='missing_race':target['race_id']=target['race_id'].rsplit(':',1)[0]+':10'
            elif change=='wrong_cutoff':target['cutoff_at']='2030-11-09T16:00:00+09:00'
            else:target['card_url']=CARD
            with self.subTest(change=change),f.patches():
                held=f.wrapper.freeze.generate(700,f.root/('missing-'+str(index)),f.env,fm,source_root=stage,target_case=target)
                self.assertFalse(held['ready'])
        # Re-seal only authored non-target metadata with a wrong source hash.
        # Its raw card stays retained; target selection may never skip this join.
        document=open_forecasts(source['metadata.enc'],key=KEY)
        document['metadata_by_url'][CARD]['source_sha256']='f'*64
        altered=seal_forecasts(document,run_id='42',round_no=f.wrapper.freeze.ROUND,key=KEY)
        changed=deepcopy(fm);checksum=sha256(altered).hexdigest()
        changed.update(source_metadata_sha256=checksum,source_metadata_path='audit/state/manual-official-source-metadata-'+checksum+'.enc')
        source['metadata.enc']=altered
        with f.patches():bad_stage=f.wrapper._staging(source,changed,f.root/'bad-metadata-staging')
        with f.patches(),self.assertRaisesRegex(ValueError,'ORIGINAL_METADATA_BINDING'):
            f.wrapper.freeze.generate(700,f.root/'bad-nontarget',f.env,changed,source_root=bad_stage,
                target_case={k:f.input[k] for k in ('race_id','cutoff_at','card_url')})
        self.assertEqual(len(f.requested),3)
    def test_wrong_native_target_or_missing_target_card_is_hold(self):
        f=self.fixture
        # Fresh current source target URL advertises12; an authored11 body is a
        # source identity mismatch, never permission to choose discovery11.
        f.bodies[self.target]=f.bodies[CARD]
        with f.patches():result=f.wrapper.generate(f.input,f.root/'wrong-body',f.env,marker_transport=f.transport,
            opener=self.get,sleeper=f.advance,monotonic=lambda:f.clock.timestamp())
        self.assertFalse(result['ready']);self.assertEqual(result.get('captured_native_input_count',0),0)


if __name__=='__main__':unittest.main()
