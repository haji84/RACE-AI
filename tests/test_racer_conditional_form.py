import unittest
from race_ai.core import SourceError
from race_ai.racer_conditional_form import summarize_racer

ASOF="2026-10-14T09:00:00+09:00"


def record(race, lane, course, finish, observed="2026-10-13T17:00:00+09:00"):
    return {"race_id":race,"racer_id":"4001","lane":lane,
            "actual_course":course,"finish":finish,
            "published_at":observed,"observed_at":observed}


class RacerConditionalFormTests(unittest.TestCase):
    def test_actual_course_and_lane_not_conflated(self):
        data=[record("20261013-18-01",1,2,1),record("20261013-18-02",2,2,3)]
        result=summarize_racer(data,racer_id="4001",asof=ASOF)
        course=next(x for x in result["groups"] if x["dimension"]=="actual_course" and x["number"]==2)
        lane=next(x for x in result["groups"] if x["dimension"]=="lane" and x["number"]==1)
        self.assertEqual(course["valid_finishes"],2)
        self.assertEqual(course["win_rate"],0.5)
        self.assertEqual(lane["win_rate"],1.0)
        self.assertTrue(course["insufficient_sample"])

    def test_future_information_excluded(self):
        data=[record("20261015-18-01",1,1,1,"2026-10-15T17:00:00+09:00")]
        result=summarize_racer(data,racer_id="4001",asof=ASOF)
        self.assertEqual(result["status"],"NO_VERIFIED_HISTORY")

    def test_duplicate_race_rejected(self):
        row=record("20261013-18-01",1,1,1)
        with self.assertRaises(SourceError):
            summarize_racer([row,row],racer_id="4001",asof=ASOF)
