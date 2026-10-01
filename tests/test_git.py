import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.git import MAX_FILE_BYTES, git_status


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@unittest.skipUnless(shutil.which("git"), "git not installed")
class GitStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")

    def commit(self):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "c")

    def test_counts_tracked_edits_and_new_text_files_only(self):
        (self.repo / "a.txt").write_text("one\ntwo\nthree\n")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        self.commit()
        (self.repo / "a.txt").write_text("one\nTWO\nthree\nfour\n")  # +2 -1
        (self.repo / "new.py").write_text("x = 1\ny = 2\nz = 3")  # +3, no final newline
        (self.repo / "blob.bin").write_bytes(b"\0\1\2" * 100)  # binary: not counted
        (self.repo / "big.txt").write_text("l\n" * (MAX_FILE_BYTES // 2 + 1))  # too big
        (self.repo / "ignored.txt").write_text("1\n2\n")  # .gitignore'd
        sub = self.repo / "pkg"
        sub.mkdir()
        (sub / "mod.py").write_text("a\n")  # +1, found even from a subdirectory
        status = git_status(sub)
        self.assertEqual(status, {"branch": "main", "added": 6, "removed": 1})

    def test_clean_detached_empty_and_outside(self):
        (self.repo / "a.txt").write_text("a\n")
        self.commit()
        self.assertEqual(git_status(self.repo), {"branch": "main", "added": 0, "removed": 0})
        git(self.repo, "checkout", "-q", "--detach")
        branch = git_status(self.repo)["branch"]
        self.assertRegex(branch, r"^[0-9a-f]{7,}$")
        empty = Path(self.temp.name) / "empty"
        empty.mkdir()
        git(empty, "init", "-q", "-b", "trunk")
        (empty / "f").write_text("1\n2\n")
        self.assertEqual(git_status(empty), {"branch": "trunk", "added": 2, "removed": 0})
        outside = Path(self.temp.name) / "plain"
        outside.mkdir()
        self.assertIsNone(git_status(outside))
        self.assertIsNone(git_status(Path(self.temp.name) / "missing"))
