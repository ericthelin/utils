#!/usr/bin/env python3
"""Unit tests for hist_search.py history parsing and filtering logic.

Run directly (python3 tests/test_hist_search.py) or via tests/run_tests.sh.
"""

import fcntl
import importlib.util
import os
import pty
import re
import select
import struct
import sys
import tempfile
import termios
import time
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(TOOL_DIR, "hist_search.py")

spec = importlib.util.spec_from_file_location("hist_search", MODULE_PATH)
hist_search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hist_search)


class ReadHistoryTests(unittest.TestCase):
    def _write(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".hist", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.remove, f.name)
        return f.name

    def test_parses_extended_zsh_history_most_recent_first(self):
        path = self._write(
            ": 1690000000:0;git status\n"
            ": 1690000001:0;echo hello world\n"
            ": 1690000002:0;ls -la /tmp\n"
            ': 1690000003:0;git commit -m "fix bug"\n'
        )
        commands = hist_search.read_history(path)
        self.assertEqual(commands[0], 'git commit -m "fix bug"')
        self.assertEqual(len(commands), 4)

    def test_dedupes_keeping_most_recent_occurrence(self):
        path = self._write(
            ": 1:0;git status\n"
            ": 2:0;ls\n"
            ": 3:0;git status\n"
        )
        commands = hist_search.read_history(path)
        self.assertEqual(commands.count("git status"), 1)
        self.assertEqual(commands[0], "git status")
        self.assertEqual(commands[1], "ls")

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(hist_search.read_history("/nonexistent/path/.hist"), [])

    def test_plain_non_extended_history(self):
        path = self._write("git status\nls -la\n")
        commands = hist_search.read_history(path)
        self.assertEqual(commands, ["ls -la", "git status"])

    def test_bash_timestamp_lines_are_not_commands(self):
        path = self._write("#1690000000\ngit status\n#1690000005\nls -la\n")
        self.assertEqual(hist_search.read_history(path), ["ls -la", "git status"])


class DefaultHistfileTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        self.saved = {k: os.environ.get(k) for k in ("HOME", "HISTFILE")}
        self.addCleanup(self._restore)
        os.environ["HOME"] = self.home
        os.environ.pop("HISTFILE", None)

    def _restore(self):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_histfile_env_wins(self):
        os.environ["HISTFILE"] = "/somewhere/else"
        self.assertEqual(hist_search.default_histfile(), "/somewhere/else")

    def test_falls_back_to_bash_history_when_no_zsh_history(self):
        open(os.path.join(self.home, ".bash_history"), "w").close()
        self.assertEqual(hist_search.default_histfile(), os.path.join(self.home, ".bash_history"))

    def test_prefers_zsh_history_when_both_exist(self):
        for name in (".zsh_history", ".bash_history"):
            open(os.path.join(self.home, name), "w").close()
        self.assertEqual(hist_search.default_histfile(), os.path.join(self.home, ".zsh_history"))


class FuzzyScoreTests(unittest.TestCase):
    def test_empty_query_matches_everything(self):
        self.assertEqual(hist_search.fuzzy_score("", "anything"), 0)

    def test_substring_match_scores_by_span_then_position(self):
        # "git" matches contiguously at position 0 -> span 3, start 0
        self.assertEqual(hist_search.fuzzy_score("git", "git status"), (3, 0))
        # "status" matches contiguously at position 4 -> span 6, start 4
        self.assertEqual(hist_search.fuzzy_score("status", "git status"), (6, 4))

    def test_contiguous_match_scores_better_than_scattered(self):
        contiguous = hist_search.fuzzy_score("git", "git status")
        scattered = hist_search.fuzzy_score("gts", "git status")
        self.assertLess(contiguous, scattered)

    def test_subsequence_match_when_no_substring(self):
        score = hist_search.fuzzy_score("gts", "git status")
        self.assertIsNotNone(score)

    def test_uses_real_regex_special_chars_are_escaped_literally(self):
        # "." in the query should match a literal dot, not "any character"
        self.assertIsNone(hist_search.fuzzy_score(".", "git status"))
        self.assertIsNotNone(hist_search.fuzzy_score(".", "git . status"))

    def test_no_match_returns_none(self):
        self.assertIsNone(hist_search.fuzzy_score("xyz", "git status"))


class RegexScoreTests(unittest.TestCase):
    def test_matches_return_start_position(self):
        self.assertEqual(hist_search.regex_score("^ls", "ls -la /tmp"), 0)

    def test_invalid_regex_returns_none(self):
        self.assertIsNone(hist_search.regex_score("[", "ls -la /tmp"))

    def test_no_match_returns_none(self):
        self.assertIsNone(hist_search.regex_score("^ls", "git status"))


