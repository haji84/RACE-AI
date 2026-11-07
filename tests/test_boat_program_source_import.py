"""The retained-source reader imports with the display job's PR64-only surface."""
import builtins
from datetime import date,timedelta
from tests.test_boat_entry_observations import uncompressed_lzh
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib import request
import race_ai


class ProgramSourceImportTests(unittest.TestCase):
    def test_cache_reader_imports_without_producer_bridge_or_http(self):
        original_import=builtins.__import__
        forbidden=[]
        def guarded_import(name,globals=None,locals=None,fromlist=(),level=0):
            targets=[name]+[name+'.'+part for part in (fromlist or ()) if type(part) is str]
            if any(target=='scripts.existing_day_program' or
                   target.rsplit('.',1)[-1]=='boat_observed_program_bridge' for target in targets):
                forbidden.append(name)
                raise ModuleNotFoundError('producer-only dependency blocked by isolated import test')
            return original_import(name,globals,locals,fromlist,level)
        root=Path(__file__).resolve().parents[1]
        reference=str(root/'pr64-reference/race_ai')
        paths=[item for item in race_ai.__path__ if 'pr72-reference' not in item]
        if reference not in paths:paths.append(reference)
        spec=importlib.util.spec_from_file_location('race_ai._program_source_import_probe',root/'race_ai/boat_program_source.py')
        module=importlib.util.module_from_spec(spec)
        with patch.object(race_ai,'__path__',paths), \
             patch('builtins.__import__',side_effect=guarded_import), \
             patch.object(request,'urlopen',side_effect=AssertionError('import made an HTTP call')), \
             patch.object(request,'build_opener',side_effect=AssertionError('import built an HTTP client')):
            spec.loader.exec_module(module)
            from race_ai.official_archive_probe import official_url,inspect_lzh
            for day in (date(2030,1,15),date(2024,2,29)):
                self.assertEqual(module.official_url(day,'B'),official_url(day,'B'))
            raw=uncompressed_lzh(b'invented archive fixture','B300115.TXT')
            self.assertEqual(module.inspect_lzh(raw),inspect_lzh(raw))
        self.assertEqual(module.JST.utcoffset(None),timedelta(hours=9))
        self.assertEqual(forbidden,[])


if __name__=='__main__':unittest.main()
