import unittest
from race_ai.official_daily_reconcile import reconcile_rows
from race_ai.core import SourceError


def item(race,lane,racer):
    return dict(race_id=race,lane=lane,racer_id=racer)


class OfficialReconcileTests(unittest.TestCase):
    def test_matching_all_racer_ids_across_b_and_k(self):
        b=[item('20261013-14-08',i,str(5000+i)) for i in range(1,7)]
        k=[dict(x,st_status='ABSENT',course=None) if x['lane']==3 else x for x in b]
        r=reconcile_rows(b,k)
        self.assertEqual(r['status'],'OFFICIAL_B_K_IDENTIFIERS_RECONCILED')
        self.assertEqual(r['races'],1)
        self.assertEqual(r['result_boats'],6)

    def test_mismatched_id_rejected_even_if_counts_match(self):
        b=[item('20261013-14-08',1,'5001')]
        k=[item('20261013-14-08',1,'5002')]
        with self.assertRaises(SourceError):
            reconcile_rows(b,k)

    def test_duplicate_lane_rejected(self):
        a=[item('20261013-14-08',1,'5001')]
        with self.assertRaises(SourceError):
            reconcile_rows(a+a,a)

    def test_missing_scratched_racer_rejected(self):
        b=[item('20261013-14-08',i,str(5000+i)) for i in range(1,7)]
        with self.assertRaises(SourceError):
            reconcile_rows(b,b[:-1])


if __name__=='__main__':
    unittest.main()