class FilterCommandsTests(unittest.TestCase):
    def setUp(self):
        self.commands = ['git commit -m "fix bug"', "ls -la /tmp", "echo hello world", "git status"]

    def test_empty_query_returns_all_in_order(self):
        result = hist_search.filter_commands(self.commands, "", False)
        self.assertEqual([c for _i, c in result], self.commands)

    def test_fuzzy_filters_and_ranks(self):
        result = hist_search.filter_commands(self.commands, "gts", False)
        self.assertTrue(any("git status" in c for _i, c in result))

    def test_regex_mode_filters_by_pattern(self):
        result = hist_search.filter_commands(self.commands, r"^ls", True)
        self.assertEqual(result[0][1], "ls -la /tmp")

    def test_regex_mode_no_matches_is_empty(self):
        result = hist_search.filter_commands(self.commands, r"^nomatch", True)
        self.assertEqual(result, [])


class BuildThemeTests(unittest.TestCase):
    def _clear_env(self):
        for env_name in list(hist_search.THEME_ENV_OVERRIDES.values()) + [
            "HIST_SEARCH_THEME",
            "HIST_SEARCH_CONFIG",
        ]:
            os.environ.pop(env_name, None)

    def setUp(self):
        self._clear_env()
        self.addCleanup(self._clear_env)
        # Point at a dotfile that doesn't exist by default, so tests
        # aren't affected by a real ~/.hist_searchrc on the machine.
        os.environ["HIST_SEARCH_CONFIG"] = "/nonexistent/.hist_searchrc"

    def _write_config(self, content):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".hist_searchrc", delete=False)
        f.write(content)
        f.close()
        self.addCleanup(os.remove, f.name)
        os.environ["HIST_SEARCH_CONFIG"] = f.name
        return f.name

    def test_default_theme_has_below_layout_and_reverse_video_selection(self):
        theme = hist_search.build_theme()
        self.assertEqual(theme["layout"], "below")
        self.assertEqual(theme["selected_style"], "1;36;7")
        self.assertEqual(theme["selected_indicator"], "> ")

    def test_named_theme_selected_via_env_var(self):
        os.environ["HIST_SEARCH_THEME"] = "fzf"
        theme = hist_search.build_theme()
        self.assertEqual(theme["layout"], "above")
        self.assertEqual(theme["selected_style"], "36")

    def test_unknown_theme_name_falls_back_to_default(self):
        theme = hist_search.build_theme("no-such-theme")
        self.assertEqual(theme, hist_search.THEMES["default"])

    def test_per_field_env_override_wins_over_named_theme(self):
        os.environ["HIST_SEARCH_THEME"] = "fzf"
        os.environ["HIST_SEARCH_LAYOUT"] = "below"
        os.environ["HIST_SEARCH_SELECTED_INDICATOR"] = "* "
        theme = hist_search.build_theme()
        self.assertEqual(theme["layout"], "below")
        self.assertEqual(theme["selected_indicator"], "* ")
        # Untouched fields still come from the named theme.
        self.assertEqual(theme["selected_style"], "36")

    def test_dotfile_theme_key_selects_named_theme(self):
        self._write_config("theme=fzf\n")
        theme = hist_search.build_theme()
        self.assertEqual(theme["layout"], "above")
        self.assertEqual(theme["selected_style"], "36")

    def test_dotfile_field_overrides_named_theme(self):
        self._write_config("theme=fzf\nselected_style=1;35\n# a comment\n\nlayout=below\n")
        theme = hist_search.build_theme()
        self.assertEqual(theme["selected_style"], "1;35")
        self.assertEqual(theme["layout"], "below")

    def test_env_var_wins_over_dotfile(self):
        self._write_config("theme=fzf\nselected_style=1;35\n")
        os.environ["HIST_SEARCH_SELECTED_STYLE"] = "44"
        theme = hist_search.build_theme()
        self.assertEqual(theme["selected_style"], "44")

    def test_missing_dotfile_is_ignored(self):
        os.environ["HIST_SEARCH_CONFIG"] = "/nonexistent/.hist_searchrc"
        self.assertEqual(hist_search.read_config_file(os.environ["HIST_SEARCH_CONFIG"]), {})
        theme = hist_search.build_theme()
        self.assertEqual(theme, hist_search.THEMES["default"])


class ArrangeRowsTests(unittest.TestCase):
    def test_below_layout_keeps_prompt_first_then_body_then_footer(self):
        lines, prompt_row = hist_search.arrange_rows("PROMPT", ["a", "b"], "FOOTER", "below")
        self.assertEqual(lines, ["PROMPT", "a", "b", "FOOTER"])
        self.assertEqual(prompt_row, 0)

    def test_above_layout_puts_footer_first_and_reverses_body_before_prompt(self):
        lines, prompt_row = hist_search.arrange_rows("PROMPT", ["a", "b"], "FOOTER", "above")
        self.assertEqual(lines, ["FOOTER", "b", "a", "PROMPT"])
        self.assertEqual(prompt_row, len(lines) - 1)

    def test_unknown_layout_defaults_to_below_behavior(self):
        lines, prompt_row = hist_search.arrange_rows("PROMPT", ["a"], "FOOTER", "sideways")
        self.assertEqual(lines, ["PROMPT", "a", "FOOTER"])
        self.assertEqual(prompt_row, 0)


