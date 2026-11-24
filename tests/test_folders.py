import os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
from parallax import folders

class PrivateFolders(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="plx priv "))

    def test_make_private_creates_parents_and_refuses_an_existing_folder(self):
        target = self.base / "key" / "task one"
        folders.make_private(target)
        self.assertTrue(target.is_dir())
        self.assertTrue(folders.is_private(target), self._permissions(target))
        with self.assertRaises(FileExistsError):
            folders.make_private(target)

    def test_what_is_made_inside_is_private_too(self):
        target = self.base / "task"
        folders.make_private(target)
        (target / "seat clone").mkdir()
        (target / "seat clone" / "file.txt").write_text("x", encoding="utf-8")
        self.assertTrue(folders.is_private(target / "seat clone"), self._permissions(target / "seat clone"))

    def test_the_builtin_administrator_is_recognised_by_its_alias(self):
        # SDDL writes the account with relative id 500 as `LA`, not as its SID.
        admin = "S-1-5-21-1111111111-2222222222-3333333333-500"
        self.assertEqual(folders._own_trustees(admin), {admin, "LA"})
        other = "S-1-5-21-1111111111-2222222222-3333333333-1001"
        self.assertEqual(folders._own_trustees(other), {other})

    @unittest.skipUnless(os.name == "nt", "Windows permissions")
    def test_the_alias_counts_only_for_the_builtin_administrator(self):
        target = self.base / "alias"
        folders.make_private(target)
        dacl = "(A;OICI;FA;;;LA)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)"
        with mock.patch.object(folders, "_dacl", return_value=dacl):
            with mock.patch.object(folders, "_current_sid", return_value="S-1-5-21-1-2-3-500"):
                self.assertTrue(folders.is_private(target))
            with mock.patch.object(folders, "_current_sid", return_value="S-1-5-21-1-2-3-1001"):
                self.assertFalse(folders.is_private(target))

    def _permissions(self, path):
        """What the folder's permissions are, for the message of a failed check."""
        if os.name != "nt":
            return oct(path.stat().st_mode)
        return f"permissions {folders._dacl(path)!r} for account {folders._current_sid()!r}"

    @unittest.skipUnless(os.name == "nt", "Windows permissions")
    def test_a_folder_that_names_anyone_else_is_not_private(self):
        target = self.base / "opened"
        folders.make_private(target)
        subprocess.run(["icacls", str(target), "/grant", "*S-1-1-0:(OI)(CI)RX"], check=True, capture_output=True)
        self.assertFalse(folders.is_private(target))
