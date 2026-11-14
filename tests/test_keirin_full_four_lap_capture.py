"""Safety and bounded-window tests; not a real four-lap video claim."""
import unittest
from datetime import datetime
from scripts.keirin_full_four_lap_capture import (
    WINDOW_BEGIN, WINDOW_END, offset_for, seek_available, CHANNEL_ID, VIDEO_ID
)

class FourLapWindowTests(unittest.TestCase):
    def test_target_offsets_from_broadcast_start(self):
        start="2026-11-08T20:00:00+09:00"
        self.assertEqual(offset_for(start,WINDOW_BEGIN),37*60+30)
        self.assertEqual(offset_for(start,WINDOW_END),44*60+30)
    def test_fail_older_or_wrong_dvr_window(self):
        self.assertTrue(seek_available(60,480,[[0,500]]))
        self.assertFalse(seek_available(60,480,[[200,600]]))
        self.assertFalse(seek_available(60,480,[[0,400]]))
        self.assertFalse(seek_available(60,480,[]))
        self.assertFalse(seek_available(480,60,[[0,500]]))
    def test_no_undefined_timestamps(self):
        with self.assertRaises(ValueError):
            offset_for("2026-11-08T22:00:00+09:00",WINDOW_BEGIN)
        with self.assertRaises(ValueError):
            offset_for("2026-11-08T20:00:00",WINDOW_BEGIN)
    def test_pinned_official_channel_and_video(self):
        self.assertEqual(CHANNEL_ID,"UCX3xb9FwC7jL_ZnVmoyzgDg")
        self.assertEqual(VIDEO_ID,"BhwmwNby6Ow")

if __name__=="__main__":unittest.main()
