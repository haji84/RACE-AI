import unittest
from race_ai.core import SourceError
from race_ai.official_b_motors import parse_b_motors

def b_sample(motor_nums=(11,12,13,14,15,16),rate="28.50"):
    lines=["STARTB","19BBGN","2026/10/13",
           "1R 予選 H1800m"]
    for i in range(1,7):
        s=[' ']*80
        s[0]=str(i)
        s[2:6]=list(str(4000+i))
        s[6:10]=list("選手名例")
        s[41:43]=list(f"{motor_nums[i-1]:02d}")
        s[44:49]=list(f"{rate:>5}")
        s[50:52]=list(f"{i+20:02d}")
        s[53:58]=list(f"{33.33:>5.2f}")
        lines.append(''.join(s))
    lines+=["19BEND"]
    return ("\n".join(lines)+"\n").encode("cp932")

class MotorColumnsTests(unittest.TestCase):
    def test_fixed_width_motor_not_boat_and_register_join(self):
        x=parse_b_motors(b_sample(),"2026-10-13")
        self.assertEqual(len(x),6)
        self.assertEqual([r['motor_no'] for r in x],[11,12,13,14,15,16])
        self.assertEqual(x[0]['motor_top2_rate'],28.50)
        self.assertEqual(x[0]['boat_no'],21)

    def test_reject_duplicate_motor_same_race(self):
        with self.assertRaises(SourceError):
            parse_b_motors(b_sample((11,11,13,14,15,16)),"2026-10-13")

    def test_reject_shifted_motor_columns(self):
        with self.assertRaises(SourceError):
            parse_b_motors(b_sample(rate="AB.CD"),"2026-10-13")

    def test_reject_wrong_day(self):
        with self.assertRaises(SourceError):
            parse_b_motors(b_sample(),"2026-10-14")

if __name__=="__main__":unittest.main()
