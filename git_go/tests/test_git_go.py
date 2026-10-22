import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))

import git_go


class PrefixTests(unittest.TestCase):
    def test_known_prefixes(self):
        for prefix in git_go.PREFIXES:
            self.assertTrue(git_go.has_known_prefix(prefix + "x"))
        self.assertFalse(git_go.has_known_prefix("fix-login"))
        self.assertFalse(git_go.has_known_prefix("features/x"))

    def test_prefixed_name(self):
        self.assertEqual(git_go.prefixed_name("x", "3"), "feature/x")
        self.assertEqual(git_go.prefixed_name("x", ""), "x")
        self.assertEqual(git_go.prefixed_name("x", "99"), "x")
        self.assertEqual(git_go.prefixed_name("x", "abc"), "x")


class HistoryTests(unittest.TestCase):
    def test_rewrites_zsh_entry(self):
        line = ": 1792694921:0;git go fix-login\n"
        self.assertEqual(git_go.rewrite_history_line(line, "fix-login", "feature/fix-login"),
                         ": 1792694921:0;git go feature/fix-login\n")

    def test_rewrites_quoted_and_aliased(self):
        self.assertEqual(git_go.rewrite_history_line("g go 'a'\n", "a", "chore/a"),
                         "g go 'chore/a'\n")

    def test_ignores_longer_branch_names(self):
        line = "git go fix-login-2\n"
        self.assertEqual(git_go.rewrite_history_line(line, "fix-login", "x/fix-login"), line)

    def test_only_recent_lines_are_rewritten(self):
        lines = ["git go a\n"] + ["ls\n"] * 5
        _, changed = git_go.rewrite_history(lines, "a", "feature/a")
        self.assertFalse(changed)

    def test_most_recent_match_wins(self):
        lines = ["git go a\n", "git go a\n"]
        out, changed = git_go.rewrite_history(lines, "a", "feature/a")
        self.assertTrue(changed)
        self.assertEqual(out, ["git go a\n", "git go feature/a\n"])

    def test_update_history_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hist")
            with open(path, "w") as f:
                f.write(": 1:0;ls\n: 2:0;git go topic\n")
            os.chmod(path, 0o600)
            self.assertTrue(git_go.update_history("topic", "spike/topic", path))
            with open(path) as f:
                self.assertEqual(f.read(), ": 1:0;ls\n: 2:0;git go spike/topic\n")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
