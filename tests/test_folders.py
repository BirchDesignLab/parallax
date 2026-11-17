import os, subprocess, tempfile, unittest
from pathlib import Path
from parallax import folders

class PrivateFolders(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="plx priv "))

    def test_make_private_creates_parents_and_refuses_an_existing_folder(self):
        target = self.base / "key" / "task one"
        folders.make_private(target)
        self.assertTrue(target.is_dir())
        self.assertTrue(folders.is_private(target))
        with self.assertRaises(FileExistsError):
            folders.make_private(target)

    def test_what_is_made_inside_is_private_too(self):
        target = self.base / "task"
        folders.make_private(target)
        (target / "seat clone").mkdir()
        (target / "seat clone" / "file.txt").write_text("x", encoding="utf-8")
        self.assertTrue(folders.is_private(target / "seat clone"))

    @unittest.skipUnless(os.name == "nt", "Windows permissions")
    def test_a_folder_that_names_anyone_else_is_not_private(self):
        target = self.base / "opened"
        folders.make_private(target)
        subprocess.run(["icacls", str(target), "/grant", "*S-1-1-0:(OI)(CI)RX"], check=True, capture_output=True)
        self.assertFalse(folders.is_private(target))
