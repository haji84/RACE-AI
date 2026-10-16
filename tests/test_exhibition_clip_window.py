"""The new public-player bounded clip-window shape is opt-in; legacy rejects it."""
import unittest

from race_ai.core import SourceError
from tests.test_exhibition_video_decode import master
from tests.test_exhibition_video_source import MEDIA, SOURCE


class ClipWindowTests(unittest.TestCase):
    def test_only_explicit_window_contract_accepts_observed_three_fields(self):
        from race_ai.exhibition_video_decode import select_variant
        raw=master().replace('?vt=', '?start=1792138500&end=1792138845&vt=').encode()
        with self.assertRaisesRegex(SourceError,'VIDEO_HLS_QUERY_INVALID'):
            select_variant(raw,MEDIA,SOURCE)
        selected=select_variant(raw,MEDIA,SOURCE,clip_window=True)
        self.assertEqual(selected.window,('1792138500','1792138845'))
        self.assertNotIn('SYNTHETIC_CHILD',repr(selected))

    def test_unknown_duplicate_reversed_or_large_window_is_rejected(self):
        from race_ai.exhibition_video_decode import select_variant
        good=master().replace('?vt=', '?start=1792138500&end=1792138845&vt=')
        for bad in (good.replace('end=1792138845','end=1792138500'),
                    good.replace('end=1792138845','end=1792140000'),
                    good.replace('start=1792138500','start=1'),
                    good.replace('&vt=','&start=1792138500&vt='),
                    good.replace('&vt=','&unknown=x&vt=')):
            with self.subTest(bad=bad),self.assertRaises(SourceError):
                select_variant(bad.encode(),MEDIA,SOURCE,clip_window=True)

    def test_mixed_window_variants_are_not_silently_interchangeable(self):
        from race_ai.exhibition_video_decode import select_variant
        a=master().replace('?vt=','?start=1792138500&end=1792138845&vt=')
        b=a.split('\n',1)[1].replace('manifest_2','manifest_3').replace('1792138845','1792138846')
        with self.assertRaises(SourceError):
            select_variant((a+b).encode(),MEDIA,SOURCE,clip_window=True)


if __name__=='__main__':unittest.main()
