"""Authenticated original intake; no official source calls or original edits."""
from copy import deepcopy
import json
import unittest
from race_ai import boat_saved_view_intake as intake
from race_ai.saved_view_feed import forecast_inventory
from tests.test_boat_saved_prediction_evidence import original_view


class EvidenceIntakeTests(unittest.TestCase):
    def test_missing_projection_fields_are_hydrated_once_from_actual_archive(self):
        self.assertTrue(callable(getattr(intake,'hydrate_saved_originals',None)), 'original evidence intake required')
        view,_,raw,meta=original_view();before=deepcopy(view);calls=[]
        def get(path):
            calls.append(path)
            return raw if path.endswith('/zip') else json.dumps(meta).encode()
        output,counts=intake.hydrate_saved_originals(view,get)
        self.assertEqual(view,before);self.assertEqual(forecast_inventory(output),forecast_inventory(view))
        self.assertEqual(counts['evidenced_predictions'],2);self.assertEqual(len(calls),2)
        _,again=intake.hydrate_saved_originals(output,lambda _:self.fail('already hydrated original fetched again'))
        self.assertEqual(again['evidenced_predictions'],2)

    def test_denial_or_conflicting_archive_holds_without_replacing_originals(self):
        self.assertTrue(callable(getattr(intake,'hydrate_saved_originals',None)), 'original evidence intake required')
        view,_,raw,meta=original_view();before=deepcopy(view)
        with self.assertRaisesRegex(RuntimeError,'HTTP_403'):
            intake.hydrate_saved_originals(view,lambda _:(_ for _ in ()).throw(RuntimeError('HTTP_403')))
        self.assertEqual(view,before)
        bad=deepcopy(meta);bad['digest']='sha256:'+'0'*64
        with self.assertRaises(ValueError):
            intake.hydrate_saved_originals(view,lambda p:raw if p.endswith('/zip') else json.dumps(bad).encode())
        self.assertEqual(view,before)


if __name__=='__main__':unittest.main()
