"""Synthetic source-history selection; never a forecast or licence claim."""
from copy import deepcopy
import unittest
from scripts.keirin_prior_real_input_probe import select_references
from tests.test_keirin_winticket_prior_events import (
    page_data, PriorEventContractTests, PAST,
)


class PriorReferenceSelectionTests(unittest.TestCase):
    refs=PriorEventContractTests.refs

    def test_source_category_filters_without_imputing_absent_category(self):
        doc=page_data()
        refs=self.refs()
        for record in doc['records']:
            record['latestCupResults'][0]['raceResults'][0]['raceType3']='other-category'
        selected,excluded=select_references(refs,[doc])
        self.assertEqual(selected,[])
        self.assertEqual(excluded,1)
        for record in doc['records']:
            record['latestCupResults'][0]['raceResults'][0]['raceType3']='general'
        selected,excluded=select_references(refs,[doc])
        self.assertEqual([r['race_id'] for r in selected],[PAST])
        self.assertEqual(excluded,0)
        for record in doc['records']:
            record['latestCupResults'][0]['raceResults'][0].pop('raceType3')
        selected,excluded=select_references(refs,[doc])
        self.assertEqual(len(selected),1)

    def test_home_away_interleave_and_shared_events_are_not_fetched_twice(self):
        refs=self.refs()
        home=deepcopy(refs['references'][0])
        away=deepcopy(home)
        away['race_id']='203001092501'
        older=deepcopy(home)
        older['race_id']='203001081201'
        refs['references']=[home,older,away]
        selected,excluded=select_references(refs,[])
        self.assertEqual([r['race_id'] for r in selected],
                         ['203001101201','203001092501','203001081201'])
        self.assertEqual(excluded,0)
        self.assertEqual(len(selected),len({r['race_id'] for r in selected}))


if __name__=='__main__': unittest.main()
