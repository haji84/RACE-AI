"""Invented catalogue identities; no provider requests or generated likeness assertions."""
from copy import deepcopy
import unittest


def catalogue():
    asset='assets/racer-portraits/sheet-9000.webp'
    return dict(schema='RACE_AI_RACER_PORTRAITS_V2',total=3,roster_sha256='a'*64,
        assets={asset:dict(sha256='b'*64,bytes=1234)},people=[
            dict(registration='9001',name='架空甲',aliases=['架空甲'],state='READY',asset=asset,
                 source_url='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=9001',
                 source_photo_sha256='c'*64,atlas=dict(columns=5,rows=5,slot=0)),
            dict(registration='9002',name='架空乙',aliases=['架空乙'],state='READY',asset=asset,
                 source_url='https://www.boatrace.jp/owpc/pc/data/racersearch/profile?toban=9002',
                 source_photo_sha256='d'*64,atlas=dict(columns=5,rows=5,slot=24)),
            dict(registration='9003',name='架空丙',aliases=['架空丙'],state='PENDING')])


class PortraitCatalogueTests(unittest.TestCase):
    def test_valid_shared_atlas_is_deduplicated_and_complete_target_is_explicit(self):
        from race_ai.racer_portraits import validate_catalogue,files_from_catalogue
        doc=catalogue();self.assertEqual(validate_catalogue(doc),doc)
        files=files_from_catalogue(doc)
        self.assertEqual(files.count('assets/racer-portraits/sheet-9000.webp'),1)
        self.assertIn('racer-portraits-data.js',files)
        self.assertIn('data/racer-portraits.json',files)

    def test_conflicting_ids_duplicate_cells_unknown_paths_and_wrong_sources_are_rejected(self):
        from race_ai.racer_portraits import validate_catalogue
        for kind in ['id','cell','outside','source','target','asset','geometry','unknown_state']:
            d=deepcopy(catalogue())
            if kind=='id':d['people'][1]['registration']='9001'
            elif kind=='cell':d['people'][1]['atlas']['slot']=0
            elif kind=='outside':d['people'][0]['atlas']['slot']=25
            elif kind=='source':d['people'][0]['source_url']='https://example.test/9001'
            elif kind=='target':d['total']=2
            elif kind=='asset':d['people'][0]['asset']='../owner-key.txt'
            elif kind=='geometry':d['people'][0]['atlas']['columns']=6
            else:d['people'][0]['state']='COMPLETE_BY_SUBMISSION'
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_catalogue(d)

    def test_six_by_six_geometry_keeps_distinct_last_row_identity(self):
        from race_ai.racer_portraits import validate_catalogue
        d=catalogue()
        for p in d['people'][:2]:p['atlas'].update(columns=6,rows=6)
        d['people'][1]['atlas']['slot']=35
        self.assertEqual(validate_catalogue(d)['people'][1]['atlas']['slot'],35)

    def test_offline_assets_only_include_consistent_real_view_identities(self):
        from race_ai.racer_portraits import needed_assets
        d=catalogue();asset='assets/racer-portraits/sheet-9000.webp'
        real=dict(sport='boat',scope='research',participants=[dict(registration_no='9002',name='架空乙')])
        self.assertEqual(needed_assets(d,{'records':[real]}),(asset,))
        self.assertEqual(needed_assets(d,{'records':[dict(real,scope='synthetic')]}),())
        self.assertEqual(needed_assets(d,{'records':[dict(real,sport='keirin')]}),())
        real['participants'][0]['participant_id']='9001'
        self.assertEqual(needed_assets(d,{'records':[real]}),())
