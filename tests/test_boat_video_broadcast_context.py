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

    def test_fixed_leader_escape_link_accepts_each_explicit_boat(self):
        for boat in range(1,7):
            for leader in ('先頭','トップ','1番手'):
                for link in ('は逃げる','が逃げる'):
                    with self.subTest(boat=boat,leader=leader,link=link):
                        self.assertEqual(self.parse(f'{leader}{link}{boat}号艇です。')['running_order'],
                                         [{'rank':1,'boat_number':boat}])

    def test_fixed_following_rank_link_is_not_a_pursued_rank(self):
        for rank in range(2,7):
            for boat in range(1,7):
                for link in ('追走','は追走する','が追走している','で追走中の'):
                    with self.subTest(rank=rank,boat=boat,link=link):
                        self.assertEqual(self.parse(f'{rank}番手{link}{boat}号艇。')['running_order'],
                                         [{'rank':rank,'boat_number':boat}])
        for text in ('先頭追走3号艇。','トップは追走する2号艇。',
                     '2番手を追走する4号艇。','2番手の後を追走する6号艇。'):
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_fixed_inside_outside_link_keeps_boat_number_separate_from_rank(self):
        for rank in range(1,7):
            for boat in range(1,7):
                for side in ('内','外'):
                    with self.subTest(rank=rank,boat=boat,side=side):
                        self.assertEqual(self.parse(f'{rank}番手は{side}の{boat}号艇。')['running_order'],
                                         [{'rank':rank,'boat_number':boat}])

    def test_unrecognized_gap_is_not_promoted_to_a_current_rank(self):
        for text in ('先頭は不明な語句4号艇。','2番手は何か別の話3号艇。',
                     'トップスピードは6号艇。','先頭集団は2号艇。',
                     '2番手は残り1周で4号艇。','先頭は依然として3号艇。'):
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_entire_clause_with_multiple_boats_or_ranks_stays_unresolved(self):
        for text in ('先頭は2号艇と4号艇。','2番手は内の3号艇と6号艇。',
                     '2番手は4号艇が3番手です。','先頭と2番手は5号艇。',
                     '先頭2号艇2番手。','先頭は2号艇を抜いた4号艇。'):
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_complete_positive_rank_predicates_do_not_require_asr_punctuation(self):
        for boats in ((4,6,1),(2,5,3),(6,4,2)):
            for particle in ('は',''):
                text=f'先頭{particle}{boats[0]}号艇2番手{particle}{boats[1]}号艇3番手{particle}{boats[2]}号艇'
                with self.subTest(boats=boats,particle=particle):
                    self.assertEqual(self.parse(text)['running_order'],
                        [{'rank':rank,'boat_number':boat} for rank,boat in enumerate(boats,1)])

    def test_complete_fixed_link_predicates_can_follow_without_punctuation(self):
        for boats in ((4,6,1),(2,5,3),(6,4,2)):
            text=f'先頭は逃げる{boats[0]}号艇2番手追走{boats[1]}号艇3番手は内の{boats[2]}号艇'
            with self.subTest(boats=boats):
                self.assertEqual(self.parse(text)['running_order'],
                    [{'rank':rank,'boat_number':boat} for rank,boat in enumerate(boats,1)])

    def test_dangling_rank_target_does_not_create_a_predicate_boundary(self):
        for rank in range(2,6):
            text=f'{rank}番手に5番の方が{rank+1}番手ですが'
            with self.subTest(rank=rank):self.assertEqual(self.parse(text)['running_order'],[])
        self.assertEqual(self.parse('先頭は4号艇2番手ですが')['running_order'],[])
        self.assertEqual(self.parse('先頭は4号艇2番手を追う6号艇')['running_order'],
                         [{'rank':1,'boat_number':4}])

    def test_unknown_next_link_does_not_erase_the_previous_safe_claim(self):
        for leader,following in ((4,6),(2,5),(6,1)):
            text=f'先頭は{leader}号艇2番手不明語{following}号艇'
            with self.subTest(leader=leader,following=following):
                self.assertEqual(self.parse(text)['running_order'],
                                 [{'rank':1,'boat_number':leader}])

    def test_unknown_text_unit_does_not_link_or_block_other_explicit_ranks(self):
        self.assertEqual(self.parse('先頭は4号艇2番手不明語6号艇3番手は1号艇')['running_order'],
                         [{'rank':1,'boat_number':4},{'rank':3,'boat_number':1}])
        self.assertEqual(self.parse('先頭は4号艇2番手不明語6号艇と2号艇3番手は1号艇')['running_order'],
                         [{'rank':1,'boat_number':4},{'rank':3,'boat_number':1}])
        # A dangling rank cannot appropriate a later rank's boat as its own.
        self.assertEqual(self.parse('先頭は4号艇2番手不明語3番手6号艇')['running_order'],
                         [{'rank':3,'boat_number':6}])

    def test_only_complete_safe_predicates_survive_before_a_dangling_tail(self):
        self.assertEqual(self.parse('先頭は4号艇2番手は6号艇3番手ですが')['running_order'],
                         [{'rank':1,'boat_number':4}])
        self.assertEqual(self.parse('先頭は4号艇と2号艇2番手は6号艇')['running_order'],
                         [{'rank':2,'boat_number':6}])

    def test_negation_or_alternative_suffix_cannot_confirm_the_first_boat(self):
        for text in ('先頭は逃げる2号艇じゃない。','2番手追走4号艇ではありません。',
                     '3番手は内の6号艇ではない。','先頭は2号艇または4号艇。',
                     '2番手は3番か6番です。','2番手は4号艇かな。'):
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_past_or_kanji_negated_boat_is_a_correction_not_a_current_rank(self):
        for boat in range(1,7):
            for rank in ('先頭','2番手'):
                for negative in ('ではなかった','じゃなかった','でなかった',
                                 'では無かった','じゃ無かった','で無かった',
                                 'では無い','じゃ無い','で無い','では無く',
                                 'ではありませんでした','じゃありませんでした'):
                    text=f'{rank}は{boat}号艇{negative}。'
                    with self.subTest(boat=boat,rank=rank,negative=negative):
                        parsed=self.parse(text)
                        self.assertEqual(parsed['running_order'],[])
                        self.assertEqual(parsed['status'],'CORRECTION_REQUIRES_NEW_OBSERVATION')

    def test_desired_or_wished_boat_is_noncurrent_not_a_running_order(self):
        for boat in range(1,7):
            for wish in ('になってほしい','になって欲しい','であってほしい',
                         'であって欲しい','でいてほしい','でいて欲しい',
                         'になってほしかった','であって欲しかった',
                         'だといい','だと良い','ならいい','なら良い',
                         'であればいい','であれば良い','でありますように'):
                text=f'先頭は{boat}号艇{wish}。'
                with self.subTest(boat=boat,wish=wish):
                    parsed=self.parse(text)
                    self.assertEqual(parsed['running_order'],[])
                    self.assertEqual(parsed['status'],'NONCURRENT_OR_PREDICTED_COMMENTARY')

    def test_negated_or_wished_fixed_positive_links_cannot_be_promoted(self):
        self.assertEqual(self.parse('先頭は逃げる2号艇ではなかった。')['running_order'],[])
        self.assertEqual(self.parse('2番手追走4号艇じゃ無かった。')['running_order'],[])
        self.assertEqual(self.parse('3番手は内の6号艇であって欲しい。')['running_order'],[])

    def test_pursuit_comparison_history_or_prediction_is_not_current_position(self):
        for text in ('先頭を追う3号艇。','2番手を狙う4号艇。',
                     '先頭との差を詰める6号艇。','先頭から下がった5号艇。',
                     '2番手は4号艇を追走する。','2番手は3号艇に追走しています。',
                     '先頭は2号艇に迫る。','先頭は3号艇だった。',
                     '2番手は4号艇になる予定です。','先頭は6号艇になる見込みです。',
                     '先頭は逃げたい3号艇。','3番手は逃げる4号艇。',
                     '2番手は4号艇より速い。','先頭は2号艇という説明です。'):
            with self.subTest(text=text):self.assertEqual(self.parse(text)['running_order'],[])

    def test_safe_clause_does_not_assign_the_pursuing_boat_in_another_clause(self):
        self.assertEqual(self.parse('先頭は逃げる2号艇、2番手を追う4号艇。')['running_order'],
                         [{'rank':1,'boat_number':2}])

    def test_fixed_links_do_not_create_broadcast_cues_in_unknown_phase(self):
        self.assertEqual(self.parse('先頭は逃げる2号艇。',phase='UNKNOWN')['running_order'],[])

    def test_rank_only_past_guard_does_not_change_current_exhibition_arrival(self):
        result=self.parse('続いて、3号艇が展示へ向かいました。',phase='EXHIBITION_LAP')
        self.assertEqual(result['exhibition_boat_number'],3)

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
