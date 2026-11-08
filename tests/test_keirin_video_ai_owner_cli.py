"""Private CLI regression: no overwrites, and no real footage in public CI."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import unittest
from unittest.mock import patch

from scripts.keirin_video_ai_owner_cli import private_output,load_private,main

class PrivateCliTests(unittest.TestCase):
    def test_create_once_and_read_back(self):
        with TemporaryDirectory() as root:
            p=Path(root)/"video"/"training.json"
            private_output(p,{"scenario":"synthetic","count":4})
            self.assertEqual(load_private(p)["count"],4)
            with self.assertRaisesRegex(ValueError,"PRIVATE_OUTPUT_ALREADY_EXISTS"):
                private_output(p,{"count":10})
            self.assertEqual(load_private(p)["count"],4)

    def test_public_ci_refuses_real_video_even_if_present(self):
        with TemporaryDirectory() as root:
            p=Path(root)/"video.webm"
            p.write_bytes(b"fake")
            with patch.dict(os.environ,{"GITHUB_ACTIONS":"true"}):
                with self.assertRaises(SystemExit) as exc:
                    main(["extract","--video",str(p),
                          "--race-id","20261108-matsuyama-9R",
                          "--output",str(Path(root)/"features.json")])
                self.assertIn("PRIVATE_OWNER_RUNTIME",str(exc.exception))
            self.assertFalse((Path(root)/"features.json").exists())

    def test_real_training_file_not_accessible_through_symlink(self):
        with TemporaryDirectory() as root:
            p=Path(root)/"content.json"
            p.write_text('{"sample":"fixture"}')
            alias=Path(root)/"alias.json"
            alias.symlink_to(p)
            with self.assertRaisesRegex(ValueError,"PRIVATE_INPUT_INVALID"):
                load_private(alias)

if __name__=="__main__":unittest.main()
