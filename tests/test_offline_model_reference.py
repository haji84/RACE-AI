"""Real local Git layouts: no network, fixtures are byte-checked, not executed."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.verify_offline_model_run_synthetic import check_reference

FILES=("race_ai/comprehensive_four_sport_models.py","race_ai/four_sport_model_suite.py",
       "race_ai/four_sport_matchup_models.py","race_ai/four_sport_learning.py",
       "race_ai/permissioned_source_delivery.py","race_ai/private_delivery_codec.py",
       "tests/test_permissioned_source_delivery.py","tests/test_comprehensive_four_sport_models.py")


def git(path,*args):
    return subprocess.check_output(["git","-C",str(path),*args],stderr=subprocess.PIPE).decode().strip()


def repository(path,files,git_dir=None):
    path.mkdir(parents=True)
    git(path,"init","--quiet",*(["--separate-git-dir",str(git_dir)] if git_dir else []))
    for rel in files:
        dest=path/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text("# authored byte-only fixture\n",encoding="utf-8")
    git(path,"add","--all")
    git(path,"-c","user.name=Fixture","-c","user.email=fixture@example.invalid",
        "commit","--quiet","-m","fictional reference")
    return git(path,"rev-parse","HEAD")


class ReferenceLayoutTests(unittest.TestCase):
    def test_separate_checkout_uses_its_own_pin_missing_from_parent(self):
        for git_file in (False,True):
            with self.subTest(git_file=git_file),tempfile.TemporaryDirectory() as temp:
                root=Path(temp)/"parent";repository(root,["README.md"])
                reference=root/"reference"
                pin=repository(reference,FILES,Path(temp)/"metadata" if git_file else None)
                self.assertEqual((reference/".git").is_file(),git_file)
                with self.assertRaises(subprocess.CalledProcessError):git(root,"cat-file","-e",pin)
                check_reference(root,reference,pin)

    def test_materialized_reference_is_checked_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"parent";pin=repository(root,FILES)
            reference=root/"reference"
            for rel in FILES:
                dest=reference/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes((root/rel).read_bytes())
            check_reference(root,reference,pin)
            (reference/FILES[0]).write_text("# changed fixture\n",encoding="utf-8")
            with self.assertRaises(RuntimeError):check_reference(root,reference,pin)

    def test_moved_nested_head_is_rejected_even_if_pinned_files_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"parent";repository(root,["README.md"])
            reference=root/"reference";pin=repository(reference,FILES)
            git(reference,"-c","user.name=Fixture","-c","user.email=fixture@example.invalid",
                "commit","--allow-empty","--quiet","-m","moved reference")
            with self.assertRaises(RuntimeError):check_reference(root,reference,pin)

    def test_invalid_nested_git_does_not_fall_back_to_a_valid_parent_pin(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"parent";pin=repository(root,FILES)
            reference=root/"reference"
            for rel in FILES:
                dest=reference/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes((root/rel).read_bytes())
            (reference/".git").write_text("gitdir: missing-metadata\n",encoding="utf-8")
            with self.assertRaises((RuntimeError,subprocess.CalledProcessError)):
                check_reference(root,reference,pin)


if __name__=="__main__":unittest.main()
