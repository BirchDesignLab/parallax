import unittest
from parallax.audit import forbidden_hits
from parallax.scopes import matches, outside

class Scopes(unittest.TestCase):
    def test_matching(self):
        yes = [("src/a.py", ["src/**"]), ("src/x/y/z.py", ["src/**"]), ("pyproject.toml", ["pyproject.toml"]),
               ("README.md", ["*.md"]), ("a/b/c.py", ["**/*.py"]), ("c.py", ["**/*.py"]), ("anything/at/all", ["**"]),
               ("tests/test_x.py", ["src/**", "tests/**"])]
        no = [("src.py", ["src/**"]), ("docs/x.md", ["*.md"]), ("src/a.py", ["tests/**"]), ("SRC/a.py", ["src/**"]),
              ("xsrc/a.py", ["src/**"]), ("src/a.pyc", ["src/*.py"])]
        for path, patterns in yes:
            self.assertTrue(matches(path, patterns), (path, patterns))
        for path, patterns in no:
            self.assertFalse(matches(path, patterns), (path, patterns))

    def test_outside_lists_only_strays(self):
        self.assertEqual(outside(["src/a.py", "tests/t.py", "docs/x.md"], ["src/**"]), ["tests/t.py", "docs/x.md"])

class Audit(unittest.TestCase):
    other = r"C:\Users\First Last\AppData\Local\parallax\k\t\claude-ab12cd34"

    def test_finds_the_path_in_every_spelling(self):
        for text in (self.other + r"\src\a.py",
                     self.other.replace("\\", "/") + "/src/a.py",
                     self.other.replace("\\", "\\\\") + "\\\\src",          # as JSON escapes it
                     self.other.lower()):
            self.assertEqual(forbidden_hits("cmd: type " + text, [self.other]), [self.other], text)

    def test_ignores_a_longer_sibling_name_and_clean_text(self):
        self.assertEqual(forbidden_hits(self.other + "99\\src", [self.other]), [])
        self.assertEqual(forbidden_hits(r"C:\Users\First Last\AppData\Local\parallax\k\t\codex-ffff0000\x", [self.other]), [])
