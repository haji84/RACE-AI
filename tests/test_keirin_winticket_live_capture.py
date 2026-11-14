"""Synthetic timing/continuity tests for the one-race WINTICKET recorder."""
from datetime import datetime, timedelta, timezone
import unittest
from scripts.keirin_winticket_9r_live_capture import (
    START,RACE_START,END,feasible,coverage_ok
)

class CaptureGateTest(unittest.TestCase):
    def test_race_window_pre_start(self):
        self.assertTrue(feasible(START))
        self.assertTrue(feasible(START-timedelta(minutes=1)))
        self.assertFalse(feasible(RACE_START+timedelta(seconds=1)))
        self.assertLess(START,RACE_START)
        self.assertLess(RACE_START,END)

    def test_continuity_pass_and_missed_middle(self):
        samples=[]
        clock=START
        while clock<=END:
            samples.append({
                "utc":clock.astimezone(timezone.utc).isoformat(),
                "ready":4, "width":640, "height":360, "paused":False,
                "error":None,
                "position":20+int((clock-START).total_seconds())
            })
            clock+=timedelta(seconds=2)
        self.assertTrue(coverage_ok(samples,START,END))
        self.assertFalse(coverage_ok(samples,START,START+timedelta(minutes=3)))
        self.assertFalse(coverage_ok(samples[0:30]+samples[60:],START,END))
        short=[dict(x) for x in samples]
        for item in short[0:90]:
            item["paused"]=True
        self.assertFalse(coverage_ok(short,START,END))
        backward=[dict(x) for x in samples]
        backward[140]["position"]=-100
        self.assertFalse(coverage_ok(backward,START,END))
        # A timing pass is NOT a verdict on the content of four racing laps.

if __name__=="__main__":
    unittest.main()
