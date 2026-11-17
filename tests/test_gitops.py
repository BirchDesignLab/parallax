import unittest
from pathlib import Path
from parallax import gitops
from parallax.gitops import GitError, MainMoved
from tests.helpers import commit, make_repo, run_git, write

SKIP = [".parallax-mutants", ".parallax-scratch"]
WHO = ("Test Human", "human@example.invalid")

def clone(repo: Path, name: str) -> Path:
    dest = repo.parent / name
    gitops.clone_at(repo, dest, "main")
    return dest

class Clones(unittest.TestCase):
    def test_clone_is_detached_at_ref_with_no_remote(self):
        repo = make_repo({"src/a.py": "A = 1\n"})
        self.assertIn(" ", str(repo))
        seat = clone(repo, "seat one")
        self.assertEqual((seat / "src/a.py").read_text(encoding="utf-8"), "A = 1\n")
        self.assertEqual(run_git(seat, "remote"), "")
        self.assertEqual(gitops.rev(seat), gitops.rev(repo, "main"))
        self.assertEqual(run_git(seat, "config", "core.autocrlf"), "false")

    def test_changed_paths_sees_new_modified_and_deleted(self):
        repo = make_repo({"src/a.py": "A = 1\n", "src/b.py": "B = 1\n"})
        write(repo, {"src/a.py": "A = 2\n", "src/b.py": None, "src/deep dir/c.py": "C = 1\n"})
        self.assertEqual(sorted(gitops.changed_paths(repo)), ["src/a.py", "src/b.py", "src/deep dir/c.py"])

    def test_snapshot_leaves_excluded_folders_out_and_returns_none_when_clean(self):
        seat = clone(make_repo({"src/a.py": "A = 1\n"}), "seat")
        write(seat, {"src/a.py": "A = 2\n", ".parallax-mutants/m1/src/a.py": "A = 3\n"})
        sha = gitops.snapshot(seat, "attempt 1", exclude=SKIP)
        self.assertEqual(run_git(seat, "show", "--name-only", "--format=", sha), "src/a.py")
        self.assertTrue((seat / ".parallax-mutants/m1/src/a.py").exists())
        self.assertIsNone(gitops.snapshot(seat, "again", exclude=SKIP))

    def test_remove_tree_is_idempotent(self):
        seat = clone(make_repo(), "seat")
        self.assertTrue(gitops.remove_tree(seat))
        self.assertTrue(gitops.remove_tree(seat))
        self.assertFalse(seat.exists())

    def test_show_file_and_identity(self):
        repo = make_repo({"src/a.py": "A = 1\n"})
        self.assertEqual(gitops.show_file(repo, "main", "src/a.py"), "A = 1\n")
        self.assertIsNone(gitops.show_file(repo, "main", "nope.txt"))
        self.assertEqual(gitops.identity(repo), WHO)

class Combining(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo({"src/a.py": "A = 1\n", "tests/test_a.py": "T = 1\n"})
        self.base = gitops.rev(self.repo, "main")
        self.builder, self.challenger, self.work = (clone(self.repo, n) for n in ("b", "c", "w"))

    def test_two_disjoint_ranges_combine_into_one_commit(self):
        write(self.builder, {"src/a.py": "A = 2\n"}); b = gitops.snapshot(self.builder, "b")
        write(self.challenger, {"tests/test_a.py": "T = 2\n"}); c = gitops.snapshot(self.challenger, "c")
        gitops.fetch(self.work, self.builder, b); gitops.fetch(self.work, self.challenger, c)
        gitops.apply_range(self.work, self.base, b); gitops.apply_range(self.work, self.base, c)
        sha = gitops.commit_staged(self.work, "both\n\nVerdict: consensus", WHO)
        self.assertEqual(sorted(run_git(self.work, "show", "--name-only", "--format=", sha).splitlines()),
                         ["src/a.py", "tests/test_a.py"])
        self.assertEqual(run_git(self.work, "log", "-1", "--format=%an <%ae>", sha), "Test Human <human@example.invalid>")

    def test_conflicting_range_raises_and_restores_what_was_staged(self):
        write(self.builder, {"src/a.py": "A = 2\n"}); b = gitops.snapshot(self.builder, "b")
        write(self.challenger, {"src/a.py": "A = 3\n"}); c = gitops.snapshot(self.challenger, "c")
        gitops.fetch(self.work, self.builder, b); gitops.fetch(self.work, self.challenger, c)
        gitops.apply_range(self.work, self.base, b)
        with self.assertRaises(GitError):
            gitops.apply_range(self.work, self.base, c)
        self.assertEqual((self.work / "src/a.py").read_text(encoding="utf-8"), "A = 2\n")
        self.assertEqual(run_git(self.work, "diff", "--cached", "--name-only"), "src/a.py")

class AdvancingMain(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo({"src/a.py": "A = 1\n", "notes.txt": "n\n"})
        self.old = gitops.rev(self.repo, "main")
        self.work = clone(self.repo, "land")
        write(self.work, {"src/a.py": "A = 2\n"})
        run_git(self.work, "add", "-A")
        self.new = gitops.commit_staged(self.work, "task", WHO)

    def advance(self):
        return gitops.advance_main(self.repo, "main", self.work, self.new, self.old, "parallax/ready/t1")

    def test_fast_forwards_a_checked_out_main(self):
        self.assertEqual(self.advance(), "advanced")
        self.assertEqual(gitops.rev(self.repo, "main"), self.new)
        self.assertEqual((self.repo / "src/a.py").read_text(encoding="utf-8"), "A = 2\n")

    def test_unrelated_human_edits_survive(self):
        write(self.repo, {"notes.txt": "the human is typing\n"})
        self.assertEqual(self.advance(), "advanced")
        self.assertEqual((self.repo / "notes.txt").read_text(encoding="utf-8"), "the human is typing\n")

    def test_parks_when_human_edits_are_in_the_way(self):
        write(self.repo, {"src/a.py": "HUMAN EDIT\n"})
        self.assertEqual(self.advance(), "parked")
        self.assertEqual(gitops.rev(self.repo, "main"), self.old)
        self.assertEqual((self.repo / "src/a.py").read_text(encoding="utf-8"), "HUMAN EDIT\n")
        self.assertEqual(gitops.rev(self.repo, "parallax/ready/t1"), self.new)

    def test_moves_the_ref_when_main_is_not_checked_out(self):
        run_git(self.repo, "checkout", "-b", "elsewhere")
        self.assertEqual(self.advance(), "advanced")
        self.assertEqual(gitops.rev(self.repo, "main"), self.new)
        self.assertEqual(gitops.rev(self.repo, "elsewhere"), self.old)

    def test_raises_when_main_moved(self):
        commit(self.repo, {"other.txt": "x\n"})
        with self.assertRaises(MainMoved):
            self.advance()
