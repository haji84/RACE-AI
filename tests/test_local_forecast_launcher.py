"""Private seed/bootstrap contracts; fixture bytes are not real forecasts."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import start_local_forecast as launcher


def seed_at(root, entries=None):
    seed=root/"private-seed";seed.mkdir(mode=0o700)
    values=entries or {"forecast.sqlite":b"fixture-sqlite-original", "2030-01-01/program.lzh":b"fixture-official-raw", "operation-1-receipt.json":b'{"fixture":true}'}
    records=[]
    for name,raw in values.items():
        p=seed/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        records.append({"file":name,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
    (seed/"manifest.json").write_text(json.dumps({"files":records}))
    return seed,values


@unittest.skipUnless(sys.platform=="linux" and os.name=="posix", "Owner journal bootstrap requires Linux/WSL")
class LocalForecastLauncherTests(unittest.TestCase):
    def test_exact_seed_copy_has_private_modes_and_keeps_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);seed,values=seed_at(root);target=root/"owner"
            self.assertEqual(launcher.prepare_private_root(target,seed),target)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o700)
            for name,raw in values.items():
                self.assertEqual((target/name).read_bytes(),raw)
                self.assertEqual((seed/name).read_bytes(),raw)
                self.assertEqual(stat.S_IMODE((target/name).stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE((target/'2030-01-01').stat().st_mode),0o700)
            self.assertFalse((target/'manifest.json').exists())

    def test_existing_original_store_is_never_reseeded(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);seed,_=seed_at(root);target=root/"owner";target.mkdir(mode=0o700)
            db=target/'forecast.sqlite';db.write_bytes(b'EXISTING_ORIGINAL');db.chmod(0o600)
            (seed/'manifest.json').write_text('broken-seed-must-not-be-read')
            launcher.prepare_private_root(target,seed)
            self.assertEqual(db.read_bytes(),b'EXISTING_ORIGINAL')
            self.assertEqual(sorted(p.name for p in target.iterdir()),['forecast.sqlite'])

    def test_existing_incomplete_root_is_preserved_and_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);seed,_=seed_at(root);target=root/"owner";target.mkdir(mode=0o700)
            sentinel=target/'keep.txt';sentinel.write_text('KEEP')
            with self.assertRaises(launcher.LaunchError):launcher.prepare_private_root(target,seed)
            self.assertEqual(sentinel.read_text(),'KEEP');self.assertFalse((target/'forecast.sqlite').exists())

    def test_tampered_or_missing_source_never_leaves_partial_target(self):
        for kind in ('tampered','missing'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);seed,_=seed_at(root);target=root/'owner'
                if kind=='tampered':(seed/'forecast.sqlite').write_bytes(b'WRONG')
                else:(seed/'forecast.sqlite').unlink()
                with self.assertRaises(launcher.LaunchError):launcher.prepare_private_root(target,seed)
                self.assertFalse(target.exists());self.assertEqual(sorted(p.name for p in root.iterdir()),['private-seed'])

    def test_manifest_cannot_escape_seed_or_copy_links(self):
        for kind in ('traversal','absolute','symlink','hardlink'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);seed,values=seed_at(root);target=root/'owner';outside=root/'outside';outside.write_bytes(b'outside')
                manifest=json.loads((seed/'manifest.json').read_text())
                if kind=='traversal':manifest['files'][0]['file']='../outside'
                elif kind=='absolute':manifest['files'][0]['file']=str(outside)
                else:
                    p=seed/'forecast.sqlite';p.unlink()
                    if kind=='symlink':p.symlink_to(outside)
                    else:os.link(outside,p)
                (seed/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(launcher.LaunchError):launcher.prepare_private_root(target,seed)
                self.assertFalse(target.exists());self.assertEqual(outside.read_bytes(),b'outside')

    def test_seed_publication_cannot_replace_a_concurrently_created_empty_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);seed,_=seed_at(root);target=root/'owner';real=launcher._rename_noreplace
            def raced(parent,old,new):
                target.mkdir(mode=0o700)
                return real(parent,old,new)
            with patch.object(launcher,'_rename_noreplace',side_effect=raced):
                with self.assertRaises(launcher.LaunchError):launcher.prepare_private_root(target,seed)
            self.assertTrue(target.is_dir());self.assertEqual(list(target.iterdir()),[])
            self.assertEqual(sorted(p.name for p in root.iterdir()),['owner','private-seed'])

    def test_no_seed_initializes_only_a_new_private_directory_outside_git(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'new'/'parents'/'owner'
            launcher.prepare_private_root(target)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o700)
            self.assertEqual(list(target.iterdir()),[])
            repo=root/'repo';repo.mkdir();(repo/'.git').mkdir()
            with self.assertRaises(launcher.LaunchError):launcher.prepare_private_root(repo/'owner')
            self.assertFalse((repo/'owner').exists())
            with self.assertRaises(launcher.LaunchError):launcher.prepare_private_root(Path('relative-owner'))

    def test_check_uses_status_without_generation_provider_reads_or_server_start(self):
        class Service:
            def __init__(self,path):self.path=path
            def status(self):return {'saved_prediction_count':7,'day_jst':'2030-01-01'}
            def generate(self,*args):raise AssertionError('must not generate')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'owner';output=io.StringIO()
            with patch.object(launcher,'ROOT',root),patch.object(launcher,'check_runtime') as ready,\
                 patch('race_ai.local_forecast_service.LocalForecastService',Service),\
                 patch('race_ai.local_forecast_server.make_server',side_effect=AssertionError('must not start server')),\
                 contextlib.redirect_stdout(output):
                self.assertEqual(launcher.main(['--private-dir',str(target),'--check']),0)
            ready.assert_called_once_with(root)
            self.assertIn('LOCAL_FORECAST_READY',output.getvalue())
            self.assertNotIn(str(target),output.getvalue())

    def test_missing_pinned_references_fail_before_private_target_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'owner';errors=io.StringIO()
            with patch.object(launcher,'ROOT',root),contextlib.redirect_stderr(errors):
                self.assertEqual(launcher.main(['--private-dir',str(target),'--check']),2)
            self.assertFalse(target.exists());self.assertNotIn(str(target),errors.getvalue())
