#!/usr/bin/env python3
"""Tests for verify_media: pure helpers plus end-to-end checks on generated media."""

import contextlib
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

import verify_media as vm  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_media_extensions_are_case_insensitive(self):
        self.assertTrue(vm.is_media("Book.M4B"))
        self.assertTrue(vm.is_media("a/b/movie.mp4"))
        self.assertFalse(vm.is_media("cover.jpg"))

    def test_longest_zero_run_spans_chunk_boundaries(self):
        data = b"x" + b"\0" * (vm.CHUNK_SIZE * 2 + 5) + b"y" + b"\0" * 10
        self.assertEqual(vm.longest_zero_run(self.write("a.bin", data)), vm.CHUNK_SIZE * 2 + 5)

    def test_longest_zero_run_counts_a_zero_tail(self):
        data = b"abc" + b"\0" * 1000
        self.assertEqual(vm.longest_zero_run(self.write("a.bin", data)), 1000)

    def test_longest_zero_run_is_zero_without_zeros(self):
        self.assertEqual(vm.longest_zero_run(self.write("a.bin", b"abc")), 0)

    def test_duration_mismatch_allows_small_shortfall(self):
        self.assertFalse(vm.duration_mismatch(100.0, 99.0))
        self.assertTrue(vm.duration_mismatch(100.0, 50.0))
        self.assertTrue(vm.duration_mismatch(10000.0, 9800.0))

    def test_duration_mismatch_ignores_unknown_values(self):
        self.assertFalse(vm.duration_mismatch(None, 5.0))
        self.assertFalse(vm.duration_mismatch(5.0, None))

    def test_progress_lines_are_told_apart_from_errors(self):
        self.assertTrue(vm.is_progress_line("out_time_us=2500000"))
        self.assertTrue(vm.is_progress_line("progress=end"))
        self.assertFalse(vm.is_progress_line("[mp3 @ 0x1] Header missing"))

    def test_parse_progress_seconds(self):
        self.assertEqual(vm.parse_progress_seconds("out_time_us=2500000"), 2.5)
        self.assertIsNone(vm.parse_progress_seconds("out_time_us=N/A"))
        self.assertIsNone(vm.parse_progress_seconds("fps=25"))

    def test_format_status_lists_active_files_and_truncates(self):
        line = vm.format_status(3, 10, [("a.mp3", "decode", 0.42), ("b.mp4", "probe", None)], 200)
        self.assertEqual(line, "[3/10] a.mp3 decode 42% | b.mp4 probe")
        self.assertEqual(len(vm.format_status(3, 10, [("a" * 100, "scan", 0.1)], 40)), 39)
        self.assertEqual(vm.format_status(0, 5, [], 80), "[0/5]")

    def test_parse_answer(self):
        self.assertEqual(vm.parse_answer("Y"), "y")
        self.assertEqual(vm.parse_answer("all"), "a")
        self.assertEqual(vm.parse_answer(""), "n")
        self.assertEqual(vm.parse_answer("quit"), "q")
        self.assertIsNone(vm.parse_answer("maybe"))

    def test_build_units_groups_by_directory_and_collects_loose_files(self):
        for d in ("one", "two"):
            os.mkdir(os.path.join(self.tmp, d))
        a = self.write("one/a.mp3", b"1")
        b = self.write("two/b.mp3", b"1")
        loose = self.write("c.mp3", b"1")
        units = vm.build_units([os.path.join(self.tmp, "one"), os.path.join(self.tmp, "two"), loose])
        self.assertEqual([(u.path, u.files) for u in units],
                         [(os.path.join(self.tmp, "one"), [a]), (os.path.join(self.tmp, "two"), [b]),
                          (None, [loose])])

    def test_find_media_walks_directories_and_filters(self):
        os.mkdir(os.path.join(self.tmp, "sub"))
        self.write("a.mp3", b"1")
        self.write("sub/b.m4b", b"1")
        self.write("c.txt", b"1")
        found = [os.path.relpath(p, self.tmp) for p in vm.find_media([self.tmp])]
        self.assertEqual(found, ["a.mp3", os.path.join("sub", "b.m4b")])

    def test_is_within_does_not_match_sibling_prefixes(self):
        self.assertTrue(vm.is_within("/a/x/f.mp3", "/a/x"))
        self.assertFalse(vm.is_within("/a/xy/f.mp3", "/a/x"))

    def test_destination_uses_directory_basename(self):
        self.assertEqual(vm.destination_for("/dl/Book/", "/lib"), "/lib/Book")

    def test_offer_move_with_move_all_moves_and_skips_existing(self):
        dest = os.path.join(self.tmp, "dest")
        for d in ("one", "two"):
            os.makedirs(os.path.join(self.tmp, d))
        os.makedirs(os.path.join(dest, "two"))
        progress = vm.Progress(0, io.StringIO())
        one, two = os.path.join(self.tmp, "one"), os.path.join(self.tmp, "two")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(vm.offer_move(one, dest, True, progress), ("y", 0, True))
            self.assertEqual(vm.offer_move(two, dest, True, progress), ("n", 1, True))
        self.assertTrue(os.path.isdir(os.path.join(dest, "one")))
        self.assertTrue(os.path.isdir(two))

    def test_offer_move_asks_each_time_and_remembers_all(self):
        dest = os.path.join(self.tmp, "dest")
        names = ["one", "two", "three"]
        for d in names:
            os.makedirs(os.path.join(self.tmp, d))
        progress = vm.Progress(0, io.StringIO())
        answers = iter(["n", "a"])
        move_all = False
        with mock.patch("builtins.input", lambda prompt: next(answers)), \
                contextlib.redirect_stdout(io.StringIO()):
            results = []
            for d in names:
                decision, _, move_all = vm.offer_move(os.path.join(self.tmp, d), dest, move_all, progress)
                results.append(decision)
        self.assertEqual(results, ["n", "y", "y"])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "one")))
        self.assertTrue(os.path.isdir(os.path.join(dest, "two")))
        self.assertTrue(os.path.isdir(os.path.join(dest, "three")))

    def test_offer_move_quit_moves_nothing(self):
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        with mock.patch("builtins.input", lambda prompt: "q"), contextlib.redirect_stdout(io.StringIO()):
            decision, failed, _ = vm.offer_move(src, os.path.join(self.tmp, "dest"), False,
                                                vm.Progress(0, io.StringIO()))
        self.assertEqual((decision, failed), ("q", 0))
        self.assertTrue(os.path.isdir(src))

    def test_offer_move_refuses_destination_inside_source(self):
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        with contextlib.redirect_stderr(io.StringIO()):
            result = vm.offer_move(src, os.path.join(src, "in"), True, vm.Progress(0, io.StringIO()))
        self.assertEqual(result[:2], ("n", 1))
        self.assertTrue(os.path.isdir(src))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.good = os.path.join(cls.tmp, "good.m4a")
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=60",
                        "-c:a", "aac", "-b:a", "128k", cls.good], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self, name, transform=lambda d: d):
        path = os.path.join(self.tmp, name)
        with open(self.good, "rb") as src, open(path, "wb") as dst:
            dst.write(transform(src.read()))
        return path

    def test_intact_file_passes(self):
        self.assertEqual(vm.check_file(self.good, vm.DEFAULT_ZERO_RUN, False), [])

    def test_truncated_file_fails(self):
        path = self.copy("cut.m4a", lambda d: d[:len(d) // 2])
        self.assertTrue(vm.check_file(path, vm.DEFAULT_ZERO_RUN, False))

    def test_zero_filled_gap_fails_even_in_quick_mode(self):
        gap = vm.DEFAULT_ZERO_RUN + 10
        path = self.copy("gap.m4a", lambda d: d[:100] + b"\0" * gap + d[100 + gap:])
        problems = vm.check_file(path, vm.DEFAULT_ZERO_RUN, True)
        self.assertTrue(any("zero-filled" in p for p in problems))

    def test_empty_file_fails(self):
        path = os.path.join(self.tmp, "empty.mp3")
        open(path, "wb").close()
        self.assertEqual(vm.check_file(path, vm.DEFAULT_ZERO_RUN, False), ["empty file"])

    def test_garbage_file_fails(self):
        path = os.path.join(self.tmp, "junk.mp4")
        with open(path, "wb") as handle:
            handle.write(os.urandom(5000))
        self.assertTrue(vm.check_file(path, vm.DEFAULT_ZERO_RUN, False))

    def test_main_moves_only_good_directories(self):
        good_dir = os.path.join(self.tmp, "gooddir")
        bad_dir = os.path.join(self.tmp, "baddir")
        dest = os.path.join(self.tmp, "library")
        for d in (good_dir, bad_dir):
            os.makedirs(d)
        shutil.copy(self.good, good_dir)
        with open(self.good, "rb") as src, open(os.path.join(bad_dir, "cut.m4a"), "wb") as dst:
            dst.write(src.read()[:5000])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = vm.main(["-y", "-m", dest, good_dir, bad_dir])
        self.assertEqual(result, 1)
        self.assertTrue(os.path.isdir(os.path.join(dest, "gooddir")))
        self.assertTrue(os.path.isdir(bad_dir))

    def make_dir_with_bad_first(self, name):
        d = os.path.join(self.tmp, name)
        os.makedirs(d)
        with open(self.good, "rb") as src, open(os.path.join(d, "a_cut.m4a"), "wb") as dst:
            dst.write(src.read()[:5000])
        for i in range(3):
            shutil.copy(self.good, os.path.join(d, "b%d.m4a" % i))
        return d

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            result = vm.main(list(argv))
        return result, out.getvalue()

    def test_bad_file_abandons_the_directory_when_moving(self):
        d = self.make_dir_with_bad_first("abandon")
        result, out = self.run_main("-j", "1", "-y", "-m", os.path.join(self.tmp, "d1"), d)
        self.assertEqual(result, 1)
        self.assertIn("3 files not checked", out)
        self.assertIn("1 checked, 1 bad", out)
        self.assertTrue(os.path.isdir(d))

    def test_without_move_every_file_is_still_checked(self):
        d = self.make_dir_with_bad_first("nomove")
        result, out = self.run_main("-j", "1", d)
        self.assertEqual(result, 1)
        self.assertIn("4 checked, 1 bad", out)

    def test_force_checks_everything_and_yes_moves_bad_directory(self):
        d = self.make_dir_with_bad_first("forced")
        dest = os.path.join(self.tmp, "d2")
        result, out = self.run_main("-j", "1", "-f", "-y", "-m", dest, d)
        self.assertEqual(result, 1)
        self.assertIn("4 checked, 1 bad, 1 moved", out)
        self.assertTrue(os.path.isdir(os.path.join(dest, "forced")))

    def test_force_asks_about_bad_directory_even_after_all(self):
        d = self.make_dir_with_bad_first("asked")
        dest = os.path.join(self.tmp, "d3")
        answers = iter(["n"])
        with mock.patch("builtins.input", lambda prompt: next(answers)), \
                mock.patch.object(sys.stdin, "isatty", return_value=True):
            result, out = self.run_main("-j", "1", "-f", "-m", dest, d)
        self.assertEqual(result, 1)
        self.assertTrue(os.path.isdir(d))

    def test_main_exit_codes(self):
        path = self.copy("cut2.m4a", lambda d: d[:len(d) // 2])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(vm.main([self.good]), 0)
            self.assertEqual(vm.main([path]), 1)


class CancelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bindir = os.path.join(self.tmp, "bin")
        os.mkdir(bindir)
        self.pidfile = os.path.join(self.tmp, "ffmpeg.pid")
        self.write_script(os.path.join(bindir, "ffprobe"),
                          "#!/bin/sh\necho '{\"format\":{\"duration\":\"100\"},"
                          "\"streams\":[{\"codec_type\":\"audio\"}]}'\n")
        self.write_script(os.path.join(bindir, "ffmpeg"),
                          "#!/bin/sh\necho $$ > '%s'\nexec sleep 30\n" % self.pidfile)
        self.media = os.path.join(self.tmp, "a.mp3")
        with open(self.media, "wb") as handle:
            handle.write(b"data")
        self.env = dict(os.environ, PATH=bindir + os.pathsep + os.environ["PATH"])

    @staticmethod
    def write_script(path, text):
        with open(path, "w") as handle:
            handle.write(text)
        os.chmod(path, 0o755)

    def wait_for(self, condition, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return True
            time.sleep(0.05)
        return False

    def test_sigint_exits_immediately_and_kills_the_decoder(self):
        tool = os.path.join(TOOL_DIR, "verify_media.py")
        process = subprocess.Popen([sys.executable, tool, "-z", "0", self.media], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertTrue(self.wait_for(lambda: os.path.exists(self.pidfile), 10))
        with open(self.pidfile) as handle:
            decoder_pid = int(handle.read())
        started = time.time()
        process.send_signal(signal.SIGINT)
        self.assertEqual(process.wait(timeout=5), 130)
        self.assertLess(time.time() - started, 3)
        self.assertTrue(self.wait_for(lambda: not self.alive(decoder_pid), 3))

    def test_bad_file_kills_sibling_decodes_in_the_same_directory(self):
        media_dir = os.path.join(self.tmp, "book")
        os.mkdir(media_dir)
        with open(os.path.join(media_dir, "a.mp3"), "wb") as handle:
            handle.write(b"data")
        with open(os.path.join(media_dir, "b.mp3"), "wb") as handle:
            handle.write(b"data")
        self.write_script(os.path.join(self.tmp, "bin", "ffprobe"), (
            "#!/bin/sh\ncase \"$*\" in *b.mp3*) sleep 1; echo broken >&2; exit 1;; esac\n"
            "echo '{\"format\":{\"duration\":\"100\"},\"streams\":[{\"codec_type\":\"audio\"}]}'\n"))
        tool = os.path.join(TOOL_DIR, "verify_media.py")
        started = time.time()
        result = subprocess.run([sys.executable, tool, "-z", "0", "-y", "-m", os.path.join(self.tmp, "dest"),
                                 media_dir], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1)
        self.assertLess(time.time() - started, 5)
        self.assertIn("KEEP", result.stdout)
        with open(self.pidfile) as handle:
            self.assertTrue(self.wait_for(lambda: not self.alive(int(handle.read())), 3))
        self.assertTrue(os.path.isdir(media_dir))

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        with open("/proc/%d/stat" % pid) as handle:
            return handle.read().split()[2] != "Z"


if __name__ == "__main__":
    unittest.main()
