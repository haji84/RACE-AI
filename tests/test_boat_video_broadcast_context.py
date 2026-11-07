"""Declared Japanese broadcast cues, never official results or pixel truth."""
from copy import deepcopy
from hashlib import sha256
import unittest


class BroadcastContextTests(unittest.TestCase):
    def setUp(self):
        try:
            from race_ai import boat_video_broadcast_context as module
        except ImportError:
            self.fail('Broadcast context component not implemented')
        self.module=module
        self.media='a'*64

    def segment(self,text,phase='RACE',**changes):
        row=dict(text=text,phase=phase,start_pts=1.,end_pts=2.,available_from_pts=2.,
                 valid_until_pts=4.,audio_pcm_sha256='b'*64,producer_sha256='c'*64,
                 producer_kind='SYNTHETIC_TEST',exhibition_pass_index=None)
        row.update(changes)
        return row

    def context(self,*segments,order=None):
        return dict(schema_version='RACE_AI_BOAT_BROADCAST_CONTEXT_V1',
                    media_sha256=self.media,exhibition_order=order,segments=list(segments))

    def packet(self,numbers=(1,3,2),fresh=True):
        return dict(schema_version='RACE_AI_RIDER_PART_TRACKS_V1',frame_sha256='d'*64,
            t=2.,frame_index=60,scene=0,model_eligible=False,identity_validated=False,
            tracks=[dict(track_id=f'R{i:06d}',number=n,detector_fresh=fresh,identity_source='CLOTHING_COLOR',
                number_evidence_status='CURRENT_CLOTHING_COLOR',printed_number_observed=False,
                fresh_label_observations_added=1,clothing_color={'number':n},
                pixel_support={'status':'TRACKED'}) for i,n in enumerate(numbers,1)])

    def parse(self,text,phase='RACE'):
        return self.module.parse_commentary(text,phase=phase)

    def test_explicit_rank_and_boat_are_separate(self):
        result=self.parse('先頭は１号艇、２番手は３号艇、３番手は２号艇です。')
        self.assertEqual(result['running_order'],[{'rank':1,'boat_number':1},
            {'rank':2,'boat_number':3},{'rank':3,'boat_number':2}])
        self.assertFalse(result['official_result'])

    def test_kanji_boat_and_rank_numbers_are_supported(self):
        result=self.parse('先頭は四号艇、二番手は六号艇。')
        self.assertEqual(result['running_order'],[{'rank':1,'boat_number':4},{'rank':2,'boat_number':6}])

    def test_explicit_complete_order_is_not_numeric_boat_order(self):
        result=self.parse('現在は１、３、２、４、６、５の順です。')
        self.assertEqual([r['boat_number'] for r in result['running_order']],[1,3,2,4,6,5])

    def test_numbers_without_rank_language_do_not_become_running_order(self):
        result=self.parse('1号艇と3号艇、展示タイムは6秒75です。')
        self.assertEqual(result['running_order'],[])

    def test_partial_commentary_does_not_fill_other_ranks(self):
        result=self.parse('先頭は4番、2番手は6番。')
        self.assertEqual(len(result['running_order']),2)

    def test_duplicate_boat_or_conflicting_rank_is_ambiguous(self):
        for text in ['先頭は1号艇、2番手も1号艇。','先頭は1号艇、先頭は3号艇。']:
            with self.subTest(text=text):
                result=self.parse(text)
                self.assertEqual(result['running_order'],[])
                self.assertEqual(result['status'],'AMBIGUOUS_COMMENTARY')

    def test_correction_does_not_silently_choose_last_number(self):
        result=self.parse('先頭は1号艇、失礼しました、3号艇です。')
        self.assertEqual(result['status'],'CORRECTION_REQUIRES_NEW_OBSERVATION')
        self.assertEqual(result['running_order'],[])

    def test_goal_replay_past_or_prediction_is_not_current_running_order(self):
        for text in ['ゴールは1号艇、2番手は3号艇。','リプレイです、先頭は1号艇。',
                     '前のレースは先頭が1号艇。','先頭は1号艇になるでしょう。']:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)['running_order'],[])

    def test_negated_or_alternative_boat_claim_is_not_confirmed(self):
        for text in ['先頭は1号艇ではありません。3号艇です。','先頭は1号艇か3号艇です。',
                     '先頭は1号艇ですか。']:
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_popularity_and_exhibition_order_are_not_race_running_order(self):
        for text in ['先頭は1番人気の3号艇。','人気は1、3、2の順です。',
                     'スタート展示は1、2、3、4、5、6の順です。']:
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_multidigit_boat_number_is_not_sliced_to_one_to_six(self):
        self.assertIsNone(self.parse('11号艇の周回展示です。','EXHIBITION_LAP')['exhibition_boat_number'])
        for text in ['十一号艇の周回展示です。','二十一号艇の周回展示です。']:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text,'EXHIBITION_LAP')['exhibition_boat_number'])
        for text in ['現在は11、3、2の順です。','先頭は11号艇、2番手は3号艇。','12番手は3号艇。']:
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_single_boat_lap_exhibition_announcement(self):
        result=self.parse('続いて、3号艇の周回展示です。','EXHIBITION_LAP')
        self.assertEqual(result['exhibition_boat_number'],3)
        self.assertEqual(result['running_order'],[])

    def test_lap_explanation_statistics_and_popularity_are_not_boat_identity(self):
        for text in ['全国で1番の展示タイムです。','展示タイム1位の1着率です。',
                     '1号艇の展示タイムを説明します。','人気は3番です。']:
            with self.subTest(text=text):
                self.assertIsNone(self.parse(text,'EXHIBITION_LAP')['exhibition_boat_number'])

    def test_explicit_individual_pass_can_use_short_spoken_ban(self):
        self.assertEqual(self.parse('続いて3番の周回展示です。','EXHIBITION_LAP')
                         ['exhibition_boat_number'],3)

    def test_start_exhibition_is_not_an_individual_pass(self):
        result=self.parse('1号艇、2号艇、3号艇がスタート展示です。','EXHIBITION_START')
        self.assertIsNone(result['exhibition_boat_number'])

    def test_exhibition_range_is_order_prior_not_visible_boat(self):
        result=self.parse('1号艇から6号艇の順に展示します。','EXHIBITION_LAP')
        self.assertIsNone(result['exhibition_boat_number'])

    def test_future_and_expired_commentary_cannot_annotate_current_frame(self):
        context=self.module.BroadcastIdentityContext(self.context(self.segment('先頭は1号艇。')),media_sha256=self.media)
        for stamp in (1.5,4.001):
            result=context.annotate(self.packet(),source_pts=stamp)
            self.assertEqual(result['broadcast_context']['active_cues'],[])

    def test_rank_attaches_only_to_existing_color_identity_not_x_order(self):
        context=self.module.BroadcastIdentityContext(self.context(self.segment('先頭は3号艇、2番手は1号艇。')),media_sha256=self.media)
        original=self.packet((1,None,3));before=deepcopy(original)
        out=context.annotate(original,source_pts=2.1)
        self.assertEqual([r['broadcast_identity']['announced_rank'] for r in out['tracks']],[2,None,1])
        self.assertEqual([r['number'] for r in out['tracks']],[1,None,3])
        self.assertEqual(original,before)
        self.assertTrue(all(r['fresh_label_observations_added']==1 for r in out['tracks']))
        self.assertFalse(out['broadcast_context']['prediction_eligible'])

    def test_individual_pass_order_can_offer_one_unbound_candidate(self):
        seg=self.segment('',phase='EXHIBITION_LAP',exhibition_pass_index=2)
        context=self.module.BroadcastIdentityContext(self.context(seg,order=[1,2,3,4,5,6]),media_sha256=self.media)
        out=context.annotate(self.packet((None,)),source_pts=2.1)
        evidence=out['tracks'][0]['broadcast_identity']
        self.assertEqual(evidence['exhibition_number_candidate'],2)
        self.assertEqual(evidence['status'],'UNCONFIRMED_EXHIBITION_ORDER_PRIOR')
        self.assertIsNone(out['tracks'][0]['number'])

    def test_absent_boat_order_is_explicit_not_filled(self):
        seg=self.segment('',phase='EXHIBITION_LAP',exhibition_pass_index=3)
        context=self.module.BroadcastIdentityContext(self.context(seg,order=[1,2,4,5,6]),media_sha256=self.media)
        out=context.annotate(self.packet((4,)),source_pts=2.1)
        self.assertEqual(out['tracks'][0]['broadcast_identity']['exhibition_number_candidate'],4)

    def test_ambiguous_multiple_visible_riders_do_not_bind_pass_order(self):
        seg=self.segment('3号艇の周回展示です。',phase='EXHIBITION_LAP')
        context=self.module.BroadcastIdentityContext(self.context(seg),media_sha256=self.media)
        out=context.annotate(self.packet((None,None)),source_pts=2.1)
        self.assertTrue(all(r['broadcast_identity']['exhibition_number_candidate'] is None for r in out['tracks']))

    def test_exhibition_color_conflict_is_recorded_without_relabeling(self):
        seg=self.segment('3号艇の周回展示です。',phase='EXHIBITION_LAP')
        context=self.module.BroadcastIdentityContext(self.context(seg),media_sha256=self.media)
        out=context.annotate(self.packet((4,)),source_pts=2.1)
        self.assertEqual(out['tracks'][0]['broadcast_identity']['status'],'CLOTHING_BROADCAST_CONFLICT')
        self.assertEqual(out['tracks'][0]['number'],4)

    def test_overlapping_conflicting_announcements_abstain(self):
        context=self.module.BroadcastIdentityContext(self.context(
            self.segment('先頭は1号艇。'),self.segment('先頭は3号艇。')),media_sha256=self.media)
        out=context.annotate(self.packet(),source_pts=2.1)
        self.assertTrue(all(r['broadcast_identity']['announced_rank'] is None for r in out['tracks']))
        self.assertIn('CONFLICTING_ACTIVE_BROADCAST_CUES',out['broadcast_context']['quality_flags'])

    def test_overlapping_correction_invalidates_the_older_rank_claim(self):
        context=self.module.BroadcastIdentityContext(self.context(
            self.segment('先頭は1号艇。'),self.segment('失礼しました、3号艇です。')),
            media_sha256=self.media)
        out=context.annotate(self.packet(),source_pts=2.1)
        self.assertTrue(all(r['broadcast_identity']['announced_rank'] is None for r in out['tracks']))

    def test_expired_correction_cannot_resurrect_older_claim(self):
        context=self.module.BroadcastIdentityContext(self.context(
            self.segment('先頭は1号艇。',valid_until_pts=10.),
            self.segment('失礼しました。',start_pts=3.,end_pts=4.,available_from_pts=4.,valid_until_pts=5.),
            self.segment('先頭は3号艇。',start_pts=5.,end_pts=6.,available_from_pts=6.,valid_until_pts=8.)),
            media_sha256=self.media)
        self.assertEqual(context.annotate(self.packet(),source_pts=3.)['tracks'][0]['broadcast_identity']['announced_rank'],1)
        for stamp in [4.5,5.5,8.5]:
            with self.subTest(stamp=stamp):
                out=context.annotate(self.packet(),source_pts=stamp)
                self.assertTrue(all(r['broadcast_identity']['announced_rank'] is None for r in out['tracks']))
        self.assertEqual(context.annotate(self.packet(),source_pts=6.5)['tracks'][1]['broadcast_identity']['announced_rank'],1)

    def test_newer_rank_replaces_old_rank_without_resurrection_after_expiry(self):
        context=self.module.BroadcastIdentityContext(self.context(
            self.segment('先頭は1号艇。',valid_until_pts=10.),
            self.segment('先頭は3号艇。',start_pts=3.,end_pts=4.,available_from_pts=4.,valid_until_pts=5.)),
            media_sha256=self.media)
        self.assertEqual(context.annotate(self.packet(),source_pts=4.5)['tracks'][1]['broadcast_identity']['announced_rank'],1)
        self.assertTrue(all(r['broadcast_identity']['announced_rank'] is None
                            for r in context.annotate(self.packet(),source_pts=6.)['tracks']))

    def test_newer_exhibition_pass_does_not_restore_previous_after_expiry(self):
        context=self.module.BroadcastIdentityContext(self.context(
            self.segment('1号艇の周回展示です。',phase='EXHIBITION_LAP',valid_until_pts=10.),
            self.segment('2号艇の周回展示です。',phase='EXHIBITION_LAP',start_pts=3.,end_pts=4.,
                         available_from_pts=4.,valid_until_pts=5.)),media_sha256=self.media)
        self.assertEqual(context.annotate(self.packet((None,)),source_pts=4.5)['tracks'][0]
                         ['broadcast_identity']['exhibition_number_candidate'],2)
        self.assertIsNone(context.annotate(self.packet((None,)),source_pts=6.)['tracks'][0]
                          ['broadcast_identity']['exhibition_number_candidate'])

    def test_number_from_unrelated_provider_does_not_become_clothing_confirmation(self):
        context=self.module.BroadcastIdentityContext(self.context(self.segment('先頭は1号艇。')),media_sha256=self.media)
        packet=self.packet((1,));packet['tracks'][0]['identity_source']='UNVERIFIED_OTHER_PROVIDER'
        out=context.annotate(packet,source_pts=2.1)
        self.assertIsNone(out['tracks'][0]['broadcast_identity']['announced_rank'])

    def test_duplicate_visible_identity_is_not_bound_to_one_announced_rank(self):
        context=self.module.BroadcastIdentityContext(self.context(self.segment('先頭は1号艇。')),media_sha256=self.media)
        out=context.annotate(self.packet((1,1)),source_pts=2.1)
        self.assertTrue(all(r['broadcast_identity']['announced_rank'] is None for r in out['tracks']))

    def test_invalid_phase_types_and_nonfinite_clock_are_rejected(self):
        for phase in [[],{},None,True]:
            with self.subTest(phase=phase),self.assertRaises(ValueError):
                self.parse('先頭は1号艇。',phase=phase)
        context=self.module.BroadcastIdentityContext(self.context(),media_sha256=self.media)
        with self.assertRaises(ValueError):context.annotate(self.packet(),source_pts=float('nan'))

    def test_media_binding_and_impossible_time_ranges_are_rejected(self):
        for context in [self.context(self.segment('先頭は1号艇。',available_from_pts=1.5)),
                        self.context(self.segment('先頭は1号艇。',valid_until_pts=1.9)),
                        dict(self.context(),media_sha256='e'*64)]:
            with self.subTest(context=context):
                with self.assertRaises(ValueError):
                    self.module.BroadcastIdentityContext(context,media_sha256=self.media)

    def test_missing_or_duplicate_pass_indices_do_not_generate_a_counter(self):
        seg=self.segment('',phase='EXHIBITION_LAP')
        context=self.module.BroadcastIdentityContext(self.context(seg,order=[1,2,3,4,5,6]),media_sha256=self.media)
        for stamp in (2.1,2.2,2.3):
            out=context.annotate(self.packet((None,)),source_pts=stamp)
            self.assertIsNone(out['tracks'][0]['broadcast_identity']['exhibition_number_candidate'])


if __name__=='__main__':unittest.main()