class ReadKeyTests(unittest.TestCase):
    def _read(self, raw_bytes):
        r, w = os.pipe()
        try:
            os.write(w, raw_bytes)
            return hist_search._read_key(r)
        finally:
            os.close(r)
            os.close(w)

    def test_plain_character(self):
        self.assertEqual(self._read(b"a"), b"a")

    def test_up_arrow_csi(self):
        self.assertEqual(self._read(b"\x1b[A"), b"\x1b[A")

    def test_up_arrow_ss3_normalized_to_csi(self):
        self.assertEqual(self._read(b"\x1bOA"), b"\x1b[A")

    def test_left_and_right_arrows(self):
        self.assertEqual(self._read(b"\x1b[D"), b"\x1b[D")
        self.assertEqual(self._read(b"\x1b[C"), b"\x1b[C")

    def test_page_up_and_page_down_multi_byte_csi(self):
        self.assertEqual(self._read(b"\x1b[5~"), b"\x1b[5~")
        self.assertEqual(self._read(b"\x1b[6~"), b"\x1b[6~")

    def test_delete_home_end_multi_byte_csi(self):
        self.assertEqual(self._read(b"\x1b[3~"), b"\x1b[3~")
        self.assertEqual(self._read(b"\x1b[1~"), b"\x1b[1~")
        self.assertEqual(self._read(b"\x1b[4~"), b"\x1b[4~")

    def test_home_and_end_letter_csi(self):
        self.assertEqual(self._read(b"\x1b[H"), b"\x1b[H")
        self.assertEqual(self._read(b"\x1b[F"), b"\x1b[F")

    def test_lone_escape_with_nothing_pending(self):
        self.assertEqual(self._read(b"\x1b"), b"\x1b")


ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")


def run_picker(history_lines, keys, wait_for=b"FUZZY"):
    """Drive the real picker in a pseudo-terminal; return its visible output."""
    with tempfile.NamedTemporaryFile("w", suffix=".hist", delete=False) as handle:
        handle.write("\n".join(history_lines) + "\n")
    try:
        pid, fd = pty.fork()
        if pid == 0:
            os.environ["HISTFILE"] = handle.name
            os.environ["TERM"] = "xterm"
            os.execv(sys.executable, [sys.executable, MODULE_PATH])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        out = b""
        deadline = time.time() + 5
        started = False
        sent = 0
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
            if not started and wait_for in out:
                started = True
            if started and sent < len(keys):
                os.write(fd, keys[sent])
                sent += 1
                time.sleep(0.15)
        os.waitpid(pid, 0)
        return ANSI.sub(b"", out).decode(errors="replace").replace("\r", "").rstrip()
    finally:
        os.unlink(handle.name)


HISTORY = ["ls -la", "git status", "git commit -m fix", "docker compose up"]


class PickerEndToEndTests(unittest.TestCase):
    def test_fuzzy_query_and_enter_selects_the_best_match(self):
        result = run_picker(HISTORY, [b"g", b"c", b"m", b"\r"])
        self.assertTrue(result.endswith("git commit -m fix"), result[-80:])

    def test_down_arrow_moves_to_the_next_match(self):
        result = run_picker(HISTORY, [b"g", b"i", b"t", b"\x1b[B", b"\r"])
        self.assertTrue(result.endswith("git status"), result[-80:])

    def test_tab_switches_to_regex_mode(self):
        result = run_picker(HISTORY, [b"\t", b"^", b"l", b"s", b"\r"])
        self.assertTrue(result.endswith("ls -la"), result[-80:])

    def test_escape_cancels_without_output(self):
        result = run_picker(HISTORY, [b"\x1b"])
        self.assertTrue(result.endswith("cancel"), result[-80:])

    def test_empty_history_prints_nothing_and_exits(self):
        with tempfile.NamedTemporaryFile("w", suffix=".hist", delete=False) as handle:
            pass
        try:
            env = dict(os.environ, HISTFILE=handle.name)
            import subprocess
            done = subprocess.run([sys.executable, MODULE_PATH], env=env, capture_output=True, timeout=5)
            self.assertEqual((done.returncode, done.stdout), (0, b""))
        finally:
            os.unlink(handle.name)


class WidgetTests(unittest.TestCase):
    def test_widget_binds_ctrl_r_and_finds_the_script_beside_itself(self):
        import shutil
        import subprocess
        if not shutil.which("zsh"):
            self.skipTest("zsh not installed")
        widget = os.path.join(TOOL_DIR, "zsh_hist_search_widget.zsh")
        script = "source %s; print -r -- $_hist_search_dir; bindkey '^R'" % widget
        done = subprocess.run(["zsh", "-fic", script], capture_output=True, text=True, timeout=10)
        self.assertIn(TOOL_DIR, done.stdout)
        self.assertIn("hist-search-widget", done.stdout)


if __name__ == "__main__":
    unittest.main()
