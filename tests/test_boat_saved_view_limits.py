"""Bound a large fictional multi-race forecast union without a per-feed4096 cap."""
from copy import deepcopy
import unittest
from race_ai.boat_saved_model_view import merge_saved_views
from tests.test_boat_saved_model_view import view


def many_forecasts(count, per_race=128):
    out=view();template=out['records'][0];out['records']=[]
    for index,start in enumerate(range(0,count,per_race)):
        row=deepcopy(template);row.update(race_id=f'20300401-{1+index//12:02d}-{1+index%12:02d}',race_no=1+index%12)
        predictions=[dict(stage='P0',model_id=f'synthetic-count-{n}',model_version='v1',prediction_sha256='a'*64,
            cutoff_at=row['cutoff_at'],ordered_top8=[[1,2,3]]) for n in range(start,min(count,start+per_race))]
        row.update(prediction=predictions[0],comparison_predictions=predictions[1:]);out['records'].append(row)
    return out


class SavedViewLimitTests(unittest.TestCase):
    def test_more_than4300_saved_forecasts_across_races_are_preserved(self):
        source=many_forecasts(4301);out=merge_saved_views(source)
        self.assertEqual(sum(1+len(r['comparison_predictions']) for r in out['records']),4301)
        self.assertEqual(out['records'][0]['prediction'],source['records'][0]['prediction'])

    def test_per_race128_bound_is_distinct_from_total_forecast_budget(self):
        with self.assertRaises(ValueError):merge_saved_views(many_forecasts(129,per_race=129))

    def test_total_originals_beyond32768_are_rejected(self):
        with self.assertRaises(ValueError):merge_saved_views(many_forecasts(32769))


if __name__=='__main__':unittest.main()
