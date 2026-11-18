import unittest
from parallax.delivery import check
from parallax.gitops import delta
from tests.helpers import commit, make_repo, run_git, write

def row(path, change="add", purpose="needed"):
    return {"path": path, "change": change, "purpose": purpose}

class Check(unittest.TestCase):
    def test_an_exact_match_passes(self):
        self.assertEqual(check([row("a.py"), row("b.py", "modify"), row("c.py", "delete")],
                               {"a.py": "add", "b.py": "modify", "c.py": "delete"}), [])

    def test_undeclared_unchanged_and_wrong_change(self):
        self.assertEqual(check([row("a.py", "modify"), row("gone.py")], {"a.py": "add", "new.py": "add"}),
                         ["a.py is listed as modify but the change since the task began is add",
                          "you listed gone.py in files but it is unchanged since the task began",
                          "you changed new.py but did not list it in files"])

    def test_bad_rows(self):
        reasons = check([row("../x.py"), row("C:/x.py"), row("a\\b.py"), row("/x.py"), row("a//b.py"),
                         row("ok.py", purpose=" "), row("OK.py")], {"ok.py": "add"})
        for path in ("../x.py", "C:/x.py", "a\\b.py", "/x.py", "a//b.py"):
            self.assertIn(f"bad path in files: {path}", reasons)
        self.assertIn("ok.py has no purpose in files", reasons)
        self.assertIn("OK.py is listed more than once in files", reasons)
        self.assertEqual(len(reasons), 7)

    def test_working_files_and_conductor_records(self):
        reasons = check([row(".parallax-mutants/m1/a.py")], {".parallax/ledger.jsonl": "modify"})
        self.assertEqual(reasons, [".parallax-mutants/m1/a.py is a Parallax working file or record, not a deliverable",
                                   "you changed .parallax/ledger.jsonl, which belongs to the conductor"])

class Delta(unittest.TestCase):
    def test_net_change_between_commits_and_in_the_index(self):
        repo = make_repo({"keep.py": "1\n", "edit.py": "1\n", "drop.py": "1\n", "old.py": "same\n"})
        base = run_git(repo, "rev-parse", "HEAD")
        commit(repo, {"edit.py": "2\n", "drop.py": None, "temp.py": "x\n", "old.py": None, "new.py": "same\n"})
        commit(repo, {"temp.py": None})                                   # added, then reverted: no net change
        self.assertEqual(delta(repo, base, "HEAD"),
                         {"drop.py": "delete", "edit.py": "modify", "new.py": "add", "old.py": "delete"})
        run_git(repo, "update-index", "--chmod=+x", "keep.py")
        run_git(repo, "commit", "-m", "mode only")
        self.assertEqual(delta(repo, base, "HEAD")["keep.py"], "modify")
        write(repo, {"staged.py": "s\n"})
        run_git(repo, "add", "staged.py")
        self.assertEqual(delta(repo, base)["staged.py"], "add")
        self.assertNotIn("staged.py", delta(repo, base, "HEAD"))
