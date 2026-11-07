"""Controlled screen-text evidence, never human phase ground truth."""
from copy import deepcopy
from hashlib import sha256
import importlib.util
from pathlib import Path
import math
import sys
import tempfile
import unittest
from unittest.mock import patch

try:
    import cv2
    import numpy as np
except ImportError:
    cv2=np=None


@unittest.skipIf(np is None,'optional NumPy/OpenCV needed')
class PhaseTests(unittest.TestCase):
    def setUp(self):
        try:
            from race_ai import boat_video_phase as module
        except ImportError:self.fail('Local Japanese screen phase component missing')
        self.module=module;self.text='スタート展示';self.confidence=95.;self.fail_reader=False
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def frame(self,index):
        frame=np.zeros((64,96,3),np.uint8);frame[0,0]=index
        return frame

    def words(self,text=None,confidence=None):
        return [dict(text=c,confidence=self.confidence if confidence is None else confidence,
            box=[5+i*6,10,5,15],line_key=[1,1,1,1]) for i,c in enumerate(self.text if text is None else text)]

    def reader(self,frame):
        if self.fail_reader:raise RuntimeError('CONTROLLED_READER_FAILURE')
        return self.module._make_packet(frame,self.words(),status='OCR_OBSERVATION',raw_tsv='CONTROLLED')

    def tracker(self):return self.module.ExhibitionPhaseTracker(self.reader)

    def update(self,tracker,index,**kw):
        return tracker.update(kw.pop('frame',self.frame(index)),t=kw.pop('t',float(index)),
            frame_index=index,scene=kw.pop('scene',0),**kw)

    def test_exact_start_label_requires_two_distinct_current_frames(self):
        tracker=self.tracker();first=self.update(tracker,0);second=self.update(tracker,1)
        self.assertEqual(first['phase'],'UNKNOWN')
        self.assertEqual(second['phase'],'EXHIBITION_START')
        self.assertEqual(second['observed_interval']['first_observed_t'],0.)
        self.assertEqual(second['observed_interval']['confirmed_from_t'],1.)
        self.assertFalse(second['verified_current_activity'])
        self.assertFalse(second['usable_for_identity'])

    def test_exact_lap_label_is_distinct_from_start(self):
        self.text='周回展示';tracker=self.tracker();self.update(tracker,0)
        self.assertEqual(self.update(tracker,1)['phase'],'EXHIBITION_LAP')

    def test_both_labels_abstain_instead_of_selecting_first(self):
        self.text='スタート展示 周回展示';tracker=self.tracker();self.update(tracker,0)
        out=self.update(tracker,1)
        self.assertEqual(out['phase'],'UNKNOWN')
        self.assertEqual(out['ocr']['mention_kind'],'AMBIGUOUS_PHASE_LABELS')

    def test_low_confidence_label_is_not_confirmed(self):
        self.confidence=49.;tracker=self.tracker();self.update(tracker,0)
        self.assertEqual(self.update(tracker,1)['phase'],'UNKNOWN')

    def test_one_low_support_character_invalidates_label_support(self):
        words=self.words();words[-1]['confidence']=12.
        packet=self.module._make_packet(self.frame(0),words,status='OCR_OBSERVATION',raw_tsv='')
        self.assertEqual(packet['phase_candidate'],'UNKNOWN')

    def test_explanation_is_reported_without_claiming_current_exhibition(self):
        self.text='周回展示とは';tracker=self.tracker();self.update(tracker,0)
        out=self.update(tracker,1)
        self.assertEqual(out['ocr']['phase_candidate'],'EXHIBITION_LAP')
        self.assertEqual(out['ocr']['mention_kind'],'EXPLANATORY_MENTION')
        self.assertEqual(out['phase'],'UNKNOWN')

    def test_homophones_are_not_repaired_into_phase_labels(self):
        for text in ['スタートテンジ','集会展示','周回天示']:
            with self.subTest(text=text):
                packet=self.module._make_packet(self.frame(0),self.words(text),status='OCR_OBSERVATION',raw_tsv='')
                self.assertEqual(packet['phase_candidate'],'UNKNOWN')

    def test_label_is_not_joined_across_unrelated_lines(self):
        words=self.words();words[-1]['line_key']=[1,1,1,2]
        packet=self.module._make_packet(self.frame(0),words,status='OCR_OBSERVATION',raw_tsv='')
        self.assertEqual(packet['phase_candidate'],'UNKNOWN')

    def test_replayed_pixels_cannot_confirm_a_phase(self):
        tracker=self.tracker();frame=self.frame(0)
        for i in range(3):out=self.update(tracker,i,frame=frame)
        self.assertEqual(out['phase'],'UNKNOWN')
        self.assertEqual(out['distinct_observations'],1)

    def test_unread_current_frame_closes_interval_and_restarts(self):
        tracker=self.tracker();self.update(tracker,0);self.update(tracker,1)
        self.text='';out=self.update(tracker,2)
        self.assertEqual(out['phase'],'UNKNOWN')
        self.assertEqual(len(out['closed_intervals']),1)
        self.assertEqual(out['closed_intervals'][0]['last_observed_t'],1.)
        self.text='スタート展示'
        self.assertEqual(self.update(tracker,3)['phase'],'UNKNOWN')

    def test_new_phase_cut_or_exact_gap_restarts_confirmation(self):
        for changed in ('label','scene','gap'):
            with self.subTest(changed=changed):
                self.text='スタート展示';tracker=self.tracker();self.update(tracker,0);self.update(tracker,1)
                if changed=='label':self.text='周回展示'
                out=self.update(tracker,2,scene=1 if changed=='scene' else 0,t=2.5 if changed=='gap' else 2.)
                self.assertEqual(out['phase'],'UNKNOWN')
                self.assertEqual(out['distinct_observations'],1)

    def test_reader_failure_is_unknown_and_does_not_reuse_previous_label(self):
        tracker=self.tracker();self.update(tracker,0);self.update(tracker,1);self.fail_reader=True
        out=self.update(tracker,2)
        self.assertEqual(out['phase'],'UNKNOWN')
        self.assertEqual(out['ocr']['status'],'OCR_FAILED')

    def test_wrong_source_hash_is_a_safe_unknown(self):
        def reader(frame):
            packet=self.reader(frame);packet['frame_sha256']='0'*64;return packet
        out=self.update(self.module.ExhibitionPhaseTracker(reader),0)
        self.assertEqual(out['phase'],'UNKNOWN')
        self.assertIn('INVALID_READER_PACKET',out['quality_flags'])

    def test_original_and_returned_evidence_cannot_mutate_tracker_state(self):
        tracker=self.tracker();frame=self.frame(0);before=frame.copy();out=self.update(tracker,0,frame=frame)
        out['ocr']['words'][0]['text']='CHANGED'
        self.assertTrue(np.array_equal(frame,before))
        self.assertEqual(self.update(tracker,1)['phase'],'EXHIBITION_START')

    def test_invalid_clock_cannot_advance_state(self):
        tracker=self.tracker();self.update(tracker,0)
        with self.assertRaises(ValueError):self.update(tracker,0)
        self.assertEqual(self.update(tracker,1)['phase'],'EXHIBITION_START')

    def test_long_interval_keeps_first_observation_and_processes_every_frame(self):
        tracker=self.tracker()
        for i in range(25):out=self.update(tracker,i)
        self.assertEqual(out['distinct_observations'],25)
        self.assertEqual(out['observed_interval']['first_observed_t'],0.)
        self.assertEqual(out['observed_interval']['confirmed_from_t'],1.)
        self.assertEqual(out['observed_interval']['last_observed_t'],24.)

    def test_pixels_seen_while_unread_cannot_later_add_a_fresh_vote(self):
        tracker=self.tracker();self.text='';self.update(tracker,0)
        self.text='スタート展示';self.update(tracker,1,frame=self.frame(0))
        out=self.update(tracker,2)
        self.assertEqual(out['phase'],'UNKNOWN')
        self.assertEqual(out['distinct_observations'],1)

    def test_final_clock_allocation_failure_does_not_publish_partial_state(self):
        tracker=self.tracker();self.update(tracker,0);self.update(tracker,1)
        before=deepcopy((tracker._state,tracker._seen,tracker._time));calls=[]
        native_float=float
        def allocate(value):
            if type(value) is int and value==2:
                calls.append(value)
                if len(calls)==4:raise MemoryError('CONTROLLED_FINAL_CLOCK_ALLOCATION')
            return native_float(value)
        exact_finite=lambda value:type(value) in (int,native_float) and math.isfinite(value)
        with patch.object(self.module,'float',side_effect=allocate,create=True), \
             patch.object(self.module,'_finite',side_effect=exact_finite):
            with self.assertRaises(MemoryError):self.update(tracker,2,t=2)
        self.assertEqual((tracker._state,tracker._seen,tracker._time),before)
        self.assertEqual(self.update(tracker,2)['phase'],'EXHIBITION_START')

    def make_local_reader(self,tsv,require_direct=False):
        data=self.root/'tessdata';data.mkdir();asset=data/'jpn.traineddata';asset.write_bytes(b'CONTROLLED_JPN_FIXTURE')
        binary=self.root/'tesseract'
        script='#!'+sys.executable+'\nimport sys\n'
        script+="if '--version' in sys.argv: print('tesseract CONTROLLED_TEST')\n"
        script+='else:\n'
        if require_direct:script+=" if '-c' not in sys.argv or 'tessedit_create_tsv=1' not in sys.argv: sys.exit(9)\n"
        script+=' sys.stdin.buffer.read()\n sys.stdout.write('+repr(tsv)+')\n'
        binary.write_text(script);binary.chmod(0o700)
        with patch.object(self.module,'JPN_SHA256',sha256(asset.read_bytes()).hexdigest()):
            reader=self.module.LocalJapanesePhaseReader(tesseract_path=binary,tessdata_path=data)
        return reader,asset

    def test_local_reader_returns_original_bound_words_and_fixed_preprocessing(self):
        header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        tsv=header+'5\t1\t1\t1\t1\t1\t10\t20\t140\t30\t95\tスタート展示\n'
        reader,asset=self.make_local_reader(tsv)
        frame=self.frame(0);out=reader(frame)
        self.assertEqual(out['frame_sha256'],sha256(frame.tobytes()).hexdigest())
        self.assertEqual(out['phase_candidate'],'EXHIBITION_START')
        self.assertEqual(out['words'][0]['box'],[5.,10.,70.,15.])
        self.assertEqual(out['preprocessing']['scale'],2.)
        self.assertEqual(out['raw_tsv'],tsv)
        self.assertFalse(out['scores_are_calibrated_probabilities'])

    def test_changed_local_asset_fails_safe_without_old_phase(self):
        reader,asset=self.make_local_reader('');asset.write_bytes(b'CHANGED')
        out=reader(self.frame(0))
        self.assertEqual(out['phase_candidate'],'UNKNOWN')
        self.assertEqual(out['status'],'OCR_FAILED')

    def test_tsv_output_is_enabled_directly_without_an_unpinned_config_file(self):
        header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        reader,asset=self.make_local_reader(header,require_direct=True)
        self.assertEqual(reader(self.frame(0))['status'],'OCR_OBSERVATION')

    def test_fractional_native_word_boxes_survive_two_times_preprocessing(self):
        header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        reader,asset=self.make_local_reader(header+'5\t1\t1\t1\t1\t1\t10\t20\t1\t30\t95\t。\n')
        out=reader(self.frame(0))
        self.assertEqual(out['status'],'OCR_OBSERVATION')
        self.assertEqual(out['words'][0]['box'],[5.,10.,.5,15.])

    def test_rounded_preprocessing_dimensions_use_actual_axis_scales(self):
        header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        reader,asset=self.make_local_reader(header+'5\t1\t1\t1\t1\t1\t1900\t1282\t20\t1\t95\t。\n')
        out=reader(np.zeros((1002,1500,3),np.uint8))
        self.assertEqual(out['status'],'OCR_OBSERVATION')
        self.assertAlmostEqual(out['preprocessing']['scale_y'],1283/1002)
        self.assertAlmostEqual(sum(out['words'][0]['box'][1::2]),1002.)

    def test_remote_reader_path_is_rejected_without_network(self):
        with self.assertRaises(ValueError):
            self.module.LocalJapanesePhaseReader(tesseract_path='https://invalid.example/ocr',tessdata_path=self.root)


if __name__=='__main__':unittest.main()
